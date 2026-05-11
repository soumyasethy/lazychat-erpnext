"""MCP (Model Context Protocol) wire-transport adapter.

Exposes the same in-process tool registry used by the in-Desk lazychat panel as a
JSONRPC-over-HTTP endpoint so external MCP clients (Claude Desktop, agent SDKs,
custom integrations) can connect to ERPNext.

Endpoint (whitelisted, requires Frappe authentication):
    POST /api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle

Auth:
    Standard Frappe auth — either an API key/secret pair (Authorization: token KEY:SECRET)
    or a session cookie. The calling user's permissions apply to every tool call;
    frappe.get_list / frappe.has_permission filter by their roles. No god-mode bypass.

Supported JSONRPC methods (subset of MCP 2024-11-05 spec — server-side only,
no server-initiated notifications, no SSE upgrade — that's deferred):
    - initialize         → returns capabilities + serverInfo
    - tools/list         → returns the tool registry (with MCP-compliant inputSchema key)
    - tools/call         → dispatches to execute_tool, wraps result in MCP content array
    - ping               → liveness check

This adapter is INTENTIONALLY minimal: ~150 LoC, no extra dependencies, works against
any HTTP MCP client that speaks JSONRPC. Streamable-HTTP/SSE upgrade can layer on top
later without re-doing the dispatch.
"""
import json
import secrets
import uuid

import frappe
from frappe import _

from lazychat_mcp_erpnext.desk_assistant.tool_schemas import TOOL_SCHEMAS
from lazychat_mcp_erpnext.desk_assistant.tools import execute_tool

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "lazychat-mcp-erpnext"
SERVER_VERSION = "0.2.3"


def _jsonrpc_ok(req_id, result):
	return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_err(req_id, code, message, data=None):
	err = {"code": code, "message": message}
	if data is not None:
		err["data"] = data
	return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _tool_schemas_mcp():
	"""Translate our internal tool defs (input_schema) to MCP wire format (inputSchema).

	When the calling user has any Skill active that declares an `allowed_tools`
	whitelist, the result is filtered to that union. Skills without
	allowed_tools restrict nothing. See desk_assistant/skills.py.
	"""
	out = []
	for t in TOOL_SCHEMAS:
		out.append(
			{
				"name": t["name"],
				"description": t.get("description") or "",
				"inputSchema": t.get("input_schema") or {"type": "object", "properties": {}},
			}
		)
	try:
		from lazychat_mcp_erpnext.desk_assistant import skills as _skills

		return _skills.filter_tools_for_user(out)
	except Exception:
		# Never let a skill-config error blank out the tool list; log + return
		# the unfiltered list so the agent stays usable.
		try:
			frappe.log_error(frappe.get_traceback(), "lazychat skills.filter_tools_for_user")
		except Exception:
			pass
		return out


def _content_text(obj):
	"""Wrap a tool result dict in MCP's content array (text part with JSON body)."""
	return [{"type": "text", "text": json.dumps(obj, default=str)}]


def dispatch(method, params, req_id=None):
	"""Pure dispatcher — no HTTP-level concerns. Returns a JSONRPC dict."""
	params = params or {}

	if method == "initialize":
		return _jsonrpc_ok(
			req_id,
			{
				"protocolVersion": PROTOCOL_VERSION,
				"capabilities": {"tools": {"listChanged": False}},
				"serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
			},
		)

	if method == "ping":
		return _jsonrpc_ok(req_id, {})

	if method == "tools/list":
		return _jsonrpc_ok(req_id, {"tools": _tool_schemas_mcp()})

	if method == "tools/call":
		name = params.get("name")
		args = params.get("arguments") or {}
		if not name:
			return _jsonrpc_err(req_id, -32602, "Invalid params: 'name' required")
		# Validate tool exists in our registry (defense against arbitrary execute_tool calls)
		if not any(t["name"] == name for t in TOOL_SCHEMAS):
			return _jsonrpc_err(req_id, -32601, f"Tool not found: {name}")
		try:
			result = execute_tool(name, args)
		except Exception as e:
			frappe.log_error(frappe.get_traceback(), f"mcp tools/call {name}")
			return _jsonrpc_ok(
				req_id,
				{"content": _content_text({"error": str(e)}), "isError": True},
			)
		is_error = isinstance(result, dict) and "error" in result and "ok" not in result
		return _jsonrpc_ok(req_id, {"content": _content_text(result), "isError": is_error})

	return _jsonrpc_err(req_id, -32601, f"Method not found: {method}")


def _jsonrpc_response(payload, status: int = 200):
	"""Build a Werkzeug Response carrying the JSONRPC payload as JSON.

	Don't assign a plain dict/list to `frappe.local.response` — Frappe expects a
	`frappe._dict` (with attrs like `.http_status_code`, `.exception`) and crashes
	in `frappe/utils/response.py:as_json` with `AttributeError: 'dict' object has
	no attribute 'http_status_code'` if the shape is wrong. Returning a Werkzeug
	Response sidesteps the json builder entirely (mirrors `llm_proxy.py` pattern).
	"""
	from werkzeug.wrappers import Response

	resp = Response(json.dumps(payload, default=str), status=status, mimetype="application/json")
	frappe.local.response = resp
	return resp


def _401_with_resource_metadata():
	"""401 with WWW-Authenticate header pointing at our OAuth Protected Resource
	Metadata document. Per RFC 9728 + the MCP Authorization spec (2025-06),
	clients use this header to discover where to authenticate.
	"""
	from werkzeug.wrappers import Response

	# Read scheme from X-Forwarded-Proto so the URL is https through ngrok / any
	# TLS-terminating proxy. host_url alone returns http inside this Frappe stack.
	if getattr(frappe, "request", None):
		r = frappe.request
		scheme = r.headers.get("X-Forwarded-Proto") or r.scheme or "http"
		host = r.headers.get("X-Forwarded-Host") or r.host
		base = f"{scheme}://{host}"
	else:
		base = ""
	metadata_url = f"{base}/.well-known/oauth-protected-resource"
	body = json.dumps({"error": "Authentication required", "metadata_url": metadata_url})
	resp = Response(body, status=401, mimetype="application/json")
	resp.headers["WWW-Authenticate"] = (
		f'Bearer realm="lazychat-mcp", resource_metadata="{metadata_url}"'
	)
	frappe.local.response = resp
	return resp


@frappe.whitelist(methods=["POST"], allow_guest=True)
def handle():
	"""HTTP entry point. Reads JSONRPC body, dispatches, returns JSONRPC response.

	Auth: standard Frappe auth runs upstream (validate_oauth then api_keys then
	auth_hooks). Valid OAuth Bearer / API key+secret / session cookie all set
	frappe.session.user. Unauthenticated requests reach this handler as Guest;
	we return 401 with a WWW-Authenticate header advertising the OAuth flow
	(MCP Authorization spec, 2025-06) so claude.ai can discover it.

	Notification messages (no `id`) are accepted but produce no response body — per JSONRPC spec.
	"""
	if frappe.session.user in ("", "Guest"):
		return _401_with_resource_metadata()

	try:
		raw = frappe.request.get_data(as_text=True) or "{}"
		body = json.loads(raw)
	except Exception as e:
		return _jsonrpc_response(_jsonrpc_err(None, -32700, f"Parse error: {e}"))

	# Single request OR batch (we support both — batch returns a list of responses)
	if isinstance(body, list):
		out = []
		for item in body:
			res = _handle_single(item)
			if res is not None:
				out.append(res)
		return _jsonrpc_response(out)

	return _jsonrpc_response(_handle_single(body))


def _handle_single(item):
	if not isinstance(item, dict):
		return _jsonrpc_err(None, -32600, "Invalid Request: must be object")
	method = item.get("method")
	req_id = item.get("id")  # may be omitted for notifications
	params = item.get("params") or {}
	is_notification = "id" not in item
	resp = dispatch(method, params, req_id=req_id)
	# Notifications must not produce a response
	return None if is_notification else resp


# ── Bearer-auth Streamable HTTP variant ────────────────────────────────────
# For claude.ai web Custom Connector and other MCP clients that send
# Authorization: Bearer <token> instead of Frappe's `token KEY:SECRET`.
# Same dispatcher, same tool registry, same permission model — just a
# different auth shape and a Mcp-Session-Id response header (Streamable
# HTTP spec, 2025-03-26).


def _bearer_token_from_config() -> str:
	return frappe.get_site_config().get("lazychat_mcp_bearer_token") or ""


def _bearer_user_from_config() -> str:
	return frappe.get_site_config().get("lazychat_mcp_bearer_user") or "Administrator"


def _validate_bearer(presented: str) -> bool:
	"""Constant-time compare. Returns False when no token is configured so a
	misconfigured site never accepts blanket-anonymous requests."""
	expected = _bearer_token_from_config()
	if not expected or not presented:
		return False
	return secrets.compare_digest(presented, expected)


def _bearer_response(payload, status: int = 200):
	"""Like _jsonrpc_response but adds Mcp-Session-Id per Streamable HTTP spec."""
	from werkzeug.wrappers import Response

	body = json.dumps(payload, default=str)
	resp = Response(body, status=status, mimetype="application/json")
	resp.headers["Mcp-Session-Id"] = str(uuid.uuid4())
	frappe.local.response = resp
	return resp


def _bearer_error(code: int, message: str):
	from werkzeug.wrappers import Response

	body = json.dumps({"error": message})
	resp = Response(body, status=code, mimetype="application/json")
	if code == 401:
		resp.headers["WWW-Authenticate"] = 'Bearer realm="lazychat-mcp"'
	frappe.local.response = resp
	return resp


_BEARER_PATH = "/api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle_bearer"


def bearer_pre_strip():
	"""`before_request` hook. Pre-validates Bearer tokens for handle_bearer
	and strips invalid ones from the WSGI environ.

	Why: Frappe's validate_auth() raises AuthenticationError on any
	Authorization header it can't validate (OAuth or Frappe API key+secret).
	The default response is an HTML/traceback 401 — claude.ai's connector
	parses it as a generic auth failure with no actionable detail. By
	stripping the bad header here (before validate_auth runs), Frappe sees
	no Authorization, leaves the request as Guest, and our allow_guest=True
	handler runs and returns a clean JSON 401 instead.

	Stashes `frappe.local._lazychat_invalid_bearer = True` so handle_bearer
	can distinguish "wrong token" (401: Invalid Bearer token) from "no token
	at all" (401: Missing Bearer token).

	No-op for any path other than handle_bearer.
	"""
	if not getattr(frappe, "request", None):
		return
	if frappe.request.path != _BEARER_PATH:
		return

	auth = (frappe.get_request_header("Authorization") or "").strip()
	if not auth.startswith("Bearer "):
		return  # no header — leave alone, handler returns "Missing Bearer token"

	presented = auth[len("Bearer ") :].strip()
	if _validate_bearer(presented):
		return  # valid — let bearer_auth_hook authenticate downstream

	# Invalid token — strip from environ so Frappe's validate_auth skips it,
	# and flag for handle_bearer to differentiate the message.
	try:
		del frappe.request.environ["HTTP_AUTHORIZATION"]
	except KeyError:
		pass
	frappe.local._lazychat_invalid_bearer = True


def bearer_auth_hook():
	"""Frappe `auth_hooks` callback. Authenticates Bearer tokens for the
	handle_bearer endpoint ONLY.

	Why this exists: Frappe's validate_auth() raises AuthenticationError on
	any Authorization header it can't validate (OAuth Bearer Token table or
	Frappe API key+secret) — even on allow_guest=True endpoints. Without this
	hook, claude.ai's standard `Authorization: Bearer <token>` request gets
	rejected by Frappe core before our handler runs.

	Scoped to the handle_bearer path so the configured token does NOT grant
	access to other Frappe endpoints. Anyone with the token can only call
	the MCP dispatcher; not the Desk, not /api/method/<arbitrary>, not
	/api/resource/*.
	"""
	if not getattr(frappe, "request", None):
		return
	if frappe.request.path != _BEARER_PATH:
		return

	auth = (frappe.get_request_header("Authorization") or "").strip()
	if not auth.startswith("Bearer "):
		return

	presented = auth[len("Bearer ") :].strip()
	if not _validate_bearer(presented):
		return  # let Frappe's final check raise AuthenticationError → 401

	# Token valid — set the run-as user; validate_auth's post-check at
	# auth.py:624 sees a non-Guest user and lets the request continue.
	frappe.set_user(_bearer_user_from_config())


@frappe.whitelist(methods=["POST"], allow_guest=True)
def handle_bearer():
	"""Streamable-HTTP MCP endpoint with Bearer auth.

	Auth flow: bearer_auth_hook (registered in hooks.py:auth_hooks) runs
	BEFORE this handler and either authenticates the request as the
	configured run-as user or leaves it as Guest. Wrong tokens never reach
	this handler — Frappe's validate_auth raises AuthenticationError first.
	Missing-Authorization requests do reach here (Frappe leaves them as
	Guest) and we return a tidy JSON 401 below.

	Run-as user defaults to `Administrator`; override with site_config
	`lazychat_mcp_bearer_user`. The configured user's roles still gate every
	tool (System Manager for dangerous tools, allow_dangerous_tools / allow_email
	site flags, etc.) — Bearer auth does not bypass any of the existing
	defense layers.
	"""
	if getattr(frappe.local, "_lazychat_invalid_bearer", False):
		return _bearer_error(401, "Invalid Bearer token")
	if frappe.session.user in ("", "Guest"):
		return _bearer_error(401, "Missing Bearer token")

	try:
		raw = frappe.request.get_data(as_text=True) or "{}"
		body = json.loads(raw)
	except Exception as e:
		return _bearer_response(_jsonrpc_err(None, -32700, f"Parse error: {e}"))

	if isinstance(body, list):
		out = []
		for item in body:
			res = _handle_single(item)
			if res is not None:
				out.append(res)
		return _bearer_response(out)

	return _bearer_response(_handle_single(body))
