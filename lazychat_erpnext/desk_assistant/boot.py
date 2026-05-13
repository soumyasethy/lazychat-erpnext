import frappe


# Defaults mirror the Lazychat Settings doctype defaults; used when the doctype
# row hasn't been created yet (e.g. mid-install or in tests that mock frappe).
_DEFAULT_LLM_PROXY_HOSTS = [
	"api.anthropic.com",
	"api.openai.com",
	"integrate.api.nvidia.com",
	"openrouter.ai",
	"ai-gateway.vercel.sh",
	"api.together.xyz",
	"api.groq.com",
	"api.fireworks.ai",
	"generativelanguage.googleapis.com",
	"api.deepseek.com",
	"api.mistral.ai",
	"api.cohere.com",
	"api.x.ai",
]

_SETTINGS_DEFAULTS = {
	"enabled": True,
	"iframe_base_url": "/assets/lazychat_erpnext/lazychat_dist/index.html",
	"iframe_query_params": "?frame=sidebar",
	"chat_path": "auto",
	"mcp_endpoint": "/api/method/lazychat_erpnext.desk_assistant.mcp.handle",
	"legacy_widget_enabled": False,
	# Cycle 10: allow-all defaults. Defense-in-depth via System Manager
	# role checks at tool-dispatch time + /commit confirmation per call.
	"allow_email": True,
	"allow_dangerous_tools": True,
	"allow_email_setup": True,
	"cycle9_enabled": True,
	# Cycle 13 M2: screenshot preview ON by default — graceful-degrades to
	# `{ok: False, error: "playwright not installed ..."}` if Playwright/Chromium
	# isn't on the bench. Install with `./env/bin/pip install playwright &&
	# ./env/bin/playwright install chromium` to actually enable rendering.
	"enable_screenshot_preview": True,
	"llm_proxy_allowed_hosts": list(_DEFAULT_LLM_PROXY_HOSTS),
	# Cycle 13 M3: vision-judge models per Effort tier. JSON dict mapping
	# 'high'/'max' to a vision-capable model_label configured in LLM Model.
	"vision_judge_models": '{"high": "claude-sonnet-4-6", "max": "claude-opus-4-7"}',
}


def get_lazychat_settings():
	"""Resolve effective settings: doctype values, with site_config keys overriding.

	site_config wins because it's the historical advanced-override surface — admins who
	set those flags before this doctype existed expect them to keep working.

	Callable from anywhere on the server side (tools.py uses this for the dangerous-tools
	gate; boot_session uses it for the Desk-side flags).
	"""
	out = dict(_SETTINGS_DEFAULTS)

	# 1) Read from doctype if present
	try:
		if frappe.db and frappe.db.exists("DocType", "Lazychat Settings"):
			doc = frappe.get_single("Lazychat Settings")
			for key in _SETTINGS_DEFAULTS:
				value = doc.get(key)
				# Booleans in Frappe are 0/1; coerce
				if isinstance(_SETTINGS_DEFAULTS[key], bool):
					if value is not None:
						out[key] = bool(value)
				elif value:
					out[key] = value
	except Exception:
		# Boot must not fail; defaults already populated.
		pass

	# 2) site_config overrides (advanced)
	try:
		conf = frappe.get_site_config() or {}
	except Exception:
		conf = {}

	# Map legacy site_config keys → settings keys
	site_config_overrides = {
		"lazychat_panel_enabled": "enabled",
		"lazychat_legacy_widget_enabled": "legacy_widget_enabled",
		"lazychat_allow_email": "allow_email",
		"lazychat_allow_dangerous_tools": "allow_dangerous_tools",
		"lazychat_allow_email_setup": "allow_email_setup",
		"lazychat_cycle9_enabled": "cycle9_enabled",
	}
	for site_key, settings_key in site_config_overrides.items():
		if site_key in conf:
			value = conf[site_key]
			if isinstance(_SETTINGS_DEFAULTS[settings_key], bool):
				out[settings_key] = bool(value)
			elif value:
				out[settings_key] = value
	# `lazychat_iframe_src` is a full URL — may include a query string. Split it
	# so the shim's `iframe_base_url + iframe_query_params` composition doesn't
	# double-append the query (e.g. ".../?frame=sidebar?frame=sidebar").
	if conf.get("lazychat_iframe_src"):
		full = str(conf["lazychat_iframe_src"])
		base, sep, qs = full.partition("?")
		out["iframe_base_url"] = base
		out["iframe_query_params"] = (sep + qs) if sep else ""
	return out


def _deploy_version():
	"""Build a cache-bust token: app version + mtime of the bundled dist's index.html.

	Changes whenever the lazychat dist is rebuilt + redeployed, so the shim's iframe
	URL gets a new ?v= parameter and the browser bypasses the 12h asset cache.
	"""
	import os

	try:
		import frappe as _f

		app_path = _f.get_app_path("lazychat_erpnext")
		index_html = os.path.join(app_path, "public", "lazychat_dist", "index.html")
		mt = int(os.path.getmtime(index_html)) if os.path.exists(index_html) else 0
	except Exception:
		mt = 0
	# Ship version too — even when dist mtime is 0 (e.g. dist not built yet on this bench)
	# we still get a fresh token if the app version bumps.
	try:
		from lazychat_erpnext import __version__ as _v
	except Exception:
		_v = "0"
	return f"{_v}.{mt}"


def boot_session(bootinfo):
	"""Expose lazychat panel config to the Desk JS.

	Resolution order (later wins):
	  1. _SETTINGS_DEFAULTS (hardcoded)
	  2. Lazychat Settings doctype (admin-editable in Desk)
	  3. site_config.json keys (advanced override)

	Defaults work without ANY admin action — the bundled chat-ui dist is served
	at /assets/lazychat_erpnext/lazychat_dist/index.html (same-origin).
	"""
	settings = get_lazychat_settings()
	# Inject deploy_version so the shim can cache-bust the iframe URL when the dist changes.
	settings["deploy_version"] = _deploy_version()
	bootinfo["lazychat_settings"] = settings

	# Backward-compat: the old top-level keys are still read by older versions of the
	# panel shim. Keep emitting them for one release cycle.
	bootinfo["lazychat_panel_enabled"] = settings["enabled"]
	bootinfo["lazychat_legacy_widget_enabled"] = settings["legacy_widget_enabled"]
	# Only emit lazychat_iframe_src if it differs from the default (so the shim's
	# "if (boot.lazychat_iframe_src) ..." override path triggers only on explicit override)
	if settings["iframe_base_url"] != _SETTINGS_DEFAULTS["iframe_base_url"] or settings["iframe_query_params"] != _SETTINGS_DEFAULTS["iframe_query_params"]:
		bootinfo["lazychat_iframe_src"] = settings["iframe_base_url"] + (settings["iframe_query_params"] or "")
