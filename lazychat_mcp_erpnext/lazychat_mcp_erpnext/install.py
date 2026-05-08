import json
import os

import frappe

_ASSET_LOGO = "/assets/lazychat_mcp_erpnext/images/agilitas-txt-logo.svg"
_ASSET_ICON = "/assets/lazychat_mcp_erpnext/images/agilitas.icon.svg"


def run_after_migrate():
	seed_llm_defaults()
	seed_lazychat_settings()
	seed_lazychat_form_helpers()
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
	seed_lazychat_form_helpers()
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


_LAZYCHAT_FORM_HELPER_SCRIPT = r"""
// Lazychat form-fill helper — seeded by lazychat_mcp_erpnext install hooks.
// Reads URL params on a NEW form and prefills child-table rows that URL params
// alone can't reach (Frappe's new-form route handler ignores child-table query
// params). The variance-report HTML buttons emit URLs like:
//   /app/purchase-invoice/new?is_return=1&return_against=PI-XXX&_lz_items=<base64-json>
// where _lz_items is a base64 of a JSON array of {item_code, qty, rate,
// purchase_receipt?, pr_detail?, ...} rows. Items are only injected when the
// items table is empty, so this is safe for hand-edited drafts.
(function () {
  function _decode(b64) {
    try {
      var bin = atob(decodeURIComponent(b64));
      var pct = bin.split('').map(function (c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
      }).join('');
      return JSON.parse(decodeURIComponent(pct));
    } catch (e) {
      try { return JSON.parse(atob(b64)); } catch (e2) { return null; }
    }
  }
  function _params() {
    try { return new URLSearchParams(window.location.search); }
    catch (e) { return new URLSearchParams(''); }
  }
  function _alreadyApplied(frm) { return !!(frm.__lz_helper_applied); }
  function _markApplied(frm) { frm.__lz_helper_applied = true; }

  function lazychatPrefill(frm) {
    if (!frm || !frm.is_new || !frm.is_new()) return;
    if (_alreadyApplied(frm)) return;
    var p = _params();
    var rawItems = p.get('_lz_items');
    var isReturn = p.get('_lz_is_return') === '1' || p.get('is_return') === '1';
    var returnAgainst = p.get('return_against') || p.get('_lz_return_against');

    // Parent-level return flags (URL params CAN set parent fields on new
    // forms, but only after a tick — Frappe wipes them while wiring defaults).
    if (isReturn && frm.doc && !frm.doc.is_return) {
      frm.set_value('is_return', 1);
    }
    if (returnAgainst && frm.doc && !frm.doc.return_against) {
      frm.set_value('return_against', returnAgainst);
    }

    if (!rawItems) return;
    var rows = _decode(rawItems);
    if (!Array.isArray(rows) || rows.length === 0) return;
    if (frm.doc.items && frm.doc.items.length > 0) {
      // Don't clobber existing rows (e.g. user already added items).
      var hasRealRow = frm.doc.items.some(function (r) { return r.item_code; });
      if (hasRealRow) { _markApplied(frm); return; }
      // All-blank rows -> safe to clear.
      frm.clear_table('items');
    }
    rows.forEach(function (row) {
      if (!row || typeof row !== 'object') return;
      var d = frm.add_child('items');
      // Whitelist of fields we'll let the URL set. Everything else is
      // computed by ERPNext's own item-fetch handlers when item_code is set.
      ['item_code', 'qty', 'rate', 'amount', 'uom', 'warehouse',
       'purchase_receipt', 'pr_detail', 'sales_order', 'so_detail',
       'description'].forEach(function (k) {
        if (row[k] !== undefined && row[k] !== null) d[k] = row[k];
      });
    });
    _markApplied(frm);
    frm.refresh_field('items');
    // Trigger ERPNext's item_code handler so taxes/HSN/UOM auto-fill.
    (frm.doc.items || []).forEach(function (row) {
      if (row.item_code) {
        try { frappe.model.trigger('item_code', row.item_code, row); } catch (e) {}
      }
    });
  }

  if (window.frappe && frappe.ui && frappe.ui.form) {
    frappe.ui.form.on('__DT__', {
      onload_post_render: lazychatPrefill,
      refresh: lazychatPrefill,
    });
  }
})();
""".strip()

_LAZYCHAT_FORM_HELPER_NAME = "Lazychat Form Helper"
_LAZYCHAT_FORM_HELPER_TARGETS = ("Purchase Invoice", "Sales Invoice", "Purchase Receipt", "Delivery Note")


def seed_lazychat_form_helpers():
	"""Idempotently install one Client Script per target doctype that reads
	URL params (`_lz_items`, `_lz_is_return`, `return_against`) and prefills
	the items child table. This is what makes the variance-report HTML buttons
	actually populate the form — URL params alone can't reach child rows.

	Re-running is safe: existing scripts are updated to the latest body if it
	differs (e.g. after an app upgrade). Only modifies/creates scripts whose
	`name` matches the lazychat-managed prefix; never touches user scripts.
	"""
	if not frappe.db.exists("DocType", "Client Script"):
		return  # Frappe core not migrated yet (shouldn't happen in practice)
	for dt in _LAZYCHAT_FORM_HELPER_TARGETS:
		if not frappe.db.exists("DocType", dt):
			continue  # site doesn't have this doctype (e.g. no Stock module)
		body = _LAZYCHAT_FORM_HELPER_SCRIPT.replace("__DT__", dt)
		name = f"{_LAZYCHAT_FORM_HELPER_NAME} ({dt})"
		try:
			if frappe.db.exists("Client Script", name):
				cs = frappe.get_doc("Client Script", name)
				if (cs.script or "") != body or cs.enabled != 1 or cs.view != "Form":
					cs.script = body
					cs.enabled = 1
					cs.view = "Form"
					cs.dt = dt
					cs.save(ignore_permissions=True)
			else:
				frappe.get_doc({
					"doctype": "Client Script",
					"name": name,
					"dt": dt,
					"view": "Form",
					"enabled": 1,
					"script": body,
				}).insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"lazychat_mcp_erpnext.seed_lazychat_form_helpers/{dt}")
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
