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
	"""Translate our internal tool defs (input_schema) to MCP wire format (inputSchema)."""
	out = []
	for t in TOOL_SCHEMAS:
		out.append(
			{
				"name": t["name"],
				"description": t.get("description") or "",
				"inputSchema": t.get("input_schema") or {"type": "object", "properties": {}},
			}
		)
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


@frappe.whitelist(methods=["POST"], allow_guest=False)
def handle():
	"""HTTP entry point. Reads JSONRPC body, dispatches, returns JSONRPC response.

	Notification messages (no `id`) are accepted but produce no response body — per JSONRPC spec.
	"""
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
