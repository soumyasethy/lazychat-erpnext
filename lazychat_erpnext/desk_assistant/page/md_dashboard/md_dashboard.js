frappe.pages["md-dashboard"].on_page_load = function (wrapper) {
  var page = frappe.ui.make_app_page({ parent: wrapper, title: "MD Dashboard", single_column: true });

  page.main.html(MD_DASHBOARD_HTML);

  try {

    function fmtINR(n) {
      if (n == null || isNaN(n)) return "—";
      var v = Math.abs(n);
      if (v >= 10000000) return (n < 0 ? "-" : "") + "₹" + (v / 10000000).toFixed(2) + " Cr";
      if (v >= 100000)   return (n < 0 ? "-" : "") + "₹" + (v / 100000).toFixed(2) + " L";
      return (n < 0 ? "-" : "") + "₹" + Math.round(v).toLocaleString("en-IN");
    }
    function fmtCount(n) { return n == null ? "—" : Number(n).toLocaleString("en-IN"); }
    function setText(id, v) { var el = document.getElementById(id); if (el) el.textContent = v; }
    // setNodeHtml: all callers pass escapeHtml()-sanitised strings built from bench DB data only.
    // Values come through lazychat_dashboard_aggregate (System Manager-only) or frappe.client.get_list.
    // escapeHtml() is applied to every interpolated field before concatenation.
    function setNodeHtml(id, v) { var el = document.getElementById(id); if (el) el.innerHTML = v; }
    function escapeHtml(s) {
      if (s == null) return "";
      return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function agg(spec) {
      return new Promise(function (resolve) {
        frappe.call({
          method: "lazychat_erpnext.desk_assistant.api.lazychat_dashboard_aggregate",
          args: { spec: JSON.stringify(spec) },
          callback: function (r) {
            if (r && r.message && r.message.ok) resolve(r.message.data);
            else resolve(null);
          },
          error: function () { resolve(null); }
        });
      });
    }

    function getList(doctype, opts) {
      var args = { doctype: doctype, limit_page_length: opts && opts.limit ? opts.limit : 200 };
      if (opts && opts.fields) args.fields = opts.fields;
      if (opts && opts.filters) args.filters = opts.filters;
      if (opts && opts.order_by) args.order_by = opts.order_by;
      return new Promise(function (resolve) {
        frappe.call({
          method: "frappe.client.get_list", args: args,
          callback: function (r) { resolve((r && r.message) || []); },
          error: function () { resolve([]); }
        });
      });
    }

    function loadSnapshot() {
      return Promise.all([
        agg({ doctype: "Sales Invoice", filters: { docstatus: 1 },
              aggregations: [{ name: "ytd", field: "grand_total", op: "sum" },
                             { name: "out", field: "outstanding_amount", op: "sum" },
                             { name: "n", op: "count" }] }),
        agg({ doctype: "Employee", filters: { status: "Active" }, aggregations: [{ name: "n", op: "count" }] })
      ]).then(function (res) {
        var si = res[0] || { ytd: 0, out: 0, n: 0 };
        var emp = res[1] || { n: 0 };
        setText("ytdRev", fmtINR(si.ytd));
        setText("invCnt", fmtCount(si.n));
        setText("outstand", fmtINR(si.out));
        setText("hcCount", fmtCount(emp.n));
        setText("revYtd2", fmtINR(si.ytd));
        setText("outFin", fmtINR(si.out));
        setText("hrHc", fmtCount(emp.n));
      });
    }

    function loadBSC() {
      return getList("MD KPI Score", { fields: ["name", "perspective", "status"], limit: 500 }).then(function (rows) {
        var perspMap = { "Financial": [], "Customer": [], "Internal Process": [], "Learning & Growth": [] };
        rows.forEach(function (r) { if (perspMap[r.perspective]) perspMap[r.perspective].push(r.status); });
        var html = "";
        Object.keys(perspMap).forEach(function (p) {
          var statuses = perspMap[p];
          var on = 0, atr = 0, beh = 0, ns = 0;
          statuses.forEach(function (s) {
            if (s === "On Track") on += 1;
            else if (s === "At Risk") atr += 1;
            else if (s === "Behind") beh += 1;
            else ns += 1;
          });
          html += '<div class="md-panel">'
            + '<div class="md-kpi-label">' + escapeHtml(p) + '</div>'
            + '<div style="font-family:monospace;font-size:18px;color:var(--text-color);margin:6px 0;">' + statuses.length + ' KPIs</div>'
            + '<div style="font-size:11px;color:var(--text-muted);">'
            + '<span style="color:#00B894">' + on + ' on track</span> · '
            + '<span style="color:#F39C12">' + atr + ' at risk</span> · '
            + '<span style="color:#E74C3C">' + beh + ' behind</span> · '
            + '<span>' + ns + ' not started</span>'
            + '</div></div>';
        });
        setNodeHtml("bscGrid", html);
      });
    }

    function loadDivisions() {
      return getList("MD KPI Score", { fields: ["name", "kpi_code", "kpi_name", "current_value", "status", "perspective"], limit: 500 }).then(function (rows) {
        var html = '<div class="md-list">';
        rows.slice(0, 20).forEach(function (r) {
          var cls = r.status === "On Track" ? "md-row-g" : r.status === "At Risk" ? "md-row-a" : r.status === "Behind" ? "md-row-r" : "";
          var tag = r.status === "On Track" ? "md-tag-g" : r.status === "At Risk" ? "md-tag-a" : r.status === "Behind" ? "md-tag-r" : "";
          html += '<div class="md-row ' + cls + '">'
            + '<span style="font-family:monospace;font-size:10px;color:var(--text-muted);width:42px;flex-shrink:0">' + escapeHtml(r.kpi_code || "—") + '</span>'
            + '<span style="flex:1">' + escapeHtml(r.kpi_name) + '</span>'
            + '<span style="font-family:monospace;font-size:10px;color:var(--text-muted)">' + escapeHtml(r.current_value || "—") + '</span>'
            + '<span class="md-tag ' + tag + '">' + escapeHtml(r.status) + '</span>'
            + '</div>';
        });
        if (rows.length > 20) html += '<div class="md-loading">+ ' + (rows.length - 20) + ' more — see /app/md-kpi-score</div>';
        html += "</div>";
        setNodeHtml("divList", html);
      });
    }

    function loadRisks() {
      return getList("MD Risk", {
        fields: ["name", "severity", "description", "owner"],
        filters: { resolved_date: ["is", "not set"] },
        order_by: "severity asc, raised_date desc",
        limit: 20
      }).then(function (rows) {
        if (!rows.length) { setNodeHtml("riskList", '<div class="md-loading">No open risks</div>'); return; }
        var html = "";
        rows.forEach(function (r) {
          var cls = r.severity === "High" ? "md-row-r" : r.severity === "Medium" ? "md-row-a" : "";
          var tag = r.severity === "High" ? "md-tag-r" : r.severity === "Medium" ? "md-tag-a" : "md-tag-g";
          html += '<div class="md-row ' + cls + '">'
            + '<span class="md-tag ' + tag + '" style="width:60px">' + escapeHtml(r.severity) + '</span>'
            + '<span style="flex:1">' + escapeHtml(r.description) + '</span>'
            + '<span style="font-family:monospace;font-size:10px;color:var(--text-muted);white-space:nowrap">' + escapeHtml(r.owner || "") + '</span>'
            + '</div>';
        });
        setNodeHtml("riskList", html);
      });
    }

    function loadDecisions() {
      return getList("MD Decision", {
        fields: ["name", "decision", "due_date", "category"],
        filters: { status: "Pending" },
        order_by: "due_date asc",
        limit: 20
      }).then(function (rows) {
        if (!rows.length) { setNodeHtml("decList", '<div class="md-loading">No pending decisions</div>'); return; }
        var html = "";
        rows.forEach(function (r) {
          var due = r.due_date ? frappe.datetime.str_to_user(r.due_date) : "—";
          html += '<div class="md-row md-row-a">'
            + '<span style="flex:1">' + escapeHtml(r.decision) + '</span>'
            + '<span class="md-tag" style="width:90px">' + escapeHtml(r.category || "") + '</span>'
            + '<span class="md-tag md-tag-a" style="width:80px">' + escapeHtml(due) + '</span>'
            + '</div>';
        });
        setNodeHtml("decList", html);
      });
    }

    function loadSales() {
      var t = new Date();
      var firstOfMonth = t.getFullYear() + "-" + String(t.getMonth() + 1).padStart(2, "0") + "-01";
      return Promise.all([
        agg({ doctype: "Lead", filters: { status: ["not in", ["Lost Quotation", "Closed", "Converted"]] }, aggregations: [{ name: "n", op: "count" }] }),
        agg({ doctype: "Opportunity", filters: { status: "Open" }, aggregations: [{ name: "n", op: "count" }] }),
        agg({ doctype: "Quotation", filters: { docstatus: 0 }, aggregations: [{ name: "n", op: "count" }] }),
        agg({ doctype: "Sales Order", filters: { docstatus: 1, transaction_date: [">=", firstOfMonth] },
              aggregations: [{ name: "sum", field: "grand_total", op: "sum" }] })
      ]).then(function (res) {
        setText("leadCnt", fmtCount((res[0] || {}).n));
        setText("oppCnt", fmtCount((res[1] || {}).n));
        setText("quoteCnt", fmtCount((res[2] || {}).n));
        setText("soMtd", fmtINR((res[3] || {}).sum));
      });
    }

    function loadAging() {
      var t = new Date();
      function isoMinus(days) {
        var d = new Date(t.getTime() - days * 86400000);
        return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
      }
      return Promise.all([
        agg({ doctype: "Sales Invoice", filters: { docstatus: 1, outstanding_amount: [">", 0], posting_date: [">=", isoMinus(30)] },
              aggregations: [{ name: "amt", field: "outstanding_amount", op: "sum" }, { name: "n", op: "count" }] }),
        agg({ doctype: "Sales Invoice", filters: { docstatus: 1, outstanding_amount: [">", 0], posting_date: ["between", [isoMinus(60), isoMinus(31)]] },
              aggregations: [{ name: "amt", field: "outstanding_amount", op: "sum" }, { name: "n", op: "count" }] }),
        agg({ doctype: "Sales Invoice", filters: { docstatus: 1, outstanding_amount: [">", 0], posting_date: ["between", [isoMinus(90), isoMinus(61)]] },
              aggregations: [{ name: "amt", field: "outstanding_amount", op: "sum" }, { name: "n", op: "count" }] }),
        agg({ doctype: "Sales Invoice", filters: { docstatus: 1, outstanding_amount: [">", 0], posting_date: ["<", isoMinus(90)] },
              aggregations: [{ name: "amt", field: "outstanding_amount", op: "sum" }, { name: "n", op: "count" }] })
      ]).then(function (res) {
        var buckets = [
          ["0-30 days",  res[0], "#00B894"],
          ["31-60 days", res[1], "#F39C12"],
          ["61-90 days", res[2], "#E74C3C"],
          [">90 days",   res[3], "#E74C3C"]
        ];
        var max = 0;
        buckets.forEach(function (b) { var amt = (b[1] || {}).amt || 0; if (amt > max) max = amt; });
        var html = "";
        buckets.forEach(function (b) {
          var amt = (b[1] || {}).amt || 0;
          var n = (b[1] || {}).n || 0;
          var pct = max > 0 ? Math.round((amt / max) * 100) : 0;
          html += '<div class="md-aging-row">'
            + '<span style="font-size:11px;color:var(--text-muted)">' + escapeHtml(b[0]) + '</span>'
            + '<span style="font-family:monospace;font-size:11px;color:var(--text-color)">' + fmtINR(amt) + '</span>'
            + '<div class="md-aging-bar"><div class="md-aging-fill" style="width:' + pct + '%;background:' + b[2] + ';"></div></div>'
            + '<span style="font-family:monospace;font-size:10px;color:var(--text-muted);text-align:right">' + n + ' invoices</span>'
            + '</div>';
        });
        setNodeHtml("agingTable", html);
      });
    }

    function loadPayables() {
      return Promise.all([
        agg({ doctype: "Purchase Invoice", filters: { docstatus: 1 },
              aggregations: [{ name: "creditors", field: "grand_total", op: "sum" }, { name: "overdue", field: "outstanding_amount", op: "sum" }] }),
        agg({ doctype: "Purchase Order", filters: { docstatus: 1 }, aggregations: [{ name: "n", op: "count" }] }),
        agg({ doctype: "Material Request", filters: { docstatus: 1 }, aggregations: [{ name: "n", op: "count" }] })
      ]).then(function (res) {
        var pi = res[0] || { creditors: 0, overdue: 0 };
        setText("creditors", fmtINR(pi.creditors));
        setText("credFin", fmtINR(pi.creditors));
        setText("overduePay", fmtINR(pi.overdue));
        setText("poCount", fmtCount((res[1] || {}).n));
        setText("prCount", fmtCount((res[2] || {}).n));
      });
    }

    function loadOps() {
      return Promise.all([
        agg({ doctype: "Work Order", filters: { docstatus: 1 }, aggregations: [{ name: "n", op: "count" }], group_by: "status" }),
        agg({ doctype: "Stock Entry", filters: { docstatus: 1 }, aggregations: [{ name: "n", op: "count" }] }),
        agg({ doctype: "Delivery Note", filters: { docstatus: 1 }, aggregations: [{ name: "n", op: "count" }] })
      ]).then(function (res) {
        var byStatus = res[0] || [];
        var stockN = (res[1] || {}).n || 0;
        var dnN = (res[2] || {}).n || 0;
        var html = '<div class="md-grid-4">';
        if (Array.isArray(byStatus)) {
          byStatus.slice(0, 4).forEach(function (s) {
            html += '<div class="md-kpi"><div class="md-kpi-label">WO ' + escapeHtml(s.status || "—") + '</div><div class="md-kpi-val">' + fmtCount(s.n) + '</div></div>';
          });
        }
        html += '<div class="md-kpi"><div class="md-kpi-label">Stock Entries</div><div class="md-kpi-val">' + fmtCount(stockN) + '</div></div>'
             + '<div class="md-kpi"><div class="md-kpi-label">Delivery Notes</div><div class="md-kpi-val">' + fmtCount(dnN) + '</div></div>';
        html += "</div>";
        setNodeHtml("opsBlock", html);
      });
    }

    function loadFinance() {
      return agg({
        doctype: "GL Entry",
        filters: { is_cancelled: 0 },
        aggregations: [{ name: "debit", field: "debit", op: "sum" }, { name: "credit", field: "credit", op: "sum" }]
      }).then(function (g) {
        var net = g ? ((g.debit || 0) - (g.credit || 0)) : null;
        setText("cashNet", fmtINR(net));
      });
    }

    function loadHR() {
      return Promise.all([
        agg({ doctype: "Job Opening", filters: { status: "Open" }, aggregations: [{ name: "n", op: "count" }] }),
        getList("Critical Role", { fields: ["name", "position_name", "entity", "criticality", "open_since"], limit: 20 })
      ]).then(function (res) {
        var jo = (res[0] || {}).n || 0;
        var crit = res[1] || [];
        setText("hrJob", fmtCount(jo));
        setText("hrOpen", fmtCount(jo + crit.length));
        setText("hrCrit", fmtCount(crit.filter(function (c) { return c.criticality === "Critical"; }).length));
        var html = "";
        crit.forEach(function (c) {
          var cls = c.criticality === "Critical" ? "md-row-r" : c.criticality === "High" ? "md-row-a" : "";
          var tag = c.criticality === "Critical" ? "md-tag-r" : c.criticality === "High" ? "md-tag-a" : "md-tag-g";
          html += '<div class="md-row ' + cls + '">'
            + '<span style="flex:1">' + escapeHtml(c.position_name) + '</span>'
            + '<span class="md-tag" style="width:120px">' + escapeHtml(c.entity || "") + '</span>'
            + '<span class="md-tag ' + tag + '" style="width:70px">' + escapeHtml(c.criticality) + '</span>'
            + '</div>';
        });
        setNodeHtml("critList", html || '<div class="md-loading">No critical roles flagged</div>');
      });
    }

    function loadDigital() {
      return getList("MD KPI Score", {
        fields: ["name", "kpi_code", "kpi_name", "current_value", "status"],
        filters: { perspective: "Learning & Growth" },
        order_by: "kpi_code asc",
        limit: 20
      }).then(function (rows) {
        var html = "";
        rows.forEach(function (r) {
          var cls = r.status === "On Track" ? "md-row-g" : r.status === "At Risk" ? "md-row-a" : r.status === "Behind" ? "md-row-r" : "";
          html += '<div class="md-row ' + cls + '">'
            + '<span style="font-family:monospace;font-size:10px;color:var(--text-muted);width:42px">' + escapeHtml(r.kpi_code || "—") + '</span>'
            + '<span style="flex:1">' + escapeHtml(r.kpi_name) + '</span>'
            + '<span style="font-family:monospace;font-size:10px;color:var(--text-muted)">' + escapeHtml(r.current_value || "—") + '</span>'
            + '<span class="md-tag">' + escapeHtml(r.status) + '</span>'
            + '</div>';
        });
        setNodeHtml("digList", html || '<div class="md-loading">No digital milestones tracked yet</div>');
      });
    }

    function loadAll() {
      var t = new Date();
      setText("lastUpdate", "Last updated: " + t.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }));
      return Promise.all([
        loadSnapshot(), loadBSC(), loadDivisions(), loadRisks(), loadDecisions(),
        loadSales(), loadAging(), loadPayables(), loadOps(), loadFinance(), loadHR(), loadDigital()
      ]);
    }

    loadAll().then(function () {
      document.body.dataset.lazychatReady = "1";
    });
    setInterval(loadAll, 5 * 60 * 1000);

  } catch (e) {
    console.error("[md-dashboard]", e);
  }
};

var MD_DASHBOARD_HTML = ''
  + '<header class="md-topbar">'
  + '  <div class="md-topbar-row">'
  + '    <h1>MD Dashboard</h1>'
  + '    <span id="lastUpdate" class="md-meta">—</span>'
  + '  </div>'
  + '</header>'
  + '<main class="md-main">'
  + '  <section class="md-sec" id="sec-snap"><div class="md-sec-h"><div class="md-sec-bar md-bar-g"></div><h2>Group Snapshot</h2></div><div class="md-grid-4">'
  + '    <div class="md-kpi"><div class="md-kpi-label">YTD Revenue</div><div id="ytdRev" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Sales Invoices YTD</div><div id="invCnt" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Outstanding</div><div id="outstand" class="md-kpi-val md-kpi-bad">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Headcount</div><div id="hcCount" class="md-kpi-val">—</div></div>'
  + '  </div></section>'
  + '  <section class="md-sec" id="sec-bsc"><div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Balanced Scorecard</h2></div><div id="bscGrid" class="md-grid-4"><div class="md-loading">Loading...</div></div></section>'
  + '  <section class="md-sec" id="sec-div"><div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Division KPI Progress</h2></div><div id="divList" class="md-list"><div class="md-loading">Loading...</div></div></section>'
  + '  <section class="md-sec" id="sec-risk"><div class="md-sec-h"><div class="md-sec-bar md-bar-r"></div><h2>Top Risks &amp; Issues</h2></div><div id="riskList" class="md-list"><div class="md-loading">Loading...</div></div></section>'
  + '  <section class="md-sec" id="sec-dec"><div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Decisions Required from MD</h2></div><div id="decList" class="md-list"><div class="md-loading">Loading...</div></div></section>'
  + '  <section class="md-sec" id="sec-sales"><div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Sales &amp; Business Development</h2></div><div class="md-grid-4">'
  + '    <div class="md-kpi"><div class="md-kpi-label">Active Leads</div><div id="leadCnt" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Open Opportunities</div><div id="oppCnt" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Pending Quotations</div><div id="quoteCnt" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Sales Order MTD</div><div id="soMtd" class="md-kpi-val">—</div></div>'
  + '  </div></section>'
  + '  <section class="md-sec" id="sec-rec"><div class="md-sec-h"><div class="md-sec-bar md-bar-r"></div><h2>Receivables &amp; Collections</h2></div><div id="agingTable" class="md-panel"><div class="md-loading">Loading...</div></div></section>'
  + '  <section class="md-sec" id="sec-pay"><div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Payables &amp; Procurement</h2></div><div class="md-grid-4">'
  + '    <div class="md-kpi"><div class="md-kpi-label">Total Creditors</div><div id="creditors" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Active POs</div><div id="poCount" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Overdue Payables</div><div id="overduePay" class="md-kpi-val md-kpi-bad">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Material Requests</div><div id="prCount" class="md-kpi-val">—</div></div>'
  + '  </div></section>'
  + '  <section class="md-sec" id="sec-ops"><div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Operations &amp; Production</h2></div><div id="opsBlock" class="md-panel"><div class="md-loading">Loading...</div></div></section>'
  + '  <section class="md-sec" id="sec-fin"><div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Finance Snapshot</h2></div><div class="md-grid-4">'
  + '    <div class="md-kpi"><div class="md-kpi-label">Revenue YTD</div><div id="revYtd2" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Outstanding Total</div><div id="outFin" class="md-kpi-val md-kpi-bad">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Creditors Total</div><div id="credFin" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">GL Net</div><div id="cashNet" class="md-kpi-val">—</div></div>'
  + '  </div></section>'
  + '  <section class="md-sec" id="sec-hr"><div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>HR &amp; People</h2></div><div class="md-grid-4">'
  + '    <div class="md-kpi"><div class="md-kpi-label">Active Headcount</div><div id="hrHc" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Open Positions</div><div id="hrOpen" class="md-kpi-val">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Critical Roles</div><div id="hrCrit" class="md-kpi-val md-kpi-bad">—</div></div>'
  + '    <div class="md-kpi"><div class="md-kpi-label">Job Openings (ERP)</div><div id="hrJob" class="md-kpi-val">—</div></div>'
  + '  </div><div id="critList" class="md-list md-mt-12"><div class="md-loading">Loading critical roles...</div></div></section>'
  + '  <section class="md-sec" id="sec-dig"><div class="md-sec-h"><div class="md-sec-bar md-bar-g"></div><h2>Digital Transformation Milestones</h2></div><div id="digList" class="md-list"><div class="md-loading">Loading...</div></div></section>'
  + '</main>';
