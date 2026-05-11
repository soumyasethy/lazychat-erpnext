import os

from . import __version__ as _v

_APP_ROOT = os.path.dirname(os.path.abspath(__file__))


def _asset_qs(*parts: str) -> str:
	"""Cache-bust desk assets: version + source file mtime (changes URL after edits + bench restart)."""
	full = os.path.join(_APP_ROOT, "public", *parts)
	try:
		mt = int(os.path.getmtime(full))
	except OSError:
		mt = 0
	return f"v={_v}.{mt}"


app_name = "lazychat_erpnext"
app_title = "LazyChat"
app_publisher = "Soumya Sethy"
app_description = "AI assistant for ERPNext — chat with your data, draft reports, stage edits. Bring your own LLM (any OpenAI-compatible or Anthropic key)."
app_email = "sethy.soumyaranjan@gmail.com"
app_license = "MIT"
app_version = _v
source_link = "https://github.com/soumyasethy/lazychat-erpnext"

# Installer pulls ERPNext first — the tool registry reads ERPNext doctypes
# (Purchase Invoice, Payment Entry, Stock Ledger Entry, …). `frappe` is
# implied by `erpnext`.
required_apps = ["erpnext"]

# Shared helpers (cURL parse) — load before desk + doctype scripts
app_include_js = [
	f"/assets/lazychat_erpnext/js/llm_setup_shared.js?{_asset_qs('js', 'llm_setup_shared.js')}",
	f"/assets/lazychat_erpnext/js/lazychat_erpnext_desk.js?{_asset_qs('js', 'lazychat_erpnext_desk.js')}",
	f"/assets/lazychat_erpnext/js/lazychat_panel.bundle.js?{_asset_qs('js', 'lazychat_panel.bundle.js')}",
]
app_include_css = [
	f"/assets/lazychat_erpnext/css/lazychat_erpnext_desk.css?{_asset_qs('css', 'lazychat_erpnext_desk.css')}",
	f"/assets/lazychat_erpnext/css/lazychat_panel.css?{_asset_qs('css', 'lazychat_panel.css')}",
]

extend_bootinfo = "lazychat_erpnext.desk_assistant.boot.boot_session"

# Diagnostic: log when the browser hits /llm-proxy (the dev-only fallback path).
# If this fires in production, chat-ui is on a stale bundle OR didn't get llmProxyUrl
# from the init postMessage. The Error Log entry tells us which.
before_request = [
	"lazychat_erpnext.desk_assistant.llm_proxy.trace_legacy_proxy_hit",
	# Strips invalid Bearer headers for handle_bearer so Frappe's validate_auth
	# doesn't reject them with an HTML/traceback 401. Pairs with bearer_auth_hook below.
	"lazychat_erpnext.desk_assistant.mcp.bearer_pre_strip",
	# Diagnostic only: log claude.ai's exact OAuth authorize parameters so we can
	# triage redirect_uri / scope / response_type mismatches. See oauth_meta.py.
	"lazychat_erpnext.desk_assistant.oauth_meta.log_oauth_authorize_request",
]

# Authenticate Bearer tokens for the handle_bearer Streamable-HTTP MCP endpoint
# (claude.ai web Custom Connector). Scoped to that one path inside the hook;
# does NOT grant access to other Frappe endpoints. See desk_assistant/mcp.py.
auth_hooks = ["lazychat_erpnext.desk_assistant.mcp.bearer_auth_hook"]

# OAuth 2.1 / MCP discovery URLs. The MCP Authorization spec (2025-06) requires
# clients to discover the authorization server via /.well-known/oauth-protected-resource
# and the auth server's metadata via /.well-known/oauth-authorization-server. Frappe
# already serves /.well-known/openid-configuration the same way (line 63 of
# frappe/hooks.py); we reuse that pattern.
website_redirects = [
	{
		"source": "/.well-known/oauth-authorization-server",
		"target": "/api/method/lazychat_erpnext.desk_assistant.oauth_meta.authorization_server_metadata",
	},
	{
		"source": "/.well-known/oauth-protected-resource",
		"target": "/api/method/lazychat_erpnext.desk_assistant.oauth_meta.protected_resource_metadata",
	},
]

# Bundled brand SVGs (avoid missing File attachments at /files/agilitas*.svg)
app_logo_url = "/assets/lazychat_erpnext/images/agilitas-txt-logo.svg"

doctype_js = {
	"LLM Provider": "public/js/llm_provider_form.js",
	"LLM Model": "public/js/llm_model_form.js",
}

doctype_css = {
	"LLM Provider": "public/css/llm_setup.css",
	"LLM Model": "public/css/llm_setup.css",
}

after_install = "lazychat_erpnext.install.after_install"
after_migrate = "lazychat_erpnext.install.run_after_migrate"

# Tier H2 — File doctype hook auto-indexes KB attachments. The handler
# filters internally to attached_to_doctype="Lazychat Knowledge Base" and
# enqueues a background job (frappe.enqueue) so the request returns fast.
# Re-saves of unchanged files are near-free thanks to content-hash dedupe.
doc_events = {
	"File": {
		"on_update": "lazychat_erpnext.desk_assistant.embeddings.on_file_attach",
	},
	# Tier D — universal doc-update hook for realtime subscriptions. Fires for
	# every doctype save in the bench but the handler's first line is a single
	# Redis flag GET — zero cost when no user has subscribed to anything.
	"*": {
		"on_update": "lazychat_erpnext.desk_assistant.realtime_subs.on_doc_update",
	},
}
