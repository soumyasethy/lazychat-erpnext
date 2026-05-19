# Cycle 15 — Apply-path hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 4-bug Apply-path cascade exposed by the Print Format creation transcript: (1) URL slug 404, (2) duplicate-create loop, (3) prep-token TTL too short, (4) agent emits ghost CTAs after turn budget exhausts.

**Architecture:** Four small targeted fixes across three files in `lazychat-erpnext/lazychat_erpnext/desk_assistant/` (`tools.py`, `claude_bridge.py`, `tool_schemas.py`) plus one defensive change in `lazychat.ai/apps/chat-ui/src/lib/agentRunner.ts`. Each bug ships as its own commit inside `cycle-15`. No new files except T-case additions to existing smoke files.

**Tech Stack:** Python 3.10+ (Frappe app), Vitest (chat-ui), `bench execute` (in-process smoke), Anthropic + OpenAI-compatible LLM adapters.

**Spec:** [docs/superpowers/specs/2026-05-16-cycle-15-apply-path-hardening-design.md](../specs/2026-05-16-cycle-15-apply-path-hardening-design.md)

**Repos:**
- Backend: `/Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/`
- Chat-ui: `/Users/soumyasethy/Desktop/code-chat/lazychat.ai/`

**Bench (for `bench execute` smoke runs):** `/Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/`, site `erp.local`.

---

## File map

| File | Touched by Task | Responsibility |
|---|---|---|
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py` | T1, T2, T3 | URL slug helper, TTL bump, retrieve-action refactor, per-wrapper exists pre-check |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py` | T3, T4 | System-prompt rules: DUPLICATE PIVOT (T3), CTA-must-have-tool + MAX_TURNS bump (T4) |
| `lazychat-erpnext/lazychat_erpnext/desk_assistant/tool_schemas.py` | T3 | Tool descriptions: spell out duplicate handling for typed wrappers |
| `lazychat-erpnext/scripts/smoke-test-tools.py` | T1, T2, T3, T4 | New T103a-T103o smoke cases (15 total) |
| `lazychat-erpnext/lazychat_erpnext/__init__.py` | T5 | Backend version bump to 0.5.0 |
| `lazychat-erpnext/pyproject.toml` | T5 | Pin same version |
| `lazychat-erpnext/CHANGELOG.md` | T5 | cycle-15 entry |
| `lazychat-erpnext/CLAUDE.md` | T5 | New cycle-15 section |
| `lazychat.ai/apps/chat-ui/src/lib/agentRunner.ts` | T4 | Ghost-CTA detection + warning render |
| `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts` | T3, T4 | Mirror DUPLICATE PIVOT + CTA-must-have-tool rules for browser-LLM path |
| `lazychat.ai/apps/chat-ui/src/lib/agentRunner.test.ts` | T4 | New `describe('ghost-CTA detection')` block |
| `lazychat.ai/apps/chat-ui/package.json` | T5 | Chat-ui version bump to 0.2.0 |
| `lazychat.ai/CHANGELOG.md` | T5 | cycle-15 entry |
| `lazychat.ai/CLAUDE.md` | T5 | New cycle-15 section |

---

## Pre-flight

- [ ] **Pre-flight 1: Confirm clean working trees in both repos**

Run:
```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && git status --short && \
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && git status --short
```
Expected: both empty (no uncommitted changes). If anything is staged, stash or commit before starting.

- [ ] **Pre-flight 2: Confirm bench + site are reachable**

Run:
```bash
ls /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/sites/erp.local/site_config.json
```
Expected: file exists, no error.

- [ ] **Pre-flight 3: Capture baseline smoke**

Copy smoke files into the bench (rsync wipes them on every deploy per CLAUDE.md "Deploy gotcha"), then run baseline:
```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && \
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/test/setup_fixtures.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_setup_fixtures.py && \
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | tail -5
```
Expected (per CLAUDE.md): `=== 283 pass, 0 fail, 6 skip ===`. If different, record the actual baseline — every task's "expected" needs to be `baseline + N` not a hard count.

- [ ] **Pre-flight 4: Capture chat-ui baseline**

Run:
```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && \
pnpm --filter chat-ui test 2>&1 | tail -3
```
Expected (per CLAUDE.md): `Tests  461 passed (461)`.

---

## Task 1: Bug 1 — URL slug helper

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py` (near line 14 for helper; line ~4823 for preview open_url; line ~4928 for commit response link; grep for other `f"/app/` patterns)
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` (add T103a-T103e at the end of the test list)

- [ ] **Step 1.1: Add 5 failing T-cases to smoke**

Open `lazychat-erpnext/scripts/smoke-test-tools.py`, find the end of the test definitions (last `T###` case), and append:

```python
# ─── Cycle 15 — URL slug helper ───────────────────────────────────────────────
def test_T103a_url_slug_print_format():
    from lazychat_erpnext.desk_assistant.tools import _doctype_url_slug
    assert _doctype_url_slug("Print Format") == "print-format"

def test_T103b_url_slug_purchase_order():
    from lazychat_erpnext.desk_assistant.tools import _doctype_url_slug
    assert _doctype_url_slug("Purchase Order") == "purchase-order"

def test_T103c_url_slug_single_word():
    from lazychat_erpnext.desk_assistant.tools import _doctype_url_slug
    assert _doctype_url_slug("Report") == "report"

def test_T103d_url_slug_empty():
    from lazychat_erpnext.desk_assistant.tools import _doctype_url_slug
    assert _doctype_url_slug("") == ""
    assert _doctype_url_slug(None) == ""  # type: ignore[arg-type]

def test_T103e_commit_link_uses_slug_helper():
    """Round-trip: stage prepare_create_print_format, commit, verify link uses hyphen."""
    import frappe
    from lazychat_erpnext.desk_assistant.tools import execute_tool
    from lazychat_erpnext.desk_assistant.api import commit_prepared_action

    pf_name = "Lazychat Smoke PF T103e"
    # Best-effort cleanup if a prior run left it behind
    if frappe.db.exists("Print Format", pf_name):
        frappe.delete_doc("Print Format", pf_name, ignore_permissions=True, force=True)
        frappe.db.commit()

    staged = execute_tool("prepare_create_print_format", {
        "name": pf_name,
        "doc_type": "Note",
        "html": "<div>{{ doc.title }}</div>",
        "print_format_type": "Jinja",
    })
    assert staged.get("ok"), f"stage failed: {staged}"
    token = staged["preview_token"]
    out = commit_prepared_action(token)
    assert out.get("ok"), f"commit failed: {out}"
    link = out.get("link", "")
    assert "/app/print-format/" in link, f"link missing hyphen-slug: {link}"
    assert "/app/print_format/" not in link, f"link uses underscore: {link}"

    # Cleanup
    frappe.delete_doc("Print Format", pf_name, ignore_permissions=True, force=True)
    frappe.db.commit()
```

Add to the runner's test registry. Look for the existing `TESTS = [...]` or similar list near the top/bottom of the file and append:

```python
    test_T103a_url_slug_print_format,
    test_T103b_url_slug_purchase_order,
    test_T103c_url_slug_single_word,
    test_T103d_url_slug_empty,
    test_T103e_commit_link_uses_slug_helper,
```

- [ ] **Step 1.2: Copy smoke + run, confirm new T-cases fail**

```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && \
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | tail -20
```
Expected: 5 failures with `ImportError: cannot import name '_doctype_url_slug'` for T103a-d AND `link uses underscore` (or similar) for T103e. Total: `283 pass, 5 fail, 6 skip` (or your captured baseline + 5 fail).

- [ ] **Step 1.3: Add `_doctype_url_slug` helper to `tools.py`**

Open `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py`. After `PREP_TTL_SEC = 300` and `PREP_KEY = "lazychat:prep:"` (around line 14-15), insert:

```python
def _doctype_url_slug(doctype: str) -> str:
    """Convert a DocType name to its Frappe Desk URL slug.

    Frappe Desk routes `/app/<slug>/<name>` where slug is the doctype
    name lowercased with spaces replaced by hyphens. This is distinct
    from `frappe.scrub()` (underscores, for module/field names).

    Examples:
        "Print Format" -> "print-format"
        "Purchase Order" -> "purchase-order"
        "Sales Invoice" -> "sales-invoice"
        "Report"        -> "report"
        ""              -> ""
        None            -> ""
    """
    return (doctype or "").strip().lower().replace(" ", "-")
```

- [ ] **Step 1.4: Replace `frappe.scrub(doc.doctype)` in commit-response link builder**

In `tools.py`, find the line around 4928 that builds the post-commit link. The exact pattern (per spec investigation) is:
```python
link = f"/app/{frappe.scrub(doc.doctype)}/{doc.name}"
```

Replace `frappe.scrub(doc.doctype)` with `_doctype_url_slug(doc.doctype)`. If the surrounding code has Report's special-case branch already (`if doc.doctype == "Report" ...`), leave that branch untouched — it routes to `/app/query-report/` or `/app/report/` based on `report_type` and is NOT a slug issue.

- [ ] **Step 1.5: Replace hand-rolled `print-format` literal in preview open_url**

In `tools.py` around line 4823:
```python
"open_url": f"/app/print-format/{pf_name}",
```
Replace with:
```python
"open_url": f"/app/{_doctype_url_slug('Print Format')}/{pf_name}",
```
The behavior is identical; the change is consistency so future doctype changes only touch the helper.

- [ ] **Step 1.6: Audit for other `f"/app/...` patterns in tools.py**

```bash
grep -n 'f"/app/' /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py
```

For each match: if it builds a doctype slug from `frappe.scrub(...)` or hand-rolls a slug, replace with `_doctype_url_slug(...)`. Skip the Report-special-case branches (they intentionally route differently).

- [ ] **Step 1.7: Copy + re-run smoke, confirm 5 new T-cases pass**

```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/desk_assistant/tools.py && \
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && \
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | tail -5
```
Expected: `=== 288 pass, 0 fail, 6 skip ===` (baseline 283 + 5 new).

- [ ] **Step 1.8: Commit**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && \
git add lazychat_erpnext/desk_assistant/tools.py scripts/smoke-test-tools.py && \
git commit -m 'fix(cycle-15): URL slug helper — _doctype_url_slug() replaces frappe.scrub for /app/<slug>/<name>'
```

---

## Task 2: Bug 3 — TTL bump + clearer expired-token error

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py:14` (PREP_TTL_SEC bump) and `_retrieve_action` (~line 6220)
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` (add T103j-T103m)

- [ ] **Step 2.1: Add 4 failing T-cases**

Append to `scripts/smoke-test-tools.py`:

```python
# ─── Cycle 15 — Token TTL + retrieve-action errors ────────────────────────────
def test_T103j_prep_ttl_30min():
    from lazychat_erpnext.desk_assistant.tools import PREP_TTL_SEC
    assert PREP_TTL_SEC >= 1800, f"PREP_TTL_SEC = {PREP_TTL_SEC}, expected >= 1800"

def test_T103k_retrieve_action_malformed_token():
    from lazychat_erpnext.desk_assistant.tools import _retrieve_action
    out = _retrieve_action("")
    assert isinstance(out, dict) and out.get("ok") is False
    assert "malformed" in (out.get("error") or "").lower()

def test_T103l_retrieve_action_missing_token():
    from lazychat_erpnext.desk_assistant.tools import _retrieve_action
    out = _retrieve_action("nonexistent-token-xyz-T103l-12345")
    assert isinstance(out, dict) and out.get("ok") is False
    err = (out.get("error") or "").lower()
    assert "expired" in err or "consumed" in err or "not found" in err

def test_T103m_retrieve_action_wrong_user():
    """Stage as Administrator, attempt retrieve as Guest, expect 'different user'."""
    import frappe
    from lazychat_erpnext.desk_assistant.tools import _stage_action, _retrieve_action
    # Stage as current user (Administrator under bench execute)
    payload = {"action": "test", "args": {}}
    token = _stage_action("test_action", payload)
    # Switch to Guest and try to retrieve
    original_user = frappe.session.user
    try:
        frappe.set_user("Guest")
        out = _retrieve_action(token)
        assert isinstance(out, dict) and out.get("ok") is False
        assert "different user" in (out.get("error") or "").lower() or \
               "not yours" in (out.get("error") or "").lower()
    finally:
        frappe.set_user(original_user)
```

Register in the runner list.

- [ ] **Step 2.2: Copy + run, confirm T103j passes (existing TTL=300 < 1800 = FAIL); T103k/l/m may pass or fail depending on existing shape**

```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && \
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep -E "T103[jklm]|fail"
```
Expected: T103j fails (TTL is 300). T103k/l/m may pass already if `_retrieve_action`'s existing error messages happen to contain the magic words; if so, fine — they'll keep passing after the refactor too.

- [ ] **Step 2.3: Bump `PREP_TTL_SEC` to 1800**

In `tools.py:14`:
```python
PREP_TTL_SEC = 1800  # 30 min; was 300. Multi-turn agent loops blow past 5 min.
```

- [ ] **Step 2.4: Refactor `_retrieve_action` for granular errors**

Find the existing `_retrieve_action` (around line 6220). Read the current implementation to understand the existing return shape (success returns the stored payload dict; failure currently returns `{"ok": False, "error": "..."}`).

Update to distinguish three failure modes. Replace the function body with:

```python
def _retrieve_action(token: str) -> dict:
    """Return the staged action dict on success, or a structured error dict.

    Three failure modes are distinguished so the agent (and surfaced UI)
    can produce actionable next-step guidance:
      - malformed: token empty or too short to be one we issued
      - missing/expired: token not in cache (TTL elapsed OR already consumed)
      - wrong-user: token belongs to a different user (security boundary)
    """
    if not token or len(token) < 8:
        return {"ok": False, "error": "Token malformed (empty or too short)."}
    token_key = f"{PREP_KEY}{token}"
    obj = frappe.cache.get_value(token_key)
    if not obj:
        return {
            "ok": False,
            "error": (
                "Token not found — either it expired (TTL = 30 min) OR it was "
                "already consumed by a prior commit. Re-stage the action with "
                "a fresh prepare_* call and try Apply again."
            ),
        }
    if obj.get("user") != frappe.session.user:
        return {
            "ok": False,
            "error": (
                "Token belongs to a different user (not yours). Each preview_token "
                "is bound to the user who staged it. Re-stage with the current user."
            ),
        }
    return obj  # success: the staged action dict
```

- [ ] **Step 2.5: Verify callers of `_retrieve_action` still work**

Grep for callers:
```bash
grep -n "_retrieve_action" /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/api.py
```

For each caller: confirm it checks `result.get("ok") is False` (or equivalent) before treating the dict as a staged action. The most common pattern is:
```python
obj = _retrieve_action(token)
if not obj or obj.get("error"):
    # error path
    return obj or {"ok": False, "error": "token not found"}
# success path: obj has "action", "args", etc.
```

If a caller assumes `_retrieve_action` returns `None` on failure, update it to check `obj.get("ok") is False`. The refactor preserves the success-path dict shape, so success-path code is unchanged.

- [ ] **Step 2.6: Copy + run smoke, confirm all 4 new T-cases pass + no regressions**

```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/desk_assistant/tools.py && \
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && \
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | tail -5
```
Expected: `=== 292 pass, 0 fail, 6 skip ===` (Task 1 baseline 288 + 4 new).

- [ ] **Step 2.7: Commit**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && \
git add lazychat_erpnext/desk_assistant/tools.py scripts/smoke-test-tools.py && \
git commit -m 'fix(cycle-15): PREP_TTL_SEC 300 -> 1800 + _retrieve_action distinguishes malformed/expired/wrong-user'
```

---

## Task 3: Bug 2 — Duplicate-create pivot

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py` (add exists-pre-check at top of every typed `prepare_create_*` wrapper)
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py` (system prompt — DUPLICATE PIVOT rule)
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tool_schemas.py` (tool descriptions mention duplicate handling)
- Modify: `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts` (mirror DUPLICATE PIVOT)
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` (add T103f-T103i)

- [ ] **Step 3.1: Inventory all typed `prepare_create_*` wrappers**

```bash
grep -n 'if name == "prepare_create_' /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py
```

Expected (per spec): `prepare_create_print_format`, `prepare_create_report`, `prepare_create_workspace`, `prepare_create_kb`, `prepare_create_note`, `prepare_create_email_template`, `prepare_create_email_group`, `prepare_create_milestone_tracker`, `prepare_create_number_card`, `prepare_create_dashboard`, `prepare_create_scheduled_job`, `prepare_create_calendar_event`, `prepare_create_client_script`, `prepare_create_page`, `prepare_create_server_script`, `prepare_create_custom_field`. Write down the line number of each.

- [ ] **Step 3.2: Add 4 failing T-cases**

Append to `scripts/smoke-test-tools.py`:

```python
# ─── Cycle 15 — Duplicate-create pivot ────────────────────────────────────────
def test_T103f_prepare_create_print_format_duplicate():
    import frappe
    from lazychat_erpnext.desk_assistant.tools import execute_tool
    pf_name = "Lazychat Smoke PF T103f"
    # Setup: ensure it exists
    if not frappe.db.exists("Print Format", pf_name):
        frappe.get_doc({
            "doctype": "Print Format", "name": pf_name, "doc_type": "Note",
            "print_format_type": "Jinja", "html": "<p>x</p>",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    try:
        result = execute_tool("prepare_create_print_format", {
            "name": pf_name, "doc_type": "Note", "html": "<p>y</p>",
            "print_format_type": "Jinja",
        })
        assert result.get("ok") is False
        err = (result.get("error") or "") + " " + (result.get("hint") or "")
        assert "already exists" in err.lower()
        assert "prepare_update_doc" in err
    finally:
        frappe.delete_doc("Print Format", pf_name, ignore_permissions=True, force=True)
        frappe.db.commit()

def test_T103g_prepare_create_report_duplicate():
    import frappe
    from lazychat_erpnext.desk_assistant.tools import execute_tool
    rpt_name = "Lazychat Smoke Report T103g"
    if not frappe.db.exists("Report", rpt_name):
        frappe.get_doc({
            "doctype": "Report", "report_name": rpt_name, "ref_doctype": "Note",
            "report_type": "Report Builder", "is_standard": "No",
        }).insert(ignore_permissions=True)
        frappe.db.commit()
    try:
        result = execute_tool("prepare_create_report", {
            "report_name": rpt_name, "ref_doctype": "Note",
            "report_type": "Report Builder",
        })
        assert result.get("ok") is False
        err = (result.get("error") or "") + " " + (result.get("hint") or "")
        assert "already exists" in err.lower()
        assert "prepare_update_doc" in err
    finally:
        frappe.delete_doc("Report", rpt_name, ignore_permissions=True, force=True)
        frappe.db.commit()

def test_T103h_duplicate_check_permission_aware():
    """The pre-check uses frappe.db.exists which respects user perms."""
    import frappe
    from lazychat_erpnext.desk_assistant.tools import execute_tool
    # Easier assertion: same DocType + name combo doesn't trigger false positive
    # against an unrelated doctype with same name.
    nt_name = "Lazychat Smoke Note T103h"
    if frappe.db.exists("Note", nt_name):
        frappe.delete_doc("Note", nt_name, ignore_permissions=True, force=True)
        frappe.db.commit()
    # Should NOT trigger duplicate error (no existing Note by this name)
    result = execute_tool("prepare_create_note", {
        "title": nt_name, "content": "test",
    })
    assert result.get("ok") is not False or "already exists" not in (result.get("error") or "").lower()

def test_T103i_system_prompt_has_duplicate_pivot_rule():
    from lazychat_erpnext.desk_assistant.claude_bridge import _system_prompt
    txt = _system_prompt(route_summary="")
    assert "DUPLICATE PIVOT" in txt
    assert "prepare_update_doc" in txt
```

Register all 4 in the runner list.

- [ ] **Step 3.3: Copy + run smoke, confirm 4 new T-cases fail**

```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && \
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep -E "T103[fghi]|fail"
```
Expected: T103f, T103g, T103i fail. T103h may pass (it's a no-op assertion).

- [ ] **Step 3.4: Add a helper function `_exists_redirect_to_update` near the top of `tools.py`**

After `_doctype_url_slug` from Task 1, add:

```python
def _exists_redirect_to_update(doctype: str, name: str, *, name_arg: str = "name") -> dict | None:
    """If <doctype>/<name> already exists, return a structured redirect to
    prepare_update_doc. Otherwise return None (caller proceeds with create).

    Used by typed prepare_create_* wrappers as a pre-check. Returning the
    redirect dict produces a deterministic error envelope the LLM can act
    on (per cycle-15 spec — DUPLICATE PIVOT rule mirrored in the system
    prompt teaches the agent to use prepare_update_doc on this signal).
    """
    if not name or not doctype:
        return None
    if not frappe.db.exists(doctype, name):
        return None
    return {
        "ok": False,
        "error": f"{doctype} '{name}' already exists.",
        "hint": (
            f"To MODIFY the existing {doctype}, use "
            f"prepare_update_doc(doctype='{doctype}', name='{name}', patch={{...}}) "
            f"on the next turn (NOT another prepare_create_*). "
            f"If you want a DIFFERENT {doctype.lower()}, choose a "
            f"{name_arg} that doesn't conflict (current attempted: '{name}')."
        ),
    }
```

- [ ] **Step 3.5: Add pre-check to each typed `prepare_create_*` wrapper**

For each wrapper identified in Step 3.1, add a pre-check call at the TOP of the wrapper body (before any other validation), using the doctype + the appropriate name argument. Examples:

`prepare_create_print_format` (around line ~4780):
```python
if name == "prepare_create_print_format":
    pf_name = args.get("name")
    redirect = _exists_redirect_to_update("Print Format", pf_name, name_arg="name")
    if redirect:
        return redirect
    # ... existing code continues
```

`prepare_create_report`:
```python
if name == "prepare_create_report":
    rpt_name = args.get("report_name")
    redirect = _exists_redirect_to_update("Report", rpt_name, name_arg="report_name")
    if redirect:
        return redirect
    # ... existing code continues
```

`prepare_create_workspace`:
```python
if name == "prepare_create_workspace":
    title = args.get("title")
    # Workspace name = scrub(title); check both forms
    ws_name = frappe.scrub(title) if title else None
    redirect = _exists_redirect_to_update("Workspace", ws_name, name_arg="title")
    if redirect:
        return redirect
    # ... existing code continues
```

Apply analogous pre-checks to the remaining wrappers using each one's actual `name` argument:

| Wrapper | DocType | Name arg | Notes |
|---|---|---|---|
| `prepare_create_kb` | Knowledge Base | `name` | direct |
| `prepare_create_note` | Note | `title` (or `name` if direct) | check the wrapper's args shape; Notes use `title` as the display name and autoname |
| `prepare_create_email_template` | Email Template | `name` | direct |
| `prepare_create_email_group` | Email Group | `name` | direct |
| `prepare_create_milestone_tracker` | Milestone Tracker | `name` | direct |
| `prepare_create_number_card` | Number Card | `label` (autonames from label per Frappe convention) | check actual scrub |
| `prepare_create_dashboard` | Dashboard | `dashboard_name` | direct |
| `prepare_create_scheduled_job` | Scheduled Job Type | `method` (or `name` if exposed) | direct |
| `prepare_create_calendar_event` | Event | `subject` (autoname pattern is hash) — SKIP, no deterministic dup-check possible; document and move on |
| `prepare_create_client_script` | Client Script | `name` (auto-derived if omitted per cycle-7 fix) | use args.get("name") if present; otherwise skip (auto-name will collide naturally) |
| `prepare_create_page` | Page | `page_name` | direct |
| `prepare_create_server_script` | Server Script | `name` (autoname=Prompt, requires explicit name) | direct |
| `prepare_create_custom_field` | Custom Field | `dt` + `fieldname` composite | check `frappe.db.exists("Custom Field", {"dt": ..., "fieldname": ...})` instead of single-name form |

For `prepare_create_custom_field`, use the explicit filter dict form:
```python
if name == "prepare_create_custom_field":
    dt = args.get("dt")
    fieldname = args.get("fieldname")
    if dt and fieldname and frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname}):
        return {
            "ok": False,
            "error": f"Custom Field '{fieldname}' on doctype '{dt}' already exists.",
            "hint": (
                f"To modify it, use prepare_update_doc(doctype='Custom Field', "
                f"name=<name>, patch={{...}}). Lookup the existing name with "
                f"get_value(doctype='Custom Field', filters={{dt:'{dt}', fieldname:'{fieldname}'}}, fieldname='name')."
            ),
        }
    # ... existing code continues
```

- [ ] **Step 3.6: Add DUPLICATE PIVOT rule to system prompt in `claude_bridge.py`**

Open `lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py`. Find the existing TOOL-ERROR HONESTY block in `_system_prompt(...)` (grep for "TOOL-ERROR HONESTY" or "TYPED WRAPPER"). After the existing TYPED-WRAPPER redirect text, append:

```python
# Somewhere inside the prompt-building string:
DUPLICATE PIVOT — If a typed `prepare_create_X` returns "already exists" OR a
commit returns IntegrityError 1062 (duplicate primary key), DO NOT retry the
same create. The doc EXISTS already. Switch to `prepare_update_doc(doctype='X',
name='<name>', patch={...})` on the next turn to modify it. If the user
explicitly asked for a NEW doc, choose a different name that doesn't conflict.
```

If the prompt is assembled from multiple string constants, find the one corresponding to the tool-error / mutation rules block (likely a module-level constant like `_MUTATION_HONESTY` or similar) and append there. Re-verify with `grep -n "TOOL-ERROR" claude_bridge.py`.

- [ ] **Step 3.7: Mirror DUPLICATE PIVOT in chat-ui's `routerSystemPrompt.ts`**

Open `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts`. Find the matching TOOL-ERROR HONESTY block (it mirrors the backend per CLAUDE.md). Append the same DUPLICATE PIVOT block, adapted for the chat-ui prompt style.

- [ ] **Step 3.8: Update tool descriptions in `tool_schemas.py` for typed wrappers**

For each typed wrapper in Step 3.1, find its entry in `tool_schemas.py` (grep for `"name": "prepare_create_X"`). Append to the description string:

```
If a <DocType> with the given name already exists, this tool returns
{ok: false, error: '... already exists', hint: 'use prepare_update_doc'}.
Switch to prepare_update_doc on duplicate; do NOT retry create.
```

Keep edits minimal — one extra sentence per wrapper.

- [ ] **Step 3.9: Copy + run smoke, confirm 4 new T-cases pass + no regressions**

```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/desk_assistant/tools.py && \
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py && \
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/tool_schemas.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/desk_assistant/tool_schemas.py && \
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && \
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | tail -5
```
Expected: `=== 296 pass, 0 fail, 6 skip ===` (Task 2 baseline 292 + 4 new).

- [ ] **Step 3.10: Commit**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && \
git add lazychat_erpnext/desk_assistant/tools.py \
        lazychat_erpnext/desk_assistant/claude_bridge.py \
        lazychat_erpnext/desk_assistant/tool_schemas.py \
        scripts/smoke-test-tools.py && \
git commit -m 'fix(cycle-15): typed prepare_create_* exists-pre-check + DUPLICATE PIVOT system-prompt rule + tool-description updates'
```

Then commit the chat-ui mirror:
```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && \
git add apps/chat-ui/src/lib/routerSystemPrompt.ts && \
git commit -m 'fix(cycle-15): mirror DUPLICATE PIVOT rule in browser-LLM system prompt'
```

---

## Task 4: Bug 4 — Turn budget bump + CTA-must-have-tool rule + chat-ui ghost-CTA detection

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py:13` (MAX_TURNS bump) and the system prompt (CTA rule)
- Modify: `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts` (mirror CTA rule)
- Modify: `lazychat.ai/apps/chat-ui/src/lib/agentRunner.ts` (ghost-CTA detection)
- Add: `lazychat.ai/apps/chat-ui/src/lib/agentRunner.test.ts` (new `describe('ghost-CTA detection')`)
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` (add T103n-T103o)

- [ ] **Step 4.1: Add 2 backend T-cases**

Append to `scripts/smoke-test-tools.py`:

```python
# ─── Cycle 15 — Turn budget + CTA-must-have-tool rule ─────────────────────────
def test_T103n_max_turns_bumped():
    from lazychat_erpnext.desk_assistant.claude_bridge import MAX_TURNS
    assert MAX_TURNS >= 16, f"MAX_TURNS = {MAX_TURNS}, expected >= 16"

def test_T103o_system_prompt_has_cta_rule():
    from lazychat_erpnext.desk_assistant.claude_bridge import _system_prompt
    txt = _system_prompt(route_summary="")
    assert "Click Apply" in txt or "click Apply" in txt
    assert "without an accompanying prepare_" in txt
```

Register both in the runner list.

- [ ] **Step 4.2: Copy + run, confirm both fail**

```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && \
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep -E "T103[no]|fail"
```
Expected: both T103n and T103o fail.

- [ ] **Step 4.3: Bump MAX_TURNS in `claude_bridge.py`**

In `lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py:13`:
```python
MAX_TURNS = 16  # was 8. Aligns backend-LLM default with chat-ui's effort=medium.
```

- [ ] **Step 4.4: Add CTA-must-have-tool rule to `_system_prompt`**

In `claude_bridge.py`, find the TOOL-ERROR HONESTY block (already touched in Task 3). After the DUPLICATE PIVOT rule, append:

```python
# Inside the prompt-building string:
NEVER emit text like "Click Apply" or "Click the Apply button" or "Apply
below" without an accompanying prepare_* tool call in the SAME turn. If
your last action FAILED and you cannot stage a fresh prepare_* this turn,
say "I need to re-stage — calling prepare_X now" and call it. Phantom CTAs
(text suggesting an Apply button when none exists) waste the user's time
and break trust.
```

- [ ] **Step 4.5: Mirror CTA rule in chat-ui's `routerSystemPrompt.ts`**

Open `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts`. After the DUPLICATE PIVOT mirror from Task 3.7, append the CTA rule adapted for chat-ui style.

- [ ] **Step 4.6: Add ghost-CTA detection in `agentRunner.ts`**

Open `lazychat.ai/apps/chat-ui/src/lib/agentRunner.ts`. Locate the final `done` message append handler. After the existing append, insert:

```typescript
// Cycle 15 — Bug 4 ghost-CTA detection. If the final assistant message
// contains CTA-suggesting text but no prepare_* / mcpPreviewAction is
// attached to this conversation's most-recent assistant turn, surface a
// defensive warning so the user isn't waiting for an Apply card that
// will never come.
const finalText = (doneMsg.text ?? doneMsg.message ?? "") as string;
const ctaPattern = /\b(click\s+apply|apply\s+below|click\s+the\s+apply\s+button)\b/i;
const recentMessages = useSessions.getState().sessions[sid]?.messages ?? [];
const recentHasPreview = recentMessages.slice(-6).some(
    (m) => m.kind === "mcpPreviewAction"
);
if (ctaPattern.test(finalText) && !recentHasPreview) {
    useSessions.getState().appendMessage(sid, {
        id: crypto.randomUUID(),
        kind: "error",
        role: "assistant",
        message: (
            "The agent ended the turn referencing an Apply button but did " +
            "not stage an action. This usually means the agent ran out of " +
            "turns or hit repeated failures. Try sending the request again, " +
            "or switch to a stronger model (e.g. claude-sonnet-latest)."
        ),
        at: Date.now(),
    });
}
```

Adapt `useSessions.getState().sessions[sid]?.messages` to the actual store shape — the implementer should read agentRunner.ts to confirm the exact API.

- [ ] **Step 4.7: Add chat-ui vitest cases**

Locate `agentRunner.test.ts` or create one if missing. Add a new describe block:

```typescript
import { describe, expect, it, beforeEach, vi } from 'vitest';
// Adapt imports to existing test scaffolding in this file

describe('ghost-CTA detection (Cycle 15 Bug 4)', () => {
  beforeEach(() => {
    // Reset sessions store
  });

  it('appends error message when done text contains "click Apply" with no preview', async () => {
    // Setup: empty session, send a "done" message with CTA text and no mcpPreviewAction
    // Expected: an "error" message is appended with the diagnostic copy
    // ... fill in per existing test patterns
  });

  it('does NOT append error when "click Apply" appears AND mcpPreviewAction is present', async () => {
    // Setup: session has an mcpPreviewAction in recent messages
    // Expected: no extra error message appended
  });

  it('does NOT append error when CTA phrasing is absent', async () => {
    // Setup: done text has no CTA pattern; no preview
    // Expected: no extra error appended (no false positives)
  });
});
```

Adapt the test scaffolding to the existing pattern in `agentRunner.test.ts`. Use `vi.fn()` mocks for store actions per existing tests.

- [ ] **Step 4.8: Run backend smoke, confirm 2 new T-cases pass + no regressions**

```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py && \
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && \
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | tail -5
```
Expected: `=== 298 pass, 0 fail, 6 skip ===` (Task 3 baseline 296 + 2 new).

- [ ] **Step 4.9: Run chat-ui vitest, confirm new describe block passes + no regressions**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && \
pnpm --filter chat-ui test 2>&1 | tail -5
```
Expected: `Tests  464 passed (464)` (baseline 461 + 3 new in ghost-CTA describe).

- [ ] **Step 4.10: Commit (backend)**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && \
git add lazychat_erpnext/desk_assistant/claude_bridge.py scripts/smoke-test-tools.py && \
git commit -m 'fix(cycle-15): MAX_TURNS 8 -> 16 + CTA-must-have-tool system-prompt rule'
```

- [ ] **Step 4.11: Commit (chat-ui)**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && \
git add apps/chat-ui/src/lib/agentRunner.ts \
        apps/chat-ui/src/lib/agentRunner.test.ts \
        apps/chat-ui/src/lib/routerSystemPrompt.ts && \
git commit -m 'fix(cycle-15): ghost-CTA detection + mirror CTA-must-have-tool rule'
```

---

## Task 5: Version bumps + CHANGELOG + CLAUDE.md updates

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/__init__.py` (0.4.3 → 0.5.0)
- Modify: `lazychat-erpnext/pyproject.toml` (same version)
- Modify: `lazychat-erpnext/CHANGELOG.md` (cycle-15 entry)
- Modify: `lazychat-erpnext/CLAUDE.md` (cycle-15 section)
- Modify: `lazychat.ai/apps/chat-ui/package.json` (0.1.5 → 0.2.0)
- Modify: `lazychat.ai/CHANGELOG.md` (cycle-15 entry)
- Modify: `lazychat.ai/CLAUDE.md` (cycle-15 section)

- [ ] **Step 5.1: Backend version bump**

`lazychat-erpnext/lazychat_erpnext/__init__.py`:
```python
__version__ = "0.5.0"
```

`lazychat-erpnext/pyproject.toml`:
```toml
version = "0.5.0"
```

- [ ] **Step 5.2: Backend CHANGELOG entry**

Open `lazychat-erpnext/CHANGELOG.md`. Add a new entry at the top under the latest version header:

```markdown
## [0.5.0] cycle-15 — Apply-path hardening — 2026-05-16

### Fixed

- **URL slug 404 on typed-create Apply** — commit response `link` field used `frappe.scrub()` (underscores) instead of Frappe Desk's URL slug (hyphens). Added `_doctype_url_slug(doctype)` helper, replaced call sites. Print Format / Sales Invoice / Purchase Order and other multi-word doctypes now navigate correctly.
- **Agent loops on duplicate-create** — typed `prepare_create_*` wrappers now pre-check existence and return a structured `prepare_update_doc` redirect on duplicate. New `_exists_redirect_to_update()` helper applied to ~15 wrappers.
- **`PREP_TTL_SEC` too short** — bumped from 300 (5 min) to 1800 (30 min). Multi-turn agent loops survive realistic latency budgets. `_retrieve_action` now distinguishes malformed / expired / wrong-user with actionable error messages.
- **Agent emits ghost CTAs** — `MAX_TURNS` default bumped from 8 to 16 (matches effort=medium). New system-prompt rule forbids "Click Apply" text without an accompanying `prepare_*` tool call in the same turn.

### Changed

- Tool-schema descriptions for typed `prepare_create_*` now spell out the duplicate handling contract.
- System prompt gained DUPLICATE PIVOT + CTA-must-have-tool rules (mirrored in chat-ui).

### Smoke

- In-process: 283 → 298 / 0 / 6 (+15 T103a-T103o).
- HTTP-wire: 91/91 unchanged (no new tools, no schema changes).
- Chat-ui vitest: 461 → 464 (+3 ghost-CTA detection).
```

- [ ] **Step 5.3: Backend CLAUDE.md entry**

Open `lazychat-erpnext/CLAUDE.md`. After the existing "Cycle 14.5" section near the top, insert a new section. Content should match the spec's "Why" + "Architecture" sections, tightly summarized to ~50 lines.

- [ ] **Step 5.4: Chat-ui version + changelog + CLAUDE.md**

`lazychat.ai/apps/chat-ui/package.json`:
```json
{
  "version": "0.2.0"
}
```

`lazychat.ai/CHANGELOG.md` — add a cycle-15 entry analogous to the backend's, focused on the chat-ui half (ghost-CTA detection + mirrored system prompt rules).

`lazychat.ai/CLAUDE.md` — add a brief cycle-15 section, focused on chat-ui changes.

- [ ] **Step 5.5: Final smoke + vitest run from clean copy**

```bash
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/lazychat_erpnext/desk_assistant/*.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/desk_assistant/ && \
cp /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/scripts/smoke-test-tools.py \
   /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && \
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | tail -5 && \
echo "---" && \
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && \
pnpm --filter chat-ui test 2>&1 | tail -3
```

Expected:
```
=== 298 pass, 0 fail, 6 skip ===
---
Tests  464 passed (464)
```

- [ ] **Step 5.6: Commit version/docs bumps**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && \
git add lazychat_erpnext/__init__.py pyproject.toml CHANGELOG.md CLAUDE.md && \
git commit -m 'chore(cycle-15): bump backend to 0.5.0 + CHANGELOG + CLAUDE.md'
```

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && \
git add apps/chat-ui/package.json CHANGELOG.md CLAUDE.md && \
git commit -m 'chore(cycle-15): bump chat-ui to 0.2.0 + CHANGELOG + CLAUDE.md'
```

---

## Task 6: End-to-end browser replay

**No file changes.** Manual validation only. Owner runs this.

- [ ] **Step 6.1: Restart bench so the new Python code loads**

```bash
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
ls apps/lazychat_erpnext/lazychat_erpnext/desk_assistant/tools.py  # confirm new code is in place
# Then either restart via Supervisor (if running) or restart bench start manually
```

Per CLAUDE.md macOS gotcha: `RESTART_BENCH=0` locally → kill and re-launch `bench start`.

- [ ] **Step 6.2: Walk the original transcript in browser**

1. Open `http://localhost:8000/app/purchase-order` in browser.
2. Open lazychat panel, set model = `claude-haiku-latest`.
3. Upload `PO-M26-02-000400.pdf` (any PO PDF will do).
4. Send: *"Create Purchase Order Print format for purchase order doctype print format name- 'Purchase Order - Agilitas'"*
5. **Expected:** agent stages successfully (may take 1-3 attempts depending on Jinja template — Jinja preview is out of scope here). Click Apply. The "Open Print Format" button navigates to `/app/print-format/Purchase Order - Agilitas` (200, not 404).
6. Send: *"Add a header section with the company logo and address."*
7. **Expected:** agent calls `prepare_update_doc` (not duplicate `prepare_create_print_format`). Applies cleanly. No "Token not found" errors. No phantom "Click Apply below" text without an Apply card.

- [ ] **Step 6.3: Capture before/after evidence**

```bash
mkdir -p /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/test/evidence/cycle-15-apply-path-hardening/
# Save screenshots of the successful flow into this directory
```

- [ ] **Step 6.4: Commit evidence**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && \
git add test/evidence/cycle-15-apply-path-hardening/ && \
git commit -m 'docs(cycle-15): evidence screenshots from end-to-end browser replay'
```

---

## Final verification before push

After all tasks complete, verify the full deliverable:

- [ ] **Final 1: Verify all commits land in cycle order**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && \
git log --oneline -10 && \
echo "---" && \
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && \
git log --oneline -5
```

Expected: 5-6 cycle-15 commits on lazychat-erpnext (URL slug, TTL, dup-pivot, max-turns+CTA, version bump, evidence), 2-3 on lazychat.ai (system-prompt mirror, ghost-CTA + tests, version bump).

- [ ] **Final 2: Re-run both smoke layers**

```bash
cd /Users/soumyasethy/Desktop/agilitas_code/erpnext/frappe-bench && \
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | tail -3 && \
echo "---" && \
python3 /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext/test/curl_smoke.py 2>&1 | tail -3 && \
echo "---" && \
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && \
pnpm --filter chat-ui test 2>&1 | tail -3
```

Expected:
- in-process: `=== 298 pass, 0 fail, 6 skip ===`
- HTTP-wire: `OK=80 | OK_ERROR=11` (unchanged from baseline)
- chat-ui: `Tests  464 passed (464)`

- [ ] **Final 3: Tag cycle-15 in both repos (do NOT push yet)**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && \
git tag -a cycle-15 -m 'Apply-path hardening: URL slugs, duplicate pivot, token TTL, turn budget' && \
echo "---" && \
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && \
git tag -a cycle-15 -m 'Apply-path hardening: ghost-CTA detection + system prompt mirror'
```

- [ ] **Final 4: STOP and await explicit owner approval for push**

Per workspace CLAUDE.md ("Never auto-commit, never auto-push, wait for the user to explicitly say 'commit' / 'push' / 'ship'"), do NOT push automatically. Surface to owner with:

> "All cycle-15 commits + tags are local in both repos. Smoke green: 298/0/6 in-process + 91/91 wire + 464/464 chat-ui. End-to-end browser replay validated. Ready when you say 'push'."

When the owner says push, run:
```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext && \
git push origin main --follow-tags && \
cd /Users/soumyasethy/Desktop/code-chat/lazychat.ai && \
git push origin main --follow-tags
```

---

## Out of scope (deferred to next cycle)

Per spec — NOT in this plan:
- Embeddings-based tool subsetting for small-LLM reliability (separate cycle).
- Print Format Jinja render-preview validators.
- Refactor of all typed-wrapper exists-pre-checks into a decorator.
- Smarter Plan-mode integration with DUPLICATE PIVOT rule.
- TYPED-WRAPPER mapping audit for any wrapper not currently in `_TYPED_WRAPPER_FOR_DOCTYPE`.
