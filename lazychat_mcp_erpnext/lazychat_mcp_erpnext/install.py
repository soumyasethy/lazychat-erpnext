import json
import os

import frappe

_ASSET_LOGO = "/assets/lazychat_mcp_erpnext/images/agilitas-txt-logo.svg"
_ASSET_ICON = "/assets/lazychat_mcp_erpnext/images/agilitas.icon.svg"


def run_after_migrate():
	seed_llm_defaults()
	seed_lazychat_settings()
	patch_agilitas_branding()
	lazychat_setup_check()


def after_install():
	"""Called once when bench --site <site> install-app lazychat_mcp_erpnext succeeds.

	Defaults work without any admin action:
	  - Lazychat Settings doctype auto-created with chat_path=auto, enabled=true
	  - Iframe loads bundled chat-ui dist (same-origin, port-free)
	  - Both browser-LLM and backend-LLM paths available; auto picks based on chat-ui's active model
	"""
	seed_llm_defaults()
	seed_lazychat_settings()
	lazychat_setup_check()
	_print_welcome_banner()


def seed_lazychat_settings():
	"""Insert the Lazychat Settings Single row if it doesn't exist yet.

	Frappe auto-creates Single doctype rows on first access, but seeding here ensures
	the row's there immediately so the welcome-banner instructions point at a real form.
	"""
	try:
		if not frappe.db.exists("DocType", "Lazychat Settings"):
			return  # doctype JSON not migrated yet (would happen on next bench migrate)
		# get_single creates the row with default field values if absent
		frappe.get_single("Lazychat Settings")
		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "lazychat_mcp_erpnext.seed_lazychat_settings")


def lazychat_setup_check():
	"""Verify the bundled chat-ui dist exists; warn (don't fail) with the build command if missing."""
	app_path = frappe.get_app_path("lazychat_mcp_erpnext")
	index_html = os.path.join(app_path, "public", "lazychat_dist", "index.html")
	if not os.path.exists(index_html):
		msg = (
			"\n[lazychat_mcp_erpnext] WARNING: bundled chat-ui dist NOT found at\n"
			f"    {index_html}\n"
			"  The lazychat panel will fail to load until you build it.\n"
			"  From your lazychat-mcp-erpnext repo:\n"
			"    ./scripts/build-lazychat-dist.sh\n"
			"    ./scripts/deploy-local.sh\n"
			"  Or set 'lazychat_iframe_src' in site_config.json to a running chat-ui URL.\n"
		)
		try:
			print(msg)
		except Exception:
			pass
		try:
			frappe.log_error(msg, "lazychat_mcp_erpnext lazychat dist missing")
		except Exception:
			pass


def _print_welcome_banner():
	site = getattr(frappe.local, "site", "<site>")
	banner = (
		"\n"
		"================================================================\n"
		" lazychat_mcp_erpnext installed\n"
		"================================================================\n"
		f" Site:     {site}\n"
		" Panel:    enabled by default (right-side slide-out via FAB)\n"
		" Tools:    38 registered (reads, mutations, workflow, analytics,\n"
		"           reports, ERPNext domain, communications, power tools)\n"
		"\n"
		" PRIMARY admin surface:\n"
		f"   Open http://localhost:8000/app/lazychat-settings\n"
		"   - 'Enabled' toggle, iframe URL, chat path (auto/browser/backend),\n"
		"     and security gates all live here.\n"
		"\n"
		" Pick your chat path (Lazychat Settings → Chat Path):\n"
		"   * auto (default) — chat-ui auto-routes:\n"
		"       custom model in chat-ui  -> Browser-LLM (key in browser)\n"
		"       built-in 'Default' model -> Backend-LLM (key in LLM Provider)\n"
		"   * browser — always Browser-LLM. Configure a custom model in chat-ui's\n"
		"       model picker (its existing ModelEditor with BYO key/endpoint).\n"
		"   * backend — always Backend-LLM. Open Desk → 'LLM Provider' →\n"
		"       Anthropic (or NVIDIA, OpenAI, ...) → set API Key.\n"
		"\n"
		" Site_config advanced overrides (optional):\n"
		"   {\n"
		'     "lazychat_iframe_src": "http://127.0.0.1:5173/?frame=sidebar"  // chat-ui HMR\n'
		'     "lazychat_allow_email": true                                    // enable prepare_send_email\n'
		'     "lazychat_allow_dangerous_tools": true                          // enable prepare_run_sql / prepare_run_python\n'
		"   }\n"
		"\n"
		" Smoke test (verifies all 38 tools + settings + MCP against real data):\n"
		f"   bench --site {site} execute lazychat_mcp_erpnext._smoke.run\n"
		"================================================================\n"
	)
	try:
		print(banner)
	except Exception:
		pass


def seed_llm_defaults():
	# Not under fixtures/ — Frappe migrate auto-imports every fixtures/*.json and requires each doc to have "name".
	# Now also seeds Lazychat Skill rows (starter pack: ar-collections, item-onboarding).
	path = os.path.join(os.path.dirname(__file__), "seed_data.json")
	if not os.path.exists(path):
		return
	with open(path) as f:
		rows = json.load(f)
	for row in rows:
		dt = row["doctype"]
		if dt == "LLM Provider":
			if frappe.db.exists("LLM Provider", {"provider_name": row["provider_name"]}):
				continue
		elif dt == "LLM Model":
			if frappe.db.exists("LLM Model", {"model_label": row["model_label"]}):
				continue
		elif dt == "Lazychat Skill":
			# Skip seeding if the doctype isn't migrated yet (first install before migrate),
			# or if a row with this skill_name already exists.
			if not frappe.db.exists("DocType", "Lazychat Skill"):
				continue
			if frappe.db.exists("Lazychat Skill", row["skill_name"]):
				continue
		else:
			continue
		frappe.get_doc(row).insert(ignore_permissions=True, ignore_links=True)
	frappe.db.commit()


def _map_agilitas_asset(url):
	"""Map old /files/agilitas*.svg paths to bundled /assets/... URLs."""
	if not url or not isinstance(url, str) or "/files/agilitas" not in url:
		return None
	u = url.lower()
	if "txt-logo" in u or "txt_logo" in u:
		return _ASSET_LOGO
	if ".icon" in u or u.endswith("icon.svg"):
		return _ASSET_ICON
	return _ASSET_LOGO


def patch_agilitas_branding():
	"""Fix 404/500 on /files/agilitas*.svg by pointing Website Settings (and ERPNext navbar) at app assets."""
	if getattr(frappe.flags, "in_install_app", False):
		return
	try:
		if frappe.db.exists("Website Settings", "Website Settings"):
			ws = frappe.get_single("Website Settings")
			updated = False
			for df in ws.meta.fields:
				if df.fieldtype not in ("Attach", "Attach Image", "Data", "Small Text"):
					continue
				raw = ws.get(df.fieldname)
				replacement = _map_agilitas_asset(raw)
				if replacement:
					ws.set(df.fieldname, replacement)
					updated = True
			if updated:
				ws.save(ignore_permissions=True)

		if frappe.db.exists("Navbar Settings", "Navbar Settings"):
			ns = frappe.get_single("Navbar Settings")
			ns_updated = False
			for fname in ("logo", "app_logo"):
				if not hasattr(ns, fname):
					continue
				raw = getattr(ns, fname)
				replacement = _map_agilitas_asset(raw)
				if replacement:
					setattr(ns, fname, replacement)
					ns_updated = True
			if ns_updated:
				ns.save(ignore_permissions=True)

		frappe.db.commit()
	except Exception:
		frappe.log_error(frappe.get_traceback(), "lazychat_mcp_erpnext.patch_agilitas_branding")
