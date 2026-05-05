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


app_name = "lazychat_mcp_erpnext"
app_title = "Lazychat MCP ERPNext"
app_publisher = "Soumya Sethy"
app_description = "Multi-provider LLM assistant docked on the ERPNext desk"
app_email = "sethy.soumyaranjan@gmail.com"
app_license = "MIT"
app_version = _v

# Shared helpers (cURL parse) — load before desk + doctype scripts
app_include_js = [
	f"/assets/lazychat_mcp_erpnext/js/llm_setup_shared.js?{_asset_qs('js', 'llm_setup_shared.js')}",
	f"/assets/lazychat_mcp_erpnext/js/lazychat_mcp_erpnext_desk.js?{_asset_qs('js', 'lazychat_mcp_erpnext_desk.js')}",
	f"/assets/lazychat_mcp_erpnext/js/lazychat_panel.bundle.js?{_asset_qs('js', 'lazychat_panel.bundle.js')}",
]
app_include_css = [
	f"/assets/lazychat_mcp_erpnext/css/lazychat_mcp_erpnext_desk.css?{_asset_qs('css', 'lazychat_mcp_erpnext_desk.css')}",
	f"/assets/lazychat_mcp_erpnext/css/lazychat_panel.css?{_asset_qs('css', 'lazychat_panel.css')}",
]

extend_bootinfo = "lazychat_mcp_erpnext.desk_assistant.boot.boot_session"

# Diagnostic: log when the browser hits /llm-proxy (the dev-only fallback path).
# If this fires in production, chat-ui is on a stale bundle OR didn't get llmProxyUrl
# from the init postMessage. The Error Log entry tells us which.
before_request = ["lazychat_mcp_erpnext.desk_assistant.llm_proxy.trace_legacy_proxy_hit"]

# Bundled brand SVGs (avoid missing File attachments at /files/agilitas*.svg)
app_logo_url = "/assets/lazychat_mcp_erpnext/images/agilitas-txt-logo.svg"

doctype_js = {
	"LLM Provider": "public/js/llm_provider_form.js",
	"LLM Model": "public/js/llm_model_form.js",
}

doctype_css = {
	"LLM Provider": "public/css/llm_setup.css",
	"LLM Model": "public/css/llm_setup.css",
}

after_install = "lazychat_mcp_erpnext.install.after_install"
after_migrate = "lazychat_mcp_erpnext.install.run_after_migrate"

# Tier H2 — File doctype hook auto-indexes KB attachments. The handler
# filters internally to attached_to_doctype="Lazychat Knowledge Base" and
# enqueues a background job (frappe.enqueue) so the request returns fast.
# Re-saves of unchanged files are near-free thanks to content-hash dedupe.
doc_events = {
	"File": {
		"on_update": "lazychat_mcp_erpnext.desk_assistant.embeddings.on_file_attach",
	}
}
