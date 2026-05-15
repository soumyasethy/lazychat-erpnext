# Cycle 14 — MD Dashboard rebuild + Dashboard-from-Mockup discipline (design)

**Goal.** Two coupled deliverables that close the same class of bug:

- **A** — Rebuild `/app/md-dashboard` so it actually shows real ERPNext data across all 12 sections of the original Proman MD Dashboard mockup the user uploaded. The previous Cycle-13 chat-driven attempt produced a ₹0 / ₹2 / ₹0 / 100 shell with 9 sections silently dropped.
- **B** — Upgrade the agent so the *next* time anyone uploads a complex reference mockup, the agent generates a fully-wired version on first try (no scope drift, correct aggregations, correct units).

Both ship together as `cycle-14`. Versions: `lazychat-erpnext 0.3.1 → 0.4.0` (new doctypes = minor bump per Keep-a-Changelog). `lazychat.ai 0.1.1 → 0.1.2` (prompt mirror only).

**Companion docs.** Builds on `cycle-13` (Mockup-to-ERPNext: typed UI primitives + Playwright screenshot + LLM-as-judge auto-iterate). The Building-Desk-Pages playbook from cycle-13 promised exactly this kind of dashboard generation; this cycle pays off the promise for the realistic case (88k+ rows, 12+ sections, mix of ERP-derivable and manual-entry data).

---

## Bug — what the user reported

User uploaded a 90 KB `Proman_MD_Dashboard.html` mockup with 12 strategic sections (Group Snapshot, BSC Scorecard, Division KPIs, Top Risks, MD Decisions, Sales, Receivables, Procurement, Operations, Finance, HR, Digital Milestones). Asked: *"can you create this website in erpnext website and understand the data make it dynamic picking from erpnext?"*

Agent (Haiku 4.5 via Vercel AI Gateway) generated `/app/md-dashboard` with **3 sections** and **all-zero numbers**. Specifically:

| Metric | Bench reality (verified via direct SQL) | Dashboard shows | Why |
|---|---|---|---|
| Sales Invoice count | 88,928 | (not displayed) | section dropped |
| YTD Revenue | ₹76.32 Cr | ₹0 | `limit_page_length: 500` truncated to first 500 rows; sum `÷ 10⁷` rounded to 0 |
| MTD Invoices | 0 (correct — no May 2026 invoices on this bench) | 0 | actually correct, by coincidence |
| Outstanding | ₹27.86 Cr | ₹0 | same truncation + unit bug |
| Total Creditors (PI sum) | ₹96.36 Cr | ₹2 | `limit_page_length: 200` capped sum at ~₹2 Cr / 10⁷ ≈ 2; displayed without "Cr" suffix |
| Active POs | 2,569 | 100 | `limit_page_length: 100` = direct truncation, displayed as count |
| Receivables aging | distributed across 4 buckets | 90+ days only (200 invoices, ₹6) | `limit 200` + chronological sort put all in oldest bucket; "₹6" lacks Cr suffix |

### Root causes (4 compounding)

1. **Aggregation via truncated client-side reduce.** `frappe.client.get_list` with `limit_page_length: 100/200/500` returns a slice; `.reduce((a,b) => a + b.grand_total, 0)` then sums only that slice. With 88 k rows, the result is wildly wrong. The correct shape is server-side `SUM()`.
2. **Hardcoded `÷ 10⁷` with no unit suffix.** `(value / 10000000).toFixed(0)` produces a number-of-Cr but the template doesn't append " Cr". A ₹0.2 Cr figure renders as "₹0"; a ₹76 Cr figure renders as "₹76" with no unit.
3. **Silent scope shrinkage.** Agent dropped 9 of 12 sections without telling the user. No error, no narration, just missing sections in the output.
4. **No data-source map for non-ERP sections.** BSC Scorecard, Risks, Decisions, "critical" hiring flags don't map to standard ERPNext doctypes. Agent didn't propose custom doctypes nor place explicit "manual entry needed" placeholders — it just dropped them.

### Why the existing playbook didn't catch this

Cycle 13's Building-Desk-Pages playbook covers ES5 syntax, theme tokens, semantic HTML, `lazychatReady` marker, casual-prompt cookbook. None of those address the bugs above. The playbook teaches *visual* fidelity but not *data-source* fidelity.

---

## Fix A — Real `/app/md-dashboard`

### A.1 — Four custom doctypes for the non-ERP sections

All four are per-bench data the MD owns; standard Frappe doctypes (no submittable workflow), System Manager perm only. Standard form UI for editing, no custom UI needed.

| DocType | Module | Naming | Fields | Why |
|---|---|---|---|---|
| `MD KPI Score` | Desk Assistant | autoname `KPI-{####}` | `perspective` (Select: Financial / Customer / Internal Process / Learning & Growth), `kpi_code` (Data, e.g. F01), `kpi_name` (Data, required), `target_text` (Data, e.g. ">35%"), `current_value` (Data, e.g. "32%"), `status` (Select: On Track / At Risk / Behind / Not Started), `period` (Data, e.g. "Q1 FY27"), `notes` (Small Text) | BSC Scorecard rows. 52 seed rows from the mockup. |
| `MD Risk` | Desk Assistant | autoname `RISK-{####}` | `severity` (Select: High / Medium / Low), `description` (Small Text, required), `owner` (Data), `raised_date` (Date), `resolved_date` (Date), `action_note` (Small Text) | Top Risks list. 7 seed rows. |
| `MD Decision` | Desk Assistant | autoname `DEC-{####}` | `decision` (Small Text, required), `due_date` (Date), `status` (Select: Pending / Resolved), `category` (Data), `resolution_note` (Small Text) | MD Decisions list. 7 seed rows. |
| `Critical Role` | Desk Assistant | autoname `ROLE-{####}` | `position_name` (Data, required), `entity` (Data — free text, NOT a Link to Company since the mockup uses informal entity names like "ACE", "Dynatek"), `criticality` (Select: Critical / High / Watch), `open_since` (Date) | Critical hiring flags. 5 seed rows. |

**Why custom doctypes vs reusing existing:** ToDo doesn't have severity / category / due-tracking shape needed for MD Decisions. Job Opening doesn't have a "criticality" flag and is full HR-workflow. Issue is closer but ties to support not strategic risk. Custom doctypes keep the MD-facing schema clean and minimal.

**Seed data shipped via fixture file** (`fixtures/cycle_14_md_seed.json`) loaded by `install.py:_seed_md_dashboard()` on `after_install` and `after_migrate` (idempotent — only seeds when zero rows exist for each doctype).

### A.2 — Server-side aggregate endpoint

New whitelisted method in `lazychat_erpnext/desk_assistant/api.py`:

```python
@frappe.whitelist(methods=["POST"])
def lazychat_dashboard_aggregate(spec: dict | str) -> dict:
    """Run a server-side SUM/COUNT/AVG/MIN/MAX with optional GROUP BY.

    Replaces the broken `frappe.client.get_list + JS reduce` pattern that
    truncates at limit_page_length and silently produces wrong totals on
    large tables.

    Spec shape (validated):
        {
          "doctype": "Sales Invoice",
          "filters": {"docstatus": 1, "posting_date": [">=", "2025-04-01"]},
          "aggregations": [
            {"name": "ytd_revenue", "field": "grand_total", "op": "sum"},
            {"name": "outstanding", "field": "outstanding_amount", "op": "sum"},
            {"name": "count", "op": "count"}      # field optional for count
          ],
          "group_by": null      # OR a fieldname → returns list of dicts
        }
    """
```

Validations (defense in depth):

- `doctype` must exist and caller must have `read` permission
- Each `field` must be in the doctype's meta (rejects unknown fields → no SQL injection via field name)
- `op` must be in `{"sum", "count", "avg", "min", "max"}` (whitelist)
- `aggregations` capped at 12 per call (prevents N² explosion)
- `group_by` field also meta-validated
- Filters passed verbatim to `frappe.db.get_list`'s filter builder (which already escapes); we never concatenate filter values into SQL

Returns:
- Without `group_by`: flat dict `{name: value, ...}`
- With `group_by`: list of dicts `[{<group_by>: <value>, name1: ..., name2: ...}, ...]`

Errors return `{ok: false, error: "..."}` (consistent with other lazychat endpoints).

### A.3 — `/app/md-dashboard` page rewrite (full 12 sections)

Full structural rebuild. Section list and per-section data plan:

| # | Section | Source | Tool / Query |
|---|---|---|---|
| 1 | Group Snapshot | ERP | `lazychat_dashboard_aggregate` × Sales Invoice (YTD revenue, MTD invoices, outstanding) + Purchase Invoice (creditors, overdue) + Purchase Order (count) + Employee (headcount) |
| 2 | BSC Scorecard | manual | `frappe.db.get_list("MD KPI Score", group_by_perspective)` — render 4 perspective cards with status counts |
| 3 | Division KPI Progress | manual | `frappe.db.get_list("MD KPI Score", filtered_by_division_tag)` — render the per-division table |
| 4 | Top Risks | manual | `frappe.db.get_list("MD Risk", {resolved_date: null}, order_by: severity)` |
| 5 | MD Decisions Required | manual | `frappe.db.get_list("MD Decision", {status: "Pending"}, order_by: due_date)` |
| 6 | Sales & BD | ERP | aggregate: Lead count, Opportunity sum, Quotation pending count + sum, Sales Order MTD sum, Customer count |
| 7 | Receivables & Collections | ERP | aggregate Sales Invoice with `group_by` aging buckets (custom SQL via aggregate's group_by) |
| 8 | Payables & Procurement | ERP | aggregate Purchase Invoice + Purchase Order |
| 9 | Operations & Production | ERP | aggregate Work Order (status group_by), Stock Entry MTD count, Delivery Note OTD via posting_date vs delivery_date |
| 10 | Finance Snapshot | ERP | aggregate Sales Invoice (YTD), GL Entry (cash balance), accounting close stats |
| 11 | HR & People | ERP + manual | aggregate Employee (count), Job Opening (open count) + `Critical Role` doctype for criticality flags |
| 12 | Digital Milestones | manual | `frappe.db.get_list("MD KPI Score", {perspective: "Learning & Growth", kpi_name: ["like", "%digital%"]})` OR a new sub-section in MD KPI Score |

Each section is a `<section>` block with consistent visual structure (matches the original mockup's design tokens: `--navy`, `--slate`, `--g/a/r/b/gr` color variables).

**Format helpers** in the page JS (single source of truth):

```js
function fmtINR(n) {
  if (n == null || isNaN(n)) return '—';
  var v = Math.abs(n);
  if (v >= 10000000)      return (n < 0 ? '-' : '') + '₹' + (v / 10000000).toFixed(2) + ' Cr';
  if (v >= 100000)        return (n < 0 ? '-' : '') + '₹' + (v / 100000).toFixed(2) + ' L';
  return (n < 0 ? '-' : '') + '₹' + Math.round(v).toLocaleString('en-IN');
}
function fmtCount(n) { return n == null ? '—' : Number(n).toLocaleString('en-IN'); }
function fmtPercent(n) { return n == null ? '—' : (Number(n).toFixed(1) + '%'); }
```

These NEVER produce a bare "₹0" without context — they produce "₹0" only if the input is literally 0 or null (in which case "—" is shown for null).

**Loading state.** Each section starts with `—` placeholders. As each `frappe.call` resolves, the section fills in. If a call fails (network/perm), the section shows `error: <reason>` instead of staying at `—`.

**Refresh.** Auto-refresh every 5 minutes via `setInterval`. `lazychatReady = '1'` only fires after `Promise.all` of the 12 initial calls (so M2 screenshot service waits for the rendered state).

### A.4 — Permission model

- The 4 MD doctypes have System Manager **read + write + create + delete** in their JSON metadata. No additional roles by default. (MD role may be created later if the user wants a dedicated read-only persona; out of scope for this cycle.)
- `lazychat_dashboard_aggregate` is whitelisted to **System Manager** only — defense in depth.
- `/app/md-dashboard` Page row's `roles` table includes only `System Manager` — matches the doctype gates above. Avoids surprise visibility.

---

## Fix B — Playbook upgrade

### B.1 — `_DASHBOARD_DISCIPLINE_BLOCK` added to `_DESK_PAGE_PLAYBOOK`

Inserted in both `claude_bridge.py` (backend canonical) and `routerSystemPrompt.ts` (chat-ui mirror) AFTER the existing 5-non-negotiable-rules block, BEFORE the casual-prompt cookbook.

Content:

```
## DASHBOARD-FROM-MOCKUP DISCIPLINE

When the user uploads a reference mockup with 5+ sections OR 20+ KPIs:

1. **INVENTORY**: List every section + KPI in the mockup BEFORE writing any code.
   No silent omissions. Output as a markdown table.

2. **CLASSIFY** each KPI:
   - **ERP-derivable** — name the doctype + the aggregation (sum / count / etc.)
   - **Manual entry** — propose a minimal custom doctype with 4-6 fields, OR
     reuse existing (ToDo, Note, Job Opening). Stage the doctype creation
     in the same plan.
   - **Not applicable** — skip with one-line reason.

3. **AGGREGATE via server-side SUM/COUNT/GROUP BY**, not client-side reduce.
   Use the whitelisted endpoint:

       frappe.call({
         method: 'lazychat_erpnext.desk_assistant.api.lazychat_dashboard_aggregate',
         args: { spec: {
           doctype: 'Sales Invoice',
           filters: { docstatus: 1 },
           aggregations: [{ name: 'ytd', field: 'grand_total', op: 'sum' }]
         }},
         callback: function(r) { /* r.message.ytd has the FULL sum */ }
       });

   NEVER use `frappe.client.get_list` with `limit_page_length` for totals.
   That truncates and produces silently-wrong sums on large tables (your
   88,928-row Sales Invoice table will return at most 500 rows = wrong
   sum by 99%+).

4. **UNITS — every numeric value MUST display its unit suffix.** A figure of
   ₹0.2 Cr displayed as "₹0" without a "Cr" suffix is indistinguishable
   from "no data". Use the magnitude-aware fmtINR pattern:

       function fmtINR(n) {
         if (n == null || isNaN(n)) return '—';
         var v = Math.abs(n);
         if (v >= 10000000) return '₹' + (v/10000000).toFixed(2) + ' Cr';
         if (v >= 100000)   return '₹' + (v/100000).toFixed(2) + ' L';
         return '₹' + Math.round(v).toLocaleString('en-IN');
       }

5. **RENDER ALL SECTIONS.** If the mockup has 12 sections, your output must
   have 12. If you must scope down (e.g., a section requires a custom doctype
   the user didn't authorize), LIST THE OMISSIONS in your reply text so
   the user can decide. Silent dropping is the most expensive bug class
   we have — every dropped section is a feature the user thought they
   asked for.

WRONG (silent truncation, no unit):
  frappe.call('frappe.client.get_list', {
    doctype:'Sales Invoice', limit_page_length:500
  }).then(r => {
    var sum = r.message.reduce((a,b) => a + b.grand_total, 0);
    document.getElementById('rev').textContent = '₹' + (sum/10000000).toFixed(0);
  });

RIGHT (server SUM, magnitude-aware unit):
  frappe.call({
    method: 'lazychat_erpnext.desk_assistant.api.lazychat_dashboard_aggregate',
    args: { spec: {
      doctype: 'Sales Invoice',
      filters: { docstatus: 1 },
      aggregations: [{ name: 'ytd', field: 'grand_total', op: 'sum' }]
    }},
    callback: function(r) {
      document.getElementById('rev').textContent = fmtINR(r.message.ytd);
    }
  });
```

### B.2 — Why no typed `prepare_aggregate_query` tool wrapper

We considered a typed Cycle-13-style `prepare_aggregate_query` wrapper. Rejected for now:
- The agent calls `lazychat_dashboard_aggregate` from page JS via `frappe.call` (not as a stage-and-commit mutation). It's a read-only data-fetch endpoint, not a write — doesn't need the prep/commit two-phase shape.
- One more typed tool = more system prompt surface to maintain. The playbook + endpoint together carry enough of the load.

If a future cycle finds the agent forgetting the endpoint exists or constructing wrong specs frequently, we can add a typed wrapper then.

### B.3 — Why no static-analysis validator

Considered a `page_validators.py` rule that flags `frappe.client.get_list` followed by `.reduce/.forEach` for sum/count. Rejected:
- False positives — sometimes `reduce` over a fully-fetched list (with no `limit_page_length`) is the right call (e.g., listing top-10 customers where 10 is genuinely 10).
- The playbook discipline + the endpoint's existence + the discipline's WRONG/RIGHT example carry the load; we can add a validator later if violations are still common.

---

## Tests

### Smoke (`scripts/smoke-test-tools.py`)

| Test | Asserts |
|---|---|
| **T100r** — aggregate sum on Sales Invoice | `lazychat_dashboard_aggregate({Sales Invoice, sum grand_total})` matches `bench --site execute "SELECT SUM(grand_total) FROM tabSales Invoice"` |
| **T100s** — aggregate rejects unknown field | `{field: "definitely_not_a_field"}` returns `{ok:false, error:"unknown field..."}` (NOT a SQL error / 500) |
| **T100t** — aggregate rejects op outside whitelist | `{op: "exec_arbitrary_sql"}` returns `{ok:false, error:"unknown op..."}` |
| **T100u** — 4 MD doctypes installable | After `install.py:_seed_md_dashboard()` runs idempotently, `frappe.db.count` for each doctype matches the fixture row count (52 / 7 / 7 / 5) |
| **T100v** — group_by aggregate | `{Sales Invoice, group_by: status, count}` returns multiple rows, one per status, with valid status names |
| **T100w** — permission gate | Calling `lazychat_dashboard_aggregate` as Guest returns 403 (PermissionError); as a non-System-Manager user returns 403 |

### chat-ui vitest

No new chat-ui tests — Cycle 14 is backend + page rewrite + prompt mirror only. Existing 461 tests keep passing.

### Browser E2E (manual / chrome-devtools)

After deploy:
1. Delete the old broken `/app/md-dashboard` Page row + on-disk dir
2. Re-stage via the chat panel using the SAME prompt the user originally sent ("can you create this website in erpnext website and understand the data make it dynamic picking from erpnext?") with the Proman_MD_Dashboard.html attached
3. **Pass criterion**: agent's response includes the inventory table + classification before the Apply card
4. **Pass criterion**: applied page renders all 12 sections
5. **Pass criterion**: Group Snapshot shows YTD ≈ ₹76 Cr (NOT ₹0), MTD invoices count, outstanding ≈ ₹28 Cr, creditors ≈ ₹96 Cr (with " Cr" suffix in all three)
6. **Pass criterion**: BSC Scorecard shows the 52 seed KPIs distributed across 4 perspective cards with status counts
7. **Pass criterion**: Top Risks + MD Decisions show the 7 seed rows each
8. Save screenshots to `2026-05-15-cycle-14-md-dashboard/{01-applied.png, 02-rendered.png, 03-bsc-section.png}`

---

## Files

| Path | Kind | Why |
|---|---|---|
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_kpi_score/{md_kpi_score.json, md_kpi_score.py, __init__.py}` | NEW | BSC scorecard storage |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_risk/{...}` | NEW | Top Risks storage |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_decision/{...}` | NEW | MD Decisions storage |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/critical_role/{...}` | NEW | Critical hiring flags |
| `lazychat-erpnext/lazychat_erpnext/fixtures/cycle_14_md_seed.json` | NEW | 52 + 7 + 7 + 5 seed rows |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/api.py` | MODIFY | + `lazychat_dashboard_aggregate(spec)` whitelisted method |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/install.py` | MODIFY | + `_seed_md_dashboard()` called from `after_install` + `after_migrate` |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard/{md_dashboard.html, md_dashboard.css, md_dashboard.js}` | REWRITE | Full 12-section page wired to aggregate endpoint + 4 MD doctypes |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py` | MODIFY | + `_DASHBOARD_DISCIPLINE_BLOCK` in `_DESK_PAGE_PLAYBOOK` |
| `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts` | MODIFY | Mirror discipline block byte-aligned with backend |
| `lazychat-erpnext/scripts/smoke-test-tools.py` | MODIFY | T100r through T100w (6 new tests) |
| `lazychat-erpnext/pyproject.toml` + `__init__.py` | MODIFY | `0.3.1 → 0.4.0` |
| `lazychat.ai/package.json` + `apps/chat-ui/package.json` | MODIFY | `0.1.1 → 0.1.2` |
| `lazychat-erpnext/CHANGELOG.md` + `lazychat.ai/CHANGELOG.md` | MODIFY | New `[0.4.0]` / `[0.1.2]` Cycle 14 sections |
| `lazychat-erpnext/CLAUDE.md` + `lazychat.ai/CLAUDE.md` | MODIFY | New `## Cycle 14` blocks above Cycle 13.2 |

---

## Verification (per `verification-before-completion`)

NO completion claim until ALL of:

1. **Static gates**:
   - `lazychat-erpnext` in-process smoke: 277 → **283 pass / 0 fail / 6 skip** (T100r through T100w)
   - chat-ui vitest: 461 / 0 (unchanged — no chat-ui code change)
   - chat-ui typecheck: clean
   - bench `bench --site erp.local migrate` runs cleanly with 4 new doctypes installed
   - `lazychat_erpnext.__version__ == "0.4.0"` after restart

2. **Aggregate endpoint sanity** (programmatic):
   - `lazychat_dashboard_aggregate({Sales Invoice, sum grand_total})` returns the same value as direct `bench execute "SELECT SUM(grand_total)..."`. Both should be ≈ 763,214,781.88.

3. **MD Dashboard E2E** (browser):
   - Delete + re-stage via chat with the original prompt + uploaded mockup
   - Load `/app/md-dashboard` (Cmd+Shift+R)
   - Visual: 12 sections rendered with real values, NOT ₹0 / ₹2 placeholders
   - Visual: BSC Scorecard shows distributed status counts (not all zeros)
   - Save 3 screenshots to `2026-05-15-cycle-14-md-dashboard/`

4. **Playbook discipline gate** (manual):
   - Re-run the chat with the original prompt, observe the agent's response BEFORE the Apply card
   - **Pass criterion**: response contains an inventory table listing all 12 sections AND a classification line per KPI ("Sales Invoice sum / manual / not applicable"). If the agent skips the inventory step, the playbook didn't take.

---

## Risks + open questions

- **Custom doctype proliferation.** 4 new doctypes is non-trivial; if MD doesn't actually use the BSC editor it becomes dead surface. Mitigation: seed with the mockup's 52 KPIs so there's something to look at on day one. If usage is zero after 2 weeks, deprecate via a future cycle.
- **Bench performance for the aggregate endpoint.** SUM over 88k Sales Invoice rows takes ~50 ms on this bench. We don't add caching in this cycle — 5-min auto-refresh + index-backed sums should be fine. If profile data shows it's slow, Cycle 15 can add Redis caching with a 60 s TTL.
- **`Critical Role.entity` is a free-text field, not a Link to Company.** The mockup uses informal entity names ("ACE", "Dynatek", "PCS") that don't map to standard ERPNext Company doctype rows. Going free-text is intentional for v1 — if MD wants strict referential integrity later, swap to Link in a future cycle.
- **The playbook upgrade is text-only.** It can drift from the actual `lazychat_dashboard_aggregate` signature if the endpoint changes. We accept this risk for now; a hash-diff smoke test between backend playbook and chat-ui mirror was deferred from Cycle 13.1 — same deferral applies here. Manual mirror discipline per commit.

---

## Out of scope

- Typed `prepare_aggregate_query` tool wrapper — defer to Cycle 15 if the agent struggles with the endpoint shape.
- Static-analysis validator that flags `frappe.client.get_list` + `.reduce` patterns — defer; playbook discipline + endpoint existence carry the load.
- Per-section auto-refresh independent intervals — single 5-min global refresh for v1, plenty.
- BSC Scorecard editing inline on the dashboard — MD edits via standard `/app/md-kpi-score` form. Inline editing is a future polish.
- Auto-migration of the existing broken `/app/md-dashboard` row — we delete + re-stage to validate the playbook discipline end-to-end.
- Mobile responsiveness for the 12-section dashboard — desk-only for v1 (matches the original mockup which assumed widescreen).
