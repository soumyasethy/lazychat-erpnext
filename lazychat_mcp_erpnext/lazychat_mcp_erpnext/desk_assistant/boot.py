import frappe


def boot_session(bootinfo):
	"""Expose lazychat panel config to the Desk JS.

	Iframe src defaults to the bundled chat-ui SPA at
	/assets/lazychat_mcp_erpnext/lazychat_dist/index.html — same-origin, no port
	dependency, works on every bench out of the box.

	For active chat-ui dev with HMR, override in site_config.json:
	  "lazychat_iframe_src": "http://127.0.0.1:5173/?frame=sidebar"
	(then run `pnpm --filter chat-ui dev`; vite is pinned to 5173 via strictPort).
	"""
	conf = frappe.get_site_config()
	bootinfo["lazychat_panel_enabled"] = bool(conf.get("lazychat_panel_enabled", True))
	src = conf.get("lazychat_iframe_src")
	if src:
		bootinfo["lazychat_iframe_src"] = src
	bootinfo["lazychat_legacy_widget_enabled"] = bool(
		conf.get("lazychat_legacy_widget_enabled", False)
	)
