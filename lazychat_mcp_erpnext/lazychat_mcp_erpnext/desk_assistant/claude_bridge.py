import base64
import json
import re

import frappe
from frappe import _

from lazychat_mcp_erpnext.desk_assistant.password_utils import safe_provider_api_key
from lazychat_mcp_erpnext.desk_assistant.providers import resolve_model
from lazychat_mcp_erpnext.desk_assistant.tool_schemas import TOOL_SCHEMAS
from lazychat_mcp_erpnext.desk_assistant.tools import execute_tool

MAX_TURNS = 8

MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
MAX_ATTACHMENTS = 8
MAX_TEXT_FROM_FILE = 100_000

TOOLLESS_PROMPT_SUFFIX = (
	"\nYou don't have native tool use. When you need data, respond with EXACTLY:\n"
	'<tool>{"name": "tool_name", "input": {...}}</tool>\n'
	"and nothing else for that turn. Available tools:\n"
	+ "\n".join(f"- {t['name']}: {t['description']}" for t in TOOL_SCHEMAS)
)


def _route_context_summary(context):
	"""Pull the most useful bits out of desk_context into a one-paragraph briefing for the LLM."""
	if not isinstance(context, dict):
		return ""
	view = context.get("view")
	dt = context.get("doctype")
	dn = context.get("docname")
	cur = context.get("current_doc") or {}
	selected = context.get("selected_rows") or []
	if view == "Form" and dt and dn:
		bits = [f"The user is currently viewing **{dt} / {dn}**"]
		if cur.get("title"):
			bits.append(f"(title: {cur['title']!r})")
		extra = []
		if cur.get("workflow_state"):
			extra.append(f"workflow_state={cur['workflow_state']}")
		elif cur.get("status"):
			extra.append(f"status={cur['status']}")
		if cur.get("dirty"):
			extra.append("UNSAVED CHANGES")
		if extra:
			bits.append("[" + ", ".join(extra) + "]")
		return (
			" ".join(bits) + ".\n"
			f"When the user says 'this', 'this doc', 'summarize', 'what is it about', 'what's wrong' — "
			f"they mean {dt}/{dn}. Call get_doc('{dt}', '{dn}') FIRST to ground your answer in the real document.\n\n"
		)
	if view == "List" and dt:
		s = f"The user is on the **{dt} list view**"
		if selected:
			preview = ", ".join(selected[:5]) + ("..." if len(selected) > 5 else "")
			s += f" with {len(selected)} row(s) selected: {preview}.\n"
			s += "When they say 'these' or 'the selected ones', use these names.\n\n"
		else:
			s += ".\n\n"
		return s
	if view == "Report" and dt:
		return f"The user is on the **{dt} report view**.\n\n"
	return ""


def _system_prompt(context, supports_tools):
	base = _route_context_summary(context) + """You are an ERPNext / Frappe desk assistant. Be concise and accurate.
Use tools to fetch real data instead of guessing.

READ tools (no confirmation needed):
- Discovery: search_doctype (find DocTypes by name), search_global (search doc content),
  search_link (autocomplete a fuzzy doc name like "Acme" → exact Customer name).
- Basic: get_list, get_doc, get_value, count_doc, describe_doctype, get_current_context.
- Relationships: get_doctype_links (other docs linking to this one).
- Workflow: list_workflow_actions, get_pending_approvals (what's waiting for me).
- Analytics: aggregate, get_sales_summary, dashboard_chart_data, number_card_value, list_user_dashboards.
- Reports: list_reports, report_requirements (call BEFORE run_report), run_report.
- Files: extract_file_content (read attached file text).
- ERPNext domain: get_stock_balance, get_account_balance, get_outstanding, get_open_invoices,
  get_item_price, get_company_defaults — prefer these over generic queries when applicable.

WRITE / WORKFLOW / COMMS (always two-phase via prepare_* + /commit):
- prepare_create_doc, prepare_update_doc, prepare_submit_doc, prepare_delete_doc — doctype mutations.
- prepare_workflow_action — workflow transition (Approve/Reject/etc).
- prepare_add_comment — comment on a doc's activity log.
- prepare_assign_to — assignment (creates a ToDo for a user).
- prepare_send_email — outbound email (gated by site_config 'lazychat_allow_email' flag).
- prepare_share_doc — share a doc with a user.
- prepare_run_sql — raw SELECT SQL (gated: 'lazychat_allow_dangerous_tools'=true AND System Manager).
  Use ONLY when the regular get_list/aggregate cannot express the query. ALWAYS show the SQL
  and warn the user that raw SQL bypasses per-user permission filters.
- prepare_run_python — Python execution with full Frappe/pandas/numpy access (same gate as run_sql).
  Use for analytics or one-off transformations. Set `_result = ...` to return a value. Show the
  user the code and warn them it has full filesystem + data access.

When the user mentions something fuzzy ("the Acme order"), CALL search_link or search_global FIRST to resolve it to an exact (doctype, name) before any other tool.

For ALL prepare_* tools:
1. The tool returns {preview_token, summary, confirm_with} (and `diff`/`preview` when relevant).
   It does NOT actually change anything.
2. Narrate the preview clearly to the user (show the doctype, fields, action, diff).
3. Tell the user EXACTLY: "Reply with `/commit TOKEN` to apply, or anything else to cancel."
   (replace TOKEN with the actual preview_token).
4. NEVER call any commit tool yourself — the /commit slash command is handled outside the agent loop.
5. If the user does NOT confirm, do not retry. Acknowledge and move on.

For unfamiliar doctypes, call describe_doctype first to learn the field schema before staging a create or update.
For workflow actions, call list_workflow_actions first to learn which actions are valid from the current state.

Desk context JSON: """
	ctx = json.dumps(context or {}, default=str)[:8000]
	s = base + ctx
	if not supports_tools:
		s += TOOLLESS_PROMPT_SUFFIX
	return s


def _estimate_cost(model, usage):
	in_cost = (usage["input_tokens"] / 1_000_000) * (model.input_price_per_mtok or 0)
	out_cost = (usage["output_tokens"] / 1_000_000) * (model.output_price_per_mtok or 0)
	return round(in_cost + out_cost, 6)


def build_user_content(message_text, attachments):
	"""Build Claude API user content: str, or list of text/image blocks."""
	attachments = attachments or []
	blocks = []
	mt = (message_text or "").strip()
	if mt:
		blocks.append({"type": "text", "text": mt})
	for raw in attachments[:MAX_ATTACHMENTS]:
		name = (raw.get("name") or "attachment").strip()
		media = (raw.get("media_type") or "application/octet-stream").strip()
		b64 = raw.get("data") or ""
		if not b64:
			continue
		try:
			raw_bytes = base64.b64decode(b64, validate=True)
		except Exception:
			frappe.throw(_("Invalid attachment encoding: {0}").format(name))
		if len(raw_bytes) > MAX_ATTACHMENT_BYTES:
			frappe.throw(_("Attachment too large (max 2 MB): {0}").format(name))
		if media.startswith("image/"):
			b64_clean = base64.standard_b64encode(raw_bytes).decode("ascii")
			blocks.append(
				{
					"type": "image",
					"source": {
						"type": "base64",
						"media_type": media,
						"data": b64_clean,
					},
				}
			)
		else:
			text = raw_bytes.decode("utf-8", errors="replace")
			if len(text) > MAX_TEXT_FROM_FILE:
				text = text[:MAX_TEXT_FROM_FILE] + f"\n\n[Truncated to {MAX_TEXT_FROM_FILE} characters]"
			blocks.append(
				{
					"type": "text",
					"text": f"--- Attached file: {name} ({media}) ---\n{text}",
				}
			)
	if not blocks:
		frappe.throw(_("Message or attachment is required"))
	if len(blocks) == 1 and blocks[0]["type"] == "text":
		return blocks[0]["text"]
	return blocks


def _parse_toolless(text):
	m = re.search(r"<tool>\s*(\{.*?\})\s*</tool>", text, re.DOTALL)
	if not m:
		return None
	try:
		payload = json.loads(m.group(1))
		return payload.get("name"), payload.get("input") or {}
	except Exception:
		return None


def run_agentic_turn(
	user_message,
	history,
	context,
	*,
	attachments=None,
	model_label=None,
	allow_writes=False,
	desk_context=None,
	emit=None,
):
	model, provider, adapter = resolve_model(model_label)
	supports_tools = bool(model.supports_tools)
	api_key = safe_provider_api_key(provider)
	base_url = provider.base_url or ""
	if not api_key and "localhost" not in base_url.lower() and "127.0.0.1" not in base_url.lower():
		frappe.throw(
			_("Set an API Key on LLM Provider: {0}").format(provider.provider_name),
			title=_("Lazychat MCP ERPNext"),
		)

	user_content = build_user_content(user_message, attachments)
	history = list(history) + [{"role": "user", "content": user_content}]
	usage_total = {"input_tokens": 0, "output_tokens": 0}
	tools = TOOL_SCHEMAS if supports_tools else None

	for _turn in range(MAX_TURNS):
		resp = adapter.chat(
			provider=provider,
			model=model,
			messages=history,
			system=_system_prompt(context, supports_tools),
			tools=tools,
			max_tokens=model.max_output_tokens or 4096,
		)
		usage_total["input_tokens"] += int(resp.usage.get("input_tokens", 0) or 0)
		usage_total["output_tokens"] += int(resp.usage.get("output_tokens", 0) or 0)

		history.append({"role": "assistant", "content": resp.content})

		tool_uses = [b for b in resp.content if b.get("type") == "tool_use"]

		if not tool_uses and not supports_tools:
			for block in resp.content:
				if block.get("type") != "text":
					continue
				parsed = _parse_toolless(block.get("text", ""))
				if parsed:
					tn, tin = parsed
					tool_uses = [
						{
							"type": "tool_use",
							"id": f"tl_{frappe.generate_hash(length=8)}",
							"name": tn,
							"input": tin,
						}
					]
					break

		for block in resp.content:
			if block.get("type") == "text" and emit:
				emit({"type": "text_delta", "delta": block.get("text", "")})
			elif block.get("type") == "tool_use" and emit:
				emit(
					{
						"type": "tool_use",
						"id": block["id"],
						"name": block["name"],
						"input": block.get("input"),
					}
				)

		if not tool_uses:
			break

		tool_results = []
		for tu in tool_uses:
			result = execute_tool(
				tu["name"],
				tu.get("input") or {},
				allow_writes=allow_writes,
				desk_context=desk_context,
			)
			if emit:
				emit({"type": "tool_result", "name": tu["name"], "result": result})
			tool_results.append(
				{
					"type": "tool_result",
					"tool_use_id": tu["id"],
					"content": json.dumps(result, default=str)[:50000],
				}
			)
		history.append({"role": "user", "content": tool_results})

	if emit:
		emit(
			{
				"type": "usage",
				"model": model.model_label,
				**usage_total,
				"cost_estimate": _estimate_cost(model, usage_total),
			}
		)
	return history, usage_total
