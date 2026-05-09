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

# Effort tiers control turn budget and (for Anthropic) extended-thinking
# budget. Mirrors apps/chat-ui/src/lib/effortConfig.ts EFFORT_CONFIG.
EFFORT_MAP = {
	"low":    {"max_turns": 8,  "thinking_budget": 0,
	           "iter_cap": 1, "critic": "skip",
	           "schema_prefetch": "jit", "exemplar_top_n": 0,
	           "live_ground": False, "reflect_retries": 0,
	           "apply_threshold": 0.50, "chip_threshold": 0.30},
	"medium": {"max_turns": 16, "thinking_budget": 0,
	           "iter_cap": 2, "critic": "skip",
	           "schema_prefetch": "lazy", "exemplar_top_n": 1,
	           "live_ground": False, "reflect_retries": 1,
	           "apply_threshold": 0.65, "chip_threshold": 0.50},
	"high":   {"max_turns": 32, "thinking_budget": 4000,
	           "iter_cap": 3, "critic": "haiku",
	           "schema_prefetch": "related", "exemplar_top_n": 3,
	           "live_ground": True, "reflect_retries": 1,
	           "apply_threshold": 0.75, "chip_threshold": 0.60},
	"max":    {"max_turns": 64, "thinking_budget": 16000,
	           "iter_cap": 5, "critic": "sonnet",
	           "schema_prefetch": "full", "exemplar_top_n": 5,
	           "live_ground": "with_screenshot", "reflect_retries": 2,
	           "apply_threshold": 0.85, "chip_threshold": 0.70},
}

# Mode-specific prompt blocks. Plan turn 1 forbids tool calls until user
# approves. Ask mode nudges toward staging tools.
PLAN_MODE_BLOCK = """
PLAN MODE IS ACTIVE. Your FIRST response in this turn MUST be a numbered plan only —
NO tool_use blocks, NO tool_calls. Format exactly:

  Plan: <one-line title>
  1. <action> — <why>
  2. ...
  N. <synthesis step>

After emitting the plan, STOP. Do NOT call any tools. The user will Approve, Edit,
or Reject. On approval you will be re-invoked with the plan in context and may
begin running tools step-by-step.
""".strip()

ASK_MODE_BLOCK = """
ASK BEFORE EDITS MODE. The user wants to confirm every mutation explicitly.
PREFER prepare_* staging tools for all mutations (the user clicks Apply per call).
For analytics, prefer run_sql_select / run_python_readonly / get_list — those
auto-execute and don't need confirmation.
""".strip()

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


def _system_prompt(context, supports_tools, mode="edit-auto", plan_resumed=False):
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
- TYPED WRAPPERS (use these INSTEAD of prepare_create_doc for these doctypes — they validate
  required fields up front so the model gets actionable errors at preview time):
  · prepare_create_report — for Report (Report Builder / Query Report / Script Report). Generic
    prepare_create_doc({doctype:'Report'}) breaks at open-time with "getdoctype() missing
    'doctype'" because ref_doctype/report_type aren't validated.
    **PREFER report_type='Query Report'** when the user asks for a report. Query Reports
    support clickable HTML buttons via `<a>` tags inside cell values:
      `CONCAT('<a href="/app/<doctype>/new?...&is_return=1" class="btn btn-xs btn-default">Click</a>')`
    Query Reports do NOT need Python — pure SQL. Avoid Script Reports unless you have a
    specific reason that needs Python (multi-pass aggregation, conditional column shapes,
    pivot, etc.). Script Reports run inside `safe_exec` (RestrictedPython) — `import`
    statements are FORBIDDEN, only the curated `frappe.*` subset (get_list, get_value,
    qb, db.count, db.get_all) is exposed. The wrapper AST-validates + safe_exec dry-runs
    the body at preview, so violations surface immediately. If you must use Script Report,
    NEVER write `import frappe` / `from frappe import _` — those names are pre-injected.
  · prepare_create_scheduled_job — for Scheduled Job Type (cron). Requires System Manager.
  · prepare_create_number_card — for single-stat dashboard tiles. Use after get_list / aggregate
    to confirm the source doctype + filter shape work.
  · prepare_create_dashboard — composes existing Dashboard Charts + Number Cards into a
    Dashboard. Create the charts/cards first (make_chart, prepare_create_number_card), then
    pass their names here.
  · prepare_create_calendar_event — Frappe Event (Public/Private). Validates ISO datetimes,
    repeat enum, participant shape. ends_on must be >= starts_on; repeat_this_event=True
    requires repeat_on (Daily/Weekly/Monthly/Yearly).
  · prepare_create_note — Frappe Note. Note autonames as hash, so the actual document `name`
    is generated at /commit time and returned in the response. DO NOT pass the title to
    follow-up tools that take `name` (e.g. prepare_add_comment) — use the name from /commit.
  · prepare_bulk_update — bulk field update across N docs filtered by criteria. Runs count_doc
    inside the prepare and refuses if N exceeds bulk_update_max_rows (default 500). Use this
    INSTEAD of looping prepare_update_doc when the user says "all overdue invoices". Gated by
    lazychat_allow_dangerous_tools because of scale; commit re-counts and refuses if matched
    rows grew >1.5× since preview.
  · prepare_download_backup — enqueues `bench backup` via frappe.enqueue and returns a job_id;
    poll progress with list_my_jobs and cancel with cancel_job. Requires System Manager.
  · prepare_create_print_format — Jinja Print Formats are dry-rendered against an empty doc
    at preview time so syntax errors surface in the same turn.
  · prepare_update_print_settings — site-wide print defaults (font, paper size, letterhead).
    System Manager only. Diff is shown in the preview.
  · prepare_create_email_template — Jinja-validated subject + body. Templates are inert until
    referenced by send tools (no `lazychat_allow_email` gate needed to STAGE a template).
  · prepare_create_notification — for Notification (alert templates). event=Days Before/After
    requires date_changed (a Date field on document_type). event=Value Change requires
    value_changed. event=Method requires method (server-side import path). channel=Email/Slack/SMS
    require at least one recipient row. Optional condition expression is AST-validated against
    imports/lambdas/dunder access.
  · prepare_create_auto_email_report — schedule a Report to email itself. Validates the Report
    exists and the user has report perm on its ref_doctype.
  · prepare_create_milestone_tracker — auto-create Milestones whenever a Link/Select field on
    a doctype changes. track_field must be a Link or Select fieldtype.
  · prepare_create_auto_repeat — recurring document creation. Refuses (preview AND commit) if
    a non-Cancelled Auto Repeat already targets the same (reference_doctype, reference_document).
  · prepare_create_email_group — mailing list bucket. Refuses if title already exists.
  · prepare_add_to_email_group(email_group, email) — append a member; idempotent at commit.
  · prepare_create_newsletter — staged ONLY; sending is admin-driven from the Desk by design.
  · prepare_create_email_account — DOUBLE-GATED: System Manager AND new
    `lazychat_allow_email_setup` flag (separate from `allow_email` because configuring
    SMTP/IMAP creds is meaningfully more dangerous than sending mail). Live SMTP/IMAP
    connection probe at preview time — result lands in preview's test_result. Test failure
    does NOT refuse staging.
  · prepare_create_assignment_rule — Round Robin / Load Balancing / Based on Field. users[]
    must all exist; Based on Field requires a Link-to-User field; assign_condition and
    unassign_condition are AST-validated against imports/lambdas/dunder. Requires
    Notification Manager OR System Manager role.
  · prepare_create_custom_field — for Custom Field (DocType schema extension). Validates
    dt + fieldtype enum + insert_after up front. Requires System Manager. Use this INSTEAD
    of prepare_create_doc({doctype:'Custom Field'}) — the generic path lets the model stage
    incomplete rows that fail at apply time. Link/Table/Dynamic Link fieldtypes require
    `options`. fieldname is auto-derived from label if omitted.
  · prepare_create_client_script — for Client Script (Form/List browser-side JS). Validates
    dt + view enum + non-empty script. Requires System Manager.
- DIRECT (no /commit) — these are reversible / single-doc / low-risk:
  · restore_deleted_doc(deleted_document_name) — restore from Frappe's recycle bin. Re-checks
    `create` permission on the original doctype.
  · update_notification_settings — per-user prefs (channels, seen, email subject filter).
    Always limited to frappe.session.user.
- prepare_workflow_action — workflow transition (Approve/Reject/etc).
- prepare_add_comment — comment on a doc's activity log.
- prepare_assign_to — assignment (creates a ToDo for a user).
- prepare_send_email — outbound email (gated by site_config 'lazychat_allow_email' flag).
- prepare_share_doc — share a doc with a user.
- run_sql_select — AUTO-EXECUTE a raw SELECT SQL query and get rows back IMMEDIATELY in this
  same turn (no /commit, no Apply button). USE THIS for analytical queries that need data to
  compare/branch/synthesize. Same gates as prepare_run_sql ('lazychat_allow_dangerous_tools'=true
  AND System Manager); validated SELECT-only by regex.

  SCHEMA-FIRST: Before constructing any non-trivial SQL, call describe_doctype FIRST for every
  doctype you'll reference. Schema-hallucinated columns are the #1 failure mode and surface as
  "Unknown column" OperationalErrors with a structured `hint` field — read it and retry.

  CHILD-TABLE LINKS: In ERPNext, cross-document references typically live on the CHILD table,
  not the parent. Common cases:
    • Purchase Receipt ↔ Purchase Order: `Purchase Receipt Item.purchase_order` (NOT a column on `tabPurchase Receipt`)
    • Purchase Invoice ↔ Purchase Receipt: `Purchase Invoice Item.purchase_receipt`
    • Purchase Invoice ↔ Purchase Order:   `Purchase Invoice Item.purchase_order`
    • Sales Invoice ↔ Sales Order:         `Sales Invoice Item.sales_order`
    • Delivery Note ↔ Sales Order:         `Delivery Note Item.against_sales_order`
  Pattern: SELECT ... FROM `tabPurchase Receipt` pr
           JOIN `tabPurchase Receipt Item` pri ON pri.parent = pr.name
           WHERE pri.purchase_order = '...'

  ITEM-LEVEL PR↔PI LINKAGE (canonical, row-to-row):
    • `Purchase Invoice Item.pr_detail`              → Purchase Receipt Item.name
    • `Purchase Invoice Item.purchase_receipt`       → Purchase Receipt.name (parent ref)
    • `Purchase Receipt Item.purchase_invoice_item`  → Purchase Invoice Item.name (back-link)
    • `Purchase Receipt Item.purchase_invoice`       → Purchase Invoice.name (back-link, sparse — only set when PR was made FROM the PI)
  For receipt-vs-invoice variance reports, ALWAYS join on the row-level link
  `pii.pr_detail = pri.name` (or equivalently `pri.purchase_invoice_item = pii.name`).
  DO NOT join on `item_code` alone — items repeat across PRs/PIs and you'll get
  bogus matches. DO NOT rely on `pri.purchase_invoice` alone — it's only populated
  for invoice-first flows and most receipts won't have it set.

  ERPNext doesn't have separate "Debit Note" / "Credit Note" doctypes. They're
  Purchase Invoice / Sales Invoice with `is_return=1` (and `return_against=<original>`).
  For Query Reports with a "Create Debit Note" link button, the URL is
  `/app/purchase-invoice/new?is_return=1&return_against=<PI-name>`. NEVER call
  describe_doctype("Debit Note") — it returns a redirect hint pointing here.

  AUTO-FILL ITEMS FROM A QUERY-REPORT BUTTON (Cycle 11 — preferred path):
  Use `prepare_form_prefill(doctype, parent_fields, items)` to stage the
  payload server-side. Returns `{ok, token, url}` where `url` is a tiny
  `/app/<dt>/new?_lz_token=<22-char>` (always under 100 chars). Embed
  THIS url in your Query Report HTML link buttons. The persistent Client
  Script fetches the staged payload on form load and applies it via
  `frappe.route_options`. WHY: a 50-item variance report base64-encoded
  into the URL exceeds 8 KB, triggering HTTP 414 "Request-URI Too Long"
  on the Frappe dev server. The token-based path keeps the URL tiny
  regardless of payload size.

  Discovery tools (call BEFORE composing the report):
  - `get_form_prefill_capabilities(doctype)` — returns the whitelisted
    parent + item-row keys for a target doctype.
  - `get_doctype_relationships(doctype)` — returns canonical row-level
    joins (e.g. PR↔PI via `pr_detail`, NOT `item_code`).

  Legacy `_lz_items` URL convention (deprecated; works for one cycle):
  The persistent Client Script also accepts `?_lz_items=<base64-json>`
  for backwards compat. Avoid this path for new reports — it hits HTTP
  414 above ~5 items. Existing reports continue to work; the LLM should
  not generate new `_lz_items` URLs.

  REPORT-LEVEL TOP-RIGHT BUTTON:
  prepare_create_report accepts a `javascript` arg persisted to
  Report.javascript. Use it for top-right `report.page.add_inner_button(...)`.

  Quality tips for variance/comparison SQL:
  • COALESCE on every LEFT-JOIN reference (NULL → 0 prevents row dropout).
  • `pi.docstatus = 1` (or equivalent) — exclude drafts/cancellations.
  • Filter to actual variances: `WHERE col_a <> COALESCE(col_b, 0)`.
  • Short button labels (≤12 chars: "Debit Note ↗") — long labels truncate.
  • Use `''` not `'-'` for the non-action ELSE branch in CASE expressions.

- prepare_run_sql — STAGES a SELECT query for user-approval (Apply button) instead of running
  it immediately. Use ONLY when the user has explicitly asked to review the SQL before it runs.
  For analytical questions that need the data NOW, use `run_sql_select` instead — staging-then-
  waiting-for-Apply means you cannot continue analysis in the same turn.

- run_python_readonly — AUTO-EXECUTE read-only Python (frappe + pandas/numpy) and get the result
  IMMEDIATELY in this same turn (no /commit). Use this for analytical Python that goes beyond
  what run_sql_select can express (pandas pivots, multi-pass computations, complex group-by-
  then-filter, etc.). Same gates as run_sql_select. Read-only enforced in two layers: (1) AST
  scan rejects imports of subprocess/os/sys/shutil/network modules and calls to file/shell I/O
  built-ins or frappe.db mutators / frappe side-effects (sendmail, publish_realtime, enqueue,
  delete_doc, …); (2) runtime savepoint that ALWAYS rolls back any DB mutations after the code
  runs. Set _result to return a value.
- prepare_run_python — Python execution with full Frappe/pandas/numpy access (same gate as run_sql).
  Use for analytics or one-off transformations. Set `_result = ...` to return a value. Show the
  user the code and warn them it has full filesystem + data access.

  Same SCHEMA-FIRST rule: call describe_doctype before referencing any field in a `frappe.db.sql`
  inside the Python code, AND for any `frappe.get_all(fields=[...])` field list.

- ERROR RECOVERY for run_sql / run_python: if /commit fails, you will see the error in the next
  turn prefixed with "[lazychat:tool-error]". The error often includes a "hint:" line — read it.
  Re-verify schema with describe_doctype, correct the query, re-stage with a NEW prepare_run_sql /
  prepare_run_python call. Do NOT regenerate the same query unchanged. If the error mentions an
  "Unknown column" on a parent doctype, check whether the column lives on the corresponding child
  table (see CHILD-TABLE LINKS above).

When the user mentions something fuzzy ("the Acme order"), CALL search_link or search_global FIRST to resolve it to an exact (doctype, name) before any other tool.

For ALL prepare_* tools:
1. The tool returns {preview_token, summary, confirm_with} (and `diff`/`preview` when relevant).
   It does NOT actually change anything.
2. After calling a prepare_* tool, your reply ENDS as soon as you've narrated what was
   staged. Cap that narration at 1–2 short sentences + (for run_sql / run_python) the
   EXACT query/code in a fenced code block. STOP THERE. Do NOT add bullet-list
   explanations of "what the script will do", do NOT write a recap section, do NOT say
   "Click Apply in the card above" or "Once it runs, I'll share..." — every line you add
   after the staging pushes the action card up and out of the user's viewport, defeating
   the inline-button UX.
3. The chat-ui auto-renders an inline Apply / Cancel action card directly below your
   reply — the user clicks Apply to commit. **COMMIT-INSTRUCTION FORBIDDEN**: NEVER
   write the literal string "/commit" followed by a token in your reply. NEVER write
   "Reply with /commit TOKEN to ...". NEVER echo the preview_token in your reply at
   all. The chat-ui auto-renders the Apply button — your job ENDS at narrating what
   was staged. Adding a /commit instruction creates two ambiguous CTAs (button vs
   slash-command) and confuses the user. The chat-ui post-processes your reply and
   strips any leaked /commit lines, but you should not rely on that — write
   correctly the first time.
4. NEVER call any commit tool yourself — the /commit slash command is handled outside the
   agent loop and only fires when the user clicks Apply (or types /commit TOKEN as a power-user
   fallback).
5. If the user does NOT confirm (clicks Cancel, or sends a new message instead), do not retry.
   Acknowledge and move on.
6. TOOL-ERROR HONESTY (CRITICAL): if a prepare_* call returned an error (the tool result has
   `error: ...` or `ok: false`, or the chat shows a red Failed card), you MUST acknowledge
   the failure to the user in your next sentence. Do NOT narrate as if the staging succeeded.
   Do NOT say "I've staged a comprehensive..." or "Click Apply" when the last call failed.
   Do NOT write recap sections describing "what the report will include" if no preview_token
   was returned. Failure modes to avoid:
   - "Perfect! I've staged..." after a Failed card → wrong; acknowledge the error and either
     fix it or ask the user.
   - Re-listing the desired columns / features after a failure → wrong; the user can read
     the failure card themselves, narrate a NEXT-STEP not a wishlist.
   - Telling the user "Click Apply below to create it" when the last action card is RED /
     Failed → wrong; that Apply doesn't exist.
   On error, your next message has shape:
     "That call failed: <one-line summary of the error>. <one-line next step>."
   If the error includes a "Use the typed wrapper X instead" hint, IMMEDIATELY retry with
   that wrapper using the SAME args translated to the wrapper's schema. If the error is a
   duplicate-name error, switch to prepare_update_doc with the existing doc's name.
7. ANTI-LOOP: if a tool call has failed twice in a row with the SAME error, STOP staging
   and tell the user what's blocking. Do NOT keep re-staging the same broken thing in the
   hope it works the third time.

For unfamiliar doctypes, call describe_doctype first to learn the field schema before staging a create or update.
For workflow actions, call list_workflow_actions first to learn which actions are valid from the current state.

COMPOUND QUESTIONS — when the user asks anything requiring multiple stages, conditional branches, aggregations across doctypes, or wording like "if X then A else B", "and then", "list X and Y", "compare A vs B", "for each X show Y":

1. PLAN FIRST. Before any tool call, output a numbered plan as plain markdown text — what data you need, in what order, what comparisons or branches to make, and what the final answer's shape will be. Example for "list POs with >100 items where stock ledger doesn't match the PR":
   > Plan:
   > 1. Find Purchase Orders where COUNT(items) > 100 (count_doc / aggregate).
   > 2. For each, fetch its linked Purchase Receipts via Purchase Receipt Item.purchase_order.
   > 3. For each PR, fetch Stock Ledger Entries where voucher_type='Purchase Receipt' AND voucher_no=<PR name>.
   > 4. Compare PR Item.qty totals vs SLE actual_qty totals per item_code.
   > 5. Branch: if any mismatch -> list PRs + missing/discrepant items; else -> list PO -> PR -> PI chain.

2. EXECUTE each step via tool calls. Narrate progress in one short sentence per step. Use describe_doctype to verify schema before any SQL — schema-hallucinated columns are the #1 source of failure on prepare_run_sql (see CHILD-TABLE LINKS above).

3. SYNTHESIZE at the end — a final answer that addresses EVERY clause of the original question, not just the most recent sub-step. Tabular data as markdown tables, branches resolved explicitly ("Yes, mismatches found:" or "No mismatches; PO -> PR -> PI chain:").

COMPLETENESS — before your final assistant turn (no more tool calls):
- Re-read the user's original message verbatim.
- For each clause / branch / "and ..." in their question, confirm you produced the data they asked for.
- If even one clause is unanswered — e.g. they asked "if X then A else B" and you only handled the X check, OR they asked "list X and Y" and you only listed X — KEEP going with another tool call. Do NOT declare done with a partial answer. The most common failure mode is stopping after one successful query when the question had multiple parts.

TOOL CHOICE FOR ANALYTICS — when you need data back to inspect/compare/branch/synthesize in the SAME turn:
- Use run_sql_select (auto-executes SELECT SQL, returns rows immediately). This is the right tool for compound analytical questions.
- Use run_python_readonly (auto-executes read-only Python with frappe + pandas/numpy, returns result immediately) when SQL alone can't express the analysis — pandas pivots, multi-pass computations, complex group-by-then-filter. Same in-turn semantics as run_sql_select; DB mutations auto-rolled-back, file/shell/network I/O AST-blocked.
- Use get_list / count_doc / aggregate for simple lookups that those tools can express.
- Do NOT use prepare_run_sql or prepare_run_python for analysis — those STAGE the action and wait for the user's Apply click; your turn ends without data so you cannot continue analysis. Use the prepare_* variants ONLY when the action GENUINELY mutates the DB and you want explicit user approval (rare for SQL, common for create/update flows).

EVIDENCE-OR-SAY-SO — when answering "is there X?", "how many X?", "list all X with property Y":
- A negative answer ("no X matches") REQUIRES a successful count_doc or aggregate or run_sql_select with COUNT(*) that returns 0. NEVER conclude "no X exists" from a sample inspection, from "typical ERP patterns", or from prior knowledge of how systems usually look. The user's data is what matters, not what's typical.
- If your first counting tool call fails (e.g. aggregate rejects a child-table group_by because `parent` is a meta field), retry with prepare_run_sql doing `GROUP BY parent HAVING COUNT(*) > N` — this is the canonical pattern for "rows whose parent has >N children" in ERPNext. Do NOT abandon and guess.
- If after 2-3 reasonable attempts you still cannot get the count (gated tool, schema you cannot describe, etc.), explicitly say "I could not verify this count because [reason]" and OFFER a concrete next step. Do NOT replace the missing data with hand-waving like "items of this magnitude are extremely rare in standard ERP systems".
- A positive sample without a count is also incomplete: "I found 3 POs with >100 items" is wrong if you only inspected 3 — say "the first 3 POs I checked have >100 items; let me run a count_doc to find the full set" and then run it.

DATA FAITHFULNESS — when reporting on a document or list returned by a tool:
- Enumerate EVERY row from the tool result. Never summarize to "and N more", "the first few", "etc.", or pick representative items. The user is asking precisely BECAUSE they want the full list.
- For tabular data (line items, line totals, child tables), render a markdown table with one row per record — not a prose summary.
- Quote numeric fields exactly as the tool returned them (qty, rate, amount, date). Do not round, re-derive, or "clean up" values.
- If the tool result was truncated server-side (presence of a "_note" field saying rows were trimmed, or a "[Result truncated to ... chars]" marker at the end), say so explicitly and call get_list (or another tool) to fetch the rest before answering.
- If a totals/aggregate is requested, compute it from ALL rows, then show the per-row table that adds up to it so the user can verify.
- TOTALS/COUNTS: NEVER trust len(rows) from get_list — its default is 20 and the call only returns what you explicitly asked for. For "how many X" questions ALWAYS call count_doc (or aggregate with field='name', op='count') to get the true total. THEN call get_list with an EXPLICIT limit sized to the actual ask (e.g. count_doc returns 774 → call get_list with limit=774 or limit=0 for unbounded). limit has NO upper bound — pass whatever the user needs. The chat-ui will truncate display at ~250 KB if the result is too big for your context window (you'll see a "[truncated]" notice — when that happens, pivot to export_list_to_csv instead of apologizing).
- USER-FACING TOTALS: After fetching, ALWAYS verify your reported total matches count_doc. If a user says "I expected 76 but got 50" — that means you used the default limit. Re-call count_doc, get the real total, then re-list with that explicit limit.
- NEVER invent file, image, or URL paths. If a tool result has an empty/null file/image/attachment field, say "no image attached" or "no attachments" — never construct a path from the document name, item code, or any other identifier. If you need an absolute URL for a file, look for a sibling "<field>_url" key in the tool result; the backend resolves these via frappe.utils.get_url.

NAVIGATION — when you mention any ERPNext document the user might want to open, format it as a clickable Desk link:
- [<doc name or label>](/app/<doctype-kebab-case>/<name>) — example: [SO26001040](/app/sales-order/SO26001040), [L1001140207](/app/item/L1001140207). Doctype names go to lowercase-kebab-case ("Sales Order" -> "sales-order").
- [<filename>](/files/<filename>) for public attachments, or use the absolute "absolute_url" field returned by get_file_url for private files.
- The chat UI intercepts these links and navigates the parent ERPNext window — do NOT add http(s):// to internal links.

KNOWLEDGE BASE CITATIONS — when answering from search_kb results:
- ALWAYS cite the source file as a clickable markdown link. Format: [<file_name>](<file_url>) where <file_url> is the file_url field returned with each chunk (e.g. /files/hr-handbook.pdf or /private/files/...). The chat UI's link interceptor opens it in a new tab.
- Quote the relevant sentence verbatim from the snippet rather than paraphrasing — the user needs to know what's IN the file vs. your inference.
- If multiple chunks support the same answer, cite each source file once at the end (e.g. "Sources: [hr-handbook.pdf](/files/hr-handbook.pdf), [policies-2026.pdf](/files/policies-2026.pdf)").
- If search_kb returned 0 chunks for a question that obviously needs internal docs, say so and suggest the user upload the relevant file to a KB via Desk -> New Lazychat Knowledge Base.
- NEVER fabricate quotes or file paths. If you don't have a verbatim snippet, say so.

INLINE CHARTS — when the user asks for a visualization (plot, chart, bar/line/pie, "show me X over time", "graph Y by Z"):
1. First call the relevant data tool (aggregate, dashboard_chart_data, get_list, run_report) to get the actual numbers. Never plot fake or guessed data.
2. Optionally call make_chart(spec) so the chart shows up as a tool-call card in the history (useful for debugging the spec).
3. Emit the chart inline in your reply using the artifact marker:
   [[lazychat:artifact kind="chart"]]<vega-lite-v5-json-spec>[[/lazychat:artifact]]
   The body MUST be a valid JSON object — no prose before or inside the marker, no triple-backtick fences.
4. Spec requirements:
   - $schema: "https://vega.github.io/schema/vega-lite/v5.json"
   - data.values: inline array of records (NOT a URL — the chat-ui has no network access for charts)
   - mark: "bar" / "line" / "point" / "area" / "arc" / etc, OR an object {type: "...", ...}
   - encoding: {x, y, color?, size?, ...} referencing fields from data.values
   - Optional width/height (omit to fill container)
5. Keep data.values under 150 rows. For larger sets call aggregate first to roll up by the dimension you want to chart.
6. After the marker, write a 1-2 sentence prose caption — what the chart shows and the user's takeaway.

Desk context JSON: """
	ctx = json.dumps(context or {}, default=str)[:8000]
	s = base + ctx
	if not supports_tools:
		s += TOOLLESS_PROMPT_SUFFIX
	# Tier E — append active skill snippets (per-user, Redis-backed). No-op when
	# the user has no skills active. compose_active_prompt is defensive: filters
	# out stale / disabled / inaccessible skill names automatically.
	try:
		from lazychat_mcp_erpnext.desk_assistant import skills as _skills

		s = _skills.compose_active_prompt(s)
	except Exception:
		# Never let skill-prompt composition break the agent loop; log and
		# fall through to the unmodified base prompt.
		frappe.log_error(frappe.get_traceback(), "lazychat skills.compose_active_prompt")
	# Mode-specific blocks composed last so they sit at the end where the model
	# weighs them most heavily. PLAN suppressed when resumed (after Approve).
	if mode == "plan" and not plan_resumed:
		s += "\n\n" + PLAN_MODE_BLOCK
	elif mode == "ask":
		s += "\n\n" + ASK_MODE_BLOCK
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
	mode="edit-auto",
	effort="medium",
	plan_resumed=False,
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

	# Effort mapping (turn budget + Anthropic thinking budget). Defaults preserve
	# the pre-Effort behavior (medium = 16 turns, no thinking). For Plan mode's
	# first turn, also cap turns at 1 (the model should emit the plan and stop).
	eff = EFFORT_MAP.get(effort, EFFORT_MAP["medium"])
	turn_budget = eff["max_turns"]
	if mode == "plan" and not plan_resumed:
		turn_budget = 1

	for _turn in range(turn_budget):
		resp = adapter.chat(
			provider=provider,
			model=model,
			messages=history,
			system=_system_prompt(context, supports_tools, mode=mode, plan_resumed=plan_resumed),
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
