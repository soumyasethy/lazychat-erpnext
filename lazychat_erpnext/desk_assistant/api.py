import json
import queue
import re
import threading

import frappe
from frappe import _

from lazychat_erpnext.desk_assistant.claude_bridge import run_agentic_turn
from lazychat_erpnext.desk_assistant.password_utils import safe_provider_api_key


def _get_or_create_conversation(conversation_id):
	user = frappe.session.user
	if conversation_id and frappe.db.exists("Claude Conversation", conversation_id):
		c = frappe.get_doc("Claude Conversation", conversation_id)
		if c.user != user and frappe.session.user != "Administrator":
			frappe.throw(_("Not permitted"))
		return c
	doc = frappe.get_doc(
		{
			"doctype": "Claude Conversation",
			"user": user,
			"title": "Desk chat",
			"history": "[]",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _load_history(convo):
	try:
		return json.loads(convo.history or "[]")
	except Exception:
		return []


@frappe.whitelist()
def send_message(
	message,
	conversation_id=None,
	context=None,
	model_label=None,
	confirmed_writes=False,
	attachments=None,
):
	msg = str(message or "").strip()
	if isinstance(attachments, str):
		try:
			attachments = json.loads(attachments) if attachments else []
		except json.JSONDecodeError:
			attachments = []
	if not isinstance(attachments, list):
		attachments = []
	if not msg and not attachments:
		frappe.throw(_("Message or attachment is required"))
	if isinstance(context, str):
		try:
			context = json.loads(context) if context else {}
		except json.JSONDecodeError:
			context = {}
	convo = _get_or_create_conversation(conversation_id)
	history = _load_history(convo)
	events = []

	def emit(evt):
		events.append(evt)

	new_history, usage = run_agentic_turn(
		msg,
		history,
		context or {},
		attachments=attachments,
		model_label=model_label or None,
		allow_writes=bool(confirmed_writes),
		desk_context=context or {},
		emit=emit,
	)
	convo.history = json.dumps(new_history, default=str)
	convo.last_model = model_label or ""
	convo.total_input_tokens = (convo.total_input_tokens or 0) + usage["input_tokens"]
	convo.total_output_tokens = (convo.total_output_tokens or 0) + usage["output_tokens"]
	convo.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"conversation_id": convo.name,
		"events": events,
		"usage": usage,
	}


def _sse_pack(event, data_obj):
	return f"event: {event}\ndata: {json.dumps(data_obj, default=str)}\n\n".encode("utf-8")


@frappe.whitelist(methods=["POST"])
def send_message_stream(
	message,
	conversation_id=None,
	context=None,
	model_label=None,
	confirmed_writes=False,
	attachments=None,
	mode=None,
	effort=None,
	plan_resumed=False,
):
	"""SSE variant of send_message — emits text_delta / tool_use / tool_result events live."""
	from werkzeug.wrappers import Response

	msg = str(message or "").strip()
	if isinstance(attachments, str):
		try:
			attachments = json.loads(attachments) if attachments else []
		except json.JSONDecodeError:
			attachments = []
	if not isinstance(attachments, list):
		attachments = []
	if not msg and not attachments:
		frappe.throw(_("Message or attachment is required"))
	if isinstance(context, str):
		try:
			context = json.loads(context) if context else {}
		except json.JSONDecodeError:
			context = {}

	# Defensive clamp on mode/effort — fall back to defaults on unknown values.
	# These pass through to claude_bridge.run_agentic_turn which honors them.
	mode_safe = mode if mode in ("ask", "edit-auto", "plan", "auto") else "edit-auto"
	effort_safe = effort if effort in ("low", "medium", "high", "max") else "medium"
	plan_resumed_safe = bool(plan_resumed)

	convo = _get_or_create_conversation(conversation_id)
	history = _load_history(convo)
	user = frappe.session.user
	site = frappe.local.site
	q: "queue.Queue" = queue.Queue()
	SENTINEL = object()
	state: dict = {}

	def emit(evt):
		q.put(evt)

	def worker():
		# Each background thread needs its own Frappe init bound to the same user/site.
		frappe.init(site=site)
		frappe.connect()
		try:
			frappe.set_user(user)
			new_history, usage = run_agentic_turn(
				msg,
				history,
				context or {},
				attachments=attachments,
				model_label=model_label or None,
				allow_writes=bool(confirmed_writes),
				desk_context=context or {},
				emit=emit,
				mode=mode_safe,
				effort=effort_safe,
				plan_resumed=plan_resumed_safe,
			)
			c = frappe.get_doc("Claude Conversation", convo.name)
			c.history = json.dumps(new_history, default=str)
			c.last_model = model_label or ""
			c.total_input_tokens = (c.total_input_tokens or 0) + usage["input_tokens"]
			c.total_output_tokens = (c.total_output_tokens or 0) + usage["output_tokens"]
			c.save(ignore_permissions=True)
			frappe.db.commit()
			state["usage"] = usage
		except Exception as e:
			state["error"] = str(e)
			frappe.log_error(frappe.get_traceback(), "send_message_stream worker")
		finally:
			q.put(SENTINEL)
			frappe.destroy()

	threading.Thread(target=worker, daemon=True).start()

	def stream():
		yield _sse_pack("conversation", {"conversation_id": convo.name})
		while True:
			evt = q.get()
			if evt is SENTINEL:
				break
			etype = evt.get("type")
			if etype == "text_delta":
				yield _sse_pack("text_delta", {"delta": evt.get("delta", "")})
			elif etype == "tool_use":
				yield _sse_pack(
					"tool_use",
					{"id": evt.get("id"), "name": evt.get("name"), "input": evt.get("input")},
				)
			elif etype == "tool_result":
				yield _sse_pack("tool_result", {"name": evt.get("name"), "result": evt.get("result")})
			elif etype == "usage":
				yield _sse_pack("usage", evt)
		if "error" in state:
			yield _sse_pack("error", {"message": state["error"], "retryable": True})
		else:
			yield _sse_pack("done", {"finishReason": "stop", "usage": state.get("usage", {})})

	resp = Response(stream(), mimetype="text/event-stream", direct_passthrough=True)
	resp.headers["Cache-Control"] = "no-cache, no-transform"
	resp.headers["X-Accel-Buffering"] = "no"
	resp.headers["Connection"] = "keep-alive"
	frappe.local.response = resp
	return resp


@frappe.whitelist(allow_guest=False)
def list_models():
	rows = frappe.get_all(
		"LLM Model",
		filters={"enabled": 1},
		fields=["name", "model_label", "model_id", "provider", "supports_tools", "is_default"],
		order_by="is_default desc, model_label asc",
	)
	out = []
	for r in rows:
		prov = frappe.get_cached_doc("LLM Provider", r["provider"])
		if not prov.enabled:
			continue
		key = safe_provider_api_key(prov)
		base = (prov.base_url or "").lower()
		local = "localhost" in base or "127.0.0.1" in base
		if not key and not local:
			continue
		r["provider_name"] = prov.provider_name
		out.append(r)
	return out


@frappe.whitelist()
def ping():
	return {"ok": True, "app": "lazychat_erpnext"}


# ---------------------------------------------------------------------------
# Usage tracking — chat-ui reports per-turn token counts here after every LLM
# call (both browser-LLM path via runChatWithMcp and standalone runChatWith-
# Turns). Backend run_agentic_turn writes directly via the same Document
# insert in claude_bridge.py — single doctype, two writers.
# ---------------------------------------------------------------------------

# Provider rate hints when LLM Model lookup misses (e.g. user runs a custom
# model not in the LLM Model registry). Conservative: zero cost when unknown
# rather than guessing. Override per-model via LLM Model.input_price_per_mtok
# / output_price_per_mtok.
_USD_RATES = {  # input_per_mtok, output_per_mtok (in USD)
	"claude-haiku-4-5": (0.25, 1.25),
	"claude-haiku-4.5": (0.25, 1.25),
	"claude-sonnet-4-6": (3.00, 15.00),
	"claude-sonnet-4.6": (3.00, 15.00),
	"claude-opus-4-7": (15.00, 75.00),
	"claude-opus-4.7": (15.00, 75.00),
	"gpt-4o": (2.50, 10.00),
	"gpt-4o-mini": (0.15, 0.60),
}


def _resolve_cost(model_label: str, input_tokens: int, output_tokens: int) -> float:
	"""Look up the cost per LLM Model row first; fall back to _USD_RATES;
	return 0 when unknown. NEVER raise — cost is best-effort."""
	try:
		row = frappe.db.get_value(
			"LLM Model",
			{"model_label": model_label},
			["input_price_per_mtok", "output_price_per_mtok"],
			as_dict=True,
		)
		if row and (row.get("input_price_per_mtok") or row.get("output_price_per_mtok")):
			ip = float(row.get("input_price_per_mtok") or 0)
			op = float(row.get("output_price_per_mtok") or 0)
			return (input_tokens / 1_000_000.0) * ip + (output_tokens / 1_000_000.0) * op
	except Exception:
		pass
	rates = _USD_RATES.get((model_label or "").lower())
	if rates:
		ip, op = rates
		return (input_tokens / 1_000_000.0) * ip + (output_tokens / 1_000_000.0) * op
	return 0.0


@frappe.whitelist(methods=["POST"])
def record_usage(model_label=None, provider=None, input_tokens=0, output_tokens=0,
                 session_id=None, path="browser"):
	"""Persist one usage row. Called by chat-ui after each LLM turn completes.

	Defensive: zero-tokens calls (no usage info from upstream) skip the write
	entirely — no point storing empty rows.
	"""
	try:
		input_tokens = int(input_tokens or 0)
		output_tokens = int(output_tokens or 0)
	except (TypeError, ValueError):
		return {"ok": False, "error": "input_tokens / output_tokens must be integers"}
	if input_tokens <= 0 and output_tokens <= 0:
		return {"ok": True, "skipped": "zero tokens — nothing to record"}
	if frappe.session.user in ("", "Guest"):
		return {"ok": False, "error": "must be authenticated"}

	cost = _resolve_cost(model_label or "", input_tokens, output_tokens)
	doc = frappe.get_doc({
		"doctype": "Lazychat Usage Log",
		"user": frappe.session.user,
		"model_label": (model_label or "")[:140],
		"provider": (provider or "")[:140],
		"input_tokens": input_tokens,
		"output_tokens": output_tokens,
		"cost_estimate": round(cost, 6),
		"currency": "USD",
		"session_id": (session_id or "")[:140],
		"path": (path or "browser")[:32],
	})
	doc.insert(ignore_permissions=True)
	return {"ok": True, "name": doc.name}


@frappe.whitelist(methods=["GET", "POST"])
def get_usage_summary(days=30):
	"""Aggregate usage for the calling user (or ALL users when caller is
	System Manager). Returns per-model rollup + totals + a tiny daily series
	for the last `days` days.

	Output:
	  {
	    user_scope: 'self' | 'all',
	    days: int,
	    totals: {input_tokens, output_tokens, cost_estimate, calls},
	    by_model: [{model_label, provider, calls, input, output, cost}],
	    daily: [{day: 'YYYY-MM-DD', input, output, cost}],
	  }
	"""
	try:
		days = max(1, min(365, int(days or 30)))
	except (TypeError, ValueError):
		days = 30
	from frappe.utils import nowdate, add_days

	is_sysmgr = "System Manager" in frappe.get_roles(frappe.session.user)
	scope = "all" if is_sysmgr else "self"

	since = add_days(nowdate(), -days + 1)  # inclusive: today - (days-1) covers `days` days
	filters = ["creation >= %(since)s"]
	values = {"since": since + " 00:00:00"}
	if not is_sysmgr:
		filters.append("user = %(user)s")
		values["user"] = frappe.session.user
	where = " AND ".join(filters)

	# nosemgrep: frappe-sql-format-injection -- {where} below is built only from constant predicates with %(...)s placeholders; every value is bound via the params dict
	by_model_rows = frappe.db.sql(f"""
		SELECT model_label, provider,
		       COUNT(*) AS calls,
		       SUM(input_tokens) AS input_tokens,
		       SUM(output_tokens) AS output_tokens,
		       ROUND(SUM(cost_estimate), 4) AS cost_estimate
		  FROM `tabLazychat Usage Log`
		 WHERE {where}
		 GROUP BY model_label, provider
		 ORDER BY (SUM(input_tokens) + SUM(output_tokens)) DESC
	""", values, as_dict=True)

	# nosemgrep: frappe-sql-format-injection -- {where} is constant predicates with %(...)s placeholders; values bound via params
	daily_rows = frappe.db.sql(f"""
		SELECT DATE(creation) AS day,
		       SUM(input_tokens) AS input_tokens,
		       SUM(output_tokens) AS output_tokens,
		       ROUND(SUM(cost_estimate), 4) AS cost_estimate
		  FROM `tabLazychat Usage Log`
		 WHERE {where}
		 GROUP BY DATE(creation)
		 ORDER BY day ASC
	""", values, as_dict=True)

	totals = {
		"input_tokens": sum(int(r["input_tokens"] or 0) for r in by_model_rows),
		"output_tokens": sum(int(r["output_tokens"] or 0) for r in by_model_rows),
		"cost_estimate": round(sum(float(r["cost_estimate"] or 0) for r in by_model_rows), 4),
		"calls": sum(int(r["calls"] or 0) for r in by_model_rows),
	}
	# Cast day to str for JSON safety
	for r in daily_rows:
		r["day"] = str(r["day"])
	return {
		"user_scope": scope,
		"days": days,
		"since": since,
		"totals": totals,
		"by_model": by_model_rows,
		"daily": daily_rows,
	}


@frappe.whitelist(methods=["POST"])
def save_conversation(conversation_id=None, messages=None, title=None, model_label=None, usage=None):
	"""Persist a conversation turn into Claude Conversation (Browser-LLM path entry).

	Mirrors what send_message_stream does after run_agentic_turn finishes — gives
	chat-ui a way to push the same shape of history when chat-ui owns the LLM call.
	Both paths produce the same audit log.
	"""
	if isinstance(messages, str):
		try:
			messages = json.loads(messages)
		except json.JSONDecodeError:
			frappe.throw(_("messages must be a JSON list"))
	if not isinstance(messages, list):
		messages = []
	if isinstance(usage, str):
		try:
			usage = json.loads(usage)
		except json.JSONDecodeError:
			usage = {}
	usage = usage or {}

	convo = _get_or_create_conversation(conversation_id)
	if title and not convo.title:
		convo.title = str(title)[:140]
	convo.history = json.dumps(messages, default=str)
	if model_label:
		convo.last_model = str(model_label)
	if isinstance(usage, dict):
		convo.total_input_tokens = (convo.total_input_tokens or 0) + int(usage.get("input_tokens", 0) or 0)
		convo.total_output_tokens = (convo.total_output_tokens or 0) + int(usage.get("output_tokens", 0) or 0)
	convo.save(ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True, "conversation_id": convo.name}


@frappe.whitelist(methods=["POST"])
def commit_prepared_action(token, file_url=None, fields=None):
	"""Apply a previously staged action (returned by prepare_*) by token.
	Called by /commit and /upload slash commands.

	Optional extras (action-specific):
	  - file_url: panel shim's /upload TOKEN flow passes the URL of a freshly
	    uploaded file so the attach_file action can wire it to the target doc.
	  - fields: chat-ui's field-picker UI passes the selected fields list (or
	    comma-separated string) so the export_csv action runs the actual CSV.
	"""
	from lazychat_erpnext.desk_assistant.tools import commit_prepared

	tok = str(token or "").strip()
	if not tok:
		return {"ok": False, "error": "Token required"}
	extras = {}
	if file_url:
		extras["file_url"] = str(file_url).strip()
	if fields is not None:
		extras["fields"] = fields
	return commit_prepared(tok, **extras)


def _anthropic_curated_model_ids():
	return [
		"claude-sonnet-4-20250514",
		"claude-3-5-sonnet-20241022",
		"claude-3-5-haiku-20241022",
		"claude-3-opus-20240229",
	]


def _openai_compatible_models_urls(base_url):
	"""Candidate URLs for OpenAI-style GET …/models (handles roots missing /v1, e.g. NVIDIA)."""
	root = (base_url or "").strip().rstrip("/")
	if not root:
		return []
	urls = []
	if re.search(r"/v\d+$", root, re.I):
		urls.append(root + "/models")
	else:
		urls.append(root + "/v1/models")
		urls.append(root + "/models")
	seen = set()
	out = []
	for u in urls:
		if u not in seen:
			seen.add(u)
			out.append(u)
	return out


@frappe.whitelist()
def discover_remote_models(provider_name=None):
	"""GET /models from OpenAI-compatible or Anthropic base URL; curated fallback for Anthropic if the API fails."""
	import requests

	from frappe.utils import cstr

	provider_name = cstr(provider_name or "").strip()
	if not provider_name:
		frappe.throw(_("Provider name is required"))
	if not frappe.db.exists("LLM Provider", provider_name):
		frappe.throw(_("Unknown LLM Provider"))

	provider = frappe.get_doc("LLM Provider", provider_name)
	key = safe_provider_api_key(provider)
	base = (provider.base_url or "").strip().rstrip("/")
	local = "localhost" in base.lower() or "127.0.0.1" in base.lower()
	ptype = provider.provider_type or ""

	def curated_anthropic():
		return [
			{"id": x}
			for x in _anthropic_curated_model_ids()
		]

	if not base:
		return {
			"ok": False,
			"error": _("Set Base URL first."),
			"models": [],
			"from_fallback": False,
		}

	if ptype == "openai_compatible":
		if not key and not local:
			return {
				"ok": False,
				"error": _("Save an API key first (localhost may work without one)."),
				"models": [],
				"from_fallback": False,
			}
		headers = {"Authorization": f"Bearer {key}"}
		last_err = None
		for url in _openai_compatible_models_urls(base):
			try:
				r = requests.get(url, headers=headers, timeout=45)
				r.raise_for_status()
				payload = r.json()
				items = payload.get("data") or payload.get("models") or []
				ids = []
				for row in items:
					if isinstance(row, dict):
						mid = row.get("id") or row.get("name") or ""
					else:
						mid = str(row)
					mid = str(mid).strip()
					if mid:
						ids.append(mid)
				ids = sorted(set(ids))
				return {"ok": True, "error": None, "models": [{"id": x} for x in ids], "from_fallback": False}
			except Exception as e:
				last_err = e
				continue
		err_text = str(last_err) if last_err else _("Could not list models")
		if last_err and "404" in err_text:
			err_text += " "
			err_text += _(
				"Tip: set Base URL to the API root including /v1 (e.g. https://integrate.api.nvidia.com/v1)."
			)
		if last_err:
			frappe.log_error(message=str(last_err), title="discover_remote_models openai_compatible")
		return {
			"ok": False,
			"error": err_text,
			"models": [],
			"from_fallback": False,
		}

	if ptype == "anthropic":
		if not key and not local:
			return {
				"ok": False,
				"error": _("Save an API key first."),
				"models": curated_anthropic(),
				"from_fallback": True,
			}
		url = f"{base}/models"
		headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
		try:
			r = requests.get(url, headers=headers, timeout=45)
			r.raise_for_status()
			payload = r.json()
			items = payload.get("data") or []
			ids = []
			for row in items:
				if isinstance(row, dict):
					mid = row.get("id") or ""
				else:
					mid = ""
				mid = str(mid).strip()
				if mid:
					ids.append(mid)
			ids = sorted(set(ids))
			if ids:
				return {"ok": True, "error": None, "models": [{"id": x} for x in ids], "from_fallback": False}
		except Exception:
			frappe.log_error(frappe.get_traceback(), "discover_remote_models anthropic api")

		return {
			"ok": True,
			"error": _("Could not list models from Anthropic — pick a common ID below or type your Model ID on LLM Model."),
			"models": curated_anthropic(),
			"from_fallback": True,
		}

	return {"ok": False, "error": _("Unsupported provider type"), "models": [], "from_fallback": False}


def _extra_headers_dict(provider):
	try:
		raw = provider.extra_headers or ""
		if not str(raw).strip():
			return {}
		data = json.loads(raw)
		return data if isinstance(data, dict) else {}
	except Exception:
		return {}


@frappe.whitelist()
def test_llm_provider_connection(provider_name=None):
	"""HTTP probe: list models (same path as desk discovery). No curated fallbacks — real API status only."""
	import requests

	from frappe.utils import cstr

	provider_name = cstr(provider_name or "").strip()
	if not provider_name:
		frappe.throw(_("Save the provider first."))
	if not frappe.db.exists("LLM Provider", provider_name):
		frappe.throw(_("Unknown LLM Provider"))

	provider = frappe.get_doc("LLM Provider", provider_name)
	key = safe_provider_api_key(provider)
	base = (provider.base_url or "").strip().rstrip("/")
	local = "localhost" in base.lower() or "127.0.0.1" in base.lower()
	ptype = provider.provider_type or ""

	if not base:
		return {"ok": False, "title": _("Connection test"), "message": _("Set Base URL first.")}

	if ptype == "openai_compatible":
		if not key and not local:
			return {
				"ok": False,
				"title": _("Connection test"),
				"message": _("Save an API key first (localhost may work without one)."),
			}
		headers = {"Authorization": f"Bearer {key}"}
		headers.update(_extra_headers_dict(provider))
		last_err = None
		last_url = None
		for url in _openai_compatible_models_urls(base):
			last_url = url
			try:
				r = requests.get(url, headers=headers, timeout=30)
				r.raise_for_status()
				payload = r.json()
				items = payload.get("data") or payload.get("models") or []
				n = 0
				for row in items:
					if isinstance(row, dict):
						mid = row.get("id") or row.get("name") or ""
					else:
						mid = str(row)
					if str(mid).strip():
						n += 1
				return {
					"ok": True,
					"title": _("Connection OK"),
					"message": _("API reachable — {0} model(s) listed.").format(n),
					"model_count": n,
					"endpoint": url,
				}
			except Exception as e:
				last_err = e
				continue
		err_text = str(last_err) if last_err else _("Request failed")
		if last_err and "404" in err_text:
			err_text += " "
			err_text += _("Tip: Base URL should usually end with /v1 (e.g. https://integrate.api.nvidia.com/v1).")
		return {"ok": False, "title": _("Connection failed"), "message": err_text, "endpoint": last_url}

	if ptype == "anthropic":
		if not key and not local:
			return {"ok": False, "title": _("Connection test"), "message": _("Save an API key first.")}
		url = f"{base}/models"
		headers = {
			"x-api-key": key,
			"anthropic-version": "2023-06-01",
		}
		headers.update(_extra_headers_dict(provider))
		try:
			r = requests.get(url, headers=headers, timeout=30)
			r.raise_for_status()
			payload = r.json()
			items = payload.get("data") or []
			n = sum(
				1
				for row in items
				if isinstance(row, dict) and str(row.get("id") or "").strip()
			)
			return {
				"ok": True,
				"title": _("Connection OK"),
				"message": _("Anthropic API reachable — {0} model(s) listed.").format(n),
				"model_count": n,
				"endpoint": url,
			}
		except Exception as e:
			return {"ok": False, "title": _("Connection failed"), "message": str(e), "endpoint": url}

	return {"ok": False, "title": _("Connection test"), "message": _("Unsupported provider type.")}


@frappe.whitelist()
def reveal_llm_provider_api_key(provider_name=None):
	"""Return decrypted api_key for authorized Desk users.

	Frappe Password controls never place the real secret in the browser after save — the input
	often holds literal asterisks or stays empty. The show/hide toggle calls this so editors can
	copy or verify the key.
	"""
	from frappe.utils import cstr

	name = cstr(provider_name or "").strip()
	if not name:
		frappe.throw(_("Save the provider first."))
	if not frappe.db.exists("LLM Provider", name):
		frappe.throw(_("Unknown LLM Provider"))

	doc = frappe.get_doc("LLM Provider", name)
	if not frappe.has_permission(doc.doctype, "write", doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	key = safe_provider_api_key(doc)
	return {"api_key": key or ""}


# ============================================================================
# Cycle 10 — chat-ui admin panel endpoints
# ============================================================================
# Lets a System Manager manage Lazychat Settings + LLM Providers + LLM Models
# from inside the chat-ui (CommandPalette → Server config), removing the need
# to open the Frappe Desk doctype forms. All writes re-check System Manager
# server-side; reads are wider but mask api_key values.

_ALLOWED_SETTINGS_FIELDS = {
	"enabled", "iframe_base_url", "iframe_query_params", "chat_path",
	"llm_proxy_allowed_hosts", "legacy_widget_enabled",
	"allow_email", "allow_dangerous_tools", "allow_email_setup", "cycle9_enabled",
}

_ALLOWED_PROVIDER_FIELDS = {
	"provider_name", "provider_type", "base_url", "api_key", "enabled",
}

_ALLOWED_MODEL_FIELDS = {
	"model_label", "provider", "model_id", "supports_tools",
	"max_output_tokens", "context_window",
	"input_price_per_mtok", "output_price_per_mtok",
	"is_default", "enabled",
}

_SITE_CONFIG_SHADOW_MAP = {
	"enabled": "lazychat_panel_enabled",
	"legacy_widget_enabled": "lazychat_legacy_widget_enabled",
	"allow_email": "lazychat_allow_email",
	"allow_dangerous_tools": "lazychat_allow_dangerous_tools",
	"allow_email_setup": "lazychat_allow_email_setup",
	"cycle9_enabled": "lazychat_cycle9_enabled",
}


def _require_system_manager():
	if "System Manager" not in frappe.get_roles(frappe.session.user):
		frappe.throw(_("Lazychat admin actions require System Manager role"),
		             frappe.PermissionError)


def _is_system_manager() -> bool:
	return "System Manager" in frappe.get_roles(frappe.session.user)


def _coerce_check(value):
	"""Frappe Check fields store as 0/1 ints. Accept many truthy inputs."""
	return 1 if value in (True, 1, "1", "true", "True", "on", "yes") else 0


@frappe.whitelist()
def get_lazychat_admin_snapshot():
	"""Single round-trip read of all admin-editable lazychat config.

	Returns settings dict (with site_config-shadow flags), the LLM Providers
	list (api_key MASKED to '****' — caller uses reveal_llm_provider_api_key
	to fetch the real value), the LLM Models list, and is_system_manager.
	Non-admin users still get the snapshot but with is_system_manager=false
	so the chat-ui renders read-only.
	"""
	from lazychat_erpnext.desk_assistant.boot import get_lazychat_settings

	settings = get_lazychat_settings()
	conf = {}
	try:
		conf = frappe.get_site_config() or {}
	except Exception:
		pass
	shadowed = {
		field: True
		for field, site_key in _SITE_CONFIG_SHADOW_MAP.items()
		if site_key in conf
	}

	providers = []
	for p in frappe.get_all(
		"LLM Provider",
		fields=["name", "provider_name", "provider_type", "base_url", "enabled"],
		order_by="provider_name asc",
	):
		try:
			doc = frappe.get_doc("LLM Provider", p.name)
			has_key = bool(doc.get_password("api_key", raise_exception=False))
		except Exception:
			has_key = False
		providers.append({
			**p,
			"has_api_key": has_key,
			"api_key_masked": "****" if has_key else "",
		})

	models = frappe.get_all(
		"LLM Model",
		fields=[
			"name", "model_label", "provider", "model_id", "supports_tools",
			"max_output_tokens", "context_window",
			"input_price_per_mtok", "output_price_per_mtok",
			"is_default", "enabled",
		],
		order_by="is_default desc, model_label asc",
	)

	return {
		"ok": True,
		"settings": settings,
		"settings_shadowed": shadowed,
		"llm_providers": providers,
		"llm_models": models,
		"is_system_manager": _is_system_manager(),
	}


@frappe.whitelist(methods=["POST"])
def update_lazychat_settings(field=None, value=None):
	"""Patch a single Lazychat Settings field. System Manager only.

	Returns {ok, field, value, shadowed_by_site_config?}. When the same key
	is also set in site_config.json, the doctype value is still saved but
	the chat-ui surfaces a "(shadowed by site_config)" badge.
	"""
	_require_system_manager()
	f = str(field or "").strip()
	if f not in _ALLOWED_SETTINGS_FIELDS:
		return {"ok": False, "error": f"Field '{f}' is not editable from the chat-ui admin panel"}

	doc = frappe.get_single("Lazychat Settings")

	bool_fields = {"enabled", "legacy_widget_enabled", "allow_email",
	               "allow_dangerous_tools", "allow_email_setup", "cycle9_enabled"}
	if f in bool_fields:
		value = _coerce_check(value)
	elif f == "chat_path":
		if value not in ("auto", "browser", "backend"):
			return {"ok": False, "error": "chat_path must be one of: auto, browser, backend"}
	elif f == "llm_proxy_allowed_hosts":
		try:
			parsed = json.loads(value) if isinstance(value, str) else value
			if not isinstance(parsed, list) or not all(isinstance(x, str) for x in parsed):
				raise ValueError("must be a JSON array of strings")
			value = json.dumps(parsed)
		except Exception as e:
			return {"ok": False, "error": f"llm_proxy_allowed_hosts: {e}"}

	doc.set(f, value)
	doc.save(ignore_permissions=False)
	frappe.db.commit()

	conf = {}
	try:
		conf = frappe.get_site_config() or {}
	except Exception:
		pass
	shadow_key = _SITE_CONFIG_SHADOW_MAP.get(f)
	return {
		"ok": True,
		"field": f,
		"value": value,
		"shadowed_by_site_config": bool(shadow_key and shadow_key in conf),
	}


@frappe.whitelist(methods=["POST"])
def upsert_llm_provider(name=None, fields=None):
	"""Create or update an LLM Provider. System Manager only.

	`name` is the existing provider's docname (None to create). `fields` is
	a JSON object (or dict) with whitelisted keys. Blank or '****' api_key
	is treated as "don't change" (lets the editor save other fields without
	re-entering the key every time).
	"""
	_require_system_manager()
	payload = json.loads(fields) if isinstance(fields, str) else (fields or {})
	if not isinstance(payload, dict):
		return {"ok": False, "error": "fields must be an object"}

	safe = {k: v for k, v in payload.items() if k in _ALLOWED_PROVIDER_FIELDS}

	# Treat blank/masked api_key as "don't change"
	if "api_key" in safe and (not safe["api_key"] or safe["api_key"] == "****"):
		safe.pop("api_key")

	if name and frappe.db.exists("LLM Provider", name):
		doc = frappe.get_doc("LLM Provider", name)
	else:
		if "provider_name" not in safe or not safe["provider_name"]:
			return {"ok": False, "error": "provider_name is required to create a new provider"}
		doc = frappe.new_doc("LLM Provider")

	for k, v in safe.items():
		doc.set(k, v)

	if doc.is_new():
		doc.insert(ignore_permissions=False)
	else:
		doc.save(ignore_permissions=False)
	frappe.db.commit()
	return {"ok": True, "name": doc.name}


@frappe.whitelist(methods=["POST"])
def delete_llm_provider(name=None):
	"""Delete an LLM Provider. System Manager only. Refuses if any LLM Model
	still references it; returns blocking_models list when blocked."""
	_require_system_manager()
	if not name or not frappe.db.exists("LLM Provider", name):
		return {"ok": False, "error": "Provider not found"}

	refs = frappe.get_all("LLM Model", filters={"provider": name}, fields=["name"])
	if refs:
		return {
			"ok": False,
			"error": f"Cannot delete — {len(refs)} LLM Model(s) still reference this provider",
			"blocking_models": [r.name for r in refs],
		}
	frappe.delete_doc("LLM Provider", name, ignore_permissions=False)
	frappe.db.commit()
	return {"ok": True, "name": name}


@frappe.whitelist(methods=["POST"])
def upsert_llm_model(name=None, fields=None):
	"""Create or update an LLM Model. System Manager only.

	Setting is_default=1 clears the flag on all OTHER LLM Models so only one
	model is the default at a time (matches the existing doctype script's
	behavior).
	"""
	_require_system_manager()
	payload = json.loads(fields) if isinstance(fields, str) else (fields or {})
	if not isinstance(payload, dict):
		return {"ok": False, "error": "fields must be an object"}

	safe = {k: v for k, v in payload.items() if k in _ALLOWED_MODEL_FIELDS}

	if name and frappe.db.exists("LLM Model", name):
		doc = frappe.get_doc("LLM Model", name)
	else:
		if "model_label" not in safe or not safe["model_label"]:
			return {"ok": False, "error": "model_label is required to create a new model"}
		doc = frappe.new_doc("LLM Model")

	for k, v in safe.items():
		doc.set(k, v)

	if doc.is_new():
		doc.insert(ignore_permissions=False)
	else:
		doc.save(ignore_permissions=False)

	# Enforce single-default invariant
	if _coerce_check(safe.get("is_default")) == 1:
		frappe.db.sql(
			"UPDATE `tabLLM Model` SET is_default = 0 WHERE name != %s",
			(doc.name,),
		)
	frappe.db.commit()
	return {"ok": True, "name": doc.name}


@frappe.whitelist(methods=["POST"])
def delete_llm_model(name=None):
	"""Delete an LLM Model. System Manager only."""
	_require_system_manager()
	if not name or not frappe.db.exists("LLM Model", name):
		return {"ok": False, "error": "Model not found"}
	frappe.delete_doc("LLM Model", name, ignore_permissions=False)
	frappe.db.commit()
	return {"ok": True, "name": name}


# ============================================================
# Cycle 11 — M2: stage-and-redirect form prefill (kills HTTP 414)
# ============================================================
#
# Replaces the `_lz_items=<base64-json>` URL convention with a
# server-staged token. For Query Report HTML buttons that prefill a
# new-doc form with 50+ items, the base64 payload exceeds 8 KB and the
# Frappe dev server returns 414 Request-URI Too Long. The new flow:
#
#   1. Assistant calls `prepare_form_prefill(doctype, parent_fields,
#      items)` -> returns `{ok, token, url}` where `url` is a tiny
#      `/app/<dt>/new?_lz_token=<22-char>` (always under 100 chars).
#   2. Assistant emits the URL in a Query Report HTML link button.
#   3. User clicks. Frappe routes to the new-doc form. The persistent
#      Client Script (install.py) detects `_lz_token` in the URL,
#      calls `fetch_form_prefill(token)`, applies the payload via
#      `frappe.route_options` BEFORE form load.
#
# Single-use: `fetch_form_prefill` consumes the token on first read so
# refresh / open-in-new-tab can't replay. User-bound: refuses reads
# from a different session user.
#
# `_lz_items` decoder stays in install.py for one cycle with a
# deprecation warning so existing reports continue to work.

_LAZYCHAT_PREFILL_KEY = "lazychat:prefill:"
_LAZYCHAT_PREFILL_TTL_DEFAULT = 300  # 5 minutes
_LAZYCHAT_PREFILL_TTL_MAX = 3600     # 1 hour ceiling
_LAZYCHAT_PREFILL_TOKEN_BYTES = 16   # secrets.token_urlsafe(16) -> 22 chars


def _stage_prefill(doctype: str, parent_fields: dict, items: list) -> str:
	"""Cache a form-prefill payload bound to the current user; return a one-time token."""
	import secrets
	import json as _json
	token = secrets.token_urlsafe(_LAZYCHAT_PREFILL_TOKEN_BYTES)
	user = frappe.session.user
	payload = {
		"user": user,
		"doctype": doctype,
		"parent_fields": parent_fields or {},
		"items": items or [],
	}
	frappe.cache().set_value(
		_LAZYCHAT_PREFILL_KEY + token,
		_json.dumps(payload, default=str),
		expires_in_sec=_LAZYCHAT_PREFILL_TTL_DEFAULT,
	)
	return token


def _retrieve_prefill(token: str):
	"""Single-use fetch of a staged prefill payload. Returns None if missing,
	expired, or owned by a different user. Deletes the entry on successful read."""
	import json as _json
	user = frappe.session.user
	raw = frappe.cache().get_value(_LAZYCHAT_PREFILL_KEY + token)
	if not raw:
		return None
	try:
		obj = _json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
	except Exception:
		return None
	if obj.get("user") != user:
		return None
	# Single-use: consume on first successful read.
	frappe.cache().delete_value(_LAZYCHAT_PREFILL_KEY + token)
	return obj


@frappe.whitelist(methods=["POST"])
def prepare_form_prefill(doctype, parent_fields=None, items=None, ttl=None):
	"""Stage a form-prefill payload for a new-doc URL. Returns a short opaque
	token and a tiny URL (`/app/<scrub>/new?_lz_token=<22-char>`) that the
	persistent Client Script will fetch and apply via `frappe.route_options`.

	Replaces the legacy `_lz_items=<base64-json>` URL convention to avoid
	HTTP 414 on large item payloads.

	Args:
	  doctype: target DocType (e.g. 'Purchase Invoice').
	  parent_fields: dict of parent-level field values to apply
	                 (e.g. {'supplier': 'X', 'is_return': 1, 'return_against': 'Y'}).
	  items: list of item-row dicts to populate the items child table.
	  ttl: optional TTL seconds (clamped to [60, 3600]; default 300).

	Returns:
	  {ok: True, token: str, url: str} on success.
	  {ok: False, error: str} on validation failure.
	"""
	import json as _json
	dt = (doctype or "").strip()
	if not dt:
		return {"ok": False, "error": "doctype is required"}
	if not frappe.db.exists("DocType", dt):
		return {"ok": False, "error": f"DocType '{dt}' not found"}
	# Coerce JSON-stringified args (chat-ui paths sometimes stringify dict/list).
	if isinstance(parent_fields, str):
		try:
			parent_fields = _json.loads(parent_fields)
		except Exception:
			return {"ok": False, "error": "parent_fields must be a JSON object or dict"}
	if isinstance(items, str):
		try:
			items = _json.loads(items)
		except Exception:
			return {"ok": False, "error": "items must be a JSON array or list"}
	parent_fields = parent_fields or {}
	items = items or []
	if not isinstance(parent_fields, dict):
		return {"ok": False, "error": "parent_fields must be a dict"}
	if not isinstance(items, list):
		return {"ok": False, "error": "items must be a list"}
	# Permission re-check at staging time (defense-in-depth; client-side fetch
	# also re-checks at consume time via session user binding).
	if not frappe.has_permission(dt, ptype="create"):
		return {"ok": False, "error": f"No create permission on {dt}"}
	# Clamp TTL.
	try:
		ttl_int = int(ttl) if ttl is not None else _LAZYCHAT_PREFILL_TTL_DEFAULT
	except (TypeError, ValueError):
		ttl_int = _LAZYCHAT_PREFILL_TTL_DEFAULT
	ttl_int = max(60, min(ttl_int, _LAZYCHAT_PREFILL_TTL_MAX))

	# Stage with the (possibly-overridden) TTL.
	import secrets
	token = secrets.token_urlsafe(_LAZYCHAT_PREFILL_TOKEN_BYTES)
	payload = {
		"user": frappe.session.user,
		"doctype": dt,
		"parent_fields": parent_fields,
		"items": items,
	}
	frappe.cache().set_value(
		_LAZYCHAT_PREFILL_KEY + token,
		_json.dumps(payload, default=str),
		expires_in_sec=ttl_int,
	)
	# Build the redirect URL: scrub('Purchase Invoice') -> 'purchase_invoice'
	# then replace _ with - to match Frappe Desk's URL convention.
	scrub = frappe.scrub(dt).replace("_", "-")
	return {
		"ok": True,
		"token": token,
		"url": f"/app/{scrub}/new?_lz_token={token}",
	}


@frappe.whitelist()
def fetch_form_prefill(token):
	"""Single-use fetch of a staged prefill payload. Called by the
	persistent Client Script when it sees `?_lz_token=...` in the URL.

	Refuses cross-user reads (token is bound to the staging session user).
	Consumes the token on first successful read so refresh / open-in-new-tab
	can't replay.

	Returns:
	  {ok: True, doctype: str, parent_fields: dict, items: list} on success.
	  {ok: False, error: str} on missing/expired/wrong-user.
	"""
	tok = (token or "").strip()
	if not tok:
		return {"ok": False, "error": "token is required"}
	obj = _retrieve_prefill(tok)
	if not obj:
		return {"ok": False, "error": "token expired, invalid, or not owned by this session"}
	return {
		"ok": True,
		"doctype": obj.get("doctype"),
		"parent_fields": obj.get("parent_fields") or {},
		"items": obj.get("items") or [],
	}
