# Cycle 14 — MD Dashboard rebuild + Dashboard-from-Mockup discipline (plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `/app/md-dashboard` so it shows real ERPNext data across all 12 sections (vs the broken zero shell), plus 4 minimal custom doctypes for non-ERP sections, plus a server-side aggregate endpoint that replaces the truncating `client.get_list + JS reduce` pattern, plus a playbook discipline block so the agent does this right next time.

**Architecture:** 4 new Frappe doctypes (System-Manager-only) + 1 new whitelisted aggregate endpoint with field-meta + op-whitelist validation + full 12-section page rewrite using both the aggregate endpoint and direct doctype reads + mirrored playbook block in backend `claude_bridge.py` and chat-ui `routerSystemPrompt.ts`.

**Tech Stack:** Python 3.11 + Frappe v15 + ES5 page JS; vitest unchanged.

**Spec:** [`../specs/2026-05-15-cycle-14-md-dashboard-discipline-design.md`](../specs/2026-05-15-cycle-14-md-dashboard-discipline-design.md)

**Repos:**
- backend: `/Users/soumyasethy/Desktop/code-chat/lazychat-erpnext` (`0.3.1 → 0.4.0`)
- chat-ui: `/Users/soumyasethy/Desktop/code-chat/lazychat.ai` (`0.1.1 → 0.1.2`)

---

## File structure

| File | Purpose | Touch |
|---|---|---|
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_kpi_score/{json,py,__init__.py}` | BSC scorecard rows (52 seed) | NEW |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_risk/{json,py,__init__.py}` | Top Risks (7 seed) | NEW |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_decision/{json,py,__init__.py}` | MD Decisions (7 seed) | NEW |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/critical_role/{json,py,__init__.py}` | Critical hiring flags (5 seed) | NEW |
| `lazychat-erpnext/lazychat_erpnext/install.py` | + `_seed_md_dashboard()` called from `after_install` + `run_after_migrate` | MODIFY |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/api.py` | + `lazychat_dashboard_aggregate(spec)` whitelisted | MODIFY |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard/md_dashboard.json` | Tighten roles to System Manager | MODIFY |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard/{html,css,js}` | Full 12-section page wired to aggregate endpoint + 4 MD doctypes | REWRITE |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py` | + `_DASHBOARD_DISCIPLINE_BLOCK` in `_DESK_PAGE_PLAYBOOK` | MODIFY |
| `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts` | Mirror discipline block | MODIFY |
| `lazychat-erpnext/scripts/smoke-test-tools.py` | T100r through T100w (6 new) | MODIFY |
| `lazychat-erpnext/CHANGELOG.md` + `CLAUDE.md` | New `[0.4.0]` Cycle 14 sections | MODIFY |
| `lazychat.ai/CHANGELOG.md` + `CLAUDE.md` | New `[0.1.2]` Cycle 14 sections | MODIFY |
| `lazychat-erpnext/pyproject.toml` + `__init__.py` | `0.3.1 → 0.4.0` | MODIFY |
| `lazychat.ai/package.json` + `apps/chat-ui/package.json` | `0.1.1 → 0.1.2` | MODIFY |

## Notes for the implementer

- **NEVER `git commit` / `git push`.** Wait for explicit user authorization.
- **NO `Co-Authored-By: Claude` trailer.**
- **Tab indentation** in Python + Frappe doctype JSON; spaces in JS / TS / package.json.
- The `lazychat_erpnext` Frappe app lives at the repo root; the bench at `/Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench` is a deploy target. Edit in source, then `sh build.sh`.
- Bench cache-bust trap (per project CLAUDE.md): after Python changes, `sh restart.sh --bg` is required. After new doctypes, `bench --site erp.local migrate` is required.
- **Page JS XSS safety**: the page JS uses `escapeHtml()` to safely render user-controlled doctype field values into DOM. All HTML construction is wrapped through that helper — never assemble HTML strings directly from `r.description` etc.

---

## Task 1 — MD KPI Score doctype

**Files:** Create `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_kpi_score/{md_kpi_score.json, md_kpi_score.py, __init__.py}`

- [ ] **Step 1: Create dir + empty `__init__.py`.**

```bash
mkdir -p /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_kpi_score && touch /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_kpi_score/__init__.py
```

- [ ] **Step 2: Write the doctype JSON** at `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_kpi_score/md_kpi_score.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "format:KPI-{####}",
 "creation": "2026-05-15 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["section_identity","perspective","kpi_code","kpi_name","section_targets","target_text","current_value","status","section_meta","period","notes"],
 "fields": [
  {"fieldname": "section_identity", "fieldtype": "Section Break", "label": "KPI Identity"},
  {"fieldname": "perspective", "fieldtype": "Select", "options": "Financial\nCustomer\nInternal Process\nLearning & Growth", "label": "BSC Perspective", "reqd": 1, "in_list_view": 1},
  {"fieldname": "kpi_code", "fieldtype": "Data", "label": "KPI Code", "in_list_view": 1, "description": "e.g. F01, C03, I05, L02"},
  {"fieldname": "kpi_name", "fieldtype": "Data", "label": "KPI Name", "reqd": 1, "in_list_view": 1},
  {"fieldname": "section_targets", "fieldtype": "Section Break", "label": "Targets & Status"},
  {"fieldname": "target_text", "fieldtype": "Data", "label": "Target", "description": "e.g. >35% or <60d"},
  {"fieldname": "current_value", "fieldtype": "Data", "label": "Current Value"},
  {"fieldname": "status", "fieldtype": "Select", "options": "On Track\nAt Risk\nBehind\nNot Started", "label": "Status", "reqd": 1, "default": "Not Started", "in_list_view": 1},
  {"fieldname": "section_meta", "fieldtype": "Section Break", "label": "Meta"},
  {"fieldname": "period", "fieldtype": "Data", "label": "Reporting Period"},
  {"fieldname": "notes", "fieldtype": "Small Text", "label": "Notes"}
 ],
 "issingle": 0, "links": [],
 "modified": "2026-05-15 12:00:00.000000", "modified_by": "Administrator",
 "module": "Desk Assistant", "name": "MD KPI Score", "owner": "Administrator",
 "permissions": [{"create": 1, "delete": 1, "email": 0, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1}],
 "sort_field": "modified", "sort_order": "DESC", "track_changes": 1
}
```

- [ ] **Step 3: Write the controller** at `md_kpi_score.py`:

```python
import frappe
from frappe.model.document import Document


class MDKPIScore(Document):
	"""One row of the MD's Balanced Scorecard. Edited via /app/md-kpi-score/<name>.
	Read by /app/md-dashboard which groups rows by perspective and renders status counts."""

	pass
```

- [ ] **Step 4: Verify JSON parses.**

```bash
python3 -c "import json; json.load(open('/Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_kpi_score/md_kpi_score.json'))" && echo OK
```
Expected: `OK`. Any error → fix.

---

## Task 2 — MD Risk doctype

**Files:** Create `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_risk/{md_risk.json, md_risk.py, __init__.py}`

- [ ] **Step 1: Create dir + empty `__init__.py`.**

```bash
mkdir -p /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_risk && touch /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_risk/__init__.py
```

- [ ] **Step 2: Write JSON** at `md_risk.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "format:RISK-{####}",
 "creation": "2026-05-15 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["severity","description","owner","section_dates","raised_date","resolved_date","section_action","action_note"],
 "fields": [
  {"fieldname": "severity", "fieldtype": "Select", "options": "High\nMedium\nLow", "label": "Severity", "reqd": 1, "default": "Medium", "in_list_view": 1},
  {"fieldname": "description", "fieldtype": "Small Text", "label": "Description", "reqd": 1, "in_list_view": 1},
  {"fieldname": "owner", "fieldtype": "Data", "label": "Owner / Function", "in_list_view": 1},
  {"fieldname": "section_dates", "fieldtype": "Section Break", "label": "Lifecycle"},
  {"fieldname": "raised_date", "fieldtype": "Date", "label": "Raised On"},
  {"fieldname": "resolved_date", "fieldtype": "Date", "label": "Resolved On", "description": "Leave empty while the risk is open. Dashboard treats null = unresolved."},
  {"fieldname": "section_action", "fieldtype": "Section Break", "label": "Action"},
  {"fieldname": "action_note", "fieldtype": "Small Text", "label": "Action / Mitigation"}
 ],
 "issingle": 0, "links": [],
 "modified": "2026-05-15 12:00:00.000000", "modified_by": "Administrator",
 "module": "Desk Assistant", "name": "MD Risk", "owner": "Administrator",
 "permissions": [{"create": 1, "delete": 1, "email": 0, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1}],
 "sort_field": "modified", "sort_order": "DESC", "track_changes": 1
}
```

- [ ] **Step 3: Write controller** at `md_risk.py`:

```python
import frappe
from frappe.model.document import Document


class MDRisk(Document):
	"""One executive risk tracked on the MD Dashboard's Top Risks list.
	Treated as 'open' when resolved_date is null."""

	pass
```

- [ ] **Step 4: Verify.**

```bash
python3 -c "import json; json.load(open('/Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_risk/md_risk.json'))" && echo OK
```

---

## Task 3 — MD Decision doctype

**Files:** Create `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_decision/{md_decision.json, md_decision.py, __init__.py}`

- [ ] **Step 1: Create dir + empty `__init__.py`.**

```bash
mkdir -p /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_decision && touch /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/md_decision/__init__.py
```

- [ ] **Step 2: Write JSON** at `md_decision.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "format:DEC-{####}",
 "creation": "2026-05-15 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["decision","category","section_due","due_date","status","section_resolution","resolution_note"],
 "fields": [
  {"fieldname": "decision", "fieldtype": "Small Text", "label": "Decision Required", "reqd": 1, "in_list_view": 1},
  {"fieldname": "category", "fieldtype": "Data", "label": "Category", "in_list_view": 1},
  {"fieldname": "section_due", "fieldtype": "Section Break", "label": "Tracking"},
  {"fieldname": "due_date", "fieldtype": "Date", "label": "Due By", "in_list_view": 1},
  {"fieldname": "status", "fieldtype": "Select", "options": "Pending\nResolved", "label": "Status", "reqd": 1, "default": "Pending", "in_list_view": 1},
  {"fieldname": "section_resolution", "fieldtype": "Section Break", "label": "Resolution"},
  {"fieldname": "resolution_note", "fieldtype": "Small Text", "label": "Resolution Note"}
 ],
 "issingle": 0, "links": [],
 "modified": "2026-05-15 12:00:00.000000", "modified_by": "Administrator",
 "module": "Desk Assistant", "name": "MD Decision", "owner": "Administrator",
 "permissions": [{"create": 1, "delete": 1, "email": 0, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1}],
 "sort_field": "modified", "sort_order": "DESC", "track_changes": 1
}
```

- [ ] **Step 3: Write controller** at `md_decision.py`:

```python
import frappe
from frappe.model.document import Document


class MDDecision(Document):
	"""A pending or resolved MD-level decision. Read by /app/md-dashboard,
	ordered by due_date when status='Pending'."""

	pass
```

- [ ] **Step 4: Verify.** (same pattern as Task 2 Step 4)

---

## Task 4 — Critical Role doctype

**Files:** Create `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/critical_role/{critical_role.json, critical_role.py, __init__.py}`

- [ ] **Step 1: Create dir + empty `__init__.py`.**

```bash
mkdir -p /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/critical_role && touch /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/critical_role/__init__.py
```

- [ ] **Step 2: Write JSON** at `critical_role.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "autoname": "format:ROLE-{####}",
 "creation": "2026-05-15 12:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["position_name","entity","section_meta","criticality","open_since"],
 "fields": [
  {"fieldname": "position_name", "fieldtype": "Data", "label": "Position Name", "reqd": 1, "in_list_view": 1},
  {"fieldname": "entity", "fieldtype": "Data", "label": "Entity / Division", "in_list_view": 1, "description": "Free-text. Mockup uses informal entity names like ACE, Dynatek, PCS."},
  {"fieldname": "section_meta", "fieldtype": "Section Break", "label": "Status"},
  {"fieldname": "criticality", "fieldtype": "Select", "options": "Critical\nHigh\nWatch", "label": "Criticality", "reqd": 1, "default": "Watch", "in_list_view": 1},
  {"fieldname": "open_since", "fieldtype": "Date", "label": "Open Since"}
 ],
 "issingle": 0, "links": [],
 "modified": "2026-05-15 12:00:00.000000", "modified_by": "Administrator",
 "module": "Desk Assistant", "name": "Critical Role", "owner": "Administrator",
 "permissions": [{"create": 1, "delete": 1, "email": 0, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1}],
 "sort_field": "modified", "sort_order": "DESC", "track_changes": 1
}
```

- [ ] **Step 3: Write controller** at `critical_role.py`:

```python
import frappe
from frappe.model.document import Document


class CriticalRole(Document):
	"""A critical/watched open hiring slot tracked on the MD Dashboard.
	Standalone of standard Job Opening to keep MD-facing schema minimal."""

	pass
```

- [ ] **Step 4: Verify.** (same pattern)

---

## Task 5 — `bench migrate` to install the 4 new doctypes

- [ ] **Step 1: Build + sync.**
```bash
cd /Users/soumyasethy/Desktop/code-chat && sh build.sh 2>&1 | tail -8
```

- [ ] **Step 2: Run `bench migrate`.**
```bash
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && bench --site erp.local migrate 2>&1 | tail -25
```
Look for: `Updating DocType MD KPI Score`, `Updating DocType MD Risk`, `Updating DocType MD Decision`, `Updating DocType Critical Role`. No errors at end.

- [ ] **Step 3: Confirm doctypes exist.**
```bash
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && bench --site erp.local console <<'PY' 2>&1 | tail -8
import frappe
for dt in ("MD KPI Score", "MD Risk", "MD Decision", "Critical Role"):
    print(dt, "exists:", bool(frappe.db.exists("DocType", dt)), "rows:", frappe.db.count(dt))
PY
```
Expected: 4 lines, each with `exists: True rows: 0` (Task 6 will seed rows).

---

## Task 6 — `_seed_md_dashboard()` in install.py

**Files:** Modify `lazychat-erpnext/lazychat_erpnext/install.py`

See spec section A.1 for the seed list shape. The seed function is large but mechanical (lists of tuples → `frappe.get_doc(...).insert()`).

- [ ] **Step 1: Read install.py top to find `after_install` and `run_after_migrate`.**
```bash
sed -n '1,30p' /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/install.py
```

- [ ] **Step 2: Append `_seed_md_dashboard()` to the END of install.py.**

Use Edit tool to append (or use the file append pattern). Function body:

```python


def _seed_md_dashboard():
	"""Cycle 14 — seed the 4 MD Dashboard doctypes with starter rows from the
	Proman MD Dashboard mockup. Idempotent: only seeds when the table is empty
	for that doctype, so re-running after_install or run_after_migrate is safe."""
	import frappe

	# MD KPI Score — ~52 BSC starter rows (4 perspectives × ~13 KPIs each).
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
```

- [ ] **Step 3: Wire `_seed_md_dashboard()` into `after_install` and `run_after_migrate`.**

Read both function bodies; append a call to `_seed_md_dashboard()` to each, after the existing `seed_lazychat_settings()` call.

- [ ] **Step 4: Run the seed once via bench console.**

```bash
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && bench --site erp.local console <<'PY' 2>&1 | tail -10
from lazychat_erpnext.install import _seed_md_dashboard
_seed_md_dashboard()
import frappe
print("KPI:", frappe.db.count("MD KPI Score"))
print("Risk:", frappe.db.count("MD Risk"))
print("Decision:", frappe.db.count("MD Decision"))
print("Role:", frappe.db.count("Critical Role"))
PY
```

Expected: 4 print lines + counts: KPI ≈ 53 (the seed list above has 53 entries — confirm the actual length matches), Risk: 7, Decision: 7, Role: 5.

- [ ] **Step 5: Re-run to confirm idempotency.** Repeat Step 4. Counts must be UNCHANGED, and no `[lazychat] seeded` print lines should appear.

---

## Task 7 — `lazychat_dashboard_aggregate` endpoint

**Files:** Modify `lazychat-erpnext/lazychat_erpnext/desk_assistant/api.py` (append at end).

- [ ] **Step 1: Read api.py top + bottom to know existing imports + style.**
```bash
sed -n '1,12p' /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/api.py
wc -l /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/api.py
```

- [ ] **Step 2: Append the endpoint.** Use Edit to add at end of file:

```python


# Cycle 14 — Dashboard aggregate endpoint
# Replaces the broken `frappe.client.get_list + JS reduce` pattern.
# Validates field names against doctype meta; op against fixed whitelist.
# System Manager only.

_AGG_OPS = {"sum", "count", "avg", "min", "max"}
_AGG_MAX_AGGREGATIONS = 12

_OP_MAP = {
	"=": "=", "!=": "!=", ">": ">", "<": "<", ">=": ">=", "<=": "<=",
	"like": "LIKE", "in": "IN", "not in": "NOT IN",
	"is": "IS", "is not": "IS NOT", "between": "BETWEEN",
}


@frappe.whitelist(methods=["POST"])
def lazychat_dashboard_aggregate(spec):
	"""Server-side SUM/COUNT/AVG/MIN/MAX with optional GROUP BY.

	spec shape (validated):
	  {
	    "doctype": "Sales Invoice",
	    "filters": {"docstatus": 1, "posting_date": [">=", "2025-04-01"]},
	    "aggregations": [
	      {"name": "ytd", "field": "grand_total", "op": "sum"},
	      {"name": "n", "op": "count"}
	    ],
	    "group_by": "status"
	  }

	Returns: {"ok": true, "data": <dict or list>} on success,
	         {"ok": false, "error": "..."} on any rejection.
	"""
	import json as _json

	if "System Manager" not in (frappe.get_roles(frappe.session.user) or []):
		return {"ok": False, "error": "System Manager required."}

	if isinstance(spec, str):
		try:
			spec = _json.loads(spec)
		except Exception as e:
			return {"ok": False, "error": "spec must be a JSON object: {0}".format(e)}
	if not isinstance(spec, dict):
		return {"ok": False, "error": "spec must be an object."}

	doctype = spec.get("doctype")
	if not doctype or not isinstance(doctype, str):
		return {"ok": False, "error": "spec.doctype is required (string)."}
	if not frappe.db.exists("DocType", doctype):
		return {"ok": False, "error": "unknown doctype: {0}".format(doctype)}
	if not frappe.has_permission(doctype, "read"):
		return {"ok": False, "error": "no read permission on {0}".format(doctype)}

	aggregations = spec.get("aggregations") or []
	if not isinstance(aggregations, list) or not aggregations:
		return {"ok": False, "error": "spec.aggregations must be a non-empty list."}
	if len(aggregations) > _AGG_MAX_AGGREGATIONS:
		return {"ok": False, "error": "too many aggregations (max {0}).".format(_AGG_MAX_AGGREGATIONS)}

	meta = frappe.get_meta(doctype)
	valid_fields = {f.fieldname for f in meta.fields} | {
		"name", "creation", "modified", "owner", "modified_by", "docstatus", "idx"
	}

	parts = []
	names = []
	for i, agg in enumerate(aggregations):
		if not isinstance(agg, dict):
			return {"ok": False, "error": "aggregations[{0}] must be an object.".format(i)}
		op = (agg.get("op") or "").strip().lower()
		if op not in _AGG_OPS:
			return {"ok": False, "error": "aggregations[{0}].op must be one of {1}; got {2!r}.".format(i, sorted(_AGG_OPS), op)}
		name = agg.get("name") or "agg_{0}".format(i)
		if not isinstance(name, str) or not name.replace("_", "").isalnum():
			return {"ok": False, "error": "aggregations[{0}].name must be alphanumeric/underscore; got {1!r}.".format(i, name)}
		if op == "count":
			fragment = "COUNT(*)"
		else:
			field = agg.get("field")
			if not field:
				return {"ok": False, "error": "aggregations[{0}].field required for op={1}.".format(i, op)}
			if field not in valid_fields:
				return {"ok": False, "error": "aggregations[{0}].field {1!r} is not in {2} meta.".format(i, field, doctype)}
			fragment = "{0}(`{1}`)".format(op.upper(), field)
		parts.append("{0} AS `{1}`".format(fragment, name))
		names.append(name)

	group_by_field = spec.get("group_by")
	if group_by_field is not None:
		if not isinstance(group_by_field, str) or group_by_field not in valid_fields:
			return {"ok": False, "error": "group_by {0!r} is not in {1} meta.".format(group_by_field, doctype)}
		parts.insert(0, "`{0}` AS `{0}`".format(group_by_field))
		names.insert(0, group_by_field)

	filters = spec.get("filters") or {}
	where_sql, where_values = _build_safe_where(filters, valid_fields)
	table = "`tab{0}`".format(doctype)
	select_sql = ", ".join(parts)
	group_sql = "GROUP BY `{0}`".format(group_by_field) if group_by_field else ""
	sql = "SELECT {0} FROM {1} {2} {3}".format(select_sql, table, where_sql, group_sql).strip()

	try:
		rows = frappe.db.sql(sql, where_values, as_dict=True)
	except Exception as e:
		return {"ok": False, "error": "sql error: {0}: {1}".format(type(e).__name__, e)}

	if group_by_field:
		return {"ok": True, "data": rows}
	return {"ok": True, "data": rows[0] if rows else {n: 0 for n in names}}


def _build_safe_where(filters, valid_fields):
	"""Translate dict / list filters into a WHERE fragment with parametrised
	values. Only fields in `valid_fields` are accepted. Op is whitelisted.
	Unknown fields and unknown ops are SILENTLY skipped (matches Frappe's
	lenient internal behaviour; safer than letting them through to SQL)."""
	if not filters:
		return "", []
	if isinstance(filters, list):
		filters = {f[0]: [f[1], f[2]] for f in filters if isinstance(f, (list, tuple)) and len(f) >= 3}

	clauses = []
	values = []
	for field, val in filters.items():
		if field not in valid_fields:
			continue
		if isinstance(val, (list, tuple)) and len(val) >= 2:
			op = (val[0] or "=").strip().lower()
			if op not in _OP_MAP:
				continue
			sql_op = _OP_MAP[op]
			if op in ("in", "not in"):
				if not isinstance(val[1], (list, tuple)) or not val[1]:
					continue
				placeholders = ", ".join(["%s"] * len(val[1]))
				clauses.append("`{0}` {1} ({2})".format(field, sql_op, placeholders))
				values.extend(val[1])
			elif op == "between":
				if not isinstance(val[1], (list, tuple)) or len(val[1]) != 2:
					continue
				clauses.append("`{0}` BETWEEN %s AND %s".format(field))
				values.extend(val[1])
			elif op in ("is", "is not"):
				v = val[1]
				if v is None or str(v).lower() in ("not set", "null", ""):
					clauses.append("`{0}` {1} NULL".format(field, sql_op))
				else:
					clauses.append("`{0}` {1} NOT NULL".format(field, sql_op))
			else:
				clauses.append("`{0}` {1} %s".format(field, sql_op))
				values.append(val[1])
		else:
			clauses.append("`{0}` = %s".format(field))
			values.append(val)
	if not clauses:
		return "", []
	return "WHERE " + " AND ".join(clauses), values
```

- [ ] **Step 3: Restart bench + smoke-probe the endpoint.**
```bash
cd /Users/soumyasethy/Desktop/code-chat && sh restart.sh --bg
until curl -sf http://localhost:8000/api/method/ping >/dev/null 2>&1; do sleep 3; done

cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && bench --site erp.local console <<'PY' 2>&1 | tail -15
from lazychat_erpnext.desk_assistant.api import lazychat_dashboard_aggregate
import json
r = lazychat_dashboard_aggregate({
    "doctype": "Sales Invoice", "filters": {"docstatus": 1},
    "aggregations": [{"name": "ytd", "field": "grand_total", "op": "sum"}, {"name": "n", "op": "count"}],
})
print("happy:", json.dumps(r, default=str)[:200])
r = lazychat_dashboard_aggregate({"doctype": "Sales Invoice", "aggregations": [{"name": "x", "field": "definitely_not_a_field", "op": "sum"}]})
print("unknown field:", r)
r = lazychat_dashboard_aggregate({"doctype": "Sales Invoice", "aggregations": [{"name": "x", "op": "exec_sql"}]})
print("unknown op:", r)
PY
```

Expected:
- `happy:` shows `{"ok": true, "data": {"ytd": <large number>, "n": 88928}}`
- `unknown field:` shows `{"ok": false, "error": "...definitely_not_a_field..."}`
- `unknown op:` shows `{"ok": false, "error": "...exec_sql..."}`

---

## Task 8 — Smoke tests T100r through T100w

**Files:** Modify `lazychat-erpnext/scripts/smoke-test-tools.py` — insert after the T100q block.

- [ ] **Step 1: Find insertion point.**
```bash
grep -n "T100q\|cleanup section" /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py | head
```

- [ ] **Step 2: Insert this block right after T100q.**

```python
	# T100r — Cycle 14 — aggregate sum matches direct SQL on Sales Invoice
	from lazychat_erpnext.desk_assistant.api import lazychat_dashboard_aggregate
	r = lazychat_dashboard_aggregate({
		"doctype": "Sales Invoice", "filters": {"docstatus": 1},
		"aggregations": [{"name": "total", "field": "grand_total", "op": "sum"}, {"name": "n", "op": "count"}],
	})
	direct = frappe.db.sql("SELECT SUM(grand_total) AS total, COUNT(*) AS n FROM `tabSales Invoice` WHERE docstatus=1", as_dict=True)
	d_total = (direct[0]["total"] or 0) if direct else 0
	d_n = (direct[0]["n"] or 0) if direct else 0
	api_total = (r.get("data") or {}).get("total", 0) or 0
	api_n = (r.get("data") or {}).get("n", 0) or 0
	record(_ok(
		"T100r aggregate sum matches direct SQL",
		r.get("ok") and float(api_total) == float(d_total) and int(api_n) == int(d_n),
		"api={0}, d_total={1}, d_n={2}".format(r, d_total, d_n),
	))

	# T100s — aggregate rejects unknown field
	r = lazychat_dashboard_aggregate({
		"doctype": "Sales Invoice",
		"aggregations": [{"name": "x", "field": "definitely_not_a_field_xyz", "op": "sum"}],
	})
	record(_ok(
		"T100s aggregate rejects unknown field",
		(not r.get("ok")) and "definitely_not_a_field_xyz" in (r.get("error") or ""),
		"r={0}".format(r),
	))

	# T100t — aggregate rejects op outside whitelist
	r = lazychat_dashboard_aggregate({
		"doctype": "Sales Invoice",
		"aggregations": [{"name": "x", "op": "exec_arbitrary_sql"}],
	})
	record(_ok(
		"T100t aggregate rejects unknown op",
		(not r.get("ok")) and "exec_arbitrary_sql" in (r.get("error") or ""),
		"r={0}".format(r),
	))

	# T100u — 4 MD doctypes installed + seeded with expected counts
	from lazychat_erpnext.install import _seed_md_dashboard
	_seed_md_dashboard()
	expected = {"MD KPI Score": "non_zero", "MD Risk": 7, "MD Decision": 7, "Critical Role": 5}
	all_ok = True
	notes = []
	for dt, want in expected.items():
		actual = frappe.db.count(dt)
		if want == "non_zero":
			ok = actual > 0
		else:
			ok = actual == want
		if not ok:
			all_ok = False
		notes.append("{0}={1} (want {2})".format(dt, actual, want))
	record(_ok("T100u MD doctype seed counts", all_ok, "; ".join(notes)))

	# T100v — group_by aggregate returns multiple rows with the group_by field
	r = lazychat_dashboard_aggregate({
		"doctype": "Sales Invoice", "filters": {"docstatus": 1},
		"aggregations": [{"name": "count", "op": "count"}],
		"group_by": "status",
	})
	rows = r.get("data") or []
	record(_ok(
		"T100v aggregate group_by returns rows with group_by field",
		r.get("ok") and isinstance(rows, list) and len(rows) >= 1
		and all(isinstance(row, dict) and "status" in row and "count" in row for row in rows),
		"rows[:3]={0}".format(rows[:3] if isinstance(rows, list) else rows),
	))

	# T100w — permission gate rejects non-System-Manager (monkey-patch get_roles)
	original_get_roles = frappe.get_roles
	frappe.get_roles = lambda *args, **kwargs: []
	try:
		r = lazychat_dashboard_aggregate({
			"doctype": "Sales Invoice",
			"aggregations": [{"name": "x", "op": "count"}],
		})
		record(_ok(
			"T100w aggregate rejects non-System-Manager",
			(not r.get("ok")) and "System Manager" in (r.get("error") or ""),
			"r={0}".format(r),
		))
	finally:
		frappe.get_roles = original_get_roles
```

- [ ] **Step 3: Sync + run smoke.**
```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/_smoke.py
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | tail -15
```

Expected: 6 lines `T100r ... PASS` through `T100w ... PASS`. Final tally `pass=283 / fail=0 / skip=6`.

---

## Task 9 — md_dashboard.html (12 sections)

**Files:** Rewrite `lazychat-erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard/md_dashboard.html`

- [ ] **Step 1: Use Write tool to overwrite with this content** (12 sections, structurally consistent):

```html
<header class="md-topbar">
  <div class="md-topbar-row">
    <h1>MD Dashboard</h1>
    <span id="lastUpdate" class="md-meta">—</span>
  </div>
</header>
<main class="md-main">

  <section class="md-sec" id="sec-snap">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-g"></div><h2>Group Snapshot</h2></div>
    <div class="md-grid-4">
      <div class="md-kpi"><div class="md-kpi-label">YTD Revenue</div><div id="ytdRev" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Sales Invoices YTD</div><div id="invCnt" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Outstanding</div><div id="outstand" class="md-kpi-val md-kpi-bad">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Headcount</div><div id="hcCount" class="md-kpi-val">—</div></div>
    </div>
  </section>

  <section class="md-sec" id="sec-bsc">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Balanced Scorecard</h2></div>
    <div id="bscGrid" class="md-grid-4"><div class="md-loading">Loading…</div></div>
  </section>

  <section class="md-sec" id="sec-div">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Division KPI Progress</h2></div>
    <div id="divList" class="md-list"><div class="md-loading">Loading…</div></div>
  </section>

  <section class="md-sec" id="sec-risk">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-r"></div><h2>Top Risks &amp; Issues</h2></div>
    <div id="riskList" class="md-list"><div class="md-loading">Loading…</div></div>
  </section>

  <section class="md-sec" id="sec-dec">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Decisions Required from MD</h2></div>
    <div id="decList" class="md-list"><div class="md-loading">Loading…</div></div>
  </section>

  <section class="md-sec" id="sec-sales">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Sales &amp; Business Development</h2></div>
    <div class="md-grid-4">
      <div class="md-kpi"><div class="md-kpi-label">Active Leads</div><div id="leadCnt" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Open Opportunities</div><div id="oppCnt" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Pending Quotations</div><div id="quoteCnt" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Sales Order MTD</div><div id="soMtd" class="md-kpi-val">—</div></div>
    </div>
  </section>

  <section class="md-sec" id="sec-rec">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-r"></div><h2>Receivables &amp; Collections</h2></div>
    <div id="agingTable" class="md-panel"><div class="md-loading">Loading…</div></div>
  </section>

  <section class="md-sec" id="sec-pay">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Payables &amp; Procurement</h2></div>
    <div class="md-grid-4">
      <div class="md-kpi"><div class="md-kpi-label">Total Creditors</div><div id="creditors" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Active POs</div><div id="poCount" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Overdue Payables</div><div id="overduePay" class="md-kpi-val md-kpi-bad">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Material Requests</div><div id="prCount" class="md-kpi-val">—</div></div>
    </div>
  </section>

  <section class="md-sec" id="sec-ops">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Operations &amp; Production</h2></div>
    <div id="opsBlock" class="md-panel"><div class="md-loading">Loading…</div></div>
  </section>

  <section class="md-sec" id="sec-fin">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>Finance Snapshot</h2></div>
    <div class="md-grid-4">
      <div class="md-kpi"><div class="md-kpi-label">Revenue YTD</div><div id="revYtd2" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Outstanding Total</div><div id="outFin" class="md-kpi-val md-kpi-bad">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Creditors Total</div><div id="credFin" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">GL Net</div><div id="cashNet" class="md-kpi-val">—</div></div>
    </div>
  </section>

  <section class="md-sec" id="sec-hr">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-a"></div><h2>HR &amp; People</h2></div>
    <div class="md-grid-4">
      <div class="md-kpi"><div class="md-kpi-label">Active Headcount</div><div id="hrHc" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Open Positions</div><div id="hrOpen" class="md-kpi-val">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Critical Roles</div><div id="hrCrit" class="md-kpi-val md-kpi-bad">—</div></div>
      <div class="md-kpi"><div class="md-kpi-label">Job Openings (ERP)</div><div id="hrJob" class="md-kpi-val">—</div></div>
    </div>
    <div id="critList" class="md-list md-mt-12"><div class="md-loading">Loading critical roles…</div></div>
  </section>

  <section class="md-sec" id="sec-dig">
    <div class="md-sec-h"><div class="md-sec-bar md-bar-g"></div><h2>Digital Transformation Milestones</h2></div>
    <div id="digList" class="md-list"><div class="md-loading">Loading…</div></div>
  </section>

</main>
```

- [ ] **Step 2: Sanity-check.**
```bash
grep -c '<section' /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard/md_dashboard.html
```
Expected: `12`.

---

## Task 10 — md_dashboard.css

**Files:** Rewrite `lazychat-erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard/md_dashboard.css`

- [ ] **Step 1: Overwrite with this content:**

```css
/* Cycle 14 — MD Dashboard. Uses Frappe theme tokens for theme adaptivity.
   Status colors hardcoded for stable RAG signal across themes. */

.md-topbar { padding: 14px 20px; border-bottom: 1px solid var(--border-color, rgba(0,0,0,.08)); background: var(--bg-color, #fff); }
.md-topbar-row { display: flex; align-items: center; justify-content: space-between; }
.md-topbar h1 { margin: 0; font-size: 22px; color: var(--text-color); }
.md-meta { font-family: monospace; font-size: 11px; color: var(--text-muted, #888); }

.md-main { padding: 18px 20px; display: flex; flex-direction: column; gap: 22px; }

.md-sec { background: transparent; }
.md-sec-h { display: flex; align-items: center; gap: 10px; padding-bottom: 10px; margin-bottom: 14px; border-bottom: 1px solid var(--border-color, rgba(0,0,0,.08)); }
.md-sec-h h2 { font-size: 16px; font-weight: 500; margin: 0; color: var(--text-color); }
.md-sec-bar { width: 3px; height: 18px; }
.md-bar-g { background: #00B894; } .md-bar-a { background: #F39C12; } .md-bar-r { background: #E74C3C; } .md-bar-b { background: #2980B9; }

.md-grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }

.md-kpi { background: var(--bg-light, var(--card-bg, #f7f7f7)); border: 1px solid var(--border-color, rgba(0,0,0,.06)); padding: 12px 14px; }
.md-kpi-label { font-size: 9px; letter-spacing: .07em; text-transform: uppercase; color: var(--text-muted, #888); margin-bottom: 6px; }
.md-kpi-val { font-family: monospace; font-size: 19px; font-weight: 500; color: var(--text-color); }
.md-kpi-bad { color: #E74C3C; } .md-kpi-good { color: #00B894; } .md-kpi-warn { color: #F39C12; }

.md-panel { background: var(--bg-light, var(--card-bg, #f7f7f7)); border: 1px solid var(--border-color, rgba(0,0,0,.06)); padding: 14px; }

.md-list { display: flex; flex-direction: column; gap: 4px; }
.md-row { display: flex; align-items: flex-start; gap: 10px; padding: 8px 12px; background: var(--bg-light, var(--card-bg, #f7f7f7)); border-left: 2px solid #5F6E7A; border-bottom: 1px solid var(--border-color, rgba(0,0,0,.04)); font-size: 12px; }
.md-row-r { border-left-color: #E74C3C; } .md-row-a { border-left-color: #F39C12; } .md-row-g { border-left-color: #00B894; } .md-row-b { border-left-color: #2980B9; }

.md-tag { font-family: monospace; font-size: 10px; padding: 1px 6px; border: 1px solid var(--border-color); color: var(--text-muted); white-space: nowrap; }
.md-tag-r { color: #E74C3C; border-color: #E74C3C; } .md-tag-a { color: #F39C12; border-color: #F39C12; } .md-tag-g { color: #00B894; border-color: #00B894; }

.md-loading { color: var(--text-muted, #888); font-size: 12px; }
.md-mt-12 { margin-top: 12px; }

.md-aging-row { display: grid; grid-template-columns: 100px 120px 1fr 80px; gap: 10px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border-color, rgba(0,0,0,.04)); }
.md-aging-row:last-child { border-bottom: 0; }
.md-aging-bar { height: 6px; background: var(--border-color, rgba(0,0,0,.06)); }
.md-aging-fill { height: 100%; }
```

- [ ] **Step 2: Verify.** `wc -l` should be ~40 lines.

---

## Task 11 — md_dashboard.js (12-section data wiring)

**Files:** Rewrite `lazychat-erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard/md_dashboard.js`

The JS uses jQuery's `.html()` (already escaped via `escapeHtml()` helper) to render rows for the 4 list-style sections (BSC / Risks / Decisions / Critical Roles) and the aging table. All user-controlled doctype values pass through `escapeHtml()` before injection — XSS-safe by construction.

- [ ] **Step 1: Use Write tool to overwrite** with the full JS file. The structure:

  - Wrapper auto-fires on `frappe.pages["md-dashboard"].on_page_load`
  - Format helpers: `fmtINR(n)` (magnitude-aware Cr/L), `fmtCount(n)`, `escapeHtml(s)`
  - DOM helpers: `setText(id, v)` uses `textContent`; `setHTML(id, v)` uses jQuery's `.html()` (existing safe-escape pattern in Frappe pages)
  - `agg(spec)` calls `lazychat_erpnext.desk_assistant.api.lazychat_dashboard_aggregate` via `frappe.call`
  - `getList(doctype, opts)` calls `frappe.client.get_list` (small lists only — never for aggregation)
  - 12 `loadXxx()` functions, one per section, each returning a Promise
  - `loadAll()` runs `Promise.all` of all 12; sets `lazychatReady = '1'` after; auto-refresh `setInterval(loadAll, 5*60*1000)`

The full file is in the spec at section A.3 — the implementer copies that body verbatim into `md_dashboard.js`. Per the spec, the JS is ~270 lines.

If the Write hook flags the JS for using `setHTML`: the helper wraps jQuery `.html()` which is the same pattern Frappe's own page templates use (`page.main.html(...)`). All values passed in are pre-escaped via `escapeHtml(s)` which converts `&`, `<`, `>`, `"`, `'` to entities. Document this explicitly in a header comment at the top of the JS file:

```js
// SAFETY: setHTML(id, html) wraps jQuery `.html()` which sets innerHTML.
// All interpolated values are pre-escaped via escapeHtml(s) before
// concatenation. The agg/getList paths hit lazychat_dashboard_aggregate
// (System Manager only, field-meta validated) and frappe.client.get_list
// (read-permission gated). No user input flows directly into HTML.
```

- [ ] **Step 2: Verify the JS file syntax-checks via bench page load.**

After deploy + restart in Task 16, load `/app/md-dashboard` in a browser and check the JS console for parse errors. If any `SyntaxError`, fix the file.

---

## Task 12 — md_dashboard.json — tighten roles to System Manager

**Files:** Modify `lazychat-erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard/md_dashboard.json`

- [ ] **Step 1: Read current file.**
```bash
cat /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard/md_dashboard.json
```

- [ ] **Step 2: Replace the `"roles"` array.** Use Edit:

OLD: `"roles": [{"role": "All"}],` (or whatever's there)
NEW: `"roles": [{"role": "System Manager"}],`

- [ ] **Step 3: Verify.**
```bash
python3 -c "import json; d=json.load(open('/Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard/md_dashboard.json')); print(d.get('roles'))"
```
Expected: `[{'role': 'System Manager'}]`.

---

## Task 13 — `_DASHBOARD_DISCIPLINE_BLOCK` in claude_bridge.py

**Files:** Modify `lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py`

- [ ] **Step 1: Find insertion anchor.** The block goes immediately after the Cycle-13.2 entity-rule WRONG/RIGHT example, before the next playbook section.
```bash
grep -n "RIGHT: \`content: '<header>Hello</header>'\`" /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py
```

- [ ] **Step 2: Insert block via Edit.**

OLD `old_string` (the exact line returned by Step 1):
```
   RIGHT: `content: '<header>Hello</header>'`
```

NEW `new_string`:
```
   RIGHT: `content: '<header>Hello</header>'`

## DASHBOARD-FROM-MOCKUP DISCIPLINE

When the user uploads a reference mockup with 5+ sections OR 20+ KPIs:

1. **INVENTORY** — list every section + KPI in the mockup BEFORE writing
   any code. No silent omissions. Output as a markdown table.

2. **CLASSIFY** each KPI:
   - **ERP-derivable** — name the doctype + the aggregation (sum / count / etc.)
   - **Manual entry** — propose a minimal custom doctype (4-6 fields), OR
     reuse existing (ToDo, Note, Job Opening). Stage the doctype creation
     in the same plan.
   - **Not applicable** — skip with one-line reason.

3. **AGGREGATE via server-side SUM/COUNT/GROUP BY** — use the whitelisted
   endpoint:

       frappe.call({
         method: 'lazychat_erpnext.desk_assistant.api.lazychat_dashboard_aggregate',
         args: { spec: JSON.stringify({
           doctype: 'Sales Invoice',
           filters: { docstatus: 1 },
           aggregations: [{ name: 'ytd', field: 'grand_total', op: 'sum' }]
         }) },
         callback: function (r) { /* r.message.data.ytd has the FULL sum */ }
       });

   NEVER use `frappe.client.get_list` with `limit_page_length` for totals.
   That truncates and produces silently-wrong sums on large tables (an
   88,000-row Sales Invoice table will return at most 500 rows = wrong
   sum by 99%+).

4. **UNITS — every numeric value MUST display its unit suffix.** A figure
   of 0.2 Cr displayed as "0" without a "Cr" suffix is indistinguishable
   from "no data". Use a magnitude-aware fmtINR helper:

       function fmtINR(n) {
         if (n == null || isNaN(n)) return '-';
         var v = Math.abs(n);
         if (v >= 10000000) return '₹' + (v/10000000).toFixed(2) + ' Cr';
         if (v >= 100000)   return '₹' + (v/100000).toFixed(2) + ' L';
         return '₹' + Math.round(v).toLocaleString('en-IN');
       }

5. **RENDER ALL SECTIONS.** If the mockup has 12 sections, your output
   must have 12. If you must scope down, LIST THE OMISSIONS in your reply
   text so the user can decide. Silent dropping is the most expensive bug
   class we have.

WRONG (silent truncation, no unit suffix):
  frappe.call('frappe.client.get_list', {
    doctype: 'Sales Invoice', limit_page_length: 500
  })   // returns at most 500 of 88,928 rows
  // then JS reduce + (sum/10000000).toFixed(0)  — wrong total + bare "0"

RIGHT (server SUM, magnitude-aware unit suffix):
  agg({ doctype: 'Sales Invoice', filters: {docstatus: 1},
        aggregations: [{name: 'ytd', field: 'grand_total', op: 'sum'}] })
    .then(function (r) { setText('rev', fmtINR(r.ytd)); });
```

- [ ] **Step 3: Verify the block is in the loaded prompt.**
```bash
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && bench --site erp.local console <<'PY' 2>&1 | tail -3
from lazychat_erpnext.desk_assistant.claude_bridge import _DESK_PAGE_PLAYBOOK
assert "DASHBOARD-FROM-MOCKUP DISCIPLINE" in _DESK_PAGE_PLAYBOOK
assert "lazychat_dashboard_aggregate" in _DESK_PAGE_PLAYBOOK
print("OK: discipline block present")
PY
```

---

## Task 14 — Mirror discipline block in chat-ui

**Files:** Modify `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts`

Same insertion anchor pattern: after the cycle-13.2 entity-rule WRONG/RIGHT example, before whatever follows.

- [ ] **Step 1: Find insertion point.**
```bash
grep -n "RIGHT: \\\\\`content: '<header>Hello</header>'\\\\\`" /Users/soumyasethy/Desktop/code-chat/lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts
```

(Note: in the .ts template literal, backticks are escaped with `\``.)

- [ ] **Step 2: Insert via Edit. **OLD `old_string` (with TS escapes):
```
   RIGHT: \`content: '<header>Hello</header>'\`
```

NEW `new_string`:
```
   RIGHT: \`content: '<header>Hello</header>'\`

## DASHBOARD-FROM-MOCKUP DISCIPLINE

When the user uploads a reference mockup with 5+ sections OR 20+ KPIs:

1. **INVENTORY** — list every section + KPI in the mockup BEFORE writing
   any code. No silent omissions. Output as a markdown table.

2. **CLASSIFY** each KPI:
   - **ERP-derivable** — name the doctype + aggregation (sum / count)
   - **Manual entry** — propose a minimal custom doctype (4-6 fields)
   - **Not applicable** — skip with one-line reason.

3. **AGGREGATE via server-side SUM/COUNT/GROUP BY** — use the whitelisted
   endpoint \`lazychat_erpnext.desk_assistant.api.lazychat_dashboard_aggregate\`.
   NEVER use \`frappe.client.get_list\` with \`limit_page_length\` for totals
   — that truncates and silently produces wrong sums on large tables.

4. **UNITS — every numeric value MUST display its unit suffix.** A figure
   of 0.2 Cr displayed as "0" without "Cr" is indistinguishable from "no data".

5. **RENDER ALL SECTIONS.** If the mockup has 12 sections your output must
   have 12. If you scope down, LIST THE OMISSIONS in your reply text.

WRONG: \`frappe.client.get_list({doctype:'Sales Invoice', limit_page_length:500})\`
RIGHT: call \`lazychat_dashboard_aggregate\` for any total/count over a
       table with > a few hundred rows.
```

- [ ] **Step 3: Verify typecheck.**
```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && pnpm --filter chat-ui typecheck 2>&1 | tail -3
```
Expected: 0 errors. If template-literal escape errors, check backtick escaping.

---

## Task 15 — Bump versions + CHANGELOG + CLAUDE.md

- [ ] **Step 1: Bump backend version.**

Edit `lazychat-erpnext/pyproject.toml`: `version = "0.3.1"` → `version = "0.4.0"`.
Edit `lazychat-erpnext/lazychat_erpnext/__init__.py`: `__version__ = "0.3.1"` → `"0.4.0"`.

- [ ] **Step 2: Bump chat-ui version.**

Edit `lazychat.ai/package.json` and `lazychat.ai/apps/chat-ui/package.json`: `"version": "0.1.1",` → `"0.1.2",` (top-level only — don't touch deps).

- [ ] **Step 3: Insert backend CHANGELOG entry.** Use Edit on `lazychat-erpnext/CHANGELOG.md`. Insert between `## [Unreleased]` line and `## [0.3.1]` line:

```markdown
## [0.4.0] — Cycle 14 — MD Dashboard rebuild + Dashboard-from-Mockup discipline — 2026-05-15

Two coupled fixes that close the same class of bug. Companion chat-ui release: `lazychat.ai 0.1.2`.

### Added
- 4 minimal custom doctypes for non-ERP MD-facing data: `MD KPI Score` (BSC, 52 seed), `MD Risk` (7 seed), `MD Decision` (7 seed), `Critical Role` (5 seed). System Manager only. Seeded idempotently via `_seed_md_dashboard()` in `install.py`.
- Server-side aggregate endpoint `lazychat_dashboard_aggregate(spec)` in `api.py`: SUM/COUNT/AVG/MIN/MAX with optional GROUP BY. Validates field names against doctype meta and op against `{sum,count,avg,min,max}`. System Manager only. Replaces the broken `frappe.client.get_list + JS reduce` pattern.
- `/app/md-dashboard` full 12-section rebuild (Group Snapshot · BSC · Division KPIs · Risks · Decisions · Sales · Receivables · Payables · Operations · Finance · HR · Digital). Magnitude-aware `fmtINR` helper. Auto-refresh every 5 min.
- 6 new in-process smoke tests (T100r-w).

### Changed
- Playbook DASHBOARD-FROM-MOCKUP DISCIPLINE block in `claude_bridge.py` (mirrored in chat-ui `routerSystemPrompt.ts`): for any 5+ section / 20+ KPI mockup, agent must INVENTORY → CLASSIFY → AGGREGATE via the new endpoint → handle UNITS magnitude-aware → RENDER ALL sections.
- `/app/md-dashboard` Page roles tightened from `All` to `System Manager` only.

### Verification
- in-process smoke: 277 → 283 pass / 0 fail / 6 skip
- chat-ui vitest: 461 / 0 (unchanged)
- bench migrate clean (4 new doctypes)
- E2E: `/app/md-dashboard` shows real ₹76 Cr YTD revenue, 88k Sales Invoices, ₹96 Cr creditors, 4 BSC perspective cards, 7 risks, 7 decisions

### Commits in this release
```
<sha> feat(cycle-14): 4 MD custom doctypes + idempotent seed
<sha> feat(cycle-14): lazychat_dashboard_aggregate endpoint w/ field-meta + op-whitelist
<sha> feat(cycle-14): /app/md-dashboard 12-section rebuild
<sha> feat(cycle-14): playbook DASHBOARD-FROM-MOCKUP DISCIPLINE block
<sha> test(cycle-14): T100r-w smoke for aggregate + seed
<sha> docs(cycle-14): CHANGELOG + CLAUDE.md + version bump → 0.4.0
```

```

Update bottom comparison links: prepend `[0.4.0]: .../compare/cycle-13.2...cycle-14` and update `[Unreleased]` to `cycle-14...HEAD`.

- [ ] **Step 4: Insert chat-ui CHANGELOG entry.** Edit `lazychat.ai/CHANGELOG.md`. Insert between `## [Unreleased]` and `## [0.1.1]`:

```markdown
## [0.1.2] — Cycle 14 — Dashboard-from-Mockup discipline mirror — 2026-05-15

Chat-ui half of Cycle 14. Companion backend release: `lazychat-erpnext 0.4.0`.

### Changed
- Playbook DASHBOARD-FROM-MOCKUP DISCIPLINE block mirrored from backend in `routerSystemPrompt.ts`: for 5+ section / 20+ KPI mockups, agent must INVENTORY all sections, CLASSIFY each KPI as ERP-derivable / manual / not-applicable, call the server-side aggregate endpoint (never `client.get_list + reduce` for big tables), use magnitude-aware unit suffixes, and render ALL mockup sections.

### Verification
- chat-ui vitest: 461 / 0 (unchanged — prompt-only)
- typecheck clean

### Commits in this release
```
<sha> feat(cycle-14): playbook DASHBOARD-FROM-MOCKUP DISCIPLINE mirror
<sha> docs(cycle-14): CHANGELOG + CLAUDE.md + version bump → 0.1.2
```

```

Update bottom comparison links similarly.

- [ ] **Step 5: Insert `## Cycle 14` block in `lazychat-erpnext/CLAUDE.md`** above the existing `## Cycle 13.2` line. The content is similar in shape to the cycle-13.2 block — see the spec for the exact prose to use. Key sections: brief intro, custom doctypes (links to `lazychat_erpnext/desk_assistant/doctype/...`), aggregate endpoint, page rebuild table (12 sections), playbook upgrade summary, verification stats.

- [ ] **Step 6: Insert mirror `## Cycle 14` block in `lazychat.ai/CLAUDE.md`** above the existing `## Cycle 13.2` line. Shorter — chat-ui side just has the playbook mirror.

- [ ] **Step 7: Verify version consistency.**
```bash
grep -rn "0\.3\.1\|0\.4\.0\|0\.1\.1\|0\.1\.2" /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/pyproject.toml /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/__init__.py /Users/soumyasethy/Desktop/code-chat/lazychat.ai/package.json /Users/soumyasethy/Desktop/code-chat/lazychat.ai/apps/chat-ui/package.json
```
Expected: every file shows the NEW number.

---

## Task 16 — Build + migrate + restart bench

- [ ] **Step 1: Build + sync.**
```bash
cd /Users/soumyasethy/Desktop/code-chat && sh build.sh 2>&1 | tail -8
```

- [ ] **Step 2: Migrate.**
```bash
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && bench --site erp.local migrate 2>&1 | tail -15
```
Look for clean migration; no errors at end.

- [ ] **Step 3: Restart.**
```bash
cd /Users/soumyasethy/Desktop/code-chat && sh restart.sh --bg
until curl -sf http://localhost:8000/api/method/ping >/dev/null 2>&1; do sleep 3; done && echo "BENCH UP"
```

- [ ] **Step 4: Verify version + endpoint.**
```bash
/Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/env/bin/python -c "
import sys; sys.path.insert(0, '/Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext')
import lazychat_erpnext
from lazychat_erpnext.desk_assistant.api import lazychat_dashboard_aggregate
print('version:', lazychat_erpnext.__version__)
print('endpoint:', callable(lazychat_dashboard_aggregate))
"
```
Expected: `version: 0.4.0`, `endpoint: True`.

---

## Task 17 — Run full smoke + chat-ui gates

- [ ] **Step 1: Smoke.**
```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/_smoke.py
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | tail -15
```
Expected: `pass=283 / fail=0 / skip=6`. T100r-w all PASS.

- [ ] **Step 2: chat-ui typecheck + vitest.**
```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && pnpm --filter chat-ui typecheck 2>&1 | tail -3 && pnpm --filter chat-ui test 2>&1 | tail -10
```
Expected: typecheck 0 errors, vitest 461/461.

---

## Task 18 — E2E browser verification + screenshots

- [ ] **Step 1: Re-import the Page row from disk** so the row matches the rewritten files:
```bash
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && bench --site erp.local console <<'PY' 2>&1 | tail -5
from frappe.modules.import_file import import_doc_from_file
import os
pdir = "/Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/desk_assistant/page/md_dashboard"
import_doc_from_file(os.path.join(pdir, "md_dashboard.json"), "Desk Assistant")
import frappe; frappe.db.commit()
print("md-dashboard re-imported")
PY
```

- [ ] **Step 2: Load `/app/md-dashboard` via Playwright MCP.**

Use:
- `mcp__plugin_playwright_playwright__browser_navigate http://localhost:8000/app/md-dashboard`
- `mcp__plugin_playwright_playwright__browser_snapshot` — capture the a11y tree

Read the snapshot YAML. Expected:
- `heading "MD Dashboard" [level=1]`
- 12 distinct level-2 headings (the section titles)
- Group Snapshot section shows `₹76.32 Cr` (NOT `₹0` or bare `₹76`), `88,928` invoices, `₹27.86 Cr` outstanding
- BSC Scorecard shows 4 perspective cards each with status counts
- Top Risks shows 7 rows
- MD Decisions shows 7 rows

- [ ] **Step 3: Save 3 evidence screenshots.**

```text
mkdir -p /Users/soumyasethy/Desktop/code-chat/2026-05-15-cycle-14-md-dashboard
mcp__plugin_playwright_playwright__browser_take_screenshot {
  filename: "/Users/soumyasethy/Desktop/code-chat/2026-05-15-cycle-14-md-dashboard/01-full-page.png",
  type: "png", fullPage: true
}
mcp__plugin_playwright_playwright__browser_take_screenshot {
  filename: "/Users/soumyasethy/Desktop/code-chat/2026-05-15-cycle-14-md-dashboard/02-snapshot-section.png",
  type: "png", target: "section#sec-snap"
}
mcp__plugin_playwright_playwright__browser_take_screenshot {
  filename: "/Users/soumyasethy/Desktop/code-chat/2026-05-15-cycle-14-md-dashboard/03-bsc-section.png",
  type: "png", target: "section#sec-bsc"
}
```

If any KPI persistently shows `—` after 10 seconds, check the JS console via `mcp__plugin_playwright_playwright__browser_console_messages` for failed `frappe.call` errors.

- [ ] **Step 4: Write evidence README** at `2026-05-15-cycle-14-md-dashboard/README.md` summarizing:
  - Static gates (smoke 283/0/6, vitest 461/0, typecheck clean)
  - E2E observations (which sections rendered, any issues)
  - Links to the 3 screenshots

---

## Task 19 — Final state report (NO commit, NO push)

- [ ] **Step 1: Print git status both repos.**
```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && git status -s | grep -v "lazychat_dist" | head -30
echo "---chat-ui---"
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && git status -s | head -10
```

- [ ] **Step 2: Print summary to user and STOP.**

> **Cycle 14 implementation complete and verified.**
>
> Static gates:
> - in-process smoke: 283 pass / 0 fail / 6 skip (T100r-w)
> - chat-ui vitest: 461 / 0
> - typecheck: clean
> - bench migrate: clean (4 new doctypes installed)
> - bench at v0.4.0
>
> E2E:
> - `/app/md-dashboard` renders all 12 sections with real values
> - YTD revenue ≈ ₹76 Cr, 88k Sales Invoices, ₹96 Cr creditors
> - BSC + Risks + Decisions + Critical Roles populated from seeded MD doctypes
> - Screenshots in `2026-05-15-cycle-14-md-dashboard/`
>
> Ready to commit + tag `cycle-14` + push on both repos. Awaiting your explicit "commit" or "ship".

DO NOT run `git commit` / `git push`.

---

## Self-review

**1. Spec coverage check.**

| Spec section | Implementing task |
|---|---|
| A.1 — 4 custom doctypes | Tasks 1, 2, 3, 4 |
| A.1 — seed fixture + install hook | Task 6 |
| A.1 — bench migrate to install doctypes | Task 5 |
| A.2 — `lazychat_dashboard_aggregate` endpoint | Task 7 |
| A.2 — field-meta + op-whitelist validation | Task 7 (Step 2 contains the validation logic) |
| A.3 — 12-section page rewrite (HTML + CSS + JS) | Tasks 9, 10, 11 |
| A.4 — System Manager perm gating | Task 1-4 (doctype permissions), Task 7 (endpoint role check), Task 12 (Page roles) |
| B — `_DASHBOARD_DISCIPLINE_BLOCK` mirrored | Tasks 13 + 14 |
| 6 new smoke tests T100r-w | Task 8 |
| Versions + CHANGELOG + CLAUDE.md | Task 15 |
| Build + migrate + restart | Task 16 |
| Static gates | Task 17 |
| E2E browser verification | Task 18 |
| Final state report | Task 19 |

No spec section without a task.

**2. Placeholder scan.**

- "TBD" / "TODO" — none in plan body.
- "Add appropriate error handling" — none; all validation is concrete (op whitelist, field meta lookup, role check).
- "Write tests for the above" without code — none; T100r-w have full test bodies.
- "Similar to Task N" — Tasks 2, 3, 4 repeat the full doctype JSON each (correct per "no placeholders" rule).
- The CHANGELOG `<sha>` placeholders in Task 15 Step 3+4 are intentional — backfilled at commit time.
- Task 11 Step 1 references "the spec at section A.3 — implementer copies that body verbatim into md_dashboard.js" instead of inlining the full ~270-line JS body. This IS a deviation from the strict no-placeholder rule. Justification: inlining 270 lines of JS plus a 90-line HTML twice (once in Task 9, once in Task 11) and burning 5K+ tokens to do it would not improve the plan's actionability — the implementer needs the spec open anyway to understand the data-source mapping. The implementer subagent reads the spec to copy the JS body. Acceptable trade-off.

**3. Type consistency.**

| Symbol | First defined | Used later as |
|---|---|---|
| `lazychat_dashboard_aggregate(spec)` | Task 7 | Task 8 (smoke), Task 11 (page JS), Tasks 13+14 (playbook) — same name throughout |
| `_seed_md_dashboard()` | Task 6 | Task 8 T100u — same |
| `MD KPI Score` / `MD Risk` / `MD Decision` / `Critical Role` | Tasks 1-4 | Tasks 6, 8, 11, 15 — consistent |
| `_AGG_OPS = {sum, count, avg, min, max}` | Task 7 | Task 8 T100t — consistent |
| `fmtINR(n)` magnitude-aware | Task 11 (JS) | Tasks 13+14 (playbook examples) — consistent shape |
| `cycle-14` tag, `0.4.0` / `0.1.2` versions, `277 → 283` smoke count | Tasks 15, 17, 19 | Consistent |

No drift.

---

## Execution choice

Plan complete and saved to [`docs/superpowers/plans/2026-05-15-cycle-14-md-dashboard-discipline.md`](2026-05-15-cycle-14-md-dashboard-discipline.md). Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task group, two-stage review between groups. Best for the larger Tasks 6, 7, 11.
2. **Inline Execution** — execute tasks in this session with checkpoints.

Which approach?
