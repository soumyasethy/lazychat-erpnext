import json
import queue
import re
import threading

import frappe
from frappe import _

from lazychat_mcp_erpnext.desk_assistant.claude_bridge import run_agentic_turn
from lazychat_mcp_erpnext.desk_assistant.password_utils import safe_provider_api_key


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
	return {"ok": True, "app": "lazychat_mcp_erpnext"}


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
	from lazychat_mcp_erpnext.desk_assistant.tools import commit_prepared

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
