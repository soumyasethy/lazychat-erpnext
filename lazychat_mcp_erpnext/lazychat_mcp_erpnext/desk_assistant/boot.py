import frappe


# Defaults mirror the Lazychat Settings doctype defaults; used when the doctype
# row hasn't been created yet (e.g. mid-install or in tests that mock frappe).
_SETTINGS_DEFAULTS = {
	"enabled": True,
	"iframe_base_url": "/assets/lazychat_mcp_erpnext/lazychat_dist/index.html",
	"iframe_query_params": "?frame=sidebar",
	"chat_path": "auto",
	"mcp_endpoint": "/api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle",
	"legacy_widget_enabled": False,
	"allow_email": False,
	"allow_dangerous_tools": False,
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
		"lazychat_iframe_src": "iframe_base_url",
		"lazychat_legacy_widget_enabled": "legacy_widget_enabled",
		"lazychat_allow_email": "allow_email",
		"lazychat_allow_dangerous_tools": "allow_dangerous_tools",
	}
	for site_key, settings_key in site_config_overrides.items():
		if site_key in conf:
			value = conf[site_key]
			if isinstance(_SETTINGS_DEFAULTS[settings_key], bool):
				out[settings_key] = bool(value)
			elif value:
				out[settings_key] = value
	return out


def boot_session(bootinfo):
	"""Expose lazychat panel config to the Desk JS.

	Resolution order (later wins):
	  1. _SETTINGS_DEFAULTS (hardcoded)
	  2. Lazychat Settings doctype (admin-editable in Desk)
	  3. site_config.json keys (advanced override)

	Defaults work without ANY admin action — the bundled chat-ui dist is served
	at /assets/lazychat_mcp_erpnext/lazychat_dist/index.html (same-origin).
	"""
	settings = get_lazychat_settings()
	bootinfo["lazychat_settings"] = settings

	# Backward-compat: the old top-level keys are still read by older versions of the
	# panel shim. Keep emitting them for one release cycle.
	bootinfo["lazychat_panel_enabled"] = settings["enabled"]
	bootinfo["lazychat_legacy_widget_enabled"] = settings["legacy_widget_enabled"]
	# Only emit lazychat_iframe_src if it differs from the default (so the shim's
	# "if (boot.lazychat_iframe_src) ..." override path triggers only on explicit override)
	if settings["iframe_base_url"] != _SETTINGS_DEFAULTS["iframe_base_url"] or settings["iframe_query_params"] != _SETTINGS_DEFAULTS["iframe_query_params"]:
		bootinfo["lazychat_iframe_src"] = settings["iframe_base_url"] + (settings["iframe_query_params"] or "")
