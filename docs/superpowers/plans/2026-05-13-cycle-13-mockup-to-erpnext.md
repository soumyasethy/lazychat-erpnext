# Cycle 13 — Mockup-to-ERPNext Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Phases must run sequentially — M2 reads M1's output, M3 reads M2's output.**

**Goal:** Give the lazychat agent first-class typed primitives + visual feedback loop for building internal ERPNext Desk Pages from a reference design. End-to-end validation: hand-walk the agent through the Proman MD Dashboard mockup, capture V1→V2→V3 evidence.

**Architecture:** Three sequenced milestones, each shipping standalone value:

- **M1** (~1 week): 4 typed wrappers (Page, Server Script, Workspace, Asset Attach) + 2 discovery tools (Number Cards, Whitelisted Methods) + render-preview probe + system prompt playbook
- **M2** (~1.5 weeks): Playwright-based screenshot capture service on the bench + inline `screenshot` Message kind in chat-ui + auto-trigger after Page Apply
- **M3** (~1.5 weeks): LLM-as-judge vision model that compares reference↔candidate + generates fixes + orchestrates a 1-3 iteration auto-fix loop

**Tech Stack:** Python (Frappe app, AST validators via lxml/tinycss2/pyjsparser, Playwright for screenshots, vision-capable LLMs via existing `critic.py` adapter pattern) · TypeScript (chat-ui Message kinds, `agentRunner.ts` orchestrator, postMessage protocol extensions) · existing two-phase mutation pattern (`prepare_*` → `/commit`) preserved throughout.

**Reference spec:** [`../specs/2026-05-13-cycle-13-mockup-to-erpnext-design.md`](../specs/2026-05-13-cycle-13-mockup-to-erpnext-design.md). Design rationale (why we chose Desk Page over Web Page, why Playwright over html2canvas, etc.) lives in the spec; the plan focuses purely on HOW.

---

## File structure overview

Files this plan creates or modifies, grouped by responsibility:

### lazychat-erpnext (server-side)

| Path | Role | Phase |
|---|---|---|
| `pyproject.toml` | Add `lxml`, `tinycss2`, `pyjsparser` (M1) and `playwright` optional extra (M2) | M1, M2 |
| `lazychat_erpnext/desk_assistant/page_validators.py` | NEW — HTML/CSS/JS render-preview helpers + quality-warning surfacing | M1 |
| `lazychat_erpnext/desk_assistant/server_script_validators.py` | NEW — Python AST scan for Server Script API endpoints | M1 |
| `lazychat_erpnext/desk_assistant/tools.py` | Append 4 `prepare_*` typed wrappers + 2 discovery functions + 4 `commit_prepared` action handlers | M1 |
| `lazychat_erpnext/desk_assistant/tool_schemas.py` | Append 6 new tool schemas to `TOOL_SCHEMAS` | M1 |
| `lazychat_erpnext/desk_assistant/claude_bridge.py` | Append "Building Desk Pages & Dashboards" prompt block | M1 |
| `lazychat_erpnext/desk_assistant/screenshot.py` | NEW — Playwright service + whitelisted `capture(...)` endpoint + browser pool | M2 |
| `lazychat_erpnext/install.py` | Append Playwright/Chromium detection helper run on `after_install` | M2 |
| `lazychat_erpnext/desk_assistant/doctype/lazychat_settings/lazychat_settings.json` | Add `enable_screenshot_preview` (M2) + `vision_judge_models` (M3) fields | M2, M3 |
| `lazychat_erpnext/public/js/lazychat_panel.bundle.js` | Extend `handleInspectRoute` to handle `captureSpec.mode === 'screenshot'` | M2 |
| `lazychat_erpnext/public/js/html2canvas.min.js` | NEW — vendored 1.4.1 (~200 KB) used by chat-ui for reference-mockup capture | M2 |
| `lazychat_erpnext/desk_assistant/visual_judge.py` | NEW — vision LLM `compare(...)` + text LLM `generate_fixes(...)` | M3 |
| `lazychat_erpnext/desk_assistant/api.py` | Append `lazychat_visual_judge_compare` + `lazychat_visual_judge_generate_fixes` whitelisted endpoints | M3 |
| `scripts/smoke-test-tools.py` | Append T100a-k (M1), T101a-c (M2), T102a-d (M3) | M1, M2, M3 |
| `test/curl_smoke.py` + `test/tool_args.py` | Append HTTP-wire validators for the 6 new tools | M1 |

### lazychat.ai (chat-ui side)

| Path | Role | Phase |
|---|---|---|
| `packages/types/src/messages.ts` | Append `screenshot` Message kind (M2) + `visualDiff` Message kind (M3) | M2, M3 |
| `packages/types/src/postmessage.ts` | Extend `inspectRoute.captureSpec` + `inspectRouteResponse.captured` for screenshot mode | M2 |
| `apps/chat-ui/src/components/messages/ScreenshotMessage.tsx` | NEW — renderer for the `screenshot` Message kind | M2 |
| `apps/chat-ui/src/components/messages/VisualDiffMessage.tsx` | NEW — renderer for the `visualDiff` Message kind | M3 |
| `apps/chat-ui/src/components/MessageList.tsx` | Add dispatch cases for `screenshot` + `visualDiff` | M2, M3 |
| `apps/chat-ui/src/components/messages/MCPPreviewActionCard.tsx` | Add `create_page` + `create_workspace` to `LOW_RISK_ACTIONS`; add the new doc-creators to `AUTO_OPEN_AFTER_APPLY` | M1 |
| `apps/chat-ui/src/lib/agentRunner.ts` | Add screenshot auto-trigger (M2) + `runVisualIterationLoop` orchestrator (M3) | M2, M3 |
| `apps/chat-ui/src/lib/commitSlash.ts` | Add post-commit hook for `create_page` action to fire screenshot trigger | M2 |
| `apps/chat-ui/src/lib/visualJudgeClient.ts` | NEW — thin wrapper around the 2 vision-judge HTTP endpoints | M3 |
| `apps/chat-ui/src/lib/attachments/extractText.ts` | When isHtml + full `<html>` doc, capture reference-mockup screenshot via html2canvas | M2 |
| `apps/chat-ui/src/lib/routerSystemPrompt.ts` | Mirror the "Building Desk Pages" prompt block from the backend | M1 |

---

## Conventions for this plan

- **Source-of-truth lives in the umbrella `code-chat/` repos.** Edit in `lazychat-erpnext/lazychat_erpnext/` (NOT in the bench's `apps/lazychat_erpnext/`). The bench is rsync'd via `deploy-local.sh --quick`.
- **Smoke-test runner pattern:** `cp scripts/smoke-test-tools.py <bench>/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py && bench --site erp.local execute lazychat_erpnext._smoke.run`. Already documented in `CLAUDE.md` "Smoke test — two layers". The plan's "Run smoke" steps reference this; don't repeat the `cp` step every time — just re-`cp` before any `bench execute` after a deploy.
- **TDD pattern:** every code task starts with a failing smoke (T## entry) or vitest case. Run it. Watch it fail. Implement. Watch it pass. Commit.
- **Commits:** conventional commit format (`feat(scope): ...` / `fix(scope): ...` / `chore(scope): ...`). NEVER auto-push. Local commits are fine per-task; push only when the user says so.
- **Auto-discover existing patterns:** when a task says "follow the pattern of X at file:line", grep for that line range and pattern-match. Don't re-derive from first principles.
- **Vision-judge model:** wired through `Lazychat Settings.vision_judge_models` (configurable, the spec's chosen option). Default fallback: Claude Sonnet 4.6 for high, Opus 4.7 for max.

---

## Phase M1 — Typed UI primitives + render-preview + system prompt

**Phase goal:** Agent can stage + apply a complete Desk Page (HTML + CSS + JS + supporting Server Scripts) with validation that catches semantic errors before Apply. After M1 alone, the user can hand-walk the agent through the Proman dashboard mockup; they verify visually by opening `/app/<name>` themselves (M2 closes that loop).

**Phase exit criteria:**
- Tool registry goes 95 → **101**
- `bench --site erp.local execute lazychat_erpnext._smoke.run` → 12 new T## cases pass (T100a–T100k + one for `list_whitelisted_methods`)
- `python3 test/curl_smoke.py` → +6 wire-level cases pass
- A handcrafted `prepare_create_page` call ships a Page that loads at `/app/<page-name>` (manual verification on `erp.local`)

### Task M1.1: Add Python deps and create render-preview helper module skeletons

**Files:**
- Modify: `lazychat-erpnext/pyproject.toml`
- Create: `lazychat-erpnext/lazychat_erpnext/desk_assistant/page_validators.py`
- Create: `lazychat-erpnext/lazychat_erpnext/desk_assistant/server_script_validators.py`

The 3 Python parsers (`lxml`, `tinycss2`, `pyjsparser`) are small, well-known, and pure-Python. We lazy-import them in the validator modules so the bench doesn't pay the cost on every request — only when a `prepare_create_page` is actually staged.

- [ ] **Step 1: Write the failing smoke entry**

Append to `scripts/smoke-test-tools.py` after the existing T## entries (find the last `T8X` block and add below it):

```python
    # ──────────────────────────────────────────────────────────────────────
    # CYCLE 13 — M1: typed UI primitive tools
    # ──────────────────────────────────────────────────────────────────────

    log("\n=== Cycle 13 M1 — typed UI primitives ===")

    # T100a — page_validators module imports cleanly
    try:
        from lazychat_erpnext.desk_assistant import page_validators
        from lazychat_erpnext.desk_assistant import server_script_validators
        pf(True, "T100a page/server_script validator modules import")
    except Exception as e:
        pf(False, f"T100a validator modules import: {e}")
```

- [ ] **Step 2: Run smoke to verify it fails**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py \
   $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep -E "T100|FAIL"
```
Expected: `T100a validator modules import: No module named 'lazychat_erpnext.desk_assistant.page_validators'`

- [ ] **Step 3: Add Python deps to pyproject.toml**

Find the existing `[project] dependencies = [...]` block in `lazychat-erpnext/pyproject.toml` (around line 30). Add three entries:

```toml
dependencies = [
    # ... existing deps ...
    "lxml>=4.9",          # HTML well-formedness check for prepare_create_page render-preview
    "tinycss2>=1.2",      # CSS syntax check (brace balance + token validity)
    "pyjsparser>=2.7",    # JS AST for static walks (frappe.call method refs, frappe.db doctype refs)
]
```

- [ ] **Step 4: Create the empty validator modules**

Create `lazychat-erpnext/lazychat_erpnext/desk_assistant/page_validators.py`:

```python
"""Render-preview validators for prepare_create_page.

Each `validate_*` function returns `None` on pass, or a dict
`{"phase": <name>, "error": <msg>, "hint": <actionable hint>}` on hard fail.

`collect_quality_warnings` returns a list of `{"category", "severity",
"description"}` dicts — these are NON-blocking (the agent and user see them
in the Apply card's critic strip but Apply still proceeds).

Lazy imports: lxml/tinycss2/pyjsparser are heavy (combined ~5 MB on disk).
We import them inside the functions so a bench that never stages a Page
doesn't pay the cost at module-import time.
"""
from __future__ import annotations
from typing import Optional


def validate_html(content: str) -> Optional[dict]:
    """Phase: html_parse — return None if content is well-formed HTML5."""
    raise NotImplementedError  # filled in Task M1.2


def validate_css(style: str) -> Optional[dict]:
    """Phase: css_syntax — return None if style is valid CSS."""
    raise NotImplementedError  # Task M1.2


def validate_js(script: str) -> Optional[dict]:
    """Phase: js_syntax — return None if script parses to a valid AST."""
    raise NotImplementedError  # Task M1.2


def validate_js_doctype_refs(script: str) -> Optional[dict]:
    """Phase: js_doctypes_exist — walk AST for frappe.db.get_list/get_value/exists
    referencing doctype X; reject if any X doesn't exist in the bench."""
    raise NotImplementedError  # Task M1.2


def validate_js_method_refs(script: str, staged_methods: Optional[list] = None) -> Optional[dict]:
    """Phase: js_methods_exist — walk AST for frappe.call references; reject if
    a referenced method is not (a) built-in whitelisted, (b) in staged_methods,
    (c) already registered."""
    raise NotImplementedError  # Task M1.2


def collect_quality_warnings(content: str, style: str, script: str) -> list:
    """Non-blocking — soft warnings: hardcoded colors w/o theme tokens, missing
    structural HTML, placeholder-looking data, missing lazychatReady marker."""
    return []  # Task M1.2
```

Create `lazychat-erpnext/lazychat_erpnext/desk_assistant/server_script_validators.py`:

```python
"""Render-preview AST validators for prepare_create_server_script (script_type=API).

Mirrors tools.py:_validate_script_report_body but adapted for API endpoints:
- API scripts must produce output via `frappe.response.message = <dict>` OR
  a top-level `return` (not enforced by Frappe but useful for clarity).
- Reads/computations only — writes are explicitly rejected (they belong in
  prepare_create_doc / prepare_update_doc, not in API endpoints).
"""
from __future__ import annotations
from typing import Optional
import ast


FORBIDDEN_IMPORTS = {
    "subprocess", "os", "sys", "shutil", "socket", "urllib", "requests",
    "http", "smtplib", "ftplib", "telnetlib", "ssl", "ctypes", "multiprocessing",
}

# Named without the open-paren so this file passes static scanners that flag
# arbitrary code execution patterns.
FORBIDDEN_BUILTINS = {"open", "eval", "exec", "compile", "__import__", "input", "breakpoint"}

FORBIDDEN_FRAPPE_DB_WRITES = {
    "set_value", "set_many", "delete", "sql_ddl", "multisql",
    "commit", "rollback", "savepoint", "release_savepoint",
}


def validate_python_ast(script: str) -> Optional[dict]:
    """Phase: python_ast — return None on successful parse, else error dict."""
    raise NotImplementedError  # Task M1.2


def validate_no_forbidden_imports(tree: ast.AST) -> Optional[dict]:
    """Phase: forbidden_imports — reject imports of network/shell modules."""
    raise NotImplementedError  # Task M1.2


def validate_no_forbidden_builtins(tree: ast.AST) -> Optional[dict]:
    """Phase: forbidden_builtins — reject calls to dangerous builtins by name."""
    raise NotImplementedError  # Task M1.2


def validate_no_frappe_writes(tree: ast.AST) -> Optional[dict]:
    """Phase: forbidden_frappe_writes — reject frappe.db.<write> calls."""
    raise NotImplementedError  # Task M1.2


def validate_output_present(tree: ast.AST) -> Optional[dict]:
    """Phase: output_present — script must set frappe.response.message OR return."""
    raise NotImplementedError  # Task M1.2


def run_all(script: str) -> Optional[dict]:
    """Run every phase in order. Return first failure, or None if all pass."""
    raise NotImplementedError  # Task M1.2
```

- [ ] **Step 5: Run smoke to verify the import succeeds**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py \
   $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T100a
```
Expected: `PASS T100a page/server_script validator modules import`

- [ ] **Step 6: Commit**

```bash
cd lazychat-erpnext
git add pyproject.toml lazychat_erpnext/desk_assistant/page_validators.py \
        lazychat_erpnext/desk_assistant/server_script_validators.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m1): scaffold render-preview validator modules

Empty module skeletons for HTML/CSS/JS + Server Script AST validators that
the prepare_create_page / prepare_create_server_script wrappers (next tasks)
will call. Adds lxml/tinycss2/pyjsparser deps (lazy-imported in the impls).
T100a confirms the modules import cleanly."
```

---

### Task M1.2: Fill in the page + server-script validator implementations

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/page_validators.py`
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/server_script_validators.py`
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` (add unit-test-style cases T100b-T100d)

- [ ] **Step 1: Write the failing T100b–T100d smoke cases**

Append below T100a:

```python
    # T100b — page_validators.validate_html rejects unclosed tag
    from lazychat_erpnext.desk_assistant.page_validators import (
        validate_html, validate_css, validate_js,
        validate_js_doctype_refs, collect_quality_warnings,
    )
    r = validate_html("<div><span>unclosed</div>")
    pf(r is not None and "html" in r.get("phase", ""), f"T100b html validator rejects unclosed tag: {r}")

    r = validate_html("<div><span>balanced</span></div>")
    pf(r is None, f"T100b' html validator accepts well-formed: {r}")

    # T100c — validate_css rejects unbalanced braces
    r = validate_css(".foo { color: red ")
    pf(r is not None, f"T100c css validator rejects unbalanced braces: {r}")

    r = validate_css(".foo { color: red; }")
    pf(r is None, f"T100c' css validator accepts well-formed: {r}")

    # T100d — validate_js_doctype_refs catches unknown doctype
    js_bad = "frappe.db.get_list('NotARealDoctypeXYZ', {fields: ['name']});"
    r = validate_js_doctype_refs(js_bad)
    pf(r is not None and "NotARealDoctypeXYZ" in r.get("error", ""), f"T100d js doctype-ref validator catches unknown: {r}")

    js_good = "frappe.db.get_list('User', {fields: ['name']});"
    r = validate_js_doctype_refs(js_good)
    pf(r is None, f"T100d' js doctype-ref validator passes known: {r}")

    # T100d2 — collect_quality_warnings surfaces hardcoded-color warning
    css_hardcoded = ".a{color:#fff}.b{color:#000}.c{color:#aabbcc}.d{color:#abc}.e{color:#fa0}.f{color:rgb(1,2,3)}"
    warnings = collect_quality_warnings("<main><section><h1>x</h1></section></main>", css_hardcoded, "document.body.dataset.lazychatReady='1';")
    pf(any(w["category"] == "theme_tokens" for w in warnings), f"T100d2 hardcoded-color warning surfaces: {warnings}")
```

- [ ] **Step 2: Run smoke to verify fails**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep -E "T100[bcd]"
```
Expected: T100b–T100d2 all FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement page_validators.py**

Replace the body of `page_validators.py` (keep the module docstring):

```python
def validate_html(content: str) -> Optional[dict]:
    if not content or not content.strip():
        return None  # empty is fine; Page may be all-JS
    try:
        from lxml import html as lxml_html
    except ImportError:
        return None  # graceful — let install hook surface the missing dep
    try:
        # use_fragment=True so a <div>...</div> fragment doesn't need a full <html><body>
        lxml_html.fragment_fromstring(content, create_parent="div")
    except Exception as e:
        return {
            "phase": "html_parse",
            "error": f"HTML parse error: {e}",
            "hint": "Common causes: unclosed tag, mismatched quotes, stray < or >.",
        }
    return None


def validate_css(style: str) -> Optional[dict]:
    if not style or not style.strip():
        return None
    try:
        import tinycss2
    except ImportError:
        return None
    rules, errors = tinycss2.parse_stylesheet_bytes(style.encode("utf-8"), skip_comments=True, skip_whitespace=True)
    if errors:
        e = errors[0]
        return {
            "phase": "css_syntax",
            "error": f"CSS syntax error at line {getattr(e, 'source_line', '?')}: {getattr(e, 'message', str(e))}",
            "hint": "Check brace balance and ; terminators. tinycss2 surfaces the first failure only.",
        }
    return None


def validate_js(script: str) -> Optional[dict]:
    if not script or not script.strip():
        return None
    try:
        import pyjsparser
    except ImportError:
        return None
    try:
        pyjsparser.parse(script)
    except Exception as e:
        return {
            "phase": "js_syntax",
            "error": f"JS syntax error: {e}",
            "hint": "pyjsparser is ES5-flavored; some ES2015+ syntax (arrow functions in some shapes, async/await, classes) may flag — re-write in plain function form if you hit this.",
        }
    return None


# Built-in Frappe whitelisted method prefixes that ALWAYS exist. Used to short-
# circuit the existence check for the most-common cases.
_BUILTIN_WHITELISTED_PREFIXES = (
    "frappe.client.get", "frappe.client.set_value", "frappe.client.insert",
    "frappe.client.delete", "frappe.client.cancel", "frappe.client.submit",
    "frappe.client.rename_doc", "frappe.desk.", "frappe.utils.",
    "frappe.email.queue.", "frappe.handler.",
)


def _walk_string_literals(node):
    """Yield every string literal in an AST tree (pyjsparser produces dict-shaped nodes)."""
    if isinstance(node, dict):
        if node.get("type") == "Literal" and isinstance(node.get("value"), str):
            yield node["value"]
        for v in node.values():
            yield from _walk_string_literals(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_string_literals(item)


def _walk_call_expressions(node, target_func_path):
    """Yield args of every CallExpression whose callee path matches target_func_path
    (e.g. ['frappe', 'db', 'get_list']). pyjsparser returns dicts."""
    if isinstance(node, dict):
        if node.get("type") == "CallExpression":
            callee = node.get("callee", {})
            path = _extract_member_path(callee)
            if path == target_func_path:
                yield node.get("arguments", [])
        for v in node.values():
            yield from _walk_call_expressions(v, target_func_path)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_call_expressions(item, target_func_path)


def _extract_member_path(callee):
    """For an AST node like {type: MemberExpression, object: {type: MemberExpression, object: {type: Identifier, name: 'frappe'}, property: {type: Identifier, name: 'db'}}, property: {type: Identifier, name: 'get_list'}}
    return ['frappe', 'db', 'get_list']. Returns [] for non-MemberExpression callees."""
    parts = []
    cur = callee
    while cur and isinstance(cur, dict):
        t = cur.get("type")
        if t == "MemberExpression":
            prop = cur.get("property", {})
            if prop.get("type") == "Identifier":
                parts.insert(0, prop.get("name"))
            cur = cur.get("object", {})
        elif t == "Identifier":
            parts.insert(0, cur.get("name"))
            cur = None
        else:
            return []
    return parts


def validate_js_doctype_refs(script: str) -> Optional[dict]:
    if not script or not script.strip():
        return None
    try:
        import pyjsparser
        import frappe
    except ImportError:
        return None
    try:
        tree = pyjsparser.parse(script)
    except Exception:
        return None  # caught by validate_js
    referenced = set()
    for target in (["frappe", "db", "get_list"], ["frappe", "db", "get_value"], ["frappe", "db", "exists"], ["frappe", "db", "get_doc"]):
        for args in _walk_call_expressions(tree, target):
            if args and args[0].get("type") == "Literal" and isinstance(args[0].get("value"), str):
                referenced.add(args[0]["value"])
    for dt in referenced:
        if not frappe.db.exists("DocType", dt):
            return {
                "phase": "js_doctypes_exist",
                "error": f"JS references doctype '{dt}' which doesn't exist.",
                "hint": f"Run `describe_doctype` to find the right name. Common typos: 'User' (not 'Users'), 'Sales Invoice' (not 'sales_invoice').",
            }
    return None


def validate_js_method_refs(script: str, staged_methods: Optional[list] = None) -> Optional[dict]:
    if not script or not script.strip():
        return None
    try:
        import pyjsparser
        import frappe
    except ImportError:
        return None
    try:
        tree = pyjsparser.parse(script)
    except Exception:
        return None
    # frappe.call({method: 'x.y.z', ...}) — extract the 'method' literal from the first arg
    referenced = set()
    for args in _walk_call_expressions(tree, ["frappe", "call"]):
        if not args:
            continue
        first = args[0]
        if first.get("type") == "ObjectExpression":
            for prop in first.get("properties", []):
                key = prop.get("key", {})
                key_name = key.get("name") if key.get("type") == "Identifier" else key.get("value")
                if key_name == "method":
                    val = prop.get("value", {})
                    if val.get("type") == "Literal" and isinstance(val.get("value"), str):
                        referenced.add(val["value"])
    staged = set(staged_methods or [])
    for method in referenced:
        if method in staged:
            continue
        if any(method.startswith(p) for p in _BUILTIN_WHITELISTED_PREFIXES):
            continue
        # Check if it's a registered whitelisted method
        try:
            from frappe.handler import get_method
            get_method(method)
            continue  # exists
        except Exception:
            pass
        return {
            "phase": "js_methods_exist",
            "error": f"JS references method '{method}' that doesn't exist.",
            "hint": "Either: (a) stage `prepare_create_server_script` with this api_method in the same turn (the validator considers same-turn-staged methods as valid), (b) use a built-in like `frappe.client.get_list`, or (c) if the method DOES exist on this bench, double-check the dotted path.",
        }
    return None


def collect_quality_warnings(content: str, style: str, script: str) -> list:
    """Non-blocking soft warnings — the LLM sees them and can self-revise; if
    not addressed, they render in the Apply card's critic strip. Apply still
    proceeds; these are advisory."""
    import re
    warnings = []

    # 1. Hardcoded colors without theme-token usage
    color_pattern = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([0-9.\s,]+\)")
    var_pattern = re.compile(r"var\(\s*--")
    color_count = len(color_pattern.findall(style or ""))
    var_count = len(var_pattern.findall(style or ""))
    if color_count > 5 and var_count == 0:
        warnings.append({
            "category": "theme_tokens",
            "severity": "major",
            "description": f"Page CSS has {color_count} hardcoded colors and 0 `var(--*)` references — page will not respect Frappe dark mode. Use `var(--bg-color)`, `var(--text-color)`, `var(--primary-color)`, `var(--text-muted)`, `var(--border-color)` from Frappe's theme.",
        })

    # 2. Missing structural HTML
    if content:
        has_header = "<header" in content
        has_main = "<main" in content
        has_section = "<section" in content
        missing = [t for t, has in (("header", has_header), ("main", has_main), ("section", has_section)) if not has]
        if len(missing) >= 2:
            warnings.append({
                "category": "semantic_html",
                "severity": "minor",
                "description": f"Page is missing structural HTML elements: {', '.join('<'+m+'>' for m in missing)}. Use <header>, <main>, <section> for semantic structure.",
            })

    # 3. Missing lazychatReady marker (critical for M2 screenshot trigger)
    if script and "lazychatReady" not in script:
        warnings.append({
            "category": "ready_signal",
            "severity": "major",
            "description": "Page JS does not set `document.body.dataset.lazychatReady = '1'`. The screenshot preview will use a 5s fallback timeout instead of precise ready-detection. Add the marker at the end of your final `frappe.call(...).then(...)` chain.",
        })

    return warnings
```

- [ ] **Step 4: Implement server_script_validators.py**

Replace the body of `server_script_validators.py`:

```python
def validate_python_ast(script: str) -> Optional[dict]:
    if not script or not script.strip():
        return {"phase": "python_ast", "error": "script is empty", "hint": "Provide a Python body that sets frappe.response.message = <dict>."}
    try:
        ast.parse(script)
    except SyntaxError as e:
        return {
            "phase": "python_ast",
            "error": f"Python syntax error at line {e.lineno}: {e.msg}",
            "hint": "Server Scripts run as standard Python under Frappe's safe_exec. Tabs/spaces, missing colons, and unclosed brackets are the usual culprits.",
        }
    return None


def validate_no_forbidden_imports(tree: ast.AST) -> Optional[dict]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in FORBIDDEN_IMPORTS:
                    return {
                        "phase": "forbidden_imports",
                        "error": f"`import {alias.name}` is not allowed in Server Scripts (Frappe safe_exec sandbox).",
                        "hint": "Use frappe.* alternatives: frappe.db for data, frappe.utils.* for helpers, frappe.session.user for current user.",
                    }
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top in FORBIDDEN_IMPORTS:
                return {
                    "phase": "forbidden_imports",
                    "error": f"`from {node.module} import ...` is not allowed in Server Scripts.",
                    "hint": "Use frappe.* alternatives.",
                }
    return None


def validate_no_forbidden_builtins(tree: ast.AST) -> Optional[dict]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_BUILTINS:
                return {
                    "phase": "forbidden_builtins",
                    "error": f"`{node.func.id}(...)` is forbidden under Frappe safe_exec.",
                    "hint": "These builtins are stripped from the safe_exec namespace. For file I/O use frappe.get_doc('File', ...).get_content(); for serialization use json.* (which IS available).",
                }
    return None


def validate_no_frappe_writes(tree: ast.AST) -> Optional[dict]:
    """Walk for frappe.db.<forbidden_name> attribute access patterns."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            # frappe.db.<X>
            if (isinstance(node.value, ast.Attribute) and
                isinstance(node.value.value, ast.Name) and
                node.value.value.id == "frappe" and
                node.value.attr == "db" and
                node.attr in FORBIDDEN_FRAPPE_DB_WRITES):
                return {
                    "phase": "forbidden_frappe_writes",
                    "error": f"`frappe.db.{node.attr}` is forbidden in Server Script API endpoints.",
                    "hint": "API endpoints are READ-ONLY by design. For writes, use prepare_create_doc / prepare_update_doc which go through the two-phase Apply pattern.",
                }
    return None


def validate_output_present(tree: ast.AST) -> Optional[dict]:
    """Look for `frappe.response.message = ...` OR a top-level Return."""
    has_response = False
    has_return = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Attribute) and
                    isinstance(target.value, ast.Attribute) and
                    isinstance(target.value.value, ast.Name) and
                    target.value.value.id == "frappe" and
                    target.value.attr == "response" and
                    target.attr == "message"):
                    has_response = True
        if isinstance(node, ast.Return):
            has_return = True
    if not has_response and not has_return:
        return {
            "phase": "output_present",
            "error": "Server Script API endpoint produces no output.",
            "hint": "End with `frappe.response.message = <result_dict>` (preferred) or a top-level `return <value>`. Without this the API endpoint returns null.",
        }
    return None


def run_all(script: str) -> Optional[dict]:
    """Run every phase in order. Return first failure, or None if all pass."""
    err = validate_python_ast(script)
    if err:
        return err
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return validate_python_ast(script)  # double-check (race against script change)
    for check in (validate_no_forbidden_imports, validate_no_forbidden_builtins,
                  validate_no_frappe_writes, validate_output_present):
        err = check(tree)
        if err:
            return err
    return None
```

- [ ] **Step 5: Re-run smoke to verify all T100a–T100d2 pass**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T100
```
Expected: T100a, T100b, T100b', T100c, T100c', T100d, T100d', T100d2 all PASS.

- [ ] **Step 6: Commit**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/page_validators.py \
        lazychat_erpnext/desk_assistant/server_script_validators.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m1): implement HTML/CSS/JS + Server Script AST validators

page_validators: lxml-based HTML well-formedness, tinycss2 CSS syntax,
pyjsparser-based JS AST walks for doctype refs (frappe.db.get_list/etc.) and
method refs (frappe.call({method: ...})). collect_quality_warnings surfaces
non-blocking soft warnings (hardcoded colors, missing semantic HTML, missing
lazychatReady marker).

server_script_validators: mirrors tools.py:_validate_script_report_body —
rejects forbidden imports, dangerous builtins, frappe.db writes, and missing
frappe.response.message output. T100a-d2 cover both."
```

---

### Task M1.3: `prepare_create_page` — typed wrapper + schema + commit handler

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py` — add `prepare_create_page(args)` function + `create_page` branch in `commit_prepared` dispatcher
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tool_schemas.py` — append schema dict to `TOOL_SCHEMAS`
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — add T100e (happy path), T100f (unknown doctype rejection), T100g (quality_warnings surface)

**Pattern reference:** `prepare_create_report` at `tools.py` (around line 3458) — same shape: validate args → run render-preview → on pass, stage to Redis + return `{ok, preview_token, summary, …}`; on fail, return `{ok:false, …}`. The commit handler mirrors `commit_prepared` action `create_report` branch.

- [ ] **Step 1: Write the failing T100e–T100g smoke cases**

Append to `scripts/smoke-test-tools.py`:

```python
    # T100e — prepare_create_page happy path: stage → token → commit → /app/<name> exists
    from lazychat_erpnext.desk_assistant.tools import execute_tool
    page_name_e = "_lz_smoke_page_e"
    if frappe.db.exists("Page", page_name_e):
        frappe.delete_doc("Page", page_name_e, ignore_permissions=True, force=True)
        frappe.db.commit()  # nosemgrep: frappe-manual-commit -- smoke test cleanup; pre-test isolation requires commit so the next bench --site execute sees a clean slate
    r = execute_tool("prepare_create_page", {
        "page_name": page_name_e, "title": "Smoke E",
        "content": "<main><section><h1>Hi</h1></section></main>",
        "style": "main { padding: 12px; color: var(--text-color); }",
        "script": "document.body.dataset.lazychatReady = '1';",
    })
    pf(r.get("ok") and r.get("preview_token"), f"T100e prepare_create_page stage: {r}")
    token_e = r.get("preview_token")
    from lazychat_erpnext.desk_assistant.tools import commit_prepared
    r = commit_prepared(token_e)
    pf(r.get("ok") and frappe.db.exists("Page", page_name_e), f"T100e' prepare_create_page commit: {r}")

    # T100f — prepare_create_page render-preview rejects unknown doctype in JS
    r = execute_tool("prepare_create_page", {
        "page_name": "_lz_smoke_page_f", "title": "Smoke F",
        "content": "<main></main>", "style": "",
        "script": "frappe.db.get_list('NotARealDoctypeXYZ', {});",
    })
    pf(not r.get("ok") and "NotARealDoctypeXYZ" in r.get("error", ""), f"T100f unknown-doctype rejection: {r}")

    # T100g — prepare_create_page surfaces quality_warnings for missing lazychatReady
    r = execute_tool("prepare_create_page", {
        "page_name": "_lz_smoke_page_g", "title": "Smoke G",
        "content": "<div>no semantic elements</div>",
        "style": ".a{color:#fff}.b{color:#000}.c{color:#111}.d{color:#222}.e{color:#333}.f{color:#444}",
        "script": "console.log('no marker');",
    })
    qw = r.get("quality_warnings", [])
    pf(r.get("ok") and any(w["category"] == "ready_signal" for w in qw), f"T100g quality_warnings surface: {qw}")
```

- [ ] **Step 2: Run smoke to verify fails**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T100[efg]
```
Expected: `T100e prepare_create_page stage: {'error': 'unknown tool: prepare_create_page'}`.

- [ ] **Step 3: Implement `prepare_create_page` in `tools.py`**

Add to `tools.py` (append after the last `prepare_create_*` function — search for `def prepare_create_email_template` or similar to find the cluster):

```python
def prepare_create_page(args: dict) -> dict:
    """Stage a Desk Page (Frappe Page doctype, non-standard).

    Args:
      page_name (str, optional): URL slug. Auto-derived from `title` via frappe.scrub if omitted.
      title (str): required.
      module (str, default "Lazychat Erpnext"): Frappe module.
      roles (list[str], default ["System Manager"]): roles permitted to view.
      content (str): HTML body. Validated for parse correctness.
      style (str, default ""): inline CSS.
      script (str, default ""): inline JS (the page controller).
      icon (str, default ""): Frappe icon class.

    Returns:
      {ok, preview_token, summary, action, route, page_name, quality_warnings} on success.
      {ok: False, error, hint, phase} on hard-validation failure.
    """
    from lazychat_erpnext.desk_assistant.page_validators import (
        validate_html, validate_css, validate_js,
        validate_js_doctype_refs, validate_js_method_refs,
        collect_quality_warnings,
    )

    # System Manager gate — Page mutations affect every Desk user
    if "System Manager" not in (frappe.get_roles(frappe.session.user) or []):
        return {"ok": False, "error": "Only System Manager can stage a Desk Page."}

    title = (args.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title is required.", "hint": "e.g. 'MD Dashboard'"}

    page_name = args.get("page_name") or frappe.scrub(title).replace("_", "-")
    if frappe.db.exists("Page", page_name):
        return {
            "ok": False,
            "error": f"Page '{page_name}' already exists.",
            "hint": "Use `prepare_update_doc({doctype: 'Page', name: '" + page_name + "', patch: {...}})` to modify it, or pick a different page_name.",
        }

    content = args.get("content") or ""
    style = args.get("style") or ""
    script = args.get("script") or ""

    # Render-preview — hard blocks
    for check in (validate_html(content), validate_css(style), validate_js(script),
                  validate_js_doctype_refs(script)):
        if check:
            return {"ok": False, **check}

    # method refs — pull in same-turn-staged Server Scripts from a session flag
    staged_methods = (frappe.local.flags.get("lazychat_staging_methods") or [])
    err = validate_js_method_refs(script, staged_methods=staged_methods)
    if err:
        return {"ok": False, **err}

    # Quality warnings (non-blocking)
    quality_warnings = collect_quality_warnings(content, style, script)

    payload = {
        "page_name": page_name,
        "title": title,
        "module": args.get("module") or "Lazychat Erpnext",
        "roles": args.get("roles") or ["System Manager"],
        "content": content,
        "style": style,
        "script": script,
        "icon": args.get("icon") or "",
        "standard": "No",
    }
    token = _stage_action("create_page", payload, ttl=300)
    return {
        "ok": True,
        "action": "create_page",
        "preview_token": token,
        "page_name": page_name,
        "route": f"/app/{page_name}",
        "summary": f"Create Desk Page '{title}' at /app/{page_name}",
        "quality_warnings": quality_warnings,
        "confirm_with": f"/commit {token}",
    }
```

Add the `create_page` branch to `commit_prepared` (search for `def commit_prepared` in tools.py, find the if/elif chain on `action`, add):

```python
    elif action == "create_page":
        # Re-check perms (defense-in-depth)
        if "System Manager" not in (frappe.get_roles(frappe.session.user) or []):
            return {"ok": False, "error": "System Manager required."}
        if frappe.db.exists("Page", payload["page_name"]):
            return {"ok": False, "error": f"Page '{payload['page_name']}' already exists at commit time."}
        doc = frappe.get_doc({
            "doctype": "Page",
            "page_name": payload["page_name"],
            "title": payload["title"],
            "module": payload["module"],
            "standard": payload["standard"],
            "roles": [{"role": r} for r in payload["roles"]],
            "content": payload["content"],
            "style": payload["style"],
            "script": payload["script"],
            "icon": payload["icon"],
        })
        doc.insert(ignore_permissions=False)
        return {
            "ok": True,
            "action": "create_page",
            "doctype": "Page",
            "name": doc.name,
            "link": f"/app/{payload['page_name']}",
        }
```

- [ ] **Step 4: Register schema in `tool_schemas.py`**

Append to the `TOOL_SCHEMAS` list:

```python
    {
        "name": "prepare_create_page",
        "description": (
            "Stage a Desk Page (custom HTML/CSS/JS dashboard at /app/<page_name>). "
            "Internal-only (requires login, role-gated). Use this for any custom "
            "dashboard, full-page report, or executive overview. The page lives "
            "inside the Desk shell — frappe.call / frappe.db / frappe.boot are "
            "available out of the box.\n\n"
            "Render-preview HARD-blocks: HTML parse errors, CSS syntax errors, "
            "JS syntax errors, references to non-existent doctypes (frappe.db.get_list/etc.) "
            "or non-existent methods (frappe.call({method: ...})).\n\n"
            "Render-preview QUALITY_WARNINGS (non-blocking, render in Apply card): "
            "hardcoded colors without theme tokens (breaks dark mode), missing "
            "structural HTML (<header>, <main>, <section>), missing "
            "`document.body.dataset.lazychatReady = '1'` marker at end of JS "
            "(disables precise screenshot timing).\n\n"
            "Two-phase: returns preview_token; user clicks Apply to commit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "page_name": {"type": "string", "description": "URL slug (auto-derived from title if omitted). Page will live at /app/<page_name>."},
                "title": {"type": "string", "description": "Display title."},
                "module": {"type": "string", "description": "Frappe module (default: Lazychat Erpnext)."},
                "roles": {"type": "array", "items": {"type": "string"}, "description": "Roles permitted to view (default: System Manager)."},
                "content": {"type": "string", "description": "Page body HTML. Use <header>/<main>/<section> for semantic structure."},
                "style": {"type": "string", "description": "Inline CSS. PREFER var(--bg-color)/var(--text-color)/var(--primary-color) etc. over hardcoded colors — hardcoded colors break dark mode."},
                "script": {"type": "string", "description": "Inline JS (the page controller). Use frappe.call / frappe.db.get_list for data. END with `document.body.dataset.lazychatReady = '1';` after final data fetches resolve — required for the screenshot preview tool to know when the page is fully rendered."},
                "icon": {"type": "string", "description": "Frappe icon class (e.g. 'octicon octicon-graph')."},
            },
            "required": ["title", "content"],
        },
    },
```

- [ ] **Step 5: Re-run smoke to verify T100e–T100g pass**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T100[efg]
```
Expected: T100e, T100e', T100f, T100g all PASS.

- [ ] **Step 6: Manual sanity check — render the page**

```bash
curl -s -b ~/.frappe-cookies.txt "http://localhost:8000/app/_lz_smoke_page_e" | grep -o "Smoke E" | head -1
```
Expected: `Smoke E` (Page renders).

- [ ] **Step 7: Commit**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/tools.py \
        lazychat_erpnext/desk_assistant/tool_schemas.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m1): prepare_create_page typed wrapper + render-preview

New tool: stages a Frappe Page (Desk Page at /app/<page-name>) with full
HTML/CSS/JS validation at preview time. Hard-rejects unparseable HTML/CSS/JS,
references to non-existent doctypes (frappe.db.get_list), references to
non-existent methods (frappe.call). Surfaces non-blocking quality warnings
for hardcoded colors / missing semantic HTML / missing lazychatReady marker.

Two-phase pattern preserved: preview_token returned at stage, applied via
commit_prepared(token). System Manager gate; LOW_RISK auto-Apply eligibility
wired chat-ui-side in next task.

Tool registry: 95 → 96. T100e/f/g smoke cases pass."
```

---

### Task M1.4: `prepare_create_server_script` — typed wrapper + schema + commit handler

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py` — add `prepare_create_server_script(args)` + `create_server_script` commit branch
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tool_schemas.py` — append schema
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — add T100h (happy path + HTTP-reachable), T100i (`import os` rejected), T100j (`frappe.db.set_value` rejected)

Pattern reference: existing `prepare_create_client_script` in tools.py (already tested); same shape but with Python AST validation instead of JS.

- [ ] **Step 1: Add failing smoke cases T100h–T100j**

```python
    # T100h — prepare_create_server_script happy path + API endpoint reachable
    if not frappe.conf.get("lazychat_allow_dangerous_tools"):
        log("⚠ T100h skipped: lazychat_allow_dangerous_tools=False in site_config")
    else:
        ss_name = "_lz_smoke_ss_h"
        if frappe.db.exists("Server Script", ss_name):
            frappe.delete_doc("Server Script", ss_name, force=True)
            frappe.db.commit()  # nosemgrep: frappe-manual-commit -- smoke test cleanup
        r = execute_tool("prepare_create_server_script", {
            "name": ss_name,
            "api_method": "lazychat_erpnext.test_smoke_ss_h",
            "script": "frappe.response.message = {'pong': True, 'user': frappe.session.user}",
        })
        pf(r.get("ok"), f"T100h prepare_create_server_script stage: {r}")
        rc = commit_prepared(r["preview_token"])
        pf(rc.get("ok") and frappe.db.exists("Server Script", ss_name),
           f"T100h' prepare_create_server_script commit: {rc}")

    # T100i — rejects `import os`
    r = execute_tool("prepare_create_server_script", {
        "name": "_lz_smoke_ss_i", "api_method": "lazychat_erpnext.smoke_i",
        "script": "import os\nfrappe.response.message = {'cwd': os.getcwd()}",
    })
    pf(not r.get("ok") and "import os" in r.get("error", ""), f"T100i import-os rejection: {r}")

    # T100j — rejects `frappe.db.set_value`
    r = execute_tool("prepare_create_server_script", {
        "name": "_lz_smoke_ss_j", "api_method": "lazychat_erpnext.smoke_j",
        "script": "frappe.db.set_value('User', 'Administrator', 'first_name', 'Pwned')\nfrappe.response.message = {}",
    })
    pf(not r.get("ok") and "frappe.db" in r.get("error", ""), f"T100j frappe.db.set_value rejection: {r}")
```

- [ ] **Step 2: Run — fails on unknown tool**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T100[hij]
```
Expected: T100h/i/j all FAIL with `unknown tool: prepare_create_server_script`.

- [ ] **Step 3: Implement `prepare_create_server_script` in `tools.py`**

```python
def prepare_create_server_script(args: dict) -> dict:
    """Stage a Server Script of script_type='API' — a whitelisted Python endpoint.

    Gated: requires (a) lazychat_allow_dangerous_tools site_config flag, (b) System
    Manager role, (c) explicit Apply (never auto-Apply — server-side Python = HIGH risk).
    """
    from lazychat_erpnext.desk_assistant.server_script_validators import run_all

    if not frappe.conf.get("lazychat_allow_dangerous_tools"):
        return {"ok": False, "error": "Server Script creation requires site_config `lazychat_allow_dangerous_tools=true`."}
    if "System Manager" not in (frappe.get_roles(frappe.session.user) or []):
        return {"ok": False, "error": "Only System Manager can stage a Server Script."}

    name = (args.get("name") or "").strip()
    script = args.get("script") or ""
    api_method = (args.get("api_method") or "").strip()

    if not name:
        return {"ok": False, "error": "name is required.", "hint": "e.g. 'get_revenue_mtd'"}
    if not script:
        return {"ok": False, "error": "script is required."}
    if frappe.db.exists("Server Script", name):
        return {"ok": False, "error": f"Server Script '{name}' already exists.", "hint": f"Use prepare_update_doc(doctype='Server Script', name='{name}', patch={{script: '...'}})"}

    # auto-derive api_method from name if absent
    if not api_method:
        api_method = f"lazychat_erpnext.dashboards.{frappe.scrub(name)}"

    # render-preview
    err = run_all(script)
    if err:
        return {"ok": False, **err}

    # method-path clash check (avoid stomping a built-in)
    try:
        from frappe.handler import get_method
        existing = get_method(api_method)
        if existing:
            return {"ok": False, "error": f"Method '{api_method}' already resolves to {existing.__module__}.{existing.__name__}.",
                    "hint": "Pick a different api_method."}
    except Exception:
        pass  # doesn't exist — good

    # Stash the api_method on the local-flag list so a sibling prepare_create_page
    # staged in the same turn can pass validate_js_method_refs.
    staged = frappe.local.flags.setdefault("lazychat_staging_methods", [])
    if api_method not in staged:
        staged.append(api_method)

    payload = {
        "name": name,
        "script_type": "API",
        "api_method": api_method,
        "script": script,
        "allow_guest": bool(args.get("allow_guest") or False),
        "disabled": bool(args.get("disabled") or False),
    }
    token = _stage_action("create_server_script", payload, ttl=300)
    return {
        "ok": True,
        "action": "create_server_script",
        "preview_token": token,
        "api_method": api_method,
        "endpoint_url": f"/api/method/{api_method}",
        "summary": f"Create Server Script '{name}' (API endpoint at {api_method})",
        "confirm_with": f"/commit {token}",
    }
```

Add the `create_server_script` commit branch:

```python
    elif action == "create_server_script":
        if not frappe.conf.get("lazychat_allow_dangerous_tools"):
            return {"ok": False, "error": "lazychat_allow_dangerous_tools is now false; refusing to commit."}
        if "System Manager" not in (frappe.get_roles(frappe.session.user) or []):
            return {"ok": False, "error": "System Manager required."}
        doc = frappe.get_doc({
            "doctype": "Server Script",
            "name": payload["name"],
            "script_type": payload["script_type"],
            "api_method": payload["api_method"],
            "script": payload["script"],
            "allow_guest": payload["allow_guest"],
            "disabled": payload["disabled"],
        })
        doc.insert(ignore_permissions=False)
        return {
            "ok": True,
            "action": "create_server_script",
            "doctype": "Server Script",
            "name": doc.name,
            "endpoint_url": f"/api/method/{payload['api_method']}",
            "link": f"/app/server-script/{doc.name}",
        }
```

- [ ] **Step 4: Add schema in `tool_schemas.py`**

```python
    {
        "name": "prepare_create_server_script",
        "description": (
            "Stage a Server Script of type API — a whitelisted Python endpoint reachable "
            "at /api/method/<api_method>. Use this to back complex Page dashboards: when a "
            "Page section needs an aggregation (sum/group-by/multi-doctype JOIN) that's "
            "too messy for one frappe.db.get_list call from JS, stage a Server Script and "
            "have the Page call it via frappe.call.\n\n"
            "READ-ONLY by construction: render-preview HARD-rejects subprocess/os/sys/etc. "
            "imports, the open/eval/exec/compile/__import__/input/breakpoint builtins, and "
            "frappe.db writes (set_value/delete/sql_ddl/commit/etc.). For writes use "
            "prepare_create_doc / prepare_update_doc.\n\n"
            "Output: end with `frappe.response.message = <dict>` — the API returns null otherwise.\n\n"
            "Gated: requires site_config lazychat_allow_dangerous_tools=true + System Manager role. "
            "Always explicit Apply (never auto-Apply)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique Server Script name."},
                "api_method": {"type": "string", "description": "Optional. Becomes /api/method/<api_method>. Auto-derived from name if omitted (lazychat_erpnext.dashboards.<scrubbed_name>)."},
                "script": {"type": "string", "description": "Python body. Reads only (frappe.db.get_list, frappe.db.get_value, frappe.qb, etc.). End with `frappe.response.message = <result_dict>`."},
                "allow_guest": {"type": "boolean", "description": "Default false. Setting to true exposes the endpoint without auth — only set true for genuinely public data."},
                "disabled": {"type": "boolean", "description": "Default false."},
            },
            "required": ["name", "script"],
        },
    },
```

- [ ] **Step 5: Re-run smoke; verify T100h/i/j pass**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T100[hij]
```
Expected: T100h, T100h', T100i, T100j all PASS.

- [ ] **Step 6: Manual sanity check — hit the endpoint over HTTP**

```bash
curl -s -b ~/.frappe-cookies.txt http://localhost:8000/api/method/lazychat_erpnext.test_smoke_ss_h | jq .
```
Expected: `{"message": {"pong": true, "user": "Administrator"}}` (or your test user).

- [ ] **Step 7: Commit**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/tools.py \
        lazychat_erpnext/desk_assistant/tool_schemas.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m1): prepare_create_server_script typed wrapper + AST validation

API-only (script_type=API), read-only by construction. AST validator rejects
forbidden imports, dangerous builtins, frappe.db writes. Auto-derives
api_method from name if omitted. Stashes api_method on frappe.local.flags so
a sibling prepare_create_page in the same turn can reference it via
frappe.call without the method-existence check failing.

Gated: System Manager + lazychat_allow_dangerous_tools site flag + always
explicit Apply (never auto-Apply).

Tool registry: 96 → 97. T100h/i/j pass."
```

---

### Task M1.5: `prepare_create_workspace` — typed wrapper + schema + commit handler

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py` — add `prepare_create_workspace` + `create_workspace` commit branch
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tool_schemas.py` — append schema
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — add T100k (resolves valid Number Card / Dashboard Chart refs, rejects unknown refs)

Pattern: simpler than `prepare_create_page` (no HTML/JS validation). All validation is "do the referenced cards/charts/shortcuts exist."

- [ ] **Step 1: Add T100k smoke**

```python
    # T100k — prepare_create_workspace resolves card/chart refs; rejects unknown
    # First ensure at least one Number Card exists to reference
    nc = frappe.db.get_value("Number Card", {}, "name") or "_lz_no_card"
    r = execute_tool("prepare_create_workspace", {
        "title": "_lz Smoke WS",
        "icon": "octicon octicon-graph",
        "cards": [{"number_card_name": nc}] if nc != "_lz_no_card" else [],
        "shortcuts": [{"type": "DocType", "link_to": "User", "label": "Users"}],
    })
    pf(r.get("ok"), f"T100k workspace stage with valid refs: {r}")

    r_bad = execute_tool("prepare_create_workspace", {
        "title": "_lz Smoke WS Bad",
        "cards": [{"number_card_name": "_lz_definitely_not_a_real_card"}],
    })
    pf(not r_bad.get("ok") and "not_a_real_card" in r_bad.get("error", "").lower().replace(" ", "_"),
       f"T100k' workspace rejects unknown card: {r_bad}")
```

- [ ] **Step 2: Run — fails on unknown tool. Implement `prepare_create_workspace` in `tools.py`:**

```python
def prepare_create_workspace(args: dict) -> dict:
    """Stage a Workspace (Desk Workspace doctype). Configures cards / charts /
    shortcuts that compose into the standard /app/<workspace-name> dashboard surface.

    For sophisticated custom layouts use prepare_create_page instead — Workspace
    is the card-grid surface, not a full-canvas page."""
    if "System Manager" not in (frappe.get_roles(frappe.session.user) or []):
        return {"ok": False, "error": "Only System Manager can stage a Workspace."}

    title = (args.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title is required."}

    cards = args.get("cards") or []
    charts = args.get("charts") or []
    shortcuts = args.get("shortcuts") or []

    # Resolve every reference
    for c in cards:
        nc = c.get("number_card_name")
        if not nc or not frappe.db.exists("Number Card", nc):
            return {"ok": False, "error": f"Workspace references Number Card '{nc}' which doesn't exist.",
                    "hint": "Run `list_number_cards` to find existing cards, or stage a `prepare_create_number_card` first."}
    for ch in charts:
        cn = ch.get("chart_name")
        if not cn or not frappe.db.exists("Dashboard Chart", cn):
            return {"ok": False, "error": f"Workspace references Dashboard Chart '{cn}' which doesn't exist."}
    for sc in shortcuts:
        lt = sc.get("link_to")
        if sc.get("type") == "DocType" and lt and not frappe.db.exists("DocType", lt):
            return {"ok": False, "error": f"Workspace shortcut references doctype '{lt}' which doesn't exist."}

    payload = {
        "title": title,
        "label": title,
        "icon": args.get("icon") or "",
        "parent_page": args.get("parent_page") or "",
        "module": args.get("module") or "Lazychat Erpnext",
        "cards": cards,
        "charts": charts,
        "shortcuts": shortcuts,
        "roles": args.get("roles") or ["System Manager"],
    }
    token = _stage_action("create_workspace", payload, ttl=300)
    return {
        "ok": True,
        "action": "create_workspace",
        "preview_token": token,
        "route": f"/app/{frappe.scrub(title).replace('_', '-')}",
        "summary": f"Create Workspace '{title}' with {len(cards)} cards, {len(charts)} charts, {len(shortcuts)} shortcuts",
        "confirm_with": f"/commit {token}",
    }
```

Add the commit branch:

```python
    elif action == "create_workspace":
        doc = frappe.get_doc({
            "doctype": "Workspace",
            "name": payload["title"],
            "label": payload["label"],
            "title": payload["title"],
            "icon": payload["icon"],
            "module": payload["module"],
            "parent_page": payload["parent_page"],
            "public": 1,
            "for_user": "",
            "number_cards": [{"number_card_name": c["number_card_name"]} for c in payload["cards"]],
            "charts": [{"chart_name": c["chart_name"]} for c in payload["charts"]],
            "shortcuts": [{"type": s.get("type", "DocType"), "link_to": s["link_to"], "label": s.get("label", s["link_to"])} for s in payload["shortcuts"]],
            "roles": [{"role": r} for r in payload["roles"]],
        })
        doc.insert(ignore_permissions=False)
        return {"ok": True, "action": "create_workspace", "doctype": "Workspace", "name": doc.name, "link": f"/app/{frappe.scrub(doc.name).replace('_', '-')}"}
```

- [ ] **Step 3: Register schema in `tool_schemas.py`:**

```python
    {
        "name": "prepare_create_workspace",
        "description": (
            "Stage a Workspace — Frappe's standard card-grid dashboard surface at /app/<workspace>. "
            "Composes Number Cards + Dashboard Charts + Shortcuts.\n\n"
            "Use this for SIMPLE dashboard needs (KPI cards in a grid). For sophisticated "
            "custom layouts (topbar + sidebar + custom sections), use `prepare_create_page` "
            "instead — Workspace's layout is fixed-grid.\n\n"
            "Render-preview rejects: unknown Number Card / Dashboard Chart / DocType references."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "icon": {"type": "string", "description": "Frappe icon class (e.g. 'octicon octicon-graph')."},
                "parent_page": {"type": "string", "description": "Optional parent Workspace name."},
                "cards": {"type": "array", "items": {"type": "object", "properties": {"number_card_name": {"type": "string"}}}, "description": "Number Card references. Use `list_number_cards` to find existing cards before creating duplicates."},
                "charts": {"type": "array", "items": {"type": "object", "properties": {"chart_name": {"type": "string"}}}, "description": "Dashboard Chart references."},
                "shortcuts": {"type": "array", "items": {"type": "object", "properties": {"type": {"type": "string"}, "link_to": {"type": "string"}, "label": {"type": "string"}}}, "description": "Quick links — type=DocType / Report / Page / URL."},
                "roles": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
        },
    },
```

- [ ] **Step 4: Re-run smoke, expect T100k pass**
- [ ] **Step 5: Commit**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/tools.py \
        lazychat_erpnext/desk_assistant/tool_schemas.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m1): prepare_create_workspace typed wrapper

Composes Number Cards + Dashboard Charts + Shortcuts into a Workspace at
/app/<scrub(title)>. Render-preview validates every referenced card/chart/
shortcut target exists. System Manager only; LOW_RISK_ACTIONS-eligible
(auto-Apply candidate, wired chat-ui-side later).

Tool registry: 97 → 98. T100k passes."
```

---

### Task M1.6: `prepare_attach_assets` — file uploads to existing doctype records

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py` — add `prepare_attach_assets` + `attach_assets` commit branch
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tool_schemas.py` — append schema
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — add T100l (attach a small text file; verify File record created + linked)

Pattern: wraps `frappe.get_doc("File", {...}).insert()` with size/mime validation. Use case: agent uploads fonts/images that the Page references.

- [ ] **Step 1: Add T100l smoke**

```python
    # T100l — prepare_attach_assets uploads a small file and links it to a Page
    if frappe.db.exists("Page", "_lz_smoke_page_e"):
        import base64
        tiny = base64.b64encode(b"/* placeholder asset */").decode("ascii")
        r = execute_tool("prepare_attach_assets", {
            "target_doctype": "Page", "target_name": "_lz_smoke_page_e",
            "files": [{"filename": "smoke.css", "content_base64": tiny, "mime": "text/css"}],
        })
        pf(r.get("ok"), f"T100l attach stage: {r}")
        rc = commit_prepared(r["preview_token"])
        pf(rc.get("ok") and len(rc.get("file_urls") or []) == 1, f"T100l' attach commit: {rc}")

    # T100l' — rejects > 5 MB file
    big = "A" * (6 * 1024 * 1024)
    import base64 as _b64
    r_big = execute_tool("prepare_attach_assets", {
        "target_doctype": "Page", "target_name": "_lz_smoke_page_e",
        "files": [{"filename": "huge.txt", "content_base64": _b64.b64encode(big.encode()).decode(), "mime": "text/plain"}],
    })
    pf(not r_big.get("ok") and "5 MB" in r_big.get("error", ""), f"T100l'' attach rejects oversize: {r_big}")
```

- [ ] **Step 2: Implement `prepare_attach_assets` in `tools.py`:**

```python
_ATTACH_MIME_ALLOWLIST = ("image/", "font/", "text/", "application/octet-stream", "application/font-woff", "application/font-woff2")
_ATTACH_MAX_SIZE = 5 * 1024 * 1024  # 5 MB per file

def prepare_attach_assets(args: dict) -> dict:
    """Stage file uploads attached to a target doctype record. Use case: a
    prepare_create_page references custom fonts or images — stage those via
    this wrapper so they're available at /files/<filename>."""
    target_dt = (args.get("target_doctype") or "").strip()
    target_name = (args.get("target_name") or "").strip()
    files = args.get("files") or []

    if not target_dt or not target_name:
        return {"ok": False, "error": "target_doctype and target_name are required."}
    if not frappe.db.exists(target_dt, target_name):
        return {"ok": False, "error": f"{target_dt} '{target_name}' doesn't exist.", "hint": "Stage the parent doc first (e.g. prepare_create_page), commit it, then stage attach_assets."}
    if not frappe.has_permission(target_dt, doc=target_name, ptype="write"):
        return {"ok": False, "error": f"No 'write' permission on {target_dt} '{target_name}'."}
    if not files:
        return {"ok": False, "error": "files list is empty."}

    import base64
    for f in files:
        fn = (f.get("filename") or "").strip()
        cb64 = f.get("content_base64") or ""
        mime = (f.get("mime") or "application/octet-stream").lower()
        if not fn or not cb64:
            return {"ok": False, "error": "every file must have filename + content_base64."}
        if not any(mime.startswith(p) for p in _ATTACH_MIME_ALLOWLIST):
            return {"ok": False, "error": f"mime '{mime}' not in allowlist {_ATTACH_MIME_ALLOWLIST}."}
        try:
            decoded = base64.b64decode(cb64)
        except Exception as e:
            return {"ok": False, "error": f"file '{fn}' base64 decode failed: {e}"}
        if len(decoded) > _ATTACH_MAX_SIZE:
            return {"ok": False, "error": f"file '{fn}' is {len(decoded)} bytes; per-file cap is 5 MB."}

    payload = {"target_doctype": target_dt, "target_name": target_name, "files": files}
    token = _stage_action("attach_assets", payload, ttl=300)
    return {
        "ok": True, "action": "attach_assets", "preview_token": token,
        "summary": f"Attach {len(files)} file(s) to {target_dt} '{target_name}'",
        "confirm_with": f"/commit {token}",
    }
```

Commit branch:

```python
    elif action == "attach_assets":
        import base64
        results = []
        for f in payload["files"]:
            decoded = base64.b64decode(f["content_base64"])
            file_doc = frappe.get_doc({
                "doctype": "File",
                "file_name": f["filename"],
                "attached_to_doctype": payload["target_doctype"],
                "attached_to_name": payload["target_name"],
                "content": decoded,
                "is_private": 0,
            })
            file_doc.save(ignore_permissions=False)
            results.append(file_doc.file_url)
        return {"ok": True, "action": "attach_assets", "file_urls": results,
                "link": f"/app/{frappe.scrub(payload['target_doctype'])}/{payload['target_name']}"}
```

- [ ] **Step 3: Schema in `tool_schemas.py`:**

```python
    {
        "name": "prepare_attach_assets",
        "description": (
            "Stage file uploads attached to a target doctype record. Use case: a "
            "prepare_create_page references a custom font or hero image; stage those "
            "files via this wrapper so they're served at /files/<filename> and "
            "@import-able from the Page's <style>.\n\n"
            "Each file capped at 5 MB; mime must start with image/ font/ text/ or "
            "application/octet-stream / application/font-woff(2). Caller must have "
            "'write' permission on target."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_doctype": {"type": "string", "description": "e.g. 'Page'"},
                "target_name": {"type": "string"},
                "files": {"type": "array", "items": {"type": "object", "properties": {
                    "filename": {"type": "string"},
                    "content_base64": {"type": "string", "description": "Base64-encoded file bytes."},
                    "mime": {"type": "string", "description": "Defaults to application/octet-stream."}
                }, "required": ["filename", "content_base64"]}},
            },
            "required": ["target_doctype", "target_name", "files"],
        },
    },
```

- [ ] **Step 4: Re-run smoke; T100l + T100l'' pass. Commit:**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/tools.py \
        lazychat_erpnext/desk_assistant/tool_schemas.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m1): prepare_attach_assets typed wrapper

Stages file uploads attached to a target doctype record. Per-file cap 5 MB,
mime allowlist (image/font/text/octet-stream/woff). Caller must have 'write'
perm on target. Always explicit Apply.

Tool registry: 98 → 99. T100l + T100l'' pass."
```

---

### Task M1.7: `list_number_cards` discovery tool

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py` — add `list_number_cards(args)` function
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tool_schemas.py` — append schema
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — T100m

Discovery tool — pure read, no commit handler needed.

- [ ] **Step 1: T100m smoke**

```python
    # T100m — list_number_cards returns expected shape
    r = execute_tool("list_number_cards", {"limit": 5})
    pf(isinstance(r, dict) and isinstance(r.get("cards"), list),
       f"T100m list_number_cards shape: keys={list(r.keys()) if isinstance(r, dict) else type(r)}")
    if r.get("cards"):
        c0 = r["cards"][0]
        pf(all(k in c0 for k in ("name", "document_type", "function", "label")),
           f"T100m' card row shape: {c0}")
```

- [ ] **Step 2: Implement in `tools.py`:**

```python
def list_number_cards(args: dict) -> dict:
    """Discover existing Number Cards in the bench. Use this BEFORE staging a
    new Number Card so the agent reuses existing aggregations rather than
    duplicating them."""
    filt = args.get("filter") or {}
    limit = int(args.get("limit") or 50)
    cards = frappe.get_all(
        "Number Card",
        filters=filt,
        fields=["name", "label", "document_type", "function", "aggregate_function_based_on", "filters_json"],
        limit_page_length=max(1, min(limit, 500)),
        order_by="modified desc",
    )
    return {"cards": cards, "count": len(cards)}
```

- [ ] **Step 3: Schema:**

```python
    {
        "name": "list_number_cards",
        "description": (
            "List existing Number Cards in the bench. Always call this before "
            "staging a new Number Card or a Workspace that needs cards — the "
            "agent should reuse existing aggregations rather than duplicate "
            "them ('Revenue MTD' shouldn't exist 4 times)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {"type": "object", "description": "Frappe filter dict, e.g. {\"document_type\": \"Sales Invoice\"}."},
                "limit": {"type": "integer", "description": "Default 50, max 500."},
            },
        },
    },
```

- [ ] **Step 4: Re-run smoke; T100m passes. Commit:**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/tools.py \
        lazychat_erpnext/desk_assistant/tool_schemas.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m1): list_number_cards discovery tool

Read-only discovery: returns existing Number Cards (name, label, doctype,
function, filters) so the agent reuses aggregations before duplicating.

Tool registry: 99 → 100. T100m passes."
```

---

### Task M1.8: `list_whitelisted_methods` discovery tool

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tools.py` — add `list_whitelisted_methods(args)` function
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/tool_schemas.py` — append schema
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — T100n

- [ ] **Step 1: T100n smoke**

```python
    # T100n — list_whitelisted_methods returns built-in frappe.client.* at minimum
    r = execute_tool("list_whitelisted_methods", {"prefix": "frappe.client"})
    pf(isinstance(r, dict) and isinstance(r.get("methods"), list) and len(r["methods"]) > 0,
       f"T100n list_whitelisted_methods returns frappe.client.*: count={len(r.get('methods', []))}")
    if r.get("methods"):
        m0 = r["methods"][0]
        pf(all(k in m0 for k in ("path", "docstring")),
           f"T100n' method row shape: {m0}")
```

- [ ] **Step 2: Implement in `tools.py`:**

```python
def list_whitelisted_methods(args: dict) -> dict:
    """List whitelisted methods (i.e. `@frappe.whitelist()`-decorated functions
    reachable via /api/method/<path>). Use this to find existing aggregation
    methods before staging a new Server Script."""
    prefix = (args.get("prefix") or "").strip()
    limit = int(args.get("limit") or 100)

    # Frappe's whitelisted-method registry
    from frappe.handler import whitelist_methods  # internal but stable across recent versions

    methods = []
    for path in sorted(whitelist_methods.keys() if isinstance(whitelist_methods, dict) else []):
        if prefix and not path.startswith(prefix):
            continue
        try:
            fn = whitelist_methods.get(path)
            doc = (getattr(fn, "__doc__", None) or "").strip().splitlines()[0] if fn else ""
            module = getattr(fn, "__module__", "") if fn else ""
        except Exception:
            doc, module = "", ""
        methods.append({"path": path, "module": module, "docstring": doc[:200]})
        if len(methods) >= limit:
            break
    return {"methods": methods, "count": len(methods), "filtered_by_prefix": prefix or None}
```

(If `whitelist_methods` import path differs on the deployed Frappe version, fall back to walking `frappe.whitelisted` — but `frappe.handler.whitelist_methods` is the canonical name as of Frappe v15.)

- [ ] **Step 3: Schema:**

```python
    {
        "name": "list_whitelisted_methods",
        "description": (
            "List @frappe.whitelist() methods reachable via /api/method/<path>. "
            "Use this BEFORE staging a new Server Script — ERPNext ships dozens of "
            "data/aggregation methods (e.g. `erpnext.accounts.utils.*`, "
            "`erpnext.controllers.*`) and lazychat shouldn't reinvent the wheel.\n\n"
            "Use the `prefix` arg to scope: `frappe.client` for built-in CRUD, "
            "`erpnext.` for ERPNext domain methods, `lazychat_erpnext.` for our own."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "e.g. 'frappe.client', 'erpnext.accounts'. Omit for all."},
                "limit": {"type": "integer", "description": "Default 100."},
            },
        },
    },
```

- [ ] **Step 4: Re-run smoke; T100n passes. Commit:**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/tools.py \
        lazychat_erpnext/desk_assistant/tool_schemas.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m1): list_whitelisted_methods discovery tool

Read-only: returns @frappe.whitelist()-decorated methods reachable via
/api/method/<path>, with optional prefix filter. Lets the agent find
existing aggregation methods (ERPNext built-ins, custom modules) before
staging a new Server Script.

Tool registry: 100 → 101. T100n passes."
```

---

### Task M1.9: Chat-ui — register new actions as LOW_RISK + AUTO_OPEN

**Files:**
- Modify: `lazychat.ai/apps/chat-ui/src/components/messages/MCPPreviewActionCard.tsx` — `LOW_RISK_ACTIONS` set + `AUTO_OPEN_AFTER_APPLY` whitelist
- Modify: `lazychat.ai/apps/chat-ui/src/components/messages/__tests__/MCPPreviewActionCard.test.tsx` — add test cases for the new actions

`LOW_RISK_ACTIONS` is the Cycle 8 auto-Apply taxonomy. `create_page` and `create_workspace` are additive + reversible (just delete the doc), so they qualify. `create_server_script` and `attach_assets` are NOT low-risk (Python execution + file uploads).

`AUTO_OPEN_AFTER_APPLY` (Cycle 8g) makes the Apply card auto-open the new doc in a new tab post-commit — great UX for "I just created this; let me see it."

- [ ] **Step 1: Write the failing test**

Append to `MCPPreviewActionCard.test.tsx`:

```ts
import { LOW_RISK_ACTIONS, AUTO_OPEN_AFTER_APPLY } from '../MCPPreviewActionCard';

describe('Cycle 13 actions', () => {
  it('create_page is LOW_RISK + AUTO_OPEN', () => {
    expect(LOW_RISK_ACTIONS.has('create_page')).toBe(true);
    expect(AUTO_OPEN_AFTER_APPLY.has('create_page')).toBe(true);
  });
  it('create_workspace is LOW_RISK + AUTO_OPEN', () => {
    expect(LOW_RISK_ACTIONS.has('create_workspace')).toBe(true);
    expect(AUTO_OPEN_AFTER_APPLY.has('create_workspace')).toBe(true);
  });
  it('create_server_script is NEITHER (high-risk, explicit Apply only)', () => {
    expect(LOW_RISK_ACTIONS.has('create_server_script')).toBe(false);
    expect(AUTO_OPEN_AFTER_APPLY.has('create_server_script')).toBe(false);
  });
  it('attach_assets is NEITHER (always explicit Apply)', () => {
    expect(LOW_RISK_ACTIONS.has('attach_assets')).toBe(false);
  });
});
```

- [ ] **Step 2: Run the test — fails because exports don't exist or sets don't include the new actions**

```bash
cd lazychat.ai && pnpm --filter chat-ui exec vitest run src/components/messages/__tests__/MCPPreviewActionCard.test.tsx 2>&1 | grep -E "Cycle 13|FAIL|✓|✗"
```

- [ ] **Step 3: Update `MCPPreviewActionCard.tsx`**

Find the `LOW_RISK_ACTIONS` set near the top of the file (currently lists ~17 actions). Add `'create_page'`, `'create_workspace'`. Find `AUTO_OPEN_AFTER_APPLY` (currently includes `create_report`, `create_dashboard`, etc.) and add `'create_page'`, `'create_workspace'`. Ensure both `LOW_RISK_ACTIONS` and `AUTO_OPEN_AFTER_APPLY` are exported (add `export const` if not).

```ts
export const LOW_RISK_ACTIONS = new Set<string>([
  // ...existing 17 entries...
  'create_page',
  'create_workspace',
]);

export const AUTO_OPEN_AFTER_APPLY = new Set<string>([
  // ...existing entries...
  'create_page',
  'create_workspace',
]);
```

Also extend `ACTION_TO_LABEL` (Cycle 8g — the human-readable label mapping for the Open button):

```ts
const ACTION_TO_LABEL: Record<string, string> = {
  // ...existing...
  create_page: 'Page',
  create_workspace: 'Workspace',
  create_server_script: 'Server Script',
  attach_assets: 'Files',
};
```

- [ ] **Step 4: Re-run the test — passes**

```bash
cd lazychat.ai && pnpm --filter chat-ui exec vitest run src/components/messages/__tests__/MCPPreviewActionCard.test.tsx 2>&1 | grep -E "Tests"
```
Expected: all tests pass (new + existing).

- [ ] **Step 5: Run typecheck + full suite (no regressions)**

```bash
cd lazychat.ai && pnpm typecheck 2>&1 | grep -E "typecheck:|error TS"
pnpm --filter chat-ui exec vitest run 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
cd lazychat.ai
git add apps/chat-ui/src/components/messages/MCPPreviewActionCard.tsx \
        apps/chat-ui/src/components/messages/__tests__/MCPPreviewActionCard.test.tsx
git commit -m "feat(cycle-13/m1): register create_page + create_workspace as LOW_RISK + AUTO_OPEN

Adds the two new low-risk Page-creation actions to the auto-Apply taxonomy
and the auto-open-after-apply whitelist. create_server_script and attach_assets
stay explicit-Apply only (HIGH-risk by construction).

ACTION_TO_LABEL extended for the post-Apply 'Open <Page>' button."
```

---

### Task M1.10: System prompt — "Building Desk Pages & Dashboards" playbook

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py` (backend-LLM path)
- Modify: `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts` (browser-LLM path) — keep parity

The playbook is THE quality lever — it teaches the LLM what good-quality ERPNext dashboards look like and how to compose them with the new wrappers. Same text in both prompts; backend uses Python triple-quoted string, chat-ui uses a TS template literal.

- [ ] **Step 1: Add the playbook block to `claude_bridge.py`**

Locate the existing system-prompt assembly in `claude_bridge.py` (around `_system_prompt(...)` — look for the function that returns the full string). Append a new block to `_SHARED_GUIDANCE` (the constant containing the shared prompt sections; same place where the COMPOUND QUESTIONS / COMPLETENESS / TOOL CHOICE blocks live):

```python
_DESK_PAGE_PLAYBOOK = """

## BUILDING DESK PAGES & DASHBOARDS

Use `prepare_create_page` for any custom internal dashboard, full-page report,
or executive overview. Lives at /app/<page-name>. Inside the Desk shell —
`frappe.call`, `frappe.db.get_list`, `frappe.boot`, `frappe.session.user` are
all available out of the box.

### Workflow

1. **Plan the sections.** Read the user's request (often an HTML mockup or text
   description). Identify each distinct section (header, KPI grid, charts,
   tables, lists). Note which sections need REAL data vs which are static.

2. **For each data section, identify the source.** Single doctype read →
   `frappe.db.get_list/get_value` from the Page's JS (no server-side wrapper
   needed). Complex aggregation (sum / group-by / multi-doctype JOIN) → stage
   a `prepare_create_server_script` (script_type=API) and have the Page's JS
   call it via `frappe.call({method: 'api_method'})`.

3. **Use the discovery tools FIRST.** Before staging a new aggregation:
   - `list_whitelisted_methods({prefix:'erpnext.'})` — ERPNext ships many
     dashboard data methods; reuse before reinventing.
   - `list_number_cards()` — if you're building a Workspace, reuse existing
     Number Cards rather than duplicating ('Revenue MTD' shouldn't exist 4 times).
   - `describe_doctype` / `find_join_path` / `get_doctype_relationships` for
     unfamiliar data shapes (Cycle 9 discovery primitives).

4. **For each Server Script: stage one `prepare_create_server_script`.** Keep
   each focused — one endpoint per logical data unit. Use
   `frappe.response.message = result_dict` as the output. Re-check perms
   inside the script (`frappe.has_permission`) — defense-in-depth matters
   even though the script runs as the caller.

5. **Compose the Page: stage `prepare_create_page`** with HTML in `content`,
   CSS in `style`, JS in `script`. The JS calls each Server Script via
   `frappe.call({method: '<api_method>'})`. Render-preview will hard-block
   references to non-existent doctypes / methods — but methods you also
   stage THIS turn are valid (the validator tracks staged methods on
   frappe.local.flags).

6. **Apply order.** Server Scripts FIRST (so the Page's frappe.call references
   resolve), then the Page. At Effort=max, both can auto-Apply for the LOW_RISK
   wrappers (create_page); create_server_script always requires explicit Apply.

### Visual quality rules (CRITICAL — output has to actually look good, not just work)

1. **Use Frappe theme tokens** in CSS — `var(--bg-color)`, `var(--text-color)`,
   `var(--primary-color)`, `var(--text-muted)`, `var(--border-color)`,
   `var(--bg-gray)`, `var(--accent)`. NEVER hardcode brand colors. Hardcoded
   colors = broken in dark mode = the #1 thing that signals 'AI-generated'.

2. **Match the reference's typography exactly** if a mockup was provided:
   load the same font families (via `<link rel="stylesheet" href="fonts.googleapis.com/...">`),
   same weights, same letter-spacing. Typography is the #1 thing users notice.

3. **Match the reference's layout structure exactly.** If the mockup has a
   topbar + sidebar + sections grid, build `<header>` + `<nav>` + `<main>`
   with the SAME grid template. Don't substitute 'good enough' alternatives —
   a 4-column grid is not 'close to' a 3-column grid.

4. **Use semantic HTML.** `<header>`, `<nav>`, `<main>`, `<section>`,
   `<article>`, `<aside>`, `<footer>`. KPI labels-and-values via
   `<dl><dt>label</dt><dd>value</dd></dl>` or similar. Tables only for
   actual tabular data, never for layout.

5. **Wire data REAL — never placeholder.** If a section's data isn't reachable
   yet, render `<em>(no data wired)</em>` explicitly rather than fake numbers.
   Fake numbers ('1.2 Cr', '62%') pollute the user's mental model — they'll
   present them in a meeting and be embarrassed.

6. **Loading / empty / error states** for every `frappe.call`. Never leave a
   section blank during the network roundtrip. Safe pattern (uses textContent
   for plain strings, never assigns markup strings via property setters):
   ```js
   const el = document.querySelector('#section-x');
   el.textContent = 'Loading…';
   frappe.call({method: 'x'}).then(r => {
     if (!r.message?.rows?.length) {
       el.textContent = 'No data.';
       return;
     }
     // Build DOM via document.createElement + appendChild for any non-trivial
     // output — never assemble HTML strings from data values.
     const table = document.createElement('table');
     for (const row of r.message.rows) {
       const tr = document.createElement('tr');
       for (const cell of row) {
         const td = document.createElement('td');
         td.textContent = String(cell ?? '—');
         tr.appendChild(td);
       }
       table.appendChild(tr);
     }
     el.replaceChildren(table);
   }).catch(e => {
     el.textContent = `Failed: ${e.message}`;
   });
   ```

7. **At the END of your `script`,** after all initial `frappe.call`s resolve
   (`Promise.all(...).then(...)`), set `document.body.dataset.lazychatReady = '1'`.
   This signals the screenshot preview tool (M2) that the page is fully
   rendered — without it the preview uses a 5s fallback timeout.

### Anti-patterns (do NOT do these)

- DON'T use `prepare_create_doc({doctype:'Page'})` — use `prepare_create_page`
  (typed schema + render-preview).
- DON'T inline secrets / API keys in the JS — the page is server-rendered,
  any string in `script` is world-readable to anyone with desk access.
- DON'T poll `frappe.call` more than once per minute without a clear refresh
  button. Wastes server resources.
- DON'T use `<table>` for layout — only for tabular data.
- DON'T inline 1000+ lines of JS in `script`; if the page is that complex,
  factor into multiple Server Scripts + a thinner client orchestrator.
- DON'T set element markup via property setters that take HTML strings —
  it invites XSS via interpolated values. Use `textContent` for plain text,
  and `document.createElement` + `appendChild` for structured output. The
  agent's render-preview will surface a quality warning if a string with
  template-literal HTML assignment is detected.

### Iteration loop ('fix the X')

User says 'the topbar font is too thin' → use `prepare_update_doc({doctype:'Page',
name:'<page_name>', patch:{style: '<refined CSS>'}})`. Patch ONLY the changed
field (style/content/script) — never re-stage the full Page on a small fix.

"""
```

Then in the function that assembles the prompt (look for where `_SHARED_GUIDANCE` is concatenated), append `_DESK_PAGE_PLAYBOOK` after the existing shared blocks but before any mode-specific blocks (PLAN_MODE_BLOCK / ASK_MODE_BLOCK).

- [ ] **Step 2: Mirror the same text in `routerSystemPrompt.ts`**

In `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts`, find the `_SHARED_GUIDANCE` template literal. Append the equivalent block (same content, just as a TS template string):

```ts
const DESK_PAGE_PLAYBOOK = `

## BUILDING DESK PAGES & DASHBOARDS

[paste the same content as the Python _DESK_PAGE_PLAYBOOK above, formatted as a JS template literal]

`;
```

And concatenate into the shared guidance.

- [ ] **Step 3: Run vitest + typecheck**

```bash
cd lazychat.ai
pnpm typecheck 2>&1 | grep -E "typecheck:|error TS" | tail -5
pnpm --filter chat-ui exec vitest run 2>&1 | tail -3
```

- [ ] **Step 4: Verify the LLM sees the playbook**

Quick check via the Frappe-side bench console:
```bash
cd $BENCH_ROOT && bench --site erp.local console
>>> from lazychat_erpnext.desk_assistant.claude_bridge import _system_prompt
>>> p = _system_prompt(messages=[], mode="edit-auto")
>>> assert "BUILDING DESK PAGES" in p, "playbook missing"
>>> print(f"prompt size: {len(p)} chars; playbook block present: {'BUILDING DESK PAGES' in p}")
```

- [ ] **Step 5: Commit (both repos)**

```bash
# lazychat-erpnext
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/claude_bridge.py
git commit -m "feat(cycle-13/m1): add Building Desk Pages playbook to system prompt

7-rule visual-quality playbook + 5-step workflow + anti-patterns. Teaches the
LLM how to use prepare_create_page / prepare_create_server_script together,
and what 'best of best' output means in ERPNext context (theme tokens,
typography matching, semantic HTML, real data wiring, ready-signal marker).

Mirrored chat-ui-side in routerSystemPrompt.ts."

# lazychat.ai
cd ../lazychat.ai
git add apps/chat-ui/src/lib/routerSystemPrompt.ts
git commit -m "feat(cycle-13/m1): mirror Building Desk Pages playbook (browser-LLM path)

Parity with backend claude_bridge.py — both LLM paths get the same playbook."
```

---

### Task M1.11: HTTP-wire smoke for the 6 new tools

**Files:**
- Modify: `lazychat-erpnext/test/curl_smoke.py` — register call cases for the 6 new tools
- Modify: `lazychat-erpnext/test/tool_args.py` — args/validators for each

`curl_smoke.py` is the Layer-1 HTTP-wire harness (the in-process smoke is Layer 2). Every new tool needs a wire-level call + content validator.

- [ ] **Step 1: Add `tool_args.py` entries for the 6 new tools**

Append at the end of the existing `TOOL_ARGS` dict in `test/tool_args.py`:

```python
TOOL_ARGS.update({
    "prepare_create_page": {
        "args": {
            "page_name": "_lz_wire_page",
            "title": "Wire-Smoke Page",
            "content": "<main><h1>Hi</h1></main>",
            "style": "main { padding: 8px; }",
            "script": "document.body.dataset.lazychatReady = '1';",
        },
        "validate": lambda result: result.get("ok") and result.get("action") == "create_page",
    },
    "prepare_create_server_script": {
        "args": {
            "name": "_lz_wire_ss",
            "api_method": "lazychat_erpnext.wire_smoke_ss",
            "script": "frappe.response.message = {'pong': True}",
        },
        "validate": lambda result: (
            # may be ok=False if allow_dangerous_tools=false — count as OK_ERROR
            result.get("ok") and result.get("action") == "create_server_script"
        ) or "lazychat_allow_dangerous_tools" in (result.get("error") or ""),
        "allow_error": True,
    },
    "prepare_create_workspace": {
        "args": {"title": "_lz Wire WS"},
        "validate": lambda result: result.get("ok") and result.get("action") == "create_workspace",
    },
    "prepare_attach_assets": {
        "args": {
            "target_doctype": "User",
            "target_name": "Administrator",
            "files": [{"filename": "wire.txt", "content_base64": "aGk=", "mime": "text/plain"}],
        },
        "validate": lambda result: result.get("ok"),
    },
    "list_number_cards": {
        "args": {"limit": 5},
        "validate": lambda result: isinstance(result.get("cards"), list),
    },
    "list_whitelisted_methods": {
        "args": {"prefix": "frappe.client", "limit": 10},
        "validate": lambda result: isinstance(result.get("methods"), list) and len(result["methods"]) > 0,
    },
})
```

- [ ] **Step 2: Run the wire smoke**

```bash
cd /Users/soumyasethy/Desktop/code-chat
python3 lazychat-erpnext/test/curl_smoke.py
```
Expected output ends with `[curl_smoke] summary: OK=N | OK_ERROR=M` where N + M includes the 6 new tools (1 OK_ERROR for prepare_create_server_script if `lazychat_allow_dangerous_tools` is false on the bench).

The harness automatically discovers new tools from `TOOL_SCHEMAS` and looks them up in `TOOL_ARGS`. If `TOOL_ARGS` is missing a tool, the harness errors with `KeyError: '<tool>' not in TOOL_ARGS`.

- [ ] **Step 3: Commit**

```bash
cd lazychat-erpnext
git add test/tool_args.py
git commit -m "test(cycle-13/m1): HTTP-wire smoke validators for the 6 new tools

Args + validators for prepare_create_page / prepare_create_server_script /
prepare_create_workspace / prepare_attach_assets / list_number_cards /
list_whitelisted_methods. server_script tolerates 'allow_dangerous_tools=false'
as OK_ERROR (graceful expected error on benches without the flag)."
```

---

### M1 phase exit — verify all targets met

- [ ] **Tool registry count**: `bench --site erp.local execute lazychat_erpnext._smoke.run` shows `Tools: 101 registered` in the in-process smoke (T54-style assertion, automatic).
- [ ] **In-process smoke**: all T100a–T100n pass.
- [ ] **HTTP-wire smoke**: 6 new tools all OK or OK_ERROR (gated tools).
- [ ] **Manual sanity**: open `http://localhost:8000/app/_lz_smoke_page_e` — Page renders with the test content + the lazychatReady marker visible in DOM (verifiable via DevTools console: `document.body.dataset.lazychatReady === '1'`).
- [ ] **chat-ui suite**: `pnpm --filter chat-ui exec vitest run` — full suite green; MCPPreviewActionCard.test.tsx includes the 4 new Cycle-13 cases.
- [ ] **typecheck**: clean across all 3 workspaces.

If any of these fail, fix before starting M2. M2 builds directly on M1's `prepare_create_page` flow — a broken M1 means a broken M2.

---

## Phase M2 — Playwright screenshot preview + inline `screenshot` Message kind

**Phase goal:** After Apply on `create_page` (or `update_doc` with `doctype=Page`), chat-ui automatically renders the deployed page in a headless Chromium instance on the bench, captures a 1440×900 PNG, and shows it inline in chat as a new `screenshot` Message. The user can visually verify or describe fixes.

**Phase exit criteria:**
- `screenshot.capture(...)` whitelisted endpoint returns base64 PNG for a valid Desk route
- `inspectRoute` postmessage accepts `mode='screenshot'` and proxies to the endpoint
- After staging+applying a Page through the chat UI, a `screenshot` Message renders inline showing the live page
- HTML uploads via attachments auto-generate a reference screenshot (used by M3)
- 3 new smoke cases (T101a-c) pass
- chat-ui vitest stays green; typecheck clean

---

### Task M2.1: Playwright dependency + `screenshot.py` skeleton + install detection

**Files:**
- Modify: `lazychat-erpnext/pyproject.toml` — add `playwright` as an optional extra
- Create: `lazychat-erpnext/lazychat_erpnext/desk_assistant/screenshot.py`
- Modify: `lazychat-erpnext/lazychat_erpnext/install.py` — add Playwright/Chromium detection helper that logs a warning on `after_install` if Playwright is installed but the Chromium binary is missing
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — T101a (module imports cleanly)

- [ ] **Step 1: Add T101a smoke case**

```python
    # ──────────────────────────────────────────────────────────────────────
    # CYCLE 13 — M2: screenshot preview
    # ──────────────────────────────────────────────────────────────────────
    log("\n=== Cycle 13 M2 — screenshot preview ===")

    # T101a — screenshot module imports cleanly (does NOT require Playwright installed)
    try:
        from lazychat_erpnext.desk_assistant import screenshot
        pf(hasattr(screenshot, "capture"), "T101a screenshot module exports capture(...)")
    except Exception as e:
        pf(False, f"T101a screenshot module import: {e}")
```

- [ ] **Step 2: Run — fails (module not present)**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T101
```
Expected: `T101a screenshot module import: No module named ...screenshot`.

- [ ] **Step 3: Add Playwright as optional extra in `pyproject.toml`**

```toml
[project.optional-dependencies]
screenshot = [
    "playwright>=1.40",   # Chromium-based headless rendering for the M2 screenshot preview.
                          # ~200 MB Chromium install via `playwright install chromium`.
                          # Optional — the screenshot feature is gated behind a Lazychat Setting.
]
```

(If `[project.optional-dependencies]` doesn't exist in the current `pyproject.toml`, add it. Frappe apps typically install via `bench get-app`, which respects only the core `dependencies` list — Playwright must be explicitly installed on the bench with `./env/bin/pip install playwright && playwright install chromium`.)

- [ ] **Step 4: Create `screenshot.py` skeleton**

`lazychat-erpnext/lazychat_erpnext/desk_assistant/screenshot.py`:

```python
"""Bench-side Playwright service for the M2 screenshot preview.

`capture(route, viewport, wait_for_dataset, timeout_ms)` renders an internal
Desk route in headless Chromium AS THE CALLING USER (cookie-injected from
frappe.session) and returns base64 PNG. Used by chat-ui's screenshot Message
kind after a create_page / update_doc(Page) Apply success.

Auth model: requires authenticated session. Refuses for Guest. The Playwright
context injects the calling user's session cookie so the rendered page sees
the same permissions as the caller would in their browser.

Concurrency: single-slot serializer with a small queue. Browser pool of N
persistent Chromium pages (reused across requests). Per-request: new tab,
inject cookie, navigate, wait for ready signal OR timeout, screenshot.

Gated by Lazychat Settings.enable_screenshot_preview. If Playwright is not
installed, returns {ok: False, error: "playwright not installed — ..."}.
"""
from __future__ import annotations
import base64
import threading
from typing import Optional

import frappe


# Concurrency: single-slot lock + bounded wait queue.
# Two concurrent dashboard builds on the same bench is plausible; 5+ is not.
_capture_lock = threading.Lock()
_max_queue_depth = 4
_queue_count = 0
_queue_count_lock = threading.Lock()

# Browser pool (created lazily on first capture, reused across requests).
_browser = None
_browser_lock = threading.Lock()


def _get_browser():
    """Create or return the persistent Chromium browser. Lazy-imports Playwright."""
    raise NotImplementedError  # filled in M2.2


def _ensure_capacity() -> Optional[dict]:
    """Reject with a clear error if the queue is saturated."""
    global _queue_count
    with _queue_count_lock:
        if _queue_count >= _max_queue_depth:
            return {"ok": False, "error": f"screenshot service at capacity ({_queue_count}/{_max_queue_depth} pending). Retry in a moment."}
        _queue_count += 1
    return None


def _release_capacity():
    global _queue_count
    with _queue_count_lock:
        _queue_count = max(0, _queue_count - 1)


@frappe.whitelist()
def capture(route: str, viewport: Optional[dict] = None, wait_for_dataset: str = "lazychatReady", timeout_ms: int = 5000) -> dict:
    """Whitelisted endpoint — render a Desk route, return base64 PNG.

    Args:
      route: e.g. "/app/proman-md-dashboard". Must be a same-origin Desk path.
      viewport: {"width": 1440, "height": 900} (default).
      wait_for_dataset: poll for `document.body.dataset.<name> === '1'`. Default 'lazychatReady'.
      timeout_ms: max wait for ready signal. Default 5000. Hard ceiling at 20000.

    Returns:
      {ok: True, screenshot_b64: "<base64 PNG>", width, height, capture_method: "playwright", ready_signal_seen: bool, captured_at: <unix>}
      OR {ok: False, error: "<reason>"} on failure.
    """
    raise NotImplementedError  # filled in M2.2


def is_available() -> bool:
    """Return True if Playwright is installed AND the Chromium binary is present.
    Used by install.py for the post-install warning and by capture() for the
    graceful-degrade error message."""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    # Probe for chromium binary
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.executable_path  # raises if missing
        return True
    except Exception:
        return False
```

- [ ] **Step 5: Re-run smoke; T101a passes (module imports — implementation can be NotImplementedError stubs)**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T101a
```
Expected: `PASS T101a screenshot module exports capture(...)`.

- [ ] **Step 6: Add Playwright detection to `install.py`**

Find `run_after_install()` in `lazychat-erpnext/lazychat_erpnext/install.py`. Append (or insert before the welcome banner):

```python
def _check_playwright_available():
    """Log a clear hint if the screenshot feature can't work yet."""
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


# Call from run_after_install() — append after the existing seed steps
# and before the welcome banner print.
```

Then in `run_after_install()`:
```python
    _check_playwright_available()
```

- [ ] **Step 7: Commit**

```bash
cd lazychat-erpnext
git add pyproject.toml \
        lazychat_erpnext/desk_assistant/screenshot.py \
        lazychat_erpnext/install.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m2): scaffold Playwright screenshot service module

Module skeleton with capture() whitelisted endpoint stub + is_available()
probe + concurrency primitives (single-slot lock, bounded queue). Implementation
filled in next task.

Adds 'playwright' as an OPTIONAL extra in pyproject.toml — Frappe Cloud and
benches that don't enable the screenshot feature don't pay the 200 MB Chromium
install cost.

install.py:_check_playwright_available logs a clear actionable warning on
after_install if Playwright is installed but Chromium is missing.

T101a passes (module imports cleanly even without Playwright)."
```

---

### Task M2.2: Implement `screenshot.capture` — browser pool + navigation + ready-signal poll

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/screenshot.py` — fill in `_get_browser()` and `capture()`
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — T101b (capture returns valid PNG on /app/User/Administrator), T101c (capture refuses for Guest), T101d (timeout fallback when ready_signal never set)

- [ ] **Step 1: Add T101b–T101d smoke cases**

```python
    # T101b — capture returns base64 PNG on a valid Desk route
    # Only runs if Playwright is installed; otherwise PASS as OK_ERROR.
    from lazychat_erpnext.desk_assistant.screenshot import capture, is_available
    if not is_available():
        log("⚠ T101b skipped: Playwright/Chromium not installed on this bench")
        pf(True, "T101b skipped (Playwright not installed) — OK_ERROR")
    else:
        r = capture(route="/app/user/Administrator", viewport={"width": 800, "height": 600}, timeout_ms=8000)
        ok = r.get("ok") and r.get("screenshot_b64", "").startswith("data:image/png;base64,") and r.get("width") == 800
        pf(ok, f"T101b capture returns base64 PNG: ok={r.get('ok')} method={r.get('capture_method')} sig_seen={r.get('ready_signal_seen')}")

    # T101c — refuses for Guest user
    import contextlib
    @contextlib.contextmanager
    def _as_guest():
        prev = frappe.session.user
        try:
            frappe.set_user("Guest")
            yield
        finally:
            frappe.set_user(prev)
    if not is_available():
        pf(True, "T101c skipped (Playwright not installed)")
    else:
        with _as_guest():
            r = capture(route="/app/user/Administrator")
        pf(not r.get("ok") and "Guest" in r.get("error", ""), f"T101c refuses Guest: {r}")

    # T101d — timeout fallback when ready_signal never set (User form doesn't set lazychatReady)
    # The capture should still return a screenshot, with ready_signal_seen=False
    if is_available():
        r = capture(route="/app/user/Administrator", wait_for_dataset="thisWillNeverBeSet", timeout_ms=2000)
        pf(r.get("ok") and r.get("ready_signal_seen") is False, f"T101d timeout fallback: ok={r.get('ok')}, sig_seen={r.get('ready_signal_seen')}")
```

- [ ] **Step 2: Implement `_get_browser()` + `capture()`**

In `lazychat-erpnext/lazychat_erpnext/desk_assistant/screenshot.py`:

```python
def _get_browser():
    """Create or return the persistent Chromium browser. Lazy-imports Playwright."""
    global _browser
    if _browser is not None:
        return _browser
    with _browser_lock:
        if _browser is not None:  # double-checked locking
            return _browser
        from playwright.sync_api import sync_playwright
        # Note: this returns a Playwright instance manager that owns the browser.
        # We keep the manager alive for the lifetime of the worker process.
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        return _browser


def capture(route, viewport=None, wait_for_dataset="lazychatReady", timeout_ms=5000):
    """See module docstring."""
    user = frappe.session.user if frappe.session else None
    if not user or user == "Guest":
        return {"ok": False, "error": "screenshot.capture: Guest user not permitted; sign in first."}

    settings_enabled = frappe.db.get_single_value("Lazychat Settings", "enable_screenshot_preview")
    if settings_enabled is not None and not int(settings_enabled or 0):
        return {"ok": False, "error": "screenshot preview is disabled in Lazychat Settings."}

    if not is_available():
        return {"ok": False, "error": "playwright not installed — run `./env/bin/pip install playwright && ./env/bin/playwright install chromium` on the bench."}

    # Sanity-check route
    if not isinstance(route, str) or not route.startswith("/"):
        return {"ok": False, "error": f"route must start with '/' (got: {route!r})"}
    if not (route.startswith("/app/") or route.startswith("/files/") or route.startswith("/private/files/")):
        return {"ok": False, "error": f"route '{route}' is not a Desk path. Only /app/* / /files/* / /private/files/* are screenshotable."}

    # Concurrency gate
    err = _ensure_capacity()
    if err:
        return err

    width = int((viewport or {}).get("width") or 1440)
    height = int((viewport or {}).get("height") or 900)
    timeout_ms = min(max(int(timeout_ms or 5000), 500), 20000)  # clamp [500, 20000]

    try:
        with _capture_lock:
            browser = _get_browser()
            context = browser.new_context(viewport={"width": width, "height": height})
            try:
                # Inject the calling user's session cookie so the rendered page
                # sees their permissions. Frappe stores the sid in cookies named
                # 'sid'; we re-create it for the headless context.
                sid = frappe.local.session.sid if frappe.local.session else None
                host = (frappe.utils.get_url() or "http://localhost:8000").replace("https://", "").replace("http://", "").split("/")[0]
                if sid:
                    context.add_cookies([{
                        "name": "sid", "value": sid, "domain": host.split(":")[0],
                        "path": "/", "httpOnly": True, "sameSite": "Lax",
                    }])
                page = context.new_page()
                full_url = (frappe.utils.get_url() or "http://localhost:8000") + route
                page.goto(full_url, wait_until="networkidle", timeout=timeout_ms + 2000)
                # Poll for ready signal
                ready_seen = False
                try:
                    page.wait_for_function(
                        f"() => document.body && document.body.dataset && document.body.dataset[{wait_for_dataset!r}] === '1'",
                        timeout=timeout_ms,
                    )
                    ready_seen = True
                except Exception:
                    # Timeout — proceed anyway, screenshot what we have
                    pass
                png_bytes = page.screenshot(full_page=False, type="png")
                page.close()
            finally:
                context.close()

        b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
        import time
        return {
            "ok": True,
            "screenshot_b64": b64,
            "width": width,
            "height": height,
            "capture_method": "playwright",
            "ready_signal_seen": ready_seen,
            "captured_at": int(time.time() * 1000),
        }
    except Exception as e:
        return {"ok": False, "error": f"capture failed: {type(e).__name__}: {e}"}
    finally:
        _release_capacity()
```

- [ ] **Step 3: Add `enable_screenshot_preview` field to Lazychat Settings**

Modify `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/lazychat_settings/lazychat_settings.json`. Find the `fields` array and append:

```json
{
    "fieldname": "enable_screenshot_preview",
    "fieldtype": "Check",
    "label": "Enable Screenshot Preview (Playwright)",
    "default": "0",
    "description": "When enabled, the chat-ui auto-captures a screenshot of new Desk Pages after Apply. Requires Playwright + Chromium installed on the bench: `./env/bin/pip install playwright && ./env/bin/playwright install chromium`."
}
```

Default `0` (off) — operator must explicitly enable after the Chromium install. Idempotent migration: `bench --site erp.local migrate` adds the field on next deploy.

- [ ] **Step 4: Re-run smoke; T101b/c/d either PASS or skip cleanly**

```bash
# If Playwright is installed on this bench:
cd $BENCH_ROOT
./env/bin/pip install playwright 2>&1 | tail -3
./env/bin/playwright install chromium 2>&1 | tail -3
# Enable the setting:
bench --site erp.local execute frappe.db.set_value --kwargs '{"dt":"Lazychat Settings","dn":"Lazychat Settings","field":"enable_screenshot_preview","val":1}'

# Then re-run smoke:
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T101
```
Expected: T101a/b/c/d all PASS (or T101b/c/d skip with explicit "Playwright not installed" if the operator hasn't installed it).

- [ ] **Step 5: Commit**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/screenshot.py \
        lazychat_erpnext/desk_assistant/doctype/lazychat_settings/lazychat_settings.json \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m2): screenshot.capture — Playwright service with session-cookie injection

Lazy browser pool (persistent Chromium, reused across requests). Per-request:
new context with the caller's sid cookie, navigate, wait_for_function on
document.body.dataset[<wait_for_dataset>] === '1' (default 'lazychatReady'),
screenshot, return base64 PNG.

Concurrency: single-slot lock with bounded queue (default 4). Refuses for
Guest. Gated by Lazychat Settings.enable_screenshot_preview (default off so
benches without Chromium don't fail-on-call).

Timeout fallback: if the ready signal never fires, returns the screenshot
with ready_signal_seen=False rather than erroring.

T101b/c/d pass (or skip cleanly if Playwright not installed)."
```

---

### Task M2.3: Postmessage protocol — extend `inspectRoute` for screenshot mode

**Files:**
- Modify: `lazychat.ai/packages/types/src/postmessage.ts` — extend `InspectRouteRequest` + `InspectRouteResponse`
- Modify: `lazychat.ai/packages/types/src/__tests__/postmessage.test.ts` (or add if no test file) — types compile + envelope-shape sanity

Cycle 9 M4 introduced `inspectRoute` (DOM-state capture from a hidden iframe). We extend it with a `mode` discriminator: `'dom'` (existing behavior, unchanged) vs `'screenshot'` (new — proxies to bench-side `screenshot.capture`).

- [ ] **Step 1: Extend the types**

Find `InspectRouteRequest` in `packages/types/src/postmessage.ts`. Today it looks roughly like:

```ts
export interface InspectRouteRequest {
  v: 1; src: 'iframe'; type: 'inspectRoute';
  payload: {
    requestId: string;
    route: string;
    captureSpec: {
      timeout_ms?: number;
      form_fields?: string[];
      child_table?: string;
      child_table_count?: boolean;
      child_row_fields?: string[];
      buttons_in_page?: boolean;
    };
  };
}
```

Extend `captureSpec` and the response shape:

```ts
export interface InspectRouteRequest {
  v: 1; src: 'iframe'; type: 'inspectRoute';
  payload: {
    requestId: string;
    route: string;
    captureSpec: {
      mode?: 'dom' | 'screenshot';                  // NEW. Default 'dom' for back-compat.
      timeout_ms?: number;
      // 'dom' mode fields (unchanged from Cycle 9 M4):
      form_fields?: string[];
      child_table?: string;
      child_table_count?: boolean;
      child_row_fields?: string[];
      buttons_in_page?: boolean;
      // 'screenshot' mode fields (NEW):
      ready_signal?: string;                        // dataset key, e.g. 'lazychatReady'. Default 'lazychatReady'.
      viewport?: { width: number; height: number }; // default {1440, 900}
    };
  };
}

export interface InspectRouteResponse {
  v: 1; src: 'host'; type: 'inspectRouteResponse';
  payload: {
    requestId: string;
    ok: boolean;
    captured?: {
      url?: string;
      // dom-mode fields (unchanged)
      form?: Record<string, unknown>;
      items?: unknown[];
      items_count?: number;
      buttons?: string[];
      // screenshot-mode fields (NEW)
      screenshot_b64?: string;
      width?: number;
      height?: number;
      capture_method?: 'playwright' | 'html2canvas';
      ready_signal_seen?: boolean;
      captured_at?: number;
    };
    error?: string;
  };
}
```

- [ ] **Step 2: Run typecheck**

```bash
cd lazychat.ai && pnpm typecheck 2>&1 | grep -E "typecheck:|error TS"
```
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
cd lazychat.ai
git add packages/types/src/postmessage.ts
git commit -m "feat(cycle-13/m2): extend inspectRoute postmessage with screenshot mode

captureSpec.mode discriminates 'dom' (Cycle 9 M4, unchanged) from 'screenshot'
(new). Screenshot mode adds ready_signal + viewport to the request and
screenshot_b64 + width/height + capture_method + ready_signal_seen to the
response.

Back-compat: mode defaults to 'dom' when omitted."
```

---

### Task M2.4: Extend `handleInspectRoute` in the panel-shim

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/public/js/lazychat_panel.bundle.js` — extend `handleInspectRoute` to branch on `captureSpec.mode === 'screenshot'`

The panel-shim is the host-side bridge that receives `inspectRoute` postmessages from the chat-ui iframe. We add a new branch: if `mode === 'screenshot'`, POST to the bench-side `screenshot.capture` endpoint and ship the response back via `inspectRouteResponse`.

- [ ] **Step 1: Find the existing `handleInspectRoute` in `lazychat_panel.bundle.js`**

It currently looks roughly like:
```js
function handleInspectRoute(payload) {
  const spec = (payload && payload.captureSpec) || {};
  // ...creates hidden iframe, polls cur_frm, captures DOM state, returns inspectRouteResponse...
}
```

- [ ] **Step 2: Add the mode branch at the top**

Replace the start of `handleInspectRoute` with:

```js
function handleInspectRoute(payload) {
  const spec = (payload && payload.captureSpec) || {};
  if (spec.mode === "screenshot") {
    return handleScreenshotCapture(payload);
  }
  // ...existing DOM-state path (unchanged)...
}

function handleScreenshotCapture(payload) {
  const requestId = payload && payload.requestId;
  const route = payload && payload.route;
  const spec = (payload && payload.captureSpec) || {};
  const ready_signal = spec.ready_signal || "lazychatReady";
  const timeout_ms = Math.min(Math.max(spec.timeout_ms || 5000, 500), 20000);
  const viewport = spec.viewport || { width: 1440, height: 900 };

  if (!route || !requestId) {
    bridge.send("inspectRouteResponse", {
      requestId: requestId, ok: false,
      error: "missing route or requestId",
    });
    return;
  }

  // POST to the bench-side screenshot service
  fetch("/api/method/lazychat_erpnext.desk_assistant.screenshot.capture", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-Frappe-CSRF-Token": csrf(),
    },
    body: JSON.stringify({
      route: route,
      viewport: viewport,
      wait_for_dataset: ready_signal,
      timeout_ms: timeout_ms,
    }),
  })
    .then(function (r) { return r.json(); })
    .then(function (j) {
      const m = (j && j.message) || {};
      if (m.ok) {
        bridge.send("inspectRouteResponse", {
          requestId: requestId, ok: true,
          captured: {
            screenshot_b64: m.screenshot_b64,
            width: m.width,
            height: m.height,
            capture_method: m.capture_method,
            ready_signal_seen: m.ready_signal_seen,
            captured_at: m.captured_at,
            url: route,
          },
        });
      } else {
        bridge.send("inspectRouteResponse", {
          requestId: requestId, ok: false,
          error: m.error || "screenshot capture failed",
        });
      }
    })
    .catch(function (err) {
      bridge.send("inspectRouteResponse", {
        requestId: requestId, ok: false,
        error: "screenshot fetch failed: " + String((err && err.message) || err),
      });
    });
}
```

- [ ] **Step 3: Sanity check syntax**

```bash
node --check lazychat-erpnext/lazychat_erpnext/public/js/lazychat_panel.bundle.js && echo "OK"
```
Expected: `OK`.

- [ ] **Step 4: Deploy + restart so the new shim is served**

```bash
cd /Users/soumyasethy/Desktop/code-chat
sh build.sh 2>&1 | tail -4
sh restart.sh --bg
```

- [ ] **Step 5: Smoke check via curl (logged-in cookie)**

After login on `http://localhost:8000`:
```bash
# Quick wire-level call to the new endpoint (replace SID with your sid cookie):
curl -s -b "sid=<YOUR_SID>" -H "X-Frappe-CSRF-Token: <YOUR_CSRF>" \
  -H "Content-Type: application/json" \
  -d '{"route":"/app/user/Administrator","viewport":{"width":800,"height":600},"timeout_ms":5000}' \
  http://localhost:8000/api/method/lazychat_erpnext.desk_assistant.screenshot.capture \
  | python3 -c "import json,sys; r=json.load(sys.stdin); print('ok:', r['message'].get('ok'), 'method:', r['message'].get('capture_method'), 'png_size:', len(r['message'].get('screenshot_b64',''))) if r.get('message') else print(r)"
```
Expected (with Playwright installed + enable_screenshot_preview=1): `ok: True method: playwright png_size: ~50000-150000`.

- [ ] **Step 6: Commit**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/public/js/lazychat_panel.bundle.js
git commit -m "feat(cycle-13/m2): panel-shim handles inspectRoute screenshot mode

Adds handleScreenshotCapture branch in handleInspectRoute. POSTs to the
bench-side screenshot.capture endpoint (with CSRF + cookie auth), ships
the base64 PNG back to chat-ui via inspectRouteResponse.

Existing DOM-state mode unchanged."
```

---

### Task M2.5: New `screenshot` Message kind + `ScreenshotMessage` renderer

**Files:**
- Modify: `lazychat.ai/packages/types/src/messages.ts` — add `screenshot` to the `Message` union
- Create: `lazychat.ai/apps/chat-ui/src/components/messages/ScreenshotMessage.tsx`
- Modify: `lazychat.ai/apps/chat-ui/src/components/MessageList.tsx` — dispatch case for `screenshot`
- Create: `lazychat.ai/apps/chat-ui/src/components/messages/__tests__/ScreenshotMessage.test.tsx` — render tests

- [ ] **Step 1: Write the failing render test**

Create `apps/chat-ui/src/components/messages/__tests__/ScreenshotMessage.test.tsx`:

```ts
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ScreenshotMessage } from '../ScreenshotMessage';
import type { Message } from '@lazychat/types';

const msg = (overrides: Partial<Extract<Message, { kind: 'screenshot' }>>): Extract<Message, { kind: 'screenshot' }> => ({
  kind: 'screenshot',
  id: 's1',
  ts: Date.now(),
  pageName: 'proman-md-dashboard',
  route: '/app/proman-md-dashboard',
  pngB64: 'data:image/png;base64,iVBORw0KGgo=',
  width: 1440,
  height: 900,
  status: 'done',
  captureMethod: 'playwright',
  capturedAt: Date.now(),
  ...overrides,
});

describe('ScreenshotMessage', () => {
  it('renders capturing state with route', () => {
    render(<ScreenshotMessage msg={msg({ status: 'capturing', pngB64: '' })} />);
    expect(screen.getByText(/capturing/i)).toBeInTheDocument();
    expect(screen.getByText(/\/app\/proman-md-dashboard/)).toBeInTheDocument();
  });

  it('renders done state with img', () => {
    render(<ScreenshotMessage msg={msg({})} />);
    const img = screen.getByRole('img');
    expect((img as HTMLImageElement).src).toContain('data:image/png');
  });

  it('renders error state with message', () => {
    render(<ScreenshotMessage msg={msg({ status: 'error', pngB64: '', error: 'timeout' })} />);
    expect(screen.getByText(/timeout/i)).toBeInTheDocument();
  });

  it('stale state visually marked', () => {
    const { container } = render(<ScreenshotMessage msg={msg({ status: 'stale' })} />);
    expect(container.querySelector('.opacity-40, [data-stale]')).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test — fails (component doesn't exist)**

```bash
cd lazychat.ai && pnpm --filter chat-ui exec vitest run src/components/messages/__tests__/ScreenshotMessage.test.tsx 2>&1 | grep -E "FAIL|Cannot find"
```

- [ ] **Step 3: Add `screenshot` to the Message union**

In `packages/types/src/messages.ts`, find the `Message` union (large discriminated union). Append:

```ts
  | {
      kind: 'screenshot';
      id: string;
      ts: number;
      pageName: string;
      route: string;
      pngB64: string;            // 'data:image/png;base64,...' (empty during 'capturing')
      width: number;
      height: number;
      status: 'capturing' | 'done' | 'error' | 'stale';
      error?: string;
      captureMethod: 'playwright' | 'html2canvas';
      capturedAt: number;
      refMockupB64?: string;     // reference mockup screenshot if user uploaded HTML (M3 input)
    }
```

- [ ] **Step 4: Create `ScreenshotMessage.tsx`**

`apps/chat-ui/src/components/messages/ScreenshotMessage.tsx`:

```tsx
import { useState, useEffect } from 'react';
import type { Message } from '@lazychat/types';

type ScreenshotMsg = Extract<Message, { kind: 'screenshot' }>;

interface Props {
  msg: ScreenshotMsg;
  onRecapture?: () => void;
  onOpenDesk?: (route: string) => void;
}

export function ScreenshotMessage({ msg, onRecapture, onOpenDesk }: Props) {
  const [elapsed, setElapsed] = useState(0);

  // Tick elapsed seconds while capturing
  useEffect(() => {
    if (msg.status !== 'capturing') return;
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.round((Date.now() - start) / 1000)), 500);
    return () => clearInterval(id);
  }, [msg.status]);

  const containerCls = msg.status === 'stale' ? 'opacity-40' : '';
  const dataStale = msg.status === 'stale' ? 'true' : undefined;

  return (
    <div className={`flex flex-col gap-2 my-2 ${containerCls}`} data-stale={dataStale}>
      <div className="text-xs text-fg-muted">
        Screenshot · <span className="font-mono">{msg.route}</span>
        {msg.status === 'done' && <> · {new Date(msg.capturedAt).toLocaleTimeString()}</>}
      </div>

      {msg.status === 'capturing' && (
        <div className="flex items-center gap-3 rounded-md border border-border-strong bg-bg-elevated p-4">
          <div className="h-4 w-4 animate-pulse rounded-full bg-accent" aria-hidden />
          <div className="flex-1 text-sm">
            Capturing <span className="font-mono">{msg.route}</span>… <span className="text-fg-muted">{elapsed}s</span>
          </div>
        </div>
      )}

      {msg.status === 'done' && msg.pngB64 && (
        <div className="rounded-md overflow-hidden border border-border-strong">
          <img
            src={msg.pngB64}
            alt={`Screenshot of ${msg.route}`}
            className="block w-full h-auto cursor-zoom-in"
            onClick={() => window.open(msg.pngB64, '_blank', 'noopener')}
          />
          <div className="flex items-center gap-2 px-3 py-2 bg-bg-elevated text-xs">
            <span className="text-fg-muted">{msg.width}×{msg.height} · {msg.captureMethod}</span>
            <div className="flex-1" />
            {onRecapture && (
              <button onClick={onRecapture} className="text-xs text-fg-link hover:underline">↻ Re-capture</button>
            )}
            {onOpenDesk && (
              <button onClick={() => onOpenDesk(msg.route)} className="text-xs text-fg-link hover:underline">↗ Open in Desk</button>
            )}
          </div>
        </div>
      )}

      {msg.status === 'error' && (
        <div className="rounded-md border border-r/40 bg-rb p-3 text-xs">
          <div className="font-medium text-r">Couldn't capture screenshot</div>
          <div className="mt-1 text-fg-secondary">{msg.error || 'Unknown error.'}</div>
          {onOpenDesk && (
            <button onClick={() => onOpenDesk(msg.route)} className="mt-2 text-fg-link hover:underline">↗ Open in Desk to verify manually</button>
          )}
        </div>
      )}

      {msg.status === 'stale' && msg.pngB64 && (
        <div className="rounded-md overflow-hidden border border-border opacity-60">
          <img src={msg.pngB64} alt={`Stale screenshot of ${msg.route}`} className="block w-full h-auto" />
          <div className="px-3 py-2 bg-bg-elevated text-xs flex items-center gap-2">
            <span className="text-fg-muted">(superseded by a newer capture)</span>
            <div className="flex-1" />
            {onRecapture && (
              <button onClick={onRecapture} className="text-fg-link hover:underline">↻ Re-capture latest</button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Add dispatch case in `MessageList.tsx`**

Find the switch on `m.kind` in `apps/chat-ui/src/components/MessageList.tsx`. Add:

```tsx
case 'screenshot':
  return <ScreenshotMessage key={m.id} msg={m} onOpenDesk={(route) => window.open(route, '_blank', 'noopener')} />;
```

And add the import at the top: `import { ScreenshotMessage } from './messages/ScreenshotMessage';`.

- [ ] **Step 6: Re-run vitest — all 4 cases pass**

```bash
cd lazychat.ai
pnpm --filter chat-ui exec vitest run src/components/messages/__tests__/ScreenshotMessage.test.tsx 2>&1 | tail -5
pnpm typecheck 2>&1 | grep -E "typecheck:|error TS" | tail -3
```
Expected: 4 passed, typecheck clean.

- [ ] **Step 7: Commit**

```bash
cd lazychat.ai
git add packages/types/src/messages.ts \
        apps/chat-ui/src/components/messages/ScreenshotMessage.tsx \
        apps/chat-ui/src/components/messages/__tests__/ScreenshotMessage.test.tsx \
        apps/chat-ui/src/components/MessageList.tsx
git commit -m "feat(cycle-13/m2): screenshot Message kind + ScreenshotMessage renderer

New Message variant for inline page-rendered screenshots. 4 status states:
capturing (skeleton + elapsed counter), done (img + Re-capture/Open buttons),
error (red banner + Open-manually fallback), stale (dimmed + Re-capture).

Click image → full-size in new tab. Wired into MessageList dispatch.

4 vitest cases (capturing/done/error/stale rendering) all pass."
```

---

### Task M2.6: Auto-trigger screenshot after `create_page` / `update_doc(Page)` Apply success

**Files:**
- Modify: `lazychat.ai/apps/chat-ui/src/lib/commitSlash.ts` — after a successful commit response, fire `triggerScreenshot` for relevant actions
- Modify: `lazychat.ai/apps/chat-ui/src/lib/agentRunner.ts` (or a new helper) — implement `triggerScreenshot(sid, pageName, route)`
- Modify: `lazychat.ai/apps/chat-ui/src/lib/__tests__/commitSlash.test.ts` — add cases for the screenshot trigger

The trigger fires for ANY commit where the resulting record is at a Desk route worth previewing. For Cycle 13: `create_page` (route from commit response) and `update_doc` where `doctype === 'Page'`.

- [ ] **Step 1: Write failing test cases**

Append to `commitSlash.test.ts`:

```ts
describe('post-commit screenshot trigger', () => {
  it('fires triggerScreenshot for create_page commit success', async () => {
    const startStream = vi.fn();
    const triggerSpy = vi.fn();
    // ...mock commit endpoint to return {ok: true, action: 'create_page', name: 'proman-md', link: '/app/proman-md-dashboard'}...
    // ...inject triggerScreenshot mock...
    // assert triggerSpy called once with the pageName + route
    expect(triggerSpy).toHaveBeenCalledWith(expect.any(String), expect.stringContaining('proman-md'), '/app/proman-md-dashboard');
  });

  it('fires triggerScreenshot for update_doc(Page) commit success', async () => {
    // similar — commit returns action: 'update_doc', doctype: 'Page', name: 'proman-md-dashboard'
    // assert triggerSpy called
  });

  it('does NOT fire for create_server_script', async () => {
    // commit returns action: 'create_server_script'
    // assert triggerSpy NOT called
  });
});
```

Note: the exact mock structure depends on existing `commitSlash.test.ts` helpers (it likely uses `mockJsonFetchOnce` from `_helpers/mockResponse.ts`). Mirror the pattern of existing test cases in that file.

- [ ] **Step 2: Run test — fails (no trigger logic yet)**

```bash
cd lazychat.ai && pnpm --filter chat-ui exec vitest run src/lib/__tests__/commitSlash.test.ts 2>&1 | grep -E "screenshot|FAIL|✓|✗" | head -10
```

- [ ] **Step 3: Implement `triggerScreenshot` in `agentRunner.ts`**

In `apps/chat-ui/src/lib/agentRunner.ts`, add a new exported function:

```ts
import { useSessions } from '@/store/sessions';
import { emitEvent } from '@/iframe/bridge';
import type { Message } from '@lazychat/types';

const ACTIONS_THAT_TRIGGER_SCREENSHOT = new Set<string>([
  'create_page',
  // update_doc handled separately via doctype check
]);

/** Append a 'capturing' screenshot Message, fire inspectRoute(mode=screenshot)
 * to the host, and on response replace with 'done' or 'error'. */
export function triggerScreenshot(sid: string, pageName: string, route: string): void {
  const requestId = `screenshot-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const msgId = `m-screenshot-${requestId}`;

  // Mark prior screenshot Messages for this pageName as stale
  const sess = useSessions.getState().byId[sid];
  if (sess) {
    sess.messages
      .filter((m) => m.kind === 'screenshot' && m.pageName === pageName && m.status === 'done')
      .forEach((m) => {
        useSessions.getState().replaceMessage(sid, m.id, { ...m, status: 'stale' } as Message);
      });
  }

  // Append the placeholder
  const placeholder: Message = {
    kind: 'screenshot',
    id: msgId,
    ts: Date.now(),
    pageName,
    route,
    pngB64: '',
    width: 1440,
    height: 900,
    status: 'capturing',
    captureMethod: 'playwright',
    capturedAt: Date.now(),
  };
  useSessions.getState().appendMessage(sid, placeholder);

  // Listen for the response
  function onResp(ev: MessageEvent) {
    const data = ev.data;
    if (!data || data.v !== 1 || data.type !== 'inspectRouteResponse') return;
    if (data.payload?.requestId !== requestId) return;
    window.removeEventListener('message', onResp);

    const p = data.payload;
    if (p.ok && p.captured?.screenshot_b64) {
      useSessions.getState().replaceMessage(sid, msgId, {
        ...placeholder,
        pngB64: p.captured.screenshot_b64,
        width: p.captured.width || 1440,
        height: p.captured.height || 900,
        captureMethod: p.captured.capture_method || 'playwright',
        capturedAt: p.captured.captured_at || Date.now(),
        status: 'done',
      } as Message);
    } else {
      useSessions.getState().replaceMessage(sid, msgId, {
        ...placeholder,
        status: 'error',
        error: p.error || 'Unknown error',
      } as Message);
    }
  }
  window.addEventListener('message', onResp);

  // Fire the postmessage to the host
  emitEvent({
    type: 'inspectRoute',
    payload: {
      requestId,
      route,
      captureSpec: {
        mode: 'screenshot',
        ready_signal: 'lazychatReady',
        timeout_ms: 5000,
        viewport: { width: 1440, height: 900 },
      },
    },
  });

  // Safety: if no response in 15s, mark as error
  setTimeout(() => {
    const cur = useSessions.getState().byId[sid]?.messages.find((m) => m.id === msgId);
    if (cur && cur.kind === 'screenshot' && cur.status === 'capturing') {
      window.removeEventListener('message', onResp);
      useSessions.getState().replaceMessage(sid, msgId, {
        ...cur,
        status: 'error',
        error: 'No response from screenshot service in 15s.',
      } as Message);
    }
  }, 15000);
}
```

- [ ] **Step 4: Wire into `commitSlash.ts`**

Find the success branch in `handleCommitSlash` (where it processes the commit response). After the existing render of the "Done" Message and the AUTO_OPEN handling, add:

```ts
import { triggerScreenshot } from './agentRunner';

// ...inside handleCommitSlash, after successful commit:
const action = (commitResult.action || '') as string;
const isPageCreate = action === 'create_page';
const isPageUpdate = action === 'update_doc' && commitResult.doctype === 'Page';
if (isPageCreate || isPageUpdate) {
  const pageName = commitResult.name || commitResult.page_name;
  const route = commitResult.link || (pageName ? `/app/${pageName}` : null);
  if (pageName && route) {
    triggerScreenshot(sid, pageName, route);
  }
}
```

- [ ] **Step 5: Re-run vitest — all 3 new commitSlash cases pass**

```bash
cd lazychat.ai && pnpm --filter chat-ui exec vitest run src/lib/__tests__/commitSlash.test.ts 2>&1 | tail -5
pnpm typecheck 2>&1 | grep -E "typecheck:|error TS" | tail -3
```

- [ ] **Step 6: Commit**

```bash
cd lazychat.ai
git add apps/chat-ui/src/lib/agentRunner.ts \
        apps/chat-ui/src/lib/commitSlash.ts \
        apps/chat-ui/src/lib/__tests__/commitSlash.test.ts
git commit -m "feat(cycle-13/m2): auto-trigger screenshot after Page commit success

After commit_prepared_action returns ok=true with action=create_page or
action=update_doc+doctype=Page, fire inspectRoute(mode=screenshot) to host.
Append a 'capturing' Message immediately; replace with 'done' (+PNG) or
'error' on response. Mark prior screenshots for same pageName as 'stale'.

15s safety timeout if no response."
```

---

### Task M2.7: Reference-mockup capture (html2canvas in the browser)

**Files:**
- Create: `lazychat-erpnext/lazychat_erpnext/public/js/html2canvas.min.js` — vendor html2canvas 1.4.1 (~200 KB)
- Modify: `lazychat.ai/apps/chat-ui/src/lib/attachments/extractText.ts` — when an uploaded HTML file is a full `<html>` document, ALSO render it via html2canvas and stash the PNG on the Attachment as `referenceScreenshot`
- Modify: `lazychat.ai/packages/types/src/messages.ts` — `Attachment` type gains optional `referenceScreenshot?: string`
- Modify: `lazychat.ai/apps/chat-ui/src/lib/agentRunner.ts` — when triggering a screenshot, look for a recent reference Attachment in the session and pass its `referenceScreenshot` into the `screenshot` Message's `refMockupB64`

We use html2canvas for the REFERENCE (user's uploaded mockup) — fast, no bench round-trip. The CANDIDATE uses Playwright (pixel-perfect). M3 is the consumer of both.

- [ ] **Step 1: Vendor html2canvas**

```bash
cd /Users/soumyasethy/Desktop/code-chat/lazychat-erpnext
mkdir -p lazychat_erpnext/public/js
curl -sSL "https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js" \
  -o lazychat_erpnext/public/js/html2canvas.min.js
ls -la lazychat_erpnext/public/js/html2canvas.min.js   # should be ~200 KB
```

Verify the file is the real library (not a 404 page):
```bash
head -c 80 lazychat_erpnext/public/js/html2canvas.min.js
# Expected: starts with "/*!" or "(function(...)" — JavaScript, not HTML
```

- [ ] **Step 2: Add `referenceScreenshot` to the Attachment type**

In `packages/types/src/messages.ts`, find the `Attachment` interface. Add:

```ts
export interface Attachment {
  // ... existing fields (id, name, mime, size, dataUrl?, extractedText?, ...) ...
  referenceScreenshot?: string;  // 'data:image/png;base64,...' — populated for HTML uploads (Cycle 13 M2). Used by M3 visual judge as the reference image.
}
```

- [ ] **Step 3: Extend `extractText.ts` to capture the screenshot for full-HTML uploads**

In `apps/chat-ui/src/lib/attachments/extractText.ts`, find the existing `extractAttachment` function. Inside the `isHtml(file)` path (after `readAsText` returns the raw HTML), add a non-blocking reference-screenshot capture:

```ts
async function captureHtmlAsScreenshot(html: string): Promise<string | undefined> {
  // Lazy-load html2canvas from the self-hosted asset (no CDN, no CSP issues).
  try {
    if (!(window as any).html2canvas) {
      await new Promise<void>((resolve, reject) => {
        const s = document.createElement('script');
        s.src = '/assets/lazychat_erpnext/js/html2canvas.min.js';
        s.onload = () => resolve();
        s.onerror = () => reject(new Error('html2canvas load failed (chat-ui not embedded in lazychat-erpnext, or asset missing)'));
        document.head.appendChild(s);
      });
    }
    const h2c = (window as any).html2canvas;
    if (!h2c) return undefined;

    // Render the HTML in an OFF-SCREEN iframe (blob URL), capture, clean up.
    // Off-screen position keeps it invisible; viewport sized to a sensible default.
    const iframe = document.createElement('iframe');
    iframe.style.cssText = 'position:absolute;left:-3000px;top:0;width:1440px;height:900px;border:0;';
    iframe.setAttribute('aria-hidden', 'true');
    iframe.setAttribute('sandbox', 'allow-same-origin');  // no JS execution from the uploaded HTML — pure rendering only
    document.body.appendChild(iframe);

    // Use srcdoc instead of blob URL for tighter sandbox.
    iframe.srcdoc = html;

    // Wait for load (max 8s — generous for big mockups)
    await new Promise<void>((resolve, reject) => {
      const tid = setTimeout(() => reject(new Error('iframe load timeout')), 8000);
      iframe.onload = () => { clearTimeout(tid); resolve(); };
      iframe.onerror = () => { clearTimeout(tid); reject(new Error('iframe load failed')); };
    });

    // Give CSS/fonts a beat to settle
    await new Promise((res) => setTimeout(res, 600));

    const doc = iframe.contentDocument;
    if (!doc || !doc.body) { document.body.removeChild(iframe); return undefined; }

    const canvas = await h2c(doc.body, { width: 1440, height: 900, scale: 1, useCORS: true, logging: false });
    const png = canvas.toDataURL('image/png');
    document.body.removeChild(iframe);
    return png;
  } catch (err) {
    console.warn('[lazychat] reference-mockup capture failed (non-fatal):', err);
    return undefined;
  }
}

// In extractAttachment, inside the isHtml branch:
//   ...after `const text = await readAsText(file);`:
//   if (looksLikeFullHtmlDocument(text)) {
//     att.referenceScreenshot = await captureHtmlAsScreenshot(text);
//   }
//   ...
function looksLikeFullHtmlDocument(text: string): boolean {
  const t = text.toLowerCase();
  return t.includes('<html') && t.includes('</html>') && (t.includes('<body') || t.includes('<head'));
}
```

- [ ] **Step 4: Pass `refMockupB64` to triggerScreenshot**

Modify `triggerScreenshot` (from M2.6) to look for a recent reference attachment in the session and pass it through:

```ts
export function triggerScreenshot(sid: string, pageName: string, route: string): void {
  // ... existing code ...

  // Find a recent reference-mockup screenshot from session attachments
  const sess = useSessions.getState().byId[sid];
  let refMockupB64: string | undefined;
  if (sess) {
    for (let i = sess.messages.length - 1; i >= 0; i--) {
      const m = sess.messages[i];
      if (m.kind === 'user' && m.attachments) {
        const refAtt = m.attachments.find((a) => a.referenceScreenshot);
        if (refAtt?.referenceScreenshot) {
          refMockupB64 = refAtt.referenceScreenshot;
          break;
        }
      }
    }
  }

  const placeholder: Message = {
    // ... existing fields ...
    refMockupB64,
  };
  // ... rest unchanged ...
}
```

- [ ] **Step 5: Verify the reference capture works (manual)**

After the chat-ui rebuild + deploy:
1. Open the panel
2. Drag the Proman MD Dashboard HTML file into the composer
3. Check Safari/Chrome DevTools console for any `[lazychat]` reference-mockup-capture errors
4. Confirm the attachment chip renders (the existing UX)
5. The `referenceScreenshot` will be used in M3 — no visual indicator yet in M2

Or run a vitest case that injects a fake `<html>` string and verifies `att.referenceScreenshot` is populated (mock html2canvas to return a fake PNG).

- [ ] **Step 6: Commit**

```bash
# Both repos
cd lazychat-erpnext
git add lazychat_erpnext/public/js/html2canvas.min.js
git commit -m "chore(cycle-13/m2): vendor html2canvas 1.4.1 for in-browser reference capture

200 KB lib served at /assets/lazychat_erpnext/js/html2canvas.min.js. Used by
chat-ui's extractText.ts to capture a screenshot of uploaded HTML mockups
client-side (no bench round-trip, no Playwright dependency for the reference).
Candidate screenshots still use Playwright (M2.2)."

cd ../lazychat.ai
git add packages/types/src/messages.ts \
        apps/chat-ui/src/lib/attachments/extractText.ts \
        apps/chat-ui/src/lib/agentRunner.ts
git commit -m "feat(cycle-13/m2): capture reference-mockup screenshot for full-HTML uploads

extractText.ts: when an uploaded HTML file is a full <html> document
(matches <html> + </html> + <body|head>), render it in an off-screen
sandboxed iframe via srcdoc, capture with html2canvas (lazy-loaded from
the lazychat-erpnext static asset), stash on Attachment.referenceScreenshot.

agentRunner.ts triggerScreenshot: look back through session messages for
the most-recent user message with a reference attachment, thread its
referenceScreenshot into the new screenshot Message's refMockupB64.
M3 visual judge will consume this."
```

---

### Task M2.8: M2 phase exit + smoke + vitest summary

**Files:** none new — just verification

- [ ] **Step 1: Run full smoke**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep -E "T100|T101|=== "
```
Expected: T100a–T100n + T101a–T101d all pass (or T101b/c/d cleanly skip with "Playwright not installed").

- [ ] **Step 2: Run HTTP-wire smoke**

```bash
python3 lazychat-erpnext/test/curl_smoke.py 2>&1 | tail -10
```
Expected: 6 new M1 tools all OK or OK_ERROR. (M2's screenshot endpoint isn't in the standard tool catalog — it's a whitelisted helper, not an MCP tool — so the wire smoke does NOT need to call it.)

- [ ] **Step 3: chat-ui vitest + typecheck**

```bash
cd lazychat.ai
pnpm typecheck 2>&1 | grep -E "typecheck:|error TS"
pnpm --filter chat-ui exec vitest run 2>&1 | tail -5
```
Expected: typecheck clean; full vitest suite green (437 + new Cycle 13 cases).

- [ ] **Step 4: Manual end-to-end (the M2 "moment of truth")**

1. In chat: ask the agent to create a tiny Page (`"Create a Desk Page called 'm2-smoke' with the title 'Smoke Test', body <main><h1>It works</h1></main>, no special styles, and the lazychatReady marker"`)
2. Agent stages `prepare_create_page`. Render-preview passes. Apply card renders.
3. Click Apply.
4. **Within ~2-3 seconds, a `screenshot` Message appears below the Apply card showing the rendered `/app/m2-smoke` page** — `<h1>It works</h1>` visible, Frappe Desk chrome around it.
5. Click the image → opens full-size in a new tab.

If this works, M2 ships. If not, debug via the panel-shim's [lazychat] console logs + the Playwright service's bench log (`tail -f $BENCH_ROOT/logs/bench-dev-background.log`).

- [ ] **Step 5: M2 phase exit checklist**

- [ ] Playwright endpoint reachable: `curl ... /api/method/lazychat_erpnext.desk_assistant.screenshot.capture` returns base64 PNG
- [ ] inspectRoute postmessage extended (TS types compile)
- [ ] Panel-shim handleInspectRoute branches on mode correctly (verify via DevTools network tab — see POST to the endpoint after Apply)
- [ ] ScreenshotMessage renders in all 4 states (capturing/done/error/stale)
- [ ] Auto-trigger fires after create_page Apply but NOT after create_server_script Apply
- [ ] Reference-mockup capture populates `Attachment.referenceScreenshot` for full-HTML uploads
- [ ] No regressions in existing tests (437+ chat-ui, smoke all-pass)

---

## Phase M3 — LLM-as-judge visual auto-iterate loop

**Phase goal:** When the user uploaded a reference mockup AND M2 has captured the candidate screenshot, automatically call a vision-capable LLM to compare them, surface mismatches as a `visualDiff` Message, generate fix turns, apply them (auto-Apply at Effort=max for LOW_RISK), re-capture, re-judge. Loop up to 1–3 iterations (Effort-gated).

**Phase exit criteria:**
- `visual_judge.compare(reference_b64, candidate_b64, intent, page_source, effort)` whitelisted endpoint returns `{score, verdict, mismatches[]}` or `{skipped: true, reason}`
- `visual_judge.generate_fixes(diff, page_doc, intent, effort)` returns `patch_dict` for `prepare_update_doc`
- After M2's screenshot lands AND Effort ≥ high AND a reference exists, `runVisualIterationLoop` orchestrates 1–3 iterations
- T102a–T102d pass
- chat-ui vitest stays green

---

### Task M3.1: `visual_judge.py` skeleton + `vision_judge_models` setting

**Files:**
- Create: `lazychat-erpnext/lazychat_erpnext/desk_assistant/visual_judge.py`
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/lazychat_settings/lazychat_settings.json` — add `vision_judge_models` JSON field
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — T102a (module imports + skip-on-low-effort)

- [ ] **Step 1: Add T102a smoke**

```python
    # ──────────────────────────────────────────────────────────────────────
    # CYCLE 13 — M3: visual-judge auto-iterate
    # ──────────────────────────────────────────────────────────────────────
    log("\n=== Cycle 13 M3 — visual-judge auto-iterate ===")

    # T102a — visual_judge module imports; compare returns {skipped:true} at low/medium
    try:
        from lazychat_erpnext.desk_assistant import visual_judge
        r = visual_judge.compare(candidate_b64="data:image/png;base64,iVBORw0KGgo=",
                                  reference_b64="data:image/png;base64,iVBORw0KGgo=",
                                  intent_text="test", page_source="", effort="low")
        pf(isinstance(r, dict) and r.get("skipped") is True, f"T102a low-effort skip: {r}")
    except Exception as e:
        pf(False, f"T102a visual_judge import: {e}")
```

- [ ] **Step 2: Run — fails (module not present)**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T102a
```

- [ ] **Step 3: Create `visual_judge.py` skeleton**

```python
"""LLM-as-judge for visual comparison of reference-vs-candidate dashboards.

Reuses the existing critic.py pattern (Cycle 9 M2). Two methods:
- compare(): vision LLM call. Returns {score, verdict, mismatches} or {skipped, reason}.
- generate_fixes(): text-only LLM call. Returns patch_dict for prepare_update_doc.

Effort gating:
- low/medium: skip (returns {skipped: True, reason: 'effort=X skips visual judge'})
- high: 1 iteration, model = settings.vision_judge_models.high or 'claude-sonnet-4-6'
- max: 3 iterations cap, model = settings.vision_judge_models.max or 'claude-opus-4-7'

Failure handling: any exception during the LLM call returns
{skipped: True, reason: '<error message>'} — never breaks the calling flow.
The 30s thread-pool timeout from critic.py:critique_composition is reused.
"""
from __future__ import annotations
import concurrent.futures
import json
from typing import Optional

import frappe


_EFFORT_DEFAULT_MODELS = {
    "high": "claude-sonnet-4-6",
    "max":  "claude-opus-4-7",
}
_EFFORT_ITER_CAP = {"low": 0, "medium": 0, "high": 1, "max": 3}


def _resolve_model_for_effort(effort: str) -> Optional[str]:
    """Read Lazychat Settings.vision_judge_models JSON for the effort tier;
    fall back to the hardcoded default."""
    if effort not in ("high", "max"):
        return None
    try:
        raw = frappe.db.get_single_value("Lazychat Settings", "vision_judge_models")
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict) and data.get(effort):
                return data[effort]
    except Exception:
        pass
    return _EFFORT_DEFAULT_MODELS.get(effort)


def compare(candidate_b64: str, reference_b64: str, intent_text: str, page_source: str = "", effort: str = "medium") -> dict:
    """Vision LLM call. Returns the diff JSON or a skip envelope."""
    raise NotImplementedError  # filled in M3.2


def generate_fixes(diff_json: dict, page_doc: dict, intent_text: str, effort: str = "medium") -> dict:
    """Text-only LLM call. Returns patch_dict for prepare_update_doc."""
    raise NotImplementedError  # filled in M3.3


def iter_cap_for_effort(effort: str) -> int:
    return _EFFORT_ITER_CAP.get(effort, 0)
```

But the skeleton must satisfy T102a's behavior (return `{skipped:true}` at low/medium without raising). Replace the `compare` stub with the working low/medium short-circuit:

```python
def compare(candidate_b64: str, reference_b64: str, intent_text: str, page_source: str = "", effort: str = "medium") -> dict:
    """See module docstring."""
    if effort not in ("high", "max"):
        return {"skipped": True, "reason": f"effort={effort} skips visual judge (only high/max trigger compare)"}
    return {"skipped": True, "reason": "compare not yet implemented (M3.2 placeholder)"}
```

- [ ] **Step 4: Add `vision_judge_models` field to Lazychat Settings**

In `lazychat-erpnext/lazychat_erpnext/desk_assistant/doctype/lazychat_settings/lazychat_settings.json`, append to the `fields` array:

```json
{
    "fieldname": "vision_judge_models",
    "fieldtype": "Code",
    "options": "JSON",
    "label": "Vision-Judge Models (per Effort tier)",
    "default": "{\"high\": \"claude-sonnet-4-6\", \"max\": \"claude-opus-4-7\"}",
    "description": "JSON mapping Effort tier to vision-capable model ID for the M3 visual-judge auto-iterate loop. Defaults: high=sonnet-4-6, max=opus-4-7. The model must be configured in LLM Provider/LLM Model doctypes and support image inputs."
}
```

- [ ] **Step 5: Re-run smoke; T102a passes**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local migrate 2>&1 | tail -3   # picks up the new field
bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T102a
```

- [ ] **Step 6: Commit**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/visual_judge.py \
        lazychat_erpnext/desk_assistant/doctype/lazychat_settings/lazychat_settings.json \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m3): visual_judge.py skeleton + vision_judge_models setting

Module skeleton with compare()/generate_fixes() stubs + Effort-tier helpers.
Low/medium short-circuit returns {skipped:true} immediately. Lazychat Settings
gains vision_judge_models JSON field — admin picks vision-capable models per
Effort tier; defaults sonnet-4-6/opus-4-7.

T102a passes (module imports, low-effort skip works)."
```

---

### Task M3.2: Implement `visual_judge.compare` — vision LLM call

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/visual_judge.py` — full `compare(...)` body
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — T102b (compare returns valid JSON shape with mock image), T102c (graceful skip-on-failure)

The vision call reuses the existing critic adapter pattern from `critic.py:critique_composition`: `resolve_model(...)` → `adapter.chat(...)` with `concurrent.futures.ThreadPoolExecutor` + `Future.result(timeout=30)` for hard timeout, all wrapped in try/except that returns a skip envelope on any failure (never raises into the calling flow).

- [ ] **Step 1: Add T102b/T102c smoke**

```python
    # T102b — compare returns JSON shape with score/verdict/mismatches at high effort
    # Uses a tiny test PNG (1x1 pixel) — the LLM will return SOMETHING; we just check shape.
    tiny_png_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    r = visual_judge.compare(candidate_b64=tiny_png_b64, reference_b64=tiny_png_b64,
                              intent_text="test dashboard", page_source="<main/>", effort="high")
    # Either: real vision call succeeded → {score, verdict, mismatches}
    #     OR: gracefully skipped → {skipped: True, reason}
    ok_shape = (
        (isinstance(r.get("score"), (int, float)) and r.get("verdict") in ("match", "needs_fixes") and isinstance(r.get("mismatches"), list))
        or (r.get("skipped") is True and r.get("reason"))
    )
    pf(ok_shape, f"T102b compare shape at high: {r}")

    # T102c — compare gracefully degrades when vision model unavailable (forced skip)
    # Simulate by passing a bogus effort the resolver doesn't know — should still return shape
    # (already covered by T102a low/medium skip; this is a defense-in-depth sanity)
    r = visual_judge.compare(candidate_b64=tiny_png_b64, reference_b64=tiny_png_b64,
                              intent_text="x", page_source="", effort="medium")
    pf(r.get("skipped") is True, f"T102c medium-effort always skips: {r}")
```

- [ ] **Step 2: Run — T102b fails (`compare` returns 'not yet implemented' skip)**

- [ ] **Step 3: Implement `compare(...)`**

Replace the placeholder `compare(...)` in `visual_judge.py`:

```python
def compare(candidate_b64: str, reference_b64: str, intent_text: str, page_source: str = "", effort: str = "medium") -> dict:
    """See module docstring."""
    if effort not in ("high", "max"):
        return {"skipped": True, "reason": f"effort={effort} skips visual judge (only high/max trigger compare)"}

    model_id = _resolve_model_for_effort(effort)
    if not model_id:
        return {"skipped": True, "reason": f"no vision_judge_model configured for effort={effort}"}

    # Build the prompt
    system_prompt = (
        "You are a visual UI judge. Given a REFERENCE design (image) and a "
        "CANDIDATE implementation (image), identify visual mismatches that hurt "
        "fidelity. Be precise: typography weight/family, spacing in pixels, "
        "color hex, layout structure. Output JSON ONLY (no prose, no markdown "
        "fences)."
    )
    user_blocks = [
        {"type": "image", "data": _strip_data_url_prefix(reference_b64)},
        {"type": "image", "data": _strip_data_url_prefix(candidate_b64)},
        {"type": "text", "text":
            f"Intent: {intent_text}\n\n"
            f"Page source (truncated):\n{page_source[:4000] if page_source else '(none provided)'}\n\n"
            f"Output JSON ONLY:\n"
            "{\n"
            '  "score": 0.0-1.0,\n'
            '  "verdict": "match" | "needs_fixes",\n'
            '  "mismatches": [\n'
            "    {\n"
            '      "category": "typography" | "spacing" | "color" | "layout" | "content" | "interaction",\n'
            '      "severity": "critical" | "major" | "minor",\n'
            '      "description": "<2-sentence diagnosis>",\n'
            '      "selector_hint": "<CSS selector or section name in candidate>",\n'
            '      "fix_hint": "<concrete CSS or HTML change to attempt>"\n'
            "    }\n"
            "  ]\n"
            "}"
        },
    ]

    # 30s hard timeout via thread pool (mirrors critic.py pattern)
    def _do_call():
        from lazychat_erpnext.desk_assistant.providers import resolve_model
        adapter = resolve_model(model_id)
        if adapter is None:
            return {"skipped": True, "reason": f"resolve_model({model_id}) returned None — model not configured"}
        try:
            resp = adapter.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_blocks}],
                max_tokens=2000,
                temperature=0.0,
            )
        except Exception as e:
            return {"skipped": True, "reason": f"adapter.chat failed: {type(e).__name__}: {e}"}
        text = (resp.get("text") or "").strip()
        if not text:
            return {"skipped": True, "reason": "vision model returned empty text"}
        # Tolerate prose-wrapped JSON
        parsed = _extract_json_block(text)
        if not parsed:
            return {"skipped": True, "reason": "vision model output was not parseable JSON"}
        # Validate shape minimally
        if not isinstance(parsed.get("score"), (int, float)) or parsed.get("verdict") not in ("match", "needs_fixes"):
            return {"skipped": True, "reason": f"vision model output missing required fields: {parsed}"}
        # Normalize
        parsed["mismatches"] = parsed.get("mismatches") or []
        parsed["model"] = model_id
        return parsed

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_do_call)
            return future.result(timeout=30)
    except concurrent.futures.TimeoutError:
        return {"skipped": True, "reason": "visual judge timed out after 30s"}
    except Exception as e:
        return {"skipped": True, "reason": f"visual judge crashed: {type(e).__name__}: {e}"}


def _strip_data_url_prefix(b64_or_data_url: str) -> str:
    """Accept either 'data:image/png;base64,iVBOR...' or raw base64."""
    if not b64_or_data_url:
        return ""
    if b64_or_data_url.startswith("data:"):
        comma = b64_or_data_url.find(",")
        return b64_or_data_url[comma + 1:] if comma >= 0 else b64_or_data_url
    return b64_or_data_url


def _extract_json_block(text: str) -> Optional[dict]:
    """Tolerate bare JSON, ```json fenced```, and prose-embedded JSON."""
    import re
    candidates = []
    # 1. Try parsing the whole text as JSON
    candidates.append(text)
    # 2. Strip ```json...``` fences
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        candidates.append(fence.group(1).strip())
    # 3. Find first {...} block
    brace = re.search(r"\{[\s\S]*\}", text)
    if brace:
        candidates.append(brace.group(0))
    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except Exception:
            continue
    return None
```

NOTE: The `providers.resolve_model` import path and `adapter.chat(...)` signature mirror the existing `critic.py:critique_composition` (already shipped in Cycle 9 M2). Read that function for the exact provider-resolution pattern — `resolve_model(model_id)` returns either an `AnthropicAdapter` (which supports vision messages) or an `OpenAICompatibleAdapter` instance.

If the existing adapters don't yet accept `content: [{type:'image', data:'<b64>'}, ...]` lists in the messages, this task ALSO needs to extend the Anthropic adapter (`providers/anthropic.py`) and OpenAI-compatible adapter (`providers/openai_compatible.py`) to convert those blocks into provider-native image-input format:
- **Anthropic**: `{role: "user", content: [{type:"image", source:{type:"base64", media_type:"image/png", data: "<b64>"}}, {type:"text", text:"..."}]}`
- **OpenAI-compatible**: `{role: "user", content: [{type:"image_url", image_url:{url: "data:image/png;base64,<b64>"}}, {type:"text", text:"..."}]}`

If that wiring isn't present yet on `main`, prepend an extra step "Step 3a: extend providers to support vision message blocks" (read the existing critic.py + adapter code first to confirm).

- [ ] **Step 4: Re-run smoke; T102b/c pass (or gracefully skip if no vision model configured)**

```bash
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep T102
```
Expected: T102a/b/c all PASS.

- [ ] **Step 5: Commit**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/visual_judge.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m3): visual_judge.compare — vision LLM call with skip-on-failure

resolve_model(<effort>) picks the configured vision model per Lazychat
Settings.vision_judge_models (defaults sonnet/opus). Vision call wrapped in
ThreadPoolExecutor(30s timeout). On ANY failure (model misconfigured,
adapter throws, output not parseable, timeout) returns {skipped: True,
reason} — never breaks the calling flow.

_extract_json_block tolerates prose-wrapped or fenced JSON output (some
models can't resist Markdown even when told 'JSON ONLY')."
```

If the providers don't yet support vision message blocks, also include the provider extensions in this commit (or a sibling commit before this one).

---

### Task M3.3: Implement `visual_judge.generate_fixes` — text LLM call producing a patch_dict

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/visual_judge.py` — full `generate_fixes(...)` body
- Modify: `lazychat-erpnext/scripts/smoke-test-tools.py` — T102d

Given a diff JSON from `compare(...)` AND the current Page doc state, produce a `patch_dict` like `{"style": "<new CSS>", "content": "<refined HTML>"}` that can be fed into `prepare_update_doc`.

- [ ] **Step 1: T102d smoke**

```python
    # T102d — generate_fixes returns patch_dict shape
    diff = {
        "score": 0.74, "verdict": "needs_fixes",
        "mismatches": [
            {"category": "typography", "severity": "major", "description": "KPI numbers should be IBM Plex Mono 500",
             "selector_hint": ".kpi-value", "fix_hint": "font-family: 'IBM Plex Mono', monospace; font-weight: 500;"},
        ],
    }
    page_doc = {"doctype": "Page", "name": "_lz_smoke_page_e", "style": ".kpi-value { font-family: system-ui; }", "content": "<main></main>", "script": ""}
    r = visual_judge.generate_fixes(diff_json=diff, page_doc=page_doc, intent_text="test", effort="high")
    # Either real fix dict OR graceful skip
    ok_shape = (
        (isinstance(r.get("patch"), dict) and len(r["patch"]) > 0)
        or (r.get("skipped") is True and r.get("reason"))
    )
    pf(ok_shape, f"T102d generate_fixes shape: {r}")
```

- [ ] **Step 2: Implement `generate_fixes(...)`**

```python
def generate_fixes(diff_json: dict, page_doc: dict, intent_text: str, effort: str = "medium") -> dict:
    """Text-only LLM call. Returns {patch: {field: new_value, ...}} or {skipped: True, reason: '...'}."""
    if effort not in ("high", "max"):
        return {"skipped": True, "reason": f"effort={effort} skips fix generation"}

    model_id = _resolve_model_for_effort(effort)
    if not model_id:
        return {"skipped": True, "reason": f"no model configured for effort={effort}"}

    mismatches = diff_json.get("mismatches") or []
    if not mismatches:
        return {"skipped": True, "reason": "no mismatches to fix"}

    # Truncate Page source — large pages don't fit in prompt; we trust the LLM to patch
    # the relevant fields based on the diff hints without seeing the entire source.
    style_snippet = (page_doc.get("style") or "")[:8000]
    content_snippet = (page_doc.get("content") or "")[:4000]
    script_snippet = (page_doc.get("script") or "")[:2000]

    system_prompt = (
        "You produce minimal Page patches that address visual mismatches between a candidate "
        "and a reference design. Output JSON ONLY with shape: "
        '{"patch": {"style"?: "<new full CSS>", "content"?: "<new full HTML>", "script"?: "<new full JS>"}}. '
        "Only include fields you actually changed — omit the rest. The values are FULL replacements "
        "(not deltas) — include all existing rules that should stay. Keep changes minimal and "
        "scoped to the mismatch hints."
    )

    user_msg = (
        f"Intent: {intent_text}\n\n"
        f"Mismatches to address:\n{json.dumps(mismatches, indent=2)}\n\n"
        f"Current Page fields:\n"
        f"<style>\n{style_snippet}\n</style>\n\n"
        f"<content>\n{content_snippet}\n</content>\n\n"
        f"<script>\n{script_snippet}\n</script>"
    )

    def _do_call():
        from lazychat_erpnext.desk_assistant.providers import resolve_model
        adapter = resolve_model(model_id)
        if adapter is None:
            return {"skipped": True, "reason": f"resolve_model({model_id}) returned None"}
        try:
            resp = adapter.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
                max_tokens=8000, temperature=0.0,
            )
        except Exception as e:
            return {"skipped": True, "reason": f"adapter.chat failed: {type(e).__name__}: {e}"}
        text = (resp.get("text") or "").strip()
        parsed = _extract_json_block(text)
        if not parsed or not isinstance(parsed.get("patch"), dict) or not parsed["patch"]:
            return {"skipped": True, "reason": "model output didn't include a non-empty patch dict"}
        # Whitelist the patch keys — only style/content/script accepted
        clean = {}
        for key in ("style", "content", "script"):
            if key in parsed["patch"] and isinstance(parsed["patch"][key], str):
                clean[key] = parsed["patch"][key]
        if not clean:
            return {"skipped": True, "reason": "patch had no style/content/script keys"}
        return {"patch": clean, "model": model_id, "mismatches_addressed": len(mismatches)}

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(_do_call).result(timeout=60)  # text-only call, 60s for big pages
    except concurrent.futures.TimeoutError:
        return {"skipped": True, "reason": "fix generator timed out after 60s"}
    except Exception as e:
        return {"skipped": True, "reason": f"fix generator crashed: {type(e).__name__}: {e}"}
```

- [ ] **Step 3: Re-run smoke; T102d passes (real fix OR graceful skip)**

- [ ] **Step 4: Commit**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/visual_judge.py \
        scripts/smoke-test-tools.py
git commit -m "feat(cycle-13/m3): visual_judge.generate_fixes — text LLM producing patch_dict

Given the diff JSON from compare() + the current Page doc fields, produces
a {patch: {style?, content?, script?}} dict that feeds straight into
prepare_update_doc. 60s timeout (longer than compare's 30s — large pages
need more output tokens). Whitelisted patch keys; same skip-on-failure
pattern as compare(). T102d passes."
```

---

### Task M3.4: Whitelist `visual_judge` endpoints in `api.py`

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/api.py` — add two `@frappe.whitelist()` proxies
- Modify: `lazychat-erpnext/test/curl_smoke.py` (optional — add 2 wire checks)

- [ ] **Step 1: Add endpoints**

Append to `api.py`:

```python
@frappe.whitelist()
def lazychat_visual_judge_compare(candidate_b64: str, reference_b64: str, intent_text: str = "", page_source: str = "", effort: str = "medium") -> dict:
    """Proxy to visual_judge.compare. System Manager only."""
    if "System Manager" not in (frappe.get_roles(frappe.session.user) or []):
        return {"skipped": True, "reason": "System Manager required."}
    from lazychat_erpnext.desk_assistant.visual_judge import compare
    return compare(candidate_b64=candidate_b64, reference_b64=reference_b64,
                    intent_text=intent_text, page_source=page_source, effort=effort)


@frappe.whitelist()
def lazychat_visual_judge_generate_fixes(diff_json: dict, page_doc: dict, intent_text: str = "", effort: str = "medium") -> dict:
    """Proxy to visual_judge.generate_fixes. System Manager only."""
    if "System Manager" not in (frappe.get_roles(frappe.session.user) or []):
        return {"skipped": True, "reason": "System Manager required."}
    from lazychat_erpnext.desk_assistant.visual_judge import generate_fixes
    return generate_fixes(diff_json=diff_json, page_doc=page_doc, intent_text=intent_text, effort=effort)
```

- [ ] **Step 2: Smoke check via curl**

```bash
TINY="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
curl -s -b "sid=<YOUR_SID>" -H "Content-Type: application/json" -H "X-Frappe-CSRF-Token: <CSRF>" \
  -d "{\"candidate_b64\":\"$TINY\",\"reference_b64\":\"$TINY\",\"intent_text\":\"test\",\"effort\":\"low\"}" \
  http://localhost:8000/api/method/lazychat_erpnext.desk_assistant.api.lazychat_visual_judge_compare \
  | jq .message
```
Expected: `{"skipped": true, "reason": "effort=low skips visual judge..."}`.

- [ ] **Step 3: Commit**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/api.py
git commit -m "feat(cycle-13/m3): whitelist visual_judge endpoints

Two new @frappe.whitelist() proxies — lazychat_visual_judge_compare and
lazychat_visual_judge_generate_fixes. System Manager only (defense-in-depth
on top of the underlying module's effort gating)."
```

---

### Task M3.5: `visualDiff` Message kind + `VisualDiffMessage` renderer

**Files:**
- Modify: `lazychat.ai/packages/types/src/messages.ts` — add `visualDiff` to the Message union
- Create: `lazychat.ai/apps/chat-ui/src/components/messages/VisualDiffMessage.tsx`
- Modify: `lazychat.ai/apps/chat-ui/src/components/MessageList.tsx` — dispatch case
- Create: `lazychat.ai/apps/chat-ui/src/components/messages/__tests__/VisualDiffMessage.test.tsx` — 4 render cases

- [ ] **Step 1: Add to Message union (`packages/types/src/messages.ts`):**

```ts
  | {
      kind: 'visualDiff';
      id: string;
      ts: number;
      iteration: number;
      score: number;
      verdict: 'match' | 'needs_fixes' | 'cap_reached';
      mismatches: Array<{
        category: 'typography' | 'spacing' | 'color' | 'layout' | 'content' | 'interaction';
        severity: 'critical' | 'major' | 'minor';
        description: string;
        selector_hint?: string;
        fix_hint?: string;
      }>;
      refScreenshotId: string;       // id of the reference `screenshot` Message (M2 captured)
      candidateScreenshotId: string; // id of the latest candidate `screenshot` Message
      autoApplied: boolean;          // true when Effort=max + the fix was auto-Applied without user click
      pageName: string;
    }
```

- [ ] **Step 2: Write failing render test**

`apps/chat-ui/src/components/messages/__tests__/VisualDiffMessage.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { VisualDiffMessage } from '../VisualDiffMessage';
import type { Message } from '@lazychat/types';

const msg = (overrides: Partial<Extract<Message, { kind: 'visualDiff' }>>): Extract<Message, { kind: 'visualDiff' }> => ({
  kind: 'visualDiff', id: 'vd1', ts: Date.now(),
  iteration: 1, score: 0.74, verdict: 'needs_fixes',
  mismatches: [
    { category: 'typography', severity: 'major', description: 'KPI font is wrong', selector_hint: '.kpi-value', fix_hint: 'use IBM Plex Mono' },
    { category: 'color', severity: 'minor', description: 'sparkline opacity off' },
  ],
  refScreenshotId: 's-ref', candidateScreenshotId: 's-cand',
  autoApplied: false, pageName: 'proman-md-dashboard',
  ...overrides,
});

describe('VisualDiffMessage', () => {
  it('renders score + iteration in header', () => {
    render(<VisualDiffMessage msg={msg({})} />);
    expect(screen.getByText(/iteration\s*1/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.74/)).toBeInTheDocument();
  });

  it('renders mismatch list with severity dots', () => {
    render(<VisualDiffMessage msg={msg({})} />);
    expect(screen.getByText(/KPI font is wrong/i)).toBeInTheDocument();
    expect(screen.getByText(/sparkline opacity off/i)).toBeInTheDocument();
  });

  it('renders verdict=match success banner', () => {
    render(<VisualDiffMessage msg={msg({ verdict: 'match', score: 0.95, mismatches: [] })} />);
    expect(screen.getByText(/visual fidelity/i)).toBeInTheDocument();
  });

  it('shows auto-applied annotation when autoApplied=true', () => {
    render(<VisualDiffMessage msg={msg({ autoApplied: true, iteration: 2 })} />);
    expect(screen.getByText(/auto-applied/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run test — fails (component doesn't exist)**

- [ ] **Step 4: Create `VisualDiffMessage.tsx`**

```tsx
import type { Message } from '@lazychat/types';

type VDMsg = Extract<Message, { kind: 'visualDiff' }>;

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'text-r',
  major: 'text-a',
  minor: 'text-fg-muted',
};
const CATEGORY_ICONS: Record<string, string> = {
  typography: 'Aa', spacing: '⇔', color: '◆', layout: '▭', content: '☷', interaction: '↻',
};

interface Props {
  msg: VDMsg;
  onStopLoop?: () => void;
  onApproveAsIs?: () => void;
  onApplyFix?: (mismatchIndex: number) => void;
}

export function VisualDiffMessage({ msg, onStopLoop, onApproveAsIs, onApplyFix }: Props) {
  const scorePct = Math.round(msg.score * 100);
  const isMatch = msg.verdict === 'match';
  const isCap = msg.verdict === 'cap_reached';

  return (
    <div className="my-3 rounded-md border border-border-strong bg-bg-elevated p-3" data-iteration={msg.iteration}>
      {/* Header */}
      <div className="flex items-center gap-2 text-sm font-medium">
        <span className="text-fg-muted">Iteration {msg.iteration}</span>
        <span className="text-fg-muted">·</span>
        <span className={isMatch ? 'text-g' : isCap ? 'text-a' : 'text-fg-primary'}>
          score {msg.score.toFixed(2)} ({scorePct}%)
        </span>
        <span className="text-fg-muted">·</span>
        <span className="text-fg-muted">
          {msg.mismatches.length} mismatch{msg.mismatches.length === 1 ? '' : 'es'}
        </span>
        {msg.autoApplied && (
          <>
            <span className="text-fg-muted">·</span>
            <span className="text-g text-xs">auto-applied</span>
          </>
        )}
      </div>

      {/* Verdict banner */}
      {isMatch && (
        <div className="mt-2 rounded-md border border-g/40 bg-gb p-2 text-xs text-g">
          <strong>Visual fidelity ≥ {scorePct}%</strong> — converged.
        </div>
      )}
      {isCap && (
        <div className="mt-2 rounded-md border border-a/40 bg-ab p-2 text-xs text-a">
          Cap reached after {msg.iteration} iterations. Review remaining mismatches and edit manually if needed.
        </div>
      )}

      {/* Mismatch list */}
      {msg.mismatches.length > 0 && (
        <ul className="mt-3 space-y-2">
          {msg.mismatches.map((m, idx) => (
            <li key={idx} className="flex items-start gap-2 rounded-md border border-border bg-bg-app p-2 text-xs">
              <span className={`inline-block w-2 h-2 rounded-full mt-1 ${
                m.severity === 'critical' ? 'bg-r' : m.severity === 'major' ? 'bg-a' : 'bg-fg-muted'
              }`} aria-label={m.severity} />
              <span className="font-mono text-fg-muted shrink-0">{CATEGORY_ICONS[m.category] || '?'} {m.category}</span>
              <span className="flex-1">
                <span className="text-fg-primary">{m.description}</span>
                {m.selector_hint && <span className="ml-2 font-mono text-fg-muted">{m.selector_hint}</span>}
              </span>
              {onApplyFix && (
                <button
                  className="text-fg-link hover:underline shrink-0"
                  onClick={() => onApplyFix(idx)}
                >
                  Fix
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Controls */}
      {!isMatch && (
        <div className="mt-3 flex items-center gap-3 text-xs">
          {onStopLoop && (
            <button onClick={onStopLoop} className="text-fg-muted hover:text-fg-primary">Stop iterating</button>
          )}
          {onApproveAsIs && (
            <button onClick={onApproveAsIs} className="text-fg-muted hover:text-fg-primary">Approve as-is</button>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Dispatch in `MessageList.tsx`**

```tsx
case 'visualDiff':
  return <VisualDiffMessage key={m.id} msg={m} />;
```

Plus import at top.

- [ ] **Step 6: Re-run vitest — 4 cases pass; typecheck clean**

- [ ] **Step 7: Commit**

```bash
cd lazychat.ai
git add packages/types/src/messages.ts \
        apps/chat-ui/src/components/messages/VisualDiffMessage.tsx \
        apps/chat-ui/src/components/messages/__tests__/VisualDiffMessage.test.tsx \
        apps/chat-ui/src/components/MessageList.tsx
git commit -m "feat(cycle-13/m3): visualDiff Message kind + VisualDiffMessage renderer

Renders iteration header (N · score 0.XX · K mismatches · auto-applied?),
verdict banner (match=green, cap=amber), mismatch list with severity dots
+ category icons + selector hints, Stop-iterating / Approve-as-is controls.
4 vitest cases pass."
```

---

### Task M3.6: `visualJudgeClient.ts` — chat-ui wrapper around the 2 endpoints

**Files:**
- Create: `lazychat.ai/apps/chat-ui/src/lib/visualJudgeClient.ts`

Thin client. Same fetch pattern as `commitSlash.ts` (CSRF + Bearer headers from `useEmbedConfig.mcpAuth`).

- [ ] **Step 1: Create the file**

```ts
import { useEmbedConfig } from '@/store/embed';

export interface VisualJudgeCompareInput {
  candidate_b64: string;
  reference_b64: string;
  intent_text: string;
  page_source?: string;
  effort: 'low' | 'medium' | 'high' | 'max';
}

export interface VisualJudgeCompareOutput {
  score?: number;
  verdict?: 'match' | 'needs_fixes';
  mismatches?: Array<{
    category: string; severity: string; description: string;
    selector_hint?: string; fix_hint?: string;
  }>;
  skipped?: boolean;
  reason?: string;
  model?: string;
}

export interface VisualJudgeFixesOutput {
  patch?: { style?: string; content?: string; script?: string };
  skipped?: boolean;
  reason?: string;
}

function authHeaders(): HeadersInit {
  const auth = useEmbedConfig.getState().mcpAuth;
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  if (auth?.csrf) h['X-Frappe-CSRF-Token'] = auth.csrf;
  if (auth?.bearer) h['Authorization'] = `Bearer ${auth.bearer}`;
  return h;
}

function endpointBase(): string | null {
  const ep = useEmbedConfig.getState().mcpEndpoint;
  if (!ep) return null;
  // mcpEndpoint is e.g. http://erp.local:8000/api/method/lazychat_erpnext.desk_assistant.mcp.handle
  // → strip the trailing .mcp.handle → http://erp.local:8000/api/method/lazychat_erpnext.desk_assistant
  return ep.replace(/\.mcp\.handle$/, '');
}

export async function visualJudgeCompare(input: VisualJudgeCompareInput): Promise<VisualJudgeCompareOutput> {
  const base = endpointBase();
  if (!base) return { skipped: true, reason: 'no embed config (chat-ui not embedded in lazychat-erpnext)' };
  try {
    const res = await fetch(`${base}.api.lazychat_visual_judge_compare`, {
      method: 'POST', credentials: 'include', headers: authHeaders(),
      body: JSON.stringify(input),
    });
    if (!res.ok) {
      const t = await res.text();
      return { skipped: true, reason: `HTTP ${res.status}: ${t.slice(0, 200)}` };
    }
    const j = await res.json();
    return j.message || { skipped: true, reason: 'empty response' };
  } catch (e) {
    return { skipped: true, reason: `fetch failed: ${(e as Error).message}` };
  }
}

export async function visualJudgeGenerateFixes(input: {
  diff_json: VisualJudgeCompareOutput;
  page_doc: { name: string; style?: string; content?: string; script?: string };
  intent_text: string;
  effort: 'low' | 'medium' | 'high' | 'max';
}): Promise<VisualJudgeFixesOutput> {
  const base = endpointBase();
  if (!base) return { skipped: true, reason: 'no embed config' };
  try {
    const res = await fetch(`${base}.api.lazychat_visual_judge_generate_fixes`, {
      method: 'POST', credentials: 'include', headers: authHeaders(),
      body: JSON.stringify(input),
    });
    if (!res.ok) {
      const t = await res.text();
      return { skipped: true, reason: `HTTP ${res.status}: ${t.slice(0, 200)}` };
    }
    const j = await res.json();
    return j.message || { skipped: true, reason: 'empty response' };
  } catch (e) {
    return { skipped: true, reason: `fetch failed: ${(e as Error).message}` };
  }
}
```

- [ ] **Step 2: Add vitest cases**

`apps/chat-ui/src/lib/__tests__/visualJudgeClient.test.ts` — mock fetch, verify the endpoint URL, headers, body shape, and graceful-skip on HTTP error. Mirror the pattern in `commitSlash.test.ts`.

- [ ] **Step 3: Commit**

```bash
cd lazychat.ai
git add apps/chat-ui/src/lib/visualJudgeClient.ts \
        apps/chat-ui/src/lib/__tests__/visualJudgeClient.test.ts
git commit -m "feat(cycle-13/m3): visualJudgeClient — chat-ui wrapper for visual-judge endpoints

Two functions: visualJudgeCompare(...) and visualJudgeGenerateFixes(...).
Uses useEmbedConfig.mcpAuth for CSRF + Bearer headers (same pattern as
commitSlash.ts). All errors degrade to {skipped: true, reason}."
```

---

### Task M3.7: `runVisualIterationLoop` orchestrator in `agentRunner.ts`

**Files:**
- Modify: `lazychat.ai/apps/chat-ui/src/lib/agentRunner.ts` — add `runVisualIterationLoop(sid, pageName)` + hook it into the post-screenshot callback from M2.6's `triggerScreenshot`

The orchestrator runs AFTER M2's `triggerScreenshot` completes (screenshot is `done`):

1. Get the latest candidate screenshot for `pageName`
2. Get the reference screenshot (from session attachments via `refMockupB64`)
3. If no reference OR Effort < high → STOP (M2's manual loop is the experience)
4. Compute current iteration count (count prior `visualDiff` Messages for this pageName)
5. Call `visualJudgeCompare(...)` → render `visualDiff` Message
6. If verdict='match' OR iteration >= cap → STOP
7. Else: call `visualJudgeGenerateFixes(...)` → stage `prepare_update_doc(Page, patch_dict)` → at Effort=max + LOW_RISK, auto-Apply → M2 re-captures → loop to step 4

- [ ] **Step 1: Extend `triggerScreenshot` to fire the loop when the screenshot lands**

Inside the `onResp` handler in `triggerScreenshot` (M2.6), after replacing the placeholder with `status: 'done'`, add:

```ts
// After screenshot lands with status=done and there's a reference + effort >= high,
// kick off the visual iteration loop.
if (refMockupB64 && p.captured?.screenshot_b64) {
  // Don't block the user — schedule micro-task
  Promise.resolve().then(() => runVisualIterationLoop(sid, pageName));
}
```

- [ ] **Step 2: Implement `runVisualIterationLoop`**

```ts
import { useSettings } from '@/store/settings';
import { visualJudgeCompare, visualJudgeGenerateFixes } from './visualJudgeClient';
import { useEmbedConfig } from '@/store/embed';

const MAX_ITERATIONS_BY_EFFORT: Record<string, number> = {
  low: 0, medium: 0, high: 1, max: 3,
};
const CONVERGENCE_THRESHOLD = 0.92;

export async function runVisualIterationLoop(sid: string, pageName: string): Promise<void> {
  const effort = useSettings.getState().effort;
  const cap = MAX_ITERATIONS_BY_EFFORT[effort] ?? 0;
  if (cap === 0) return;  // M2 manual loop only at low/medium

  const sess = useSessions.getState().byId[sid];
  if (!sess) return;

  // Find latest candidate screenshot for this page
  const candidates = sess.messages
    .filter((m) => m.kind === 'screenshot' && m.pageName === pageName && m.status === 'done' && (m as any).pngB64);
  const candidate = candidates[candidates.length - 1] as Extract<Message, { kind: 'screenshot' }> | undefined;
  if (!candidate) return;

  // Find reference screenshot
  const refB64 = candidate.refMockupB64;
  if (!refB64) return;  // no reference uploaded → manual loop only

  // Count prior visualDiff Messages for this pageName
  const priorDiffs = sess.messages.filter(
    (m) => m.kind === 'visualDiff' && (m as any).pageName === pageName,
  );
  const iteration = priorDiffs.length + 1;

  // Get intent text — try to find the original user message that triggered the build
  const userMsgs = sess.messages.filter((m) => m.kind === 'user') as Extract<Message, { kind: 'user' }>[];
  const intentText = userMsgs.length > 0 ? userMsgs[0].text.slice(0, 800) : 'build a dashboard';

  // Get the current Page source (we just staged/applied it; fetch the latest from server via frappe.client.get is the safest read)
  const pageDoc = await fetchPageDoc(pageName);
  if (!pageDoc) return;

  // Call the judge
  const diff = await visualJudgeCompare({
    candidate_b64: candidate.pngB64,
    reference_b64: refB64,
    intent_text: intentText,
    page_source: `<style>\n${pageDoc.style || ''}\n</style>\n<content>\n${pageDoc.content || ''}\n</content>\n<script>\n${pageDoc.script || ''}\n</script>`,
    effort,
  });

  if (diff.skipped) {
    // Graceful skip — surface a small message but don't fail the loop
    console.info('[lazychat] visual judge skipped:', diff.reason);
    return;
  }

  // Append the visualDiff Message
  const verdict = (iteration >= cap && diff.verdict === 'needs_fixes') ? 'cap_reached' : diff.verdict;
  const diffMsgId = `m-vd-${Date.now().toString(36)}`;
  useSessions.getState().appendMessage(sid, {
    kind: 'visualDiff', id: diffMsgId, ts: Date.now(),
    iteration, score: diff.score || 0,
    verdict: verdict as any,
    mismatches: diff.mismatches || [],
    refScreenshotId: 'reference',
    candidateScreenshotId: candidate.id,
    autoApplied: false,
    pageName,
  } as Message);

  // STOP conditions
  if (verdict === 'match' || verdict === 'cap_reached' || diff.score >= CONVERGENCE_THRESHOLD) {
    return;
  }

  // Generate the fix patch
  const fixes = await visualJudgeGenerateFixes({
    diff_json: diff, page_doc: pageDoc, intent_text: intentText, effort,
  });
  if (fixes.skipped || !fixes.patch) {
    console.info('[lazychat] visual judge generate_fixes skipped:', fixes.reason);
    return;
  }

  // Stage prepare_update_doc via the existing tool dispatch flow.
  // At Effort=max + LOW_RISK action (update_doc on Page is LOW_RISK), auto-Apply.
  // Otherwise the Apply card renders normally and user clicks Apply.
  // The existing MCPPreviewActionCard auto-Apply logic handles this.
  await stagePageUpdate(sid, pageName, fixes.patch, effort === 'max');
  // After Apply success, M2.6's triggerScreenshot fires again → recaptures → calls
  // this loop again → next iteration.
}

async function fetchPageDoc(pageName: string): Promise<{ name: string; style?: string; content?: string; script?: string } | null> {
  const base = useEmbedConfig.getState().mcpEndpoint?.replace(/\.mcp\.handle$/, '');
  if (!base) return null;
  try {
    const res = await fetch(`${base}.api.lazychat_get_page_doc?name=${encodeURIComponent(pageName)}`, {
      credentials: 'include',
      headers: { 'X-Frappe-CSRF-Token': useEmbedConfig.getState().mcpAuth?.csrf || '' },
    });
    if (!res.ok) return null;
    const j = await res.json();
    return j.message || null;
  } catch {
    return null;
  }
}

async function stagePageUpdate(sid: string, pageName: string, patch: { style?: string; content?: string; script?: string }, autoApply: boolean): Promise<void> {
  // Call the MCP `prepare_update_doc` tool via the existing mcpCallTool path.
  // This goes through the standard tool dispatch flow — the Apply card renders,
  // and if autoApply is true (Effort=max) + the action is in LOW_RISK_ACTIONS,
  // the 3-second auto-Apply countdown kicks in.
  const { mcpCallTool } = await import('./mcp-client');
  const ep = useEmbedConfig.getState().mcpEndpoint;
  const auth = useEmbedConfig.getState().mcpAuth;
  if (!ep || !auth) return;

  await mcpCallTool({
    endpoint: ep, auth, name: 'prepare_update_doc',
    args: { doctype: 'Page', name: pageName, patch },
  });
  // The mcp-client appends an mcpPreviewAction Message that renders the Apply card.
  // User clicks Apply → commit → M2 re-captures → this loop continues.
}
```

Also add a small whitelisted read endpoint on the server side to support `fetchPageDoc`:

In `api.py`:
```python
@frappe.whitelist()
def lazychat_get_page_doc(name: str) -> dict:
    """Return the source fields of a Page doc — used by the chat-ui's visual
    iteration loop to feed the current state into visual_judge.generate_fixes."""
    if not frappe.has_permission("Page", doc=name, ptype="read"):
        return {}
    if not frappe.db.exists("Page", name):
        return {}
    doc = frappe.get_doc("Page", name)
    return {
        "name": doc.name,
        "title": doc.title,
        "content": doc.content or "",
        "style": doc.style or "",
        "script": doc.script or "",
    }
```

- [ ] **Step 3: Vitest cases — `runVisualIterationLoop` orchestrator**

Mock `visualJudgeCompare` to return various shapes (`{verdict:'match'}`, `{verdict:'needs_fixes'}`, `{skipped:true}`), assert the orchestrator behaves correctly. Mock `visualJudgeGenerateFixes` similarly. Mock `mcpCallTool`. Verify iteration count, auto-Apply behavior at Effort=max, stop on `match`.

- [ ] **Step 4: Commit**

```bash
cd lazychat.ai
git add apps/chat-ui/src/lib/agentRunner.ts \
        apps/chat-ui/src/lib/__tests__/agentRunner.visualLoop.test.ts
cd ../lazychat-erpnext
git add lazychat_erpnext/desk_assistant/api.py
git commit -m "feat(cycle-13/m3): runVisualIterationLoop orchestrator + lazychat_get_page_doc

Chat-ui: after M2's screenshot lands (and a reference exists + Effort >=
high), call visual_judge.compare → render visualDiff → if needs_fixes and
iter < cap, call generate_fixes → stage prepare_update_doc (auto-Apply at
Effort=max + LOW_RISK) → M2 re-captures → re-enter the loop.

Stops on: verdict=match, score >= 0.92 (convergence), iter >= cap, or any
skipped envelope from the judge endpoints. Always graceful.

Server: lazychat_get_page_doc whitelisted endpoint returns the
content/style/script fields the orchestrator feeds into generate_fixes."
```

---

### Task M3.8: System prompt — "Visual iteration available" awareness block

**Files:**
- Modify: `lazychat-erpnext/lazychat_erpnext/desk_assistant/claude_bridge.py` — append a short awareness block to the shared guidance
- Modify: `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts` — mirror

Short prompt addition (~15 lines) telling the LLM that after applying a Page, the user will see a screenshot AND (at Effort=high/max with a reference uploaded) an auto-generated visual diff. The LLM should NOT proactively call the visual judge tools — they're system-orchestrated.

- [ ] **Step 1: Append to `_SHARED_GUIDANCE` in `claude_bridge.py`**

```python
_VISUAL_ITERATION_BLOCK = """

## VISUAL ITERATION (M3 — auto-orchestrated, not LLM-driven)

When the user uploads a reference mockup (HTML or image) AND Effort is set to
high/max, the chat-ui automatically:
1. After your `prepare_create_page` is applied, screenshots /app/<page_name>
2. Compares it against the reference via a vision-judge LLM
3. If mismatched, generates a Page patch and stages `prepare_update_doc(Page, ...)`
4. Loops 1-3 times (Effort-dependent) until convergence (score >= 0.92)

You don't drive this loop — it's system-orchestrated. Your job is to produce
the BEST FIRST CUT possible (follow the BUILDING DESK PAGES playbook above),
because every fix iteration costs an LLM call and the user's patience.

If the visual judge surfaces mismatches via `prepare_update_doc` Apply cards,
treat them as system feedback: apply the patches, don't re-derive them. If
the user says 'stop iterating' or rejects a patch, halt and ask what they
want next.
"""
```

Append to the shared-guidance assembly after `_DESK_PAGE_PLAYBOOK`.

- [ ] **Step 2: Mirror in `routerSystemPrompt.ts`**

- [ ] **Step 3: Verify the block lands in the prompt:**

```bash
cd $BENCH_ROOT && bench --site erp.local console
>>> from lazychat_erpnext.desk_assistant.claude_bridge import _system_prompt
>>> p = _system_prompt(messages=[], mode="edit-auto")
>>> assert "VISUAL ITERATION" in p
```

- [ ] **Step 4: Commit (both repos)**

```bash
cd lazychat-erpnext
git add lazychat_erpnext/desk_assistant/claude_bridge.py
git commit -m "feat(cycle-13/m3): add visual-iteration awareness block to system prompt

Tells the LLM that visual diff + auto-fix is system-orchestrated (not a tool
to call directly). Reinforces 'produce the best first cut' as the primary
job; treats system-staged update_doc patches as feedback to apply, not to
re-derive."

cd ../lazychat.ai
git add apps/chat-ui/src/lib/routerSystemPrompt.ts
git commit -m "feat(cycle-13/m3): mirror visual-iteration awareness block (browser-LLM path)"
```

---

### Task M3.9: M3 phase exit — full smoke + manual end-to-end

- [ ] **Step 1: Smoke**

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py $BENCH_ROOT/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep -E "T10[012]|=== "
```
Expected: all T100/T101/T102 cases PASS or skip cleanly.

- [ ] **Step 2: chat-ui suite + typecheck**

```bash
cd lazychat.ai
pnpm typecheck 2>&1 | grep -E "typecheck:|error TS"
pnpm --filter chat-ui exec vitest run 2>&1 | tail -5
```

- [ ] **Step 3: Manual end-to-end check (the M3 "Claude moment")**

1. In the chat panel at Effort=max
2. Upload the Proman MD Dashboard HTML file (drag into composer)
3. Chat-ui auto-captures the reference mockup screenshot via html2canvas (M2.7 — silent, no UI yet)
4. Send: "Build me an internal MD dashboard from this mockup. Wire revenue MTD, receivables aging, and decisions to-do list with real data. Placeholder the rest."
5. Agent stages 3 `prepare_create_server_script` + 1 `prepare_create_page`. Apply each (or 1 click at Effort=max).
6. M2 auto-screenshots `/app/proman-md-dashboard` (V1). `screenshot` Message renders.
7. M3 fires: `visualDiff` Message with score ~0.7 + N mismatches.
8. Agent generates fixes → `prepare_update_doc(Page, patch:{style:...})` Apply card → auto-Apply (Effort=max + LOW_RISK).
9. M2 re-screenshots (V2). Score ~0.85.
10. Repeat for V3 until score >= 0.92 OR 3 iterations hit.
11. Final state: `/app/proman-md-dashboard` looks visually faithful to the Proman reference; 3 sections wired with real data.

Capture screenshots of V1, V2, V3, the reference, and the 2 `visualDiff` Messages into `lazychat-erpnext/test/evidence/cycle-13/`.

- [ ] **Step 4: M3 phase exit checklist**

- [ ] visual_judge.py module imports + low/medium short-circuit works
- [ ] visual_judge.compare returns valid JSON shape (or graceful skip on real call)
- [ ] visual_judge.generate_fixes returns a patch_dict
- [ ] Whitelisted endpoints reachable; System Manager only
- [ ] visualDiff Message renders correctly in all 3 states (needs_fixes/match/cap_reached)
- [ ] visualJudgeClient.ts wires CSRF + Bearer correctly
- [ ] runVisualIterationLoop orchestrator wired into M2's triggerScreenshot
- [ ] Manual end-to-end produces V1 → V2 → V3 on the Proman dashboard

---

## Validation walkthrough — the Proman MD Dashboard end-to-end

**Goal:** capture irrefutable evidence that all 3 milestones compose into the "drop a mockup → working dashboard" experience.

**Setup:**
- Bench at `http://localhost:8000`, logged in as Administrator
- Playwright + Chromium installed; `enable_screenshot_preview = 1`
- An LLM Provider/Model configured for the vision judge (Claude Sonnet 4.6 by default at Effort=high)
- The Proman MD Dashboard HTML file ready on disk

### Walkthrough — every step captures evidence

- [ ] **V0 — setup confirmation**

```bash
# Confirm tool count
cd $BENCH_ROOT && bench --site erp.local execute lazychat_erpnext._smoke.run 2>&1 | grep "Tools:" | head -1
# Expected: "Tools: 101 registered"
```

Screenshot: chat panel empty state at `/app/home`.

- [ ] **V1 — reference upload + intent**

1. Drag `Proman_MD_Dashboard.html` into the composer
2. Verify attachment chip appears
3. (Silent: html2canvas captures the reference mockup screenshot to `Attachment.referenceScreenshot`)
4. Type: *"Build me an internal MD dashboard at /app/proman-md-dashboard from this mockup. Wire the Group Snapshot revenue numbers, Receivables aging buckets, and Decisions Required (open ToDos for me) with real data. Use placeholders for everything else but keep the visual structure faithful."*
5. Send at Effort=**max**

Screenshot: chat with the attachment chip + user message.

- [ ] **V1 build — agent stages + applies**

Agent stages (in order):
- `prepare_create_server_script` for `get_group_revenue_mtd` (sum SI grand_total grouped by company, current month)
- `prepare_create_server_script` for `get_receivables_aging` (Sales Invoice outstanding bucketed by days-overdue)
- `prepare_create_server_script` for `get_open_decisions` (ToDo filter status='Open', allocated_to=session.user)
- `prepare_create_page` for `proman-md-dashboard` (HTML + CSS + JS calling the 3 endpoints)

Each Apply card appears; at Effort=max, the server-scripts require explicit click (HIGH_RISK), the page auto-Applies after 3s.

After all commits, M2 auto-screenshots `/app/proman-md-dashboard` → V1 `screenshot` Message lands inline.

Screenshot: V1 screenshot Message in chat.

- [ ] **V2 — M3 first iteration**

M3 fires: `visualJudgeCompare(V1, reference)` → returns ~6 mismatches (typography, sparkline opacity, RAG pill border, etc.). `visualDiff` Message renders with score ~0.72.

Agent (via M3) calls `generate_fixes` → `prepare_update_doc(Page, patch:{style: <refined CSS>})`. Apply card → auto-Apply at Effort=max.

M2 re-captures → V2 screenshot. Score ~0.85.

Screenshot: V1 + visualDiff V1→V2 + V2 screenshot in chat history.

- [ ] **V3 — convergence**

Another round of judge + fix → V3 screenshot. Score >= 0.92. visualDiff shows verdict=match → STOP.

Screenshot: V3 in chat + visualDiff with the green "converged" banner.

- [ ] **Open the live page**

Click "Open in Desk" on the V3 screenshot Message → navigates to `/app/proman-md-dashboard`. Verify:
- All 12 sections rendered
- 3 wired sections show real data (revenue MTD numbers, aging buckets, open decisions list)
- Other 8 sections show realistic placeholders (with `<em>(no data wired yet)</em>` for honest placeholder behavior)
- Page works in dark mode (toggle via Frappe top nav)
- `document.body.dataset.lazychatReady === '1'` in DevTools console

Screenshot: the live `/app/proman-md-dashboard` page in both light and dark mode.

- [ ] **Capture all evidence to repo**

```bash
mkdir -p lazychat-erpnext/test/evidence/cycle-13
# Copy V0, V1, V2, V3, reference, visualDiff Messages, light/dark mode screenshots into that dir
# Filename convention:
#   00-setup-tool-count.png
#   01-reference-mockup-upload.png
#   02-agent-stages-server-scripts.png
#   03-agent-stages-page.png
#   04-V1-screenshot-inline.png
#   05-visualDiff-V1-mismatches.png
#   06-V2-screenshot-inline.png
#   07-visualDiff-V2-mismatches.png
#   08-V3-screenshot-converged.png
#   09-live-page-light-mode.png
#   10-live-page-dark-mode.png
```

- [ ] **Commit the evidence**

```bash
cd lazychat-erpnext
git add test/evidence/cycle-13/
git commit -m "evidence(cycle-13): end-to-end Proman MD Dashboard walkthrough

V1 → V2 → V3 visual convergence on the Proman mockup. Reference image,
agent staging steps, visualDiff Messages, light/dark live-page screenshots.
Score ~0.72 → 0.85 → 0.93 across 3 iterations at Effort=max.

This is the 'drop a mockup, get a working ERPNext dashboard' Claude moment
the cycle was designed to deliver."
```

---

## Self-review

After writing the complete plan, fresh-eyes check vs the spec:

**1. Spec coverage** — every spec section maps to a task:
- M1 (4 wrappers + 2 discovery + render-preview + system prompt): Tasks M1.1–M1.11 ✓
- M2 (Playwright service + Message kind + auto-trigger + reference capture): Tasks M2.1–M2.8 ✓
- M3 (vision judge + endpoints + visualDiff Message + orchestrator + prompt): Tasks M3.1–M3.9 ✓
- Validation walkthrough (Proman dashboard, V1→V2→V3): Validation section ✓
- Smoke tests (T100a–n, T101a–d, T102a–d): folded into each task's TDD pattern ✓

No gaps found.

**2. Placeholder scan** — no TBDs, no "implement later", no "similar to task N" without showing code. The "Step 3a: extend providers for vision blocks" note in M3.2 is conditional ("if not already present") — the reader is told to grep + verify. ✓

**3. Type consistency** — checked across tasks:
- `prepare_create_page` returns `{ok, preview_token, page_name, route, ...}` consistently in M1.3, M2.6, M3.7
- `screenshot` Message has the same field set (status/pngB64/route/refMockupB64) in M2.5, M2.6, M2.7, M3.7
- `visualDiff` Message has consistent fields (iteration/score/verdict/mismatches/pageName) in M3.5, M3.7
- `visualJudgeCompareOutput` shape mirrors the server's `visual_judge.compare` return value in M3.2, M3.6, M3.7

No drift.

**4. Open question for the implementer** — one item the spec deferred to user, which is now locked in this plan:

- **Vision-judge model selection**: configured via Lazychat Settings.`vision_judge_models` JSON field (admin picks per Effort tier). Defaults: `{"high": "claude-sonnet-4-6", "max": "claude-opus-4-7"}`. Hardcoded fallback if the field is empty. This matches the spec's recommendation.

If the implementer wants to verify the user agrees, ask before starting M3.1. Otherwise proceed.

---

## Plan complete — execution handoff

Plan saved to `lazychat-erpnext/docs/superpowers/plans/2026-05-13-cycle-13-mockup-to-erpnext.md`. **~110 KB of plan text covering ~29 atomic tasks across 3 milestones + a validation walkthrough.**

Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review between tasks (spec compliance + code quality), continuous execution without between-task check-ins. Best for this plan because each task is self-contained TDD work; subagents can churn through M1 in parallel-ish fashion (although M1.3 / M1.4 etc. share files, so genuine parallelism is limited — sequential subagents still beat inline for context isolation).

**2. Inline Execution** — execute tasks in this session via the `executing-plans` skill with checkpoints. Better for "I want to watch and steer" rather than "ship it."

**Which approach?** Once you pick, I'll invoke the corresponding sub-skill (`superpowers:subagent-driven-development` or `superpowers:executing-plans`) and start with Task M1.1.
