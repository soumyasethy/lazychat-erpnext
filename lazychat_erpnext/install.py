import json
import os

import frappe


def run_after_migrate():
	seed_llm_defaults()
	seed_lazychat_settings()
	seed_lazychat_form_helpers()
	lazychat_setup_check()
	_check_playwright_available()
	_seed_md_dashboard()


def after_install():
	"""Called once when bench --site <site> install-app lazychat_erpnext succeeds.

	Defaults work without any admin action:
	  - Lazychat Settings doctype auto-created with chat_path=auto, enabled=true
	  - Iframe loads bundled chat-ui dist (same-origin, port-free)
	  - Both browser-LLM and backend-LLM paths available; auto picks based on chat-ui's active model
	"""
	seed_llm_defaults()
	seed_lazychat_settings()
	seed_lazychat_form_helpers()
	lazychat_setup_check()
	_check_playwright_available()
	_seed_md_dashboard()
	_print_welcome_banner()


def _check_playwright_available():
	"""Cycle 13 M2: probe whether Playwright + Chromium are installed on this bench.

	The screenshot preview service (`desk_assistant.screenshot.capture`) is an
	OPTIONAL extra — most Frappe Cloud installs don't need it. We log a clear
	actionable warning when it's missing so admins know how to enable it, but
	we never fail the install hook on its absence.
	"""
	try:
		from lazychat_erpnext.desk_assistant.screenshot import is_available
	except Exception:
		return
	if is_available():
		frappe.logger().info("[lazychat] screenshot preview ready (Playwright + Chromium detected)")
	else:
		frappe.logger().warning(
			"[lazychat] screenshot preview is DISABLED. To enable, run:\n"
			"    ./env/bin/pip install playwright\n"
			"    ./env/bin/playwright install chromium\n"
			"Then set Lazychat Settings.enable_screenshot_preview = true."
		)


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
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- seed_lazychat_settings (after_install/after_migrate hook): commit the seeded Single row so it's durable; install hooks don't get a clean request-end commit
	except Exception:
		frappe.log_error(frappe.get_traceback(), "lazychat_erpnext.seed_lazychat_settings")


def lazychat_setup_check():
	"""Verify the bundled chat-ui dist exists; warn (don't fail) with the build command if missing."""
	app_path = frappe.get_app_path("lazychat_erpnext")
	index_html = os.path.join(app_path, "public", "lazychat_dist", "index.html")
	if not os.path.exists(index_html):
		msg = (
			"\n[lazychat_erpnext] WARNING: bundled chat-ui dist NOT found at\n"
			f"    {index_html}\n"
			"  The lazychat panel will fail to load until you build it.\n"
			"  From your lazychat-erpnext repo:\n"
			"    ./scripts/build-lazychat-dist.sh\n"
			"    ./scripts/deploy-local.sh\n"
			"  Or set 'lazychat_iframe_src' in site_config.json to a running chat-ui URL.\n"
		)
		try:
			print(msg)
		except Exception:
			pass
		try:
			frappe.log_error(msg, "lazychat_erpnext lazychat dist missing")
		except Exception:
			pass


def _print_welcome_banner():
	site = getattr(frappe.local, "site", "<site>")
	try:
		from lazychat_erpnext.desk_assistant.tool_schemas import TOOL_SCHEMAS

		n_tools = len(TOOL_SCHEMAS)
	except Exception:
		n_tools = 0
	banner = (
		"\n"
		"================================================================\n"
		" lazychat_erpnext installed\n"
		"================================================================\n"
		f" Site:     {site}\n"
		" Panel:    enabled by default (right-side slide-out via FAB)\n"
		f" Tools:    {n_tools} registered (reads, mutations, workflow, analytics,\n"
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
		f" Smoke test (verifies all {n_tools} tools + settings + MCP against real data):\n"
		f"   bench --site {site} execute lazychat_erpnext._smoke.run\n"
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
	with open(path) as f:  # nosemgrep: frappe-security-file-traversal -- fixed bundled path: os.path.join(os.path.dirname(__file__), "seed_data.json"); no external input
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
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- seed_llm_defaults (after_install/after_migrate hook): commit the seeded LLM Provider/Model/Skill rows so they're durable


# Module-level constants — single source of truth for the lazychat URL
# convention. Both the helper Client Script JS body (templated below) AND
# the get_form_prefill_capabilities MCP tool import these.
LAZYCHAT_PARENT_WHITELIST = (
	"supplier", "customer",
	"is_return", "return_against",
	"posting_date", "due_date", "set_warehouse",
	"company", "cost_center", "project", "currency",
)

LAZYCHAT_ITEM_WHITELIST = (
	"item_code", "item_name", "description",
	"qty", "rate", "amount",
	"uom", "stock_uom", "conversion_factor",
	"warehouse", "cost_center", "expense_account", "income_account",
	"project", "tax_rate",
	"purchase_receipt", "pr_detail",
	"purchase_invoice", "purchase_invoice_item",
	"sales_order", "so_detail",
	"sales_invoice", "sales_invoice_item",
	"delivery_note", "dn_detail",
)

LAZYCHAT_FORM_HELPER_TARGETS = (
	"Purchase Invoice", "Sales Invoice",
	"Purchase Receipt", "Delivery Note",
)

_LAZYCHAT_FORM_HELPER_SCRIPT = r"""
// Lazychat form-fill helper — seeded by lazychat_erpnext install hooks.
// Reads URL params on a NEW form and prefills parent fields + the items
// child table. The variance-report HTML buttons emit URLs like:
//   /app/purchase-invoice/new?is_return=1&return_against=PI-XXX&supplier=ACME&_lz_items=<base64-json>
//
// Why a Client Script: Frappe's new-form route handler reads URL params for
// PARENT fields only — child-table rows (e.g. items[0][item_code]) cannot be
// set via query string. We base64-encode a JSON array of row objects and
// decode it client-side.
//
// Why signature-based reapply: when `return_against` is set, ERPNext's Make
// Return logic auto-fetches items from the original doc and clobbers ours.
// We detect the clobber by signature mismatch on each `refresh` event and
// re-inject. This wins the race regardless of timing.
(function () {
  // Cycle 11 — M2.1: read the URL query string captured by the panel-shim
  // (`lazychat_panel.bundle.js`) at HTML-parse time, BEFORE Frappe v15's
  // `/new` route handler redirects to `/new-<dt>-<id>` and strips the query
  // string. By the time this Client Script's IIFE runs (via Frappe boot,
  // which happens AFTER the redirect), `window.location.search` is empty —
  // so we read the captured value from `window.__lazychat_initial_search`
  // instead. Falls back to live URL for SPA navigation cases where the
  // panel-shim's capture is stale (in-app `frappe.set_route` calls don't
  // re-run the panel-shim IIFE).
  var _capturedSearch = '';
  try {
    if (window.__lazychat_initial_search) {
      _capturedSearch = String(window.__lazychat_initial_search).replace(/^\?/, '');
    } else {
      _capturedSearch = (window.location.search || '').replace(/^\?/, '');
    }
  } catch (e) {}

  // Decode URL-safe base64 (handles +/= and percent-encoded variants).
  function _decode(b64) {
    if (!b64) return null;
    try {
      var s = decodeURIComponent(b64).replace(/-/g, '+').replace(/_/g, '/');
      // pad if length not multiple of 4
      while (s.length % 4) s += '=';
      var bin = atob(s);
      var pct = bin.split('').map(function (c) {
        return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
      }).join('');
      return JSON.parse(decodeURIComponent(pct));
    } catch (e) {
      try { return JSON.parse(atob(b64)); } catch (e2) { return null; }
    }
  }
  // Returns a wrapper that prefers live URL params (in case Frappe didn't
  // strip them) and falls back to the capture from script-load time.
  function _params() {
    var live;
    try { live = new URLSearchParams(window.location.search); }
    catch (e) { live = new URLSearchParams(''); }
    var captured;
    try { captured = new URLSearchParams(_capturedSearch); }
    catch (e) { captured = new URLSearchParams(''); }
    return {
      get: function (k) {
        var v = live.get(k);
        if (v != null) return v;
        return captured.get(k);
      },
    };
  }
  // Stable signature of a parsed _lz_items array — used to tell our rows
  // apart from auto-fetched / user-added rows.
  function _sig(rows) {
    return rows.map(function (r) {
      return [r.item_code || '', r.qty || 0, r.rate || 0, r.pr_detail || ''].join('|');
    }).join('::');
  }
  // Signature of currently-mounted items[] (same shape).
  function _frmSig(items) {
    return (items || []).map(function (r) {
      return [r.item_code || '', r.qty || 0, r.rate || 0, r.pr_detail || ''].join('|');
    }).join('::');
  }

  // Whitelist of item-row fields we'll honor from URL data. Everything else
  // is computed by ERPNext's own item_code/uom/warehouse handlers.
  var ITEM_WHITELIST = __ITEM_WHITELIST__;
  // Whitelist of parent-level fields settable from the URL (in addition
  // to anything Frappe's own URL parser already wires up). Some setters
  // (return_against) trigger heavy auto-fetch that races _lz_items —
  // we restore items via signature reapply below.
  var PARENT_WHITELIST = __PARENT_WHITELIST__;

  function setParentFromUrl(frm, p) {
    PARENT_WHITELIST.forEach(function (k) {
      var v = p.get(k) || p.get('_lz_' + k);
      if (!v) return;
      // is_return is integer
      if (k === 'is_return') v = (v === '1' || v === 'true') ? 1 : 0;
      if (frm.doc[k] === v) return;
      try { frm.set_value(k, v); } catch (e) {}
    });
  }

  function applyItems(frm, rows) {
    if (frm.doc.items && frm.doc.items.length > 0) {
      frm.clear_table('items');
    }
    rows.forEach(function (row) {
      if (!row || typeof row !== 'object') return;
      var d = frm.add_child('items');
      ITEM_WHITELIST.forEach(function (k) {
        if (row[k] !== undefined && row[k] !== null) d[k] = row[k];
      });
    });
    frm.refresh_field('items');
    // Trigger ERPNext's item_code handler so HSN / taxes / UOM / account
    // / warehouse defaults auto-fill. Wrap each in try/catch — some
    // doctypes don't define item_code triggers and Frappe throws then.
    (frm.doc.items || []).forEach(function (row) {
      if (!row.item_code) return;
      try { frappe.model.trigger('item_code', row.item_code, row); } catch (e) {}
    });
  }

  function lazychatPrefill(frm) {
    if (!frm || !frm.is_new || !frm.is_new()) return;
    var p = _params();

    // Always re-set parent fields on every refresh — set_value is a noop
    // if value already matches. Cheap idempotent.
    setParentFromUrl(frm, p);

    // Cycle 11 — M2: prefer `_lz_token` (server-staged payload) over the
    // legacy `_lz_items` URL convention. Token-based path is single-use
    // (server consumes on first read), so we cache the fetched payload
    // on the form to allow signature-reapply on subsequent refresh events.
    var token = p.get('_lz_token');
    if (token) {
      if (frm.__lz_token_payload) {
        // Already fetched — reapply via signature check (same as _lz_items path).
        var rowsT = frm.__lz_token_payload.items || [];
        if (Array.isArray(rowsT) && rowsT.length > 0) {
          var ourSigT = _sig(rowsT);
          var nowSigT = _frmSig(frm.doc.items);
          if (ourSigT !== nowSigT) applyItems(frm, rowsT);
        }
        // Apply parent_fields from the cached payload too (in case Make
        // Return / similar clobbered them).
        var pfT = frm.__lz_token_payload.parent_fields || {};
        Object.keys(pfT).forEach(function (k) {
          if (frm.doc[k] !== pfT[k]) {
            try { frm.set_value(k, pfT[k]); } catch (e) {}
          }
        });
        return;
      }
      // Race guard: 5 event handlers (onload_post_render, refresh, plus 3
      // field-change handlers) all call lazychatPrefill in quick succession
      // during form load. Without this flag, a second invocation dispatches
      // a parallel fetch that consumes the single-use token from the
      // server-side cache and produces a benign "{ok: false}" log. Flag
      // ensures only the first event triggers the network call.
      if (frm.__lz_token_fetching) return;
      frm.__lz_token_fetching = true;
      // First fetch — single-use, server consumes on read.
      frappe.call({
        method: "lazychat_erpnext.desk_assistant.api.fetch_form_prefill",
        args: { token: token },
        callback: function (r) {
          frm.__lz_token_fetching = false;
          if (!r || !r.message || !r.message.ok) {
            console.warn("[lazychat] fetch_form_prefill failed:", r && r.message && r.message.error);
            return;
          }
          var payload = r.message;
          frm.__lz_token_payload = payload;
          // Apply parent_fields (server-validated, doctype-bound).
          var pf = payload.parent_fields || {};
          Object.keys(pf).forEach(function (k) {
            try { frm.set_value(k, pf[k]); } catch (e) {}
          });
          // Apply items via the same applyItems path used by _lz_items.
          var rows = payload.items || [];
          if (Array.isArray(rows) && rows.length > 0) {
            applyItems(frm, rows);
          }
        },
      });
      return;
    }

    // Legacy `_lz_items` URL convention — kept for one cycle, prefer
    // `_lz_token` (Cycle 11 M2) for new reports to avoid HTTP 414.
    var rawItems = p.get('_lz_items');
    if (!rawItems) return;
    if (!frm.__lz_items_warned) {
      console.warn("[lazychat] _lz_items URL convention is deprecated. Use prepare_form_prefill (Cycle 11 M2) for new reports — generates a tiny _lz_token URL that doesn't hit HTTP 414 on large payloads.");
      frm.__lz_items_warned = true;
    }
    var rows = _decode(rawItems);
    if (!Array.isArray(rows) || rows.length === 0) return;

    var ourSig = _sig(rows);
    var nowSig = _frmSig(frm.doc.items);
    if (ourSig === nowSig) return;  // already applied, untouched

    // Items differ from our payload — either empty (first paint) OR
    // auto-fetched by Make Return. Either way, restore our payload.
    applyItems(frm, rows);
  }

  if (window.frappe && frappe.ui && frappe.ui.form) {
    frappe.ui.form.on('__DT__', {
      onload_post_render: lazychatPrefill,
      refresh: lazychatPrefill,
      // Re-apply when return_against finishes its async auto-fetch — that
      // change handler fires AFTER Make Return has already clobbered items.
      return_against: function (frm) { setTimeout(function () { lazychatPrefill(frm); }, 50); },
      supplier: function (frm) { setTimeout(function () { lazychatPrefill(frm); }, 50); },
      customer: function (frm) { setTimeout(function () { lazychatPrefill(frm); }, 50); },
    });
  }
})();
""".strip()

_LAZYCHAT_FORM_HELPER_NAME = "Lazychat Form Helper"


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
	for dt in LAZYCHAT_FORM_HELPER_TARGETS:
		if not frappe.db.exists("DocType", dt):
			continue  # site doesn't have this doctype (e.g. no Stock module)
		body = (
			_LAZYCHAT_FORM_HELPER_SCRIPT
			.replace("__DT__", dt)
			.replace("__ITEM_WHITELIST__", json.dumps(list(LAZYCHAT_ITEM_WHITELIST)))
			.replace("__PARENT_WHITELIST__", json.dumps(list(LAZYCHAT_PARENT_WHITELIST)))
		)
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
			frappe.log_error(frappe.get_traceback(), f"lazychat_erpnext.seed_lazychat_form_helpers/{dt}")
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- seed_lazychat_form_helpers (after_install/after_migrate hook): commit the seeded Client Script helpers so they're durable


def _seed_md_dashboard():
	"""Cycle 14 — seed the 4 MD Dashboard doctypes with starter rows from the
	Proman MD Dashboard mockup. Idempotent: only seeds when the table is empty
	for that doctype, so re-running after_install or run_after_migrate is safe."""
	import frappe

	# MD KPI Score — 53 BSC starter rows (4 perspectives covering ~13 each).
	# Tuple shape: (perspective, kpi_code, kpi_name, target_text, current_value, status, period)
	if frappe.db.count("MD KPI Score") == 0:
		_KPI_SEED = [
			("Financial", "F01", "Gross margin %", ">35-45%", "32%", "At Risk", "Q1 FY27"),
			("Financial", "F02", "EBITDA margin %", ">12-18%", "11.4%", "Behind", "Q1 FY27"),
			("Financial", "F03", "Net profit margin %", ">7-12%", "8.1%", "At Risk", "Q1 FY27"),
			("Financial", "F04", "Free cash flow", "Positive monthly", "Positive", "On Track", "Q1 FY27"),
			("Financial", "F05", "Cash runway (weeks)", ">10 weeks", "12 weeks", "On Track", "Q1 FY27"),
			("Financial", "F06", "DSO (debtor days)", "<60d", "68d", "Behind", "Q1 FY27"),
			("Financial", "F07", "Overdue >90d", "<25L", "320L", "Behind", "Q1 FY27"),
			("Financial", "F08", "Revenue growth YoY", ">15%", "18%", "On Track", "Q1 FY27"),
			("Financial", "F09", "Recurring revenue growth", ">20% YoY", "14%", "At Risk", "Q1 FY27"),
			("Financial", "Q01", "QMS sales 15 Cr", "1.25 Cr/month", "On track", "On Track", "Q1 FY27"),
			("Customer", "C01", "CSAT (post-install)", ">4.2/5", "4.4/5", "On Track", "Q1 FY27"),
			("Customer", "C02", "NPS", ">45", "38", "At Risk", "Q1 FY27"),
			("Customer", "C03", "Repeat order rate", ">50%", "58%", "On Track", "Q1 FY27"),
			("Customer", "C04", "AMC renewal rate", ">85%", "78%", "At Risk", "Q1 FY27"),
			("Customer", "C05", "On-site response time", "<24 hrs", "18 hrs", "On Track", "Q1 FY27"),
			("Customer", "C06", "Complaint resolution", "<5 days", "4.2 days", "On Track", "Q1 FY27"),
			("Customer", "C07", "New customers/month", "3-5/mo", None, "Not Started", "Q1 FY27"),
			("Customer", "C08", "Revenue per installed plant", "Growing YoY", None, "Not Started", "Q1 FY27"),
			("Customer", "S01", "Sales target Cr annual", "120 Cr", "98 Cr trajectory", "On Track", "Q1 FY27"),
			("Customer", "S02", "Pipeline coverage", ">=3x quarterly target", "2.7x", "At Risk", "Q1 FY27"),
			("Customer", "S03", "Conversion rate", ">35%", "28%", "Behind", "Q1 FY27"),
			("Customer", "S04", "Quote TAT", "<2 days", "3.2 days", "Behind", "Q1 FY27"),
			("Customer", "A01", "Service revenue 52 Cr", "10.4 Cr Q1", "9.8 Cr", "On Track", "Q1 FY27"),
			("Customer", "A02", "Spares fill rate", ">85% within 24hr", None, "Not Started", "Q1 FY27"),
			("Customer", "A03", "Inventory cap", "<=9 Cr all stores", None, "Not Started", "Q1 FY27"),
			("Internal Process", "I01", "OEE %", ">75%", "67%", "Behind", "Q1 FY27"),
			("Internal Process", "I02", "On-time delivery %", ">90%", "62%", "Behind", "Q1 FY27"),
			("Internal Process", "I03", "Inventory turns - spares", "6-8x", "6.4x", "On Track", "Q1 FY27"),
			("Internal Process", "I04", "Vendor OTD %", ">88%", None, "Not Started", "Q1 FY27"),
			("Internal Process", "I05", "Rework/scrap % COGS", "<1.5%", "2.1%", "Behind", "Q1 FY27"),
			("Internal Process", "I06", "BOM material variance", "<3%", "2.4%", "On Track", "Q1 FY27"),
			("Internal Process", "I07", "Plan adherence", ">85%", None, "Not Started", "Q1 FY27"),
			("Internal Process", "I08", "WIP as % revenue", "<8%", None, "Not Started", "Q1 FY27"),
			("Internal Process", "I09", "ERPNext utilisation %", ">85%", None, "Not Started", "Q1 FY27"),
			("Internal Process", "B01", "BMH equipment 11 Cr", "Sizer/Retrofit qtr", "10.2 Cr", "On Track", "Q1 FY27"),
			("Internal Process", "B02", "BMH new orders 40 Cr annual", "New equipment booking", "8 Cr Q1", "On Track", "Q1 FY27"),
			("Internal Process", "E01", "Projects on-time (IM) 75%", "75% on time", "62%", "At Risk", "Q1 FY27"),
			("Internal Process", "E02", "Drawing release error rate", "Log + zero defects", None, "Not Started", "Q1 FY27"),
			("Internal Process", "Q02", "Margin WP/SP", "WP 15% SP 40%", None, "Not Started", "Q1 FY27"),
			("Internal Process", "Q03", "Export new customers", "2-3 new/yr", None, "Not Started", "Q1 FY27"),
			("Internal Process", "P01", "Production volume", "2500 MT/yr", "Q1 ramp", "On Track", "Q1 FY27"),
			("Internal Process", "P02", "Plant utilisation", "47.5% avg", None, "Not Started", "Q1 FY27"),
			("Internal Process", "P03", "Promax DSO", "<=45 days", None, "Not Started", "Q1 FY27"),
			("Internal Process", "M01", "5S / Kaizen safety programs", "Active", "Active", "On Track", "Q1 FY27"),
			("Internal Process", "M02", "ERP operations module", "Implementation", None, "Not Started", "Q1 FY27"),
			("Learning & Growth", "L01", "Employee attrition %", "<10%", "11%", "Behind", "Q1 FY27"),
			("Learning & Growth", "L02", "Critical vacancy rate", "<10%", "9%", "At Risk", "Q1 FY27"),
			("Learning & Growth", "L03", "Training hrs/employee/yr", ">24 hrs", "26 hrs", "On Track", "Q1 FY27"),
			("Learning & Growth", "L04", "ERP utilisation %", ">85%", None, "Not Started", "Q1 FY27"),
			("Learning & Growth", "L05", "New product launches", "2-3/yr", "2", "On Track", "Q1 FY27"),
			("Learning & Growth", "L06", "Revenue from products <3 yrs", ">15%", "17%", "On Track", "Q1 FY27"),
			("Learning & Growth", "D01", "Design cycle time reduction", "Quarterly target", None, "Not Started", "Q1 FY27"),
			("Learning & Growth", "D02", "AI literacy completion", "Training rate", None, "Not Started", "Q1 FY27"),
			("Learning & Growth", "D03", "Transformation ROI", "Proman Edge ROI", None, "Not Started", "Q1 FY27"),
		]
		for persp, code, name, target, current, status, period in _KPI_SEED:
			doc = frappe.get_doc({
				"doctype": "MD KPI Score",
				"perspective": persp, "kpi_code": code, "kpi_name": name,
				"target_text": target, "current_value": current,
				"status": status, "period": period,
			})
			doc.insert(ignore_permissions=True)
		print("[lazychat] seeded {0} MD KPI Score rows".format(len(_KPI_SEED)))

	# MD Risk — 7 starter rows
	if frappe.db.count("MD Risk") == 0:
		_RISK_SEED = [
			("High", "Jaw plate castings from Glazier Tekno delayed 12 days; 3 orders at risk", "Ops / Glazier"),
			("High", "Overdue collection from Rajasthan quarry 1.2 Cr, 90+ days outstanding", "Finance / Sales"),
			("High", "Bidadi CNC machine #3 downtime 4 days; repair 1.8L pending MD approval", "Dynatek / Engg"),
			("High", "M-Sand VSI wear parts stockout; 2 customer machines idle (Pune, Hyderabad)", "ACE / Spares"),
			("Medium", "Middle East contract renewal 3.2 Cr; proposal pending 18 days, no response", "Sales / MD"),
			("Medium", "Glazier foundry quality rejection rate up 3% this quarter; RCA in progress", "Quality / Glazier"),
			("Medium", "2 senior engineers resigned; notice ends Apr 20, replacement pipeline empty", "HR"),
		]
		for severity, desc, owner in _RISK_SEED:
			doc = frappe.get_doc({
				"doctype": "MD Risk",
				"severity": severity, "description": desc, "owner": owner,
			})
			doc.insert(ignore_permissions=True)
		print("[lazychat] seeded {0} MD Risk rows".format(len(_RISK_SEED)))

	# MD Decision — 7 starter rows
	if frappe.db.count("MD Decision") == 0:
		from datetime import date, timedelta
		_today = date.today()
		_DEC_SEED = [
			("Approve 1.8L Bidadi CNC repair; vendor quote received and reviewed", "CapEx", _today + timedelta(days=2)),
			("Sanction revised credit limit for Rajasthan customer (2 Cr -> 75L)", "Credit", _today + timedelta(days=3)),
			("Approve Middle East proposal dispatch; Sales needs green light", "Sales", _today + timedelta(days=1)),
			("Sign off H1 FY27 hiring plan; 8 positions across entities", "Hiring", _today + timedelta(days=7)),
			("Confirm AI/ERP technology partner selection (Proman Edge milestone)", "Strategy", _today + timedelta(days=10)),
			("Approve strategic pricing revision; Cone Crusher CC-300 series", "Pricing", _today + timedelta(days=13)),
			("Authorise emergency spares procurement 3.4L; clear VSI wear parts stockout", "Procurement", _today + timedelta(days=1)),
		]
		for decision, category, due in _DEC_SEED:
			doc = frappe.get_doc({
				"doctype": "MD Decision",
				"decision": decision, "category": category,
				"due_date": due, "status": "Pending",
			})
			doc.insert(ignore_permissions=True)
		print("[lazychat] seeded {0} MD Decision rows".format(len(_DEC_SEED)))

	# Critical Role — 5 starter rows
	if frappe.db.count("Critical Role") == 0:
		from datetime import date, timedelta
		_open_45 = date.today() - timedelta(days=45)
		_open_30 = date.today() - timedelta(days=30)
		_ROLE_SEED = [
			("Sr Design Engineer (SolidWorks)", "Proman Infrastructure", "Critical", _open_45),
			("Production Supervisor - Bidadi", "Dynatek", "Critical", _open_45),
			("Service Engineer - Field South", "ACE", "Critical", _open_30),
			("Sales Engineer - North India", "PCS", "High", _open_30),
			("Finance Executive - Group", "Group HQ", "High", _open_30),
		]
		for pos, entity, criticality, open_since in _ROLE_SEED:
			doc = frappe.get_doc({
				"doctype": "Critical Role",
				"position_name": pos, "entity": entity,
				"criticality": criticality, "open_since": open_since,
			})
			doc.insert(ignore_permissions=True)
		print("[lazychat] seeded {0} Critical Role rows".format(len(_ROLE_SEED)))

	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- one-time idempotent seed
