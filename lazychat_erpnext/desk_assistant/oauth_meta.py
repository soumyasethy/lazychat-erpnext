"""OAuth 2.1 / MCP discovery metadata endpoints.

Exposes the two well-known documents the MCP Authorization spec (2025-06)
requires so claude.ai (and any other compliant MCP client) can discover
how to authenticate against this server:

    /.well-known/oauth-authorization-server  → RFC 8414 metadata
    /.well-known/oauth-protected-resource    → RFC 9728 metadata

Both URLs are routed via website_route_rules in hooks.py (Frappe doesn't
serve /.well-known/* by default).

The actual OAuth flow is handled entirely by Frappe core
(frappe.integrations.oauth2.{authorize,get_token,...}). This module ONLY
advertises that flow's existence to discovering clients.
"""
import frappe


def log_oauth_authorize_request():
	"""before_request hook: log every OAuth authorize call so we can diagnose
	mismatched redirect_uri / scope / response_type errors. Writes to
	frappe.log_error so it shows up in Error Log under name
	'lazychat oauth_meta.authorize_request'.

	Logs ALL query params + headers — this is acceptable because:
	- the only secret in the URL is `state` (opaque to us) and PKCE
	  code_challenge (not a secret either way, by design)
	- client_secret never travels in the authorize request (it's only used
	  on the back-channel token_endpoint POST)
	"""
	if not getattr(frappe, "request", None):
		return
	if frappe.request.path != "/api/method/frappe.integrations.oauth2.authorize":
		return
	try:
		frappe.log_error(
			f"path={frappe.request.path}\n"
			f"args={dict(frappe.request.args)}\n"
			f"user-agent={frappe.request.headers.get('User-Agent', '')[:200]}",
			"lazychat oauth_meta.authorize_request",
		)
	except Exception:
		pass


def _server_url() -> str:
	"""Public base URL the client used to reach us, scheme-correct.

	Reads X-Forwarded-Proto so https terminates correctly through ngrok /
	nginx / any TLS-terminating proxy. Werkzeug's `request.host_url` respects
	X-Forwarded-Host but NOT X-Forwarded-Proto by default in this Frappe
	stack — the result was http:// inside the response body even though the
	request came in via https. Manually combining scheme + host fixes it.
	"""
	if not getattr(frappe, "request", None):
		# Fallback only used outside a request (shouldn't happen for these endpoints)
		from frappe.oauth import get_server_url
		return get_server_url().rstrip("/")
	r = frappe.request
	scheme = r.headers.get("X-Forwarded-Proto") or r.scheme or "http"
	host = r.headers.get("X-Forwarded-Host") or r.host
	return f"{scheme}://{host}"


def _mcp_endpoint() -> str:
	"""The canonical MCP endpoint URL — what oauth-protected-resource.resource points at."""
	return f"{_server_url()}/api/method/lazychat_erpnext.desk_assistant.mcp.handle"


def _set_response(payload: dict) -> None:
	"""Write directly to frappe.local.response so Frappe doesn't wrap the body
	in its default `{"message": ...}` envelope. Discovery clients (claude.ai)
	expect OAuth metadata at the JSON root per RFC 8414 / RFC 9728.

	Mirrors the pattern Frappe's own openid_configuration uses (oauth2.py:181).
	Returning a dict from a whitelisted function would be wrapped; this
	bypasses the wrapper entirely.
	"""
	frappe.local.response = frappe._dict(payload)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def authorization_server_metadata():
	"""RFC 8414 OAuth 2.0 Authorization Server Metadata.

	claude.ai fetches this after the resource-metadata pointer in the 401
	WWW-Authenticate header tells it which authorization server to use.

	Mirrors Frappe's openid_configuration but trims OIDC-specific bits and
	adds OAuth 2.1 fields that Frappe omits (PKCE method declaration,
	standard token-endpoint auth methods).
	"""
	base = _server_url()
	_set_response({
		"issuer": base,
		"authorization_endpoint": f"{base}/api/method/frappe.integrations.oauth2.authorize",
		"token_endpoint": f"{base}/api/method/frappe.integrations.oauth2.get_token",
		"revocation_endpoint": f"{base}/api/method/frappe.integrations.oauth2.revoke_token",
		"introspection_endpoint": f"{base}/api/method/frappe.integrations.oauth2.introspect_token",
		"userinfo_endpoint": f"{base}/api/method/frappe.integrations.oauth2.openid_profile",
		"response_types_supported": ["code"],
		"grant_types_supported": ["authorization_code", "refresh_token"],
		"token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
		"code_challenge_methods_supported": ["S256", "plain"],
		"scopes_supported": ["all", "openid"],
		"service_documentation": "https://github.com/soumyasethy/lazychat-erpnext",
	})


@frappe.whitelist(allow_guest=True, methods=["GET"])
def protected_resource_metadata():
	"""RFC 9728 OAuth 2.0 Protected Resource Metadata.

	The MCP server (this Frappe site) is the protected resource; the
	authorization server is also this same site. claude.ai fetches this
	from the URL embedded in the 401 WWW-Authenticate header.
	"""
	base = _server_url()
	_set_response({
		"resource": f"{base}/api/method/lazychat_erpnext.desk_assistant.mcp.handle",
		"authorization_servers": [base],
		"bearer_methods_supported": ["header"],
		"scopes_supported": ["all"],
		"resource_documentation": "https://github.com/soumyasethy/lazychat-erpnext",
	})
