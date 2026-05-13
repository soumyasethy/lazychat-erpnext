# Cycle 13 — Mockup-to-ERPNext: typed UI primitives + visual verification loop

**Date:** 2026-05-13
**Status:** approved (brainstorm), ready for implementation plan
**Linked repos:** `lazychat-erpnext` (server: 4 typed wrappers + 2 discovery tools + Playwright service + visual judge) · `lazychat.ai` (chat-ui: 2 new Message kinds + orchestrator + extended `inspectRoute` postmessage)
**Cycle 1 of:** the 5-capability "Claude/ChatGPT-level ERPNext UI delivery" ambition (A=mockup ingestion, **B=UI primitive tools**, C=semantic data mapping, **D=visual verification**, E=PEVR loop integration — Cycle 13 ships **B + D**)

---

## Goal

Give the lazychat agent first-class capability to take a **reference design** (HTML mockup / image / pointer to an existing Desk page) and produce a **working internal ERPNext Desk Page** with real data, **iterating its own work against the reference** until visually faithful — entirely without leaving chat.

Validates end-to-end by hand-driving the agent through the **Proman MD Dashboard HTML mockup** (12 sections, partial-dynamic with 3–4 sections wired to real data, capturing V1→V2→V3 evidence screenshots).

**Output-quality is the explicit north star.** Every design choice — render-preview probe depth, system-prompt richness, Playwright over html2canvas, LLM-as-judge auto-iterate over single-pass — is biased toward final-result quality rather than ship velocity.

---

## Problem statement

Out of 95 tools in the registry, exactly **one** is a UI-building primitive (`prepare_create_client_script`, scoped to Form-view JS). The agent today cannot meaningfully create a custom Desk Page through any typed tool — it would have to use generic `prepare_create_doc` with `doctype="Page"`, with no schema validation, no Apply card, no render-preview, no visual feedback.

Result: when a user uploads a sophisticated mockup like the Proman dashboard and asks "build this in ERPNext", the agent either (a) refuses, (b) produces a poor-quality static HTML page with no real data wiring, or (c) hand-walks the user through a multi-doctype create with high friction and no quality gates.

**The user's stated goal — "Claude/ChatGPT-level expertise" — requires:**

1. Typed primitives the agent can call with confidence (Page, Server Script, Workspace, Asset Attach)
2. Render-preview validation that catches semantic issues (unknown doctypes, unknown method references, hardcoded colors that break dark mode) BEFORE Apply
3. A rich "what good ERPNext dashboards look like" playbook in the system prompt
4. Inline visual feedback after Apply — the agent shows its work
5. Autonomous iteration — the agent compares its own output against the reference and fixes mismatches without prompting

Cycle 13 ships **all five** as three sequenced milestones.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ M1 — UI primitives (week 1)                                                 │
│                                                                             │
│   user: "Build me this dashboard" + [Proman.html attached]                  │
│      │                                                                      │
│      ▼                                                                      │
│   agent reads HTML → plans 12 sections → identifies 3-4 data sources        │
│      │                                                                      │
│      ▼                                                                      │
│   prepare_create_server_script (xN) ── render-preview ──► Apply             │
│      │                                                                      │
│      ▼                                                                      │
│   prepare_create_page(content, style, script) ── render-preview ──► Apply   │
│      │                                                                      │
│      ▼                                                                      │
│   /app/proman-md-dashboard exists, looks ~70% faithful, has real data       │
└─────────────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ M2 — Inline screenshot preview (week 2, +0.5 wk for Playwright setup)       │
│                                                                             │
│   commit_prepared_action(action=create_page) returns ok=true                │
│      │                                                                      │
│      ▼                                                                      │
│   chat-ui auto-triggers inspectRoute(mode=screenshot, route=/app/...)       │
│      │                                                                      │
│      ▼                                                                      │
│   host shim calls bench-side endpoint: lazychat_erpnext.dashboards          │
│                                          .screenshot.capture(route, viewport)│
│      │                                                                      │
│      ▼                                                                      │
│   bench-side Playwright service: headless Chrome, login as session user,    │
│   navigate, wait for document.body.dataset.lazychatReady === '1' OR 5s,     │
│   screenshot → base64 PNG                                                   │
│      │                                                                      │
│      ▼                                                                      │
│   chat-ui renders `screenshot` Message inline; user sees the rendered page  │
└─────────────────────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ M3 — LLM-as-judge auto-iterate (week 3, +0.5 wk)                            │
│                                                                             │
│   reference.png + candidate.png ──► visual_judge.compare(...)               │
│      │                                                                      │
│      ▼                                                                      │
│   { score: 0.74, mismatches: [{typography...}, {spacing...}, ...] }         │
│      │                                                                      │
│      ▼ if score < threshold AND iter < cap                                  │
│   visual_judge.generate_fixes(diff, current_page_state) → patch_dict        │
│      │                                                                      │
│      ▼                                                                      │
│   agent stages prepare_update_doc(Page, patch=...) ──► Apply ──► M2 reshoot │
│      │                                                                      │
│      └──► loop: typically 1-3 iterations until score ≥ 0.92 or cap hit      │
└─────────────────────────────────────────────────────────────────────────────┘
```

Each milestone ships standalone value:

- **M1 alone**: agent builds dashboards with manual verbal-feedback iteration
- **M1+M2**: agent shows its work, user points at problems visually
- **M1+M2+M3**: agent fixes its own work, full autonomous loop

---

## M1 — Typed UI primitive tools + render-preview + system prompt

### 4 new typed wrappers

All follow the existing two-phase pattern: stage to Redis with `preview_token` (5-min TTL, user-bound) → user clicks Apply → `commit_prepared_action(token)` re-checks perms + runs inside `frappe.db.savepoint`. The same Cycle 9 critic feedback strip applies (amber band on the Apply card when the render-preview surfaces quality warnings).

#### 1. `prepare_create_page`

**Args:**

| Arg | Type | Default | Notes |
|---|---|---|---|
| `page_name` | str | derived from `title` via `frappe.scrub` | URL slug; lives at `/app/<page_name>` |
| `title` | str | required | Display title |
| `module` | str | `Lazychat Erpnext` | Frappe module |
| `roles` | list[str] | `["System Manager"]` | Roles permitted to view |
| `content` | str (HTML) | required | Page body HTML |
| `style` | str (CSS) | empty | Inline `<style>` content |
| `script` | str (JS) | empty | Inline `<script>` content (page controller) |
| `icon` | str | empty | Frappe icon class (e.g. `octicon octicon-graph`) |
| `standard` | str | `"No"` | Always "No" for dynamically-created pages |

**Risk gating:** System Manager only. Added to `LOW_RISK_ACTIONS` for Edit-auto auto-Apply (additive, easy to undo via Apply Cancel).

**Render-preview stages** (run in order; first failure wins):

| Phase | Check | Failure hint format |
|---|---|---|
| `html_parse` | `lxml.html.fromstring(content)` | `"HTML parse error at line {n}: {error}. Common: unclosed tag, mismatched quotes."` |
| `css_syntax` | `tinycss2.parse_stylesheet(style)` (brace-balance + token validity) | `"CSS syntax error at line {n}. Check brace balance and ; terminators."` |
| `js_syntax` | `pyjsparser.parse(script)` for AST validity | `"JS syntax error at line {n}: {error}."` |
| `js_doctypes_exist` | walk JS AST for `frappe.db.get_list` / `get_value` / `exists` referencing doctype `X`; for each X, check `frappe.db.exists("DocType", X)` | `"JS references doctype 'X' which doesn't exist. Run describe_doctype to find the right name."` |
| `js_methods_exist` | walk JS AST for `frappe.call` referencing method `X`; check method is (a) built-in whitelisted, (b) being staged this turn, or (c) registered | `"JS references method 'X' that doesn't exist. Stage prepare_create_server_script for it in the same turn, or use a built-in like frappe.client.get_list."` |
| `quality_warnings` | **non-blocking** — surfaced as `quality_warnings: [...]` in response, NOT a hard reject | (see below) |

**Quality warnings** (non-blocking, render in the Apply card's critic strip):

- Hardcoded colors > 5 without any `var(--*)` usage → "Page CSS uses no Frappe theme tokens — will break in dark mode. Use `var(--bg-color)`, `var(--text-color)`, etc."
- Missing structural HTML (no `<header>`, no `<main>`, no `<section>`) → "Page has no semantic structural HTML."
- Sections containing literal numeric-looking content with no `frappe.call` / `frappe.db.*` covering them → "Section appears to use placeholder data. Wire it via frappe.call or render `<em>(no data wired)</em>` instead of fake numbers."
- JS does not set `document.body.dataset.lazychatReady = '1'` anywhere → "Page won't signal ready-state to the screenshot preview. Add `document.body.dataset.lazychatReady = '1'` after your final frappe.call resolves."

The agent sees these BEFORE the user clicks Apply and can self-revise. If left unfixed, the Apply card renders the amber critic strip listing them — user can still Apply but with eyes open.

#### 2. `prepare_create_server_script`

**Args:**

| Arg | Type | Default | Notes |
|---|---|---|---|
| `name` | str | required | Server Script name (unique) |
| `script_type` | str | `"API"` | Always `API` for this wrapper (DocEvent / Permission Query / Scheduler Event NOT supported in cycle 13) |
| `api_method` | str | derived from `name` | Becomes `/api/method/<api_method>` |
| `script` | str (Python) | required | The Python body |
| `allow_guest` | bool | `False` | API endpoint can be hit without auth |
| `disabled` | bool | `False` | |

**Risk gating:** `allow_dangerous_tools` site-config flag + System Manager role + explicit Apply (never auto-Apply — server-side Python execution is HIGH-risk by definition).

**Render-preview stages** (mirrors `tools.py:_validate_script_report_body` for consistency):

| Phase | Check | Failure hint |
|---|---|---|
| `python_ast` | `ast.parse(script)` | `"Python syntax error at line {n}."` |
| `forbidden_imports` | AST scan for `import` of `subprocess` / `os` / `sys` / `shutil` / `socket` / `urllib` / `requests` / `http` / `smtplib` / `ftplib` / `telnetlib` / `ssl` / `ctypes` / `multiprocessing` | `"import {mod} is not allowed in Server Scripts (sandboxed). Use frappe.* alternatives."` |
| `forbidden_builtins` | AST scan for calls to the open / eval / exec / compile / __import__ / input / breakpoint builtins | `"{fn} is forbidden under Frappe safe_exec."` |
| `forbidden_frappe_writes` | AST scan for `frappe.db.set_value` / `set_many` / `delete` / `sql_ddl` / `multisql` / `commit` / `rollback` / `savepoint` / `release_savepoint` | `"Server Script API endpoints are READ-ONLY. For writes use prepare_create_doc / prepare_update_doc."` |
| `output_present` | AST has either `frappe.response.message = ...` OR `return ...` at module level | `"Server Script must produce output via frappe.response.message = <dict>."` |
| `safe_exec_dry_run` | `frappe.utils.safe_exec.safe_exec` invocation wrapped in try/except | (raw exception message) |
| `api_method_clash` | check `api_method` isn't already registered on another module | `"Method '{method}' already exists in module '{other}'. Use a different api_method."` |

#### 3. `prepare_create_workspace`

**Args:** `title`, `icon`, `parent_page=null`, `cards: [{number_card_name}]`, `charts: [{chart_name}]`, `shortcuts: [{type, link_to, label}]`, `roles=["System Manager"]`.

**Render-preview:** every referenced card/chart/shortcut target resolves via `frappe.db.exists`. Cheap, single SQL each.

**Risk gating:** System Manager only. Added to `LOW_RISK_ACTIONS` (auto-Apply eligible).

#### 4. `prepare_attach_assets`

**Args:** `target_doctype`, `target_name`, `files: [{filename, content_base64, mime}]`.

**Render-preview:** file size ≤ 5 MB each; mime in `{image/*, font/*, text/*, application/octet-stream}`; target exists.

**Risk gating:** caller must have `attach` perm on target. Explicit Apply (file uploads = HIGH-ish risk).

### 2 new discovery tools

| Tool | Returns | Why |
|---|---|---|
| `list_number_cards(filter?)` | All Number Cards: name, document_type, function, label, aggregate_field, filters_json | Agent reuses existing cards in a Workspace instead of duplicating. Avoids "why are there now 4 Revenue MTD cards" pain. |
| `list_whitelisted_methods(prefix?)` | All `@frappe.whitelist()` methods matching prefix, with docstrings | Agent calls existing aggregation methods (e.g. ERPNext's built-ins) before staging new Server Scripts. Avoids reinventing the wheel. |

**Total tool-registry delta: 95 → 101** (4 wrappers + 2 discovery).

### System prompt addition — "Building Desk Pages & Dashboards" playbook

Lives in both `claude_bridge.py` (backend-LLM path) and `routerSystemPrompt.ts` (browser-LLM path). ~50 lines. Structure: 5-step workflow → 7 visual quality rules → 5 anti-patterns → iteration loop guidance.

The 7 visual quality rules (these are what move output from "AI-generated mediocrity" to "ChatGPT-level"):

1. **Use Frappe theme tokens** in CSS — `var(--bg-color)`, `var(--text-color)`, `var(--primary-color)`, `var(--text-muted)`, `var(--border-color)`. Never hardcode brand colors. Hardcoded = broken dark mode.
2. **Match the reference's typography exactly** if a mockup was provided: same font families (via `<link>` to fonts.googleapis.com), same weights, same letter-spacing. Typography is the #1 thing that telegraphs "AI-generated".
3. **Match the reference's layout structure exactly**: if mockup has topbar + sidebar + sections grid, build `<header>` + `<nav>` + `<main>` with same grid template. Don't substitute "good enough" alternatives.
4. **Use semantic HTML**: `<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<aside>`, `<footer>`. KPI labels-and-values via `<dl><dt><dd>`.
5. **Wire data REAL, never placeholder.** If a section's data isn't reachable, render `<em>(no data wired yet)</em>` explicitly rather than fake numbers — fake numbers pollute user mental model.
6. **Loading / empty / error states** for every `frappe.call`. Never leave a section blank during the network roundtrip.
7. **Respect dark mode** — verify with `body.dark` toggle. The theme tokens give this for free if rule 1 was followed.

Plus a one-liner critical for M2: **"At the END of your Page's `script`, after all initial `frappe.call`s have resolved, set `document.body.dataset.lazychatReady = '1'`. This signals the screenshot tool that the page is fully rendered."**

### M1 deliverables summary

| File | Change | LoC est |
|---|---|---|
| `lazychat_erpnext/desk_assistant/tools.py` | 4 new `prepare_*` + 2 new discovery functions + render-preview helpers | +600 |
| `lazychat_erpnext/desk_assistant/tool_schemas.py` | Schemas for 6 new tools | +250 |
| `lazychat_erpnext/desk_assistant/claude_bridge.py` | System prompt addition | +80 |
| `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts` | Mirror system prompt addition | +80 |
| `lazychat_erpnext/desk_assistant/_validate_page_*.py` (new helpers) | HTML/CSS/JS validators | +200 |
| `pyproject.toml` | Add `lxml`, `tinycss2`, `pyjsparser` deps | +3 |
| `scripts/smoke-test-tools.py` | T## per new tool (12 cases) | +180 |

**M1 budget: ~1 week. ~1400 LoC + 3 small Python deps.**

---

## M2 — Inline screenshot preview via Playwright

### Why Playwright (not html2canvas)

`html2canvas` is fast and zero-setup but lossy on complex SVG (the Proman BSC card donuts), `box-shadow`-with-multiple-colors, `backdrop-filter`, and some `clip-path` shapes. For "best of best output", we need **pixel-perfect screenshots**. Playwright on the bench is the right answer:

- Headless Chromium navigates `/app/<page-name>` as the session user
- Waits for `document.body.dataset.lazychatReady === '1'` OR 5s timeout
- Captures at exact viewport (1440×900 default)
- Returns base64 PNG

Tradeoffs accepted: +~200 MB Chromium install on the bench; ~2-3s capture latency per shot; 1-2 day infra build.

### New Frappe-side service

**1. New module `lazychat_erpnext/desk_assistant/screenshot.py`** with one whitelisted function `capture(route, viewport=None, wait_for_dataset="lazychatReady", timeout_ms=5000)`:

- Auth: requires authenticated session (re-uses the calling user's session cookie via Playwright's storage_state mechanism). Refuses for Guest.
- Concurrency: serialized via a single-slot lock; concurrent requests queue (max queue depth 4, beyond that fail-fast).
- Implementation: lazy-import `playwright.sync_api` (don't pay startup cost on every request); browser pool of 1 persistent Chromium with N pages (N=4 to start), reused across requests; per-request creates a new page, injects session cookie, navigates, runs `wait_for_function` on `document.body.dataset.<wait_for_dataset> === '1'` with timeout fallback, calls `page.screenshot()`, returns base64.
- On Playwright load failure (chromium missing): returns `{ok:false, error:"playwright not installed — run `playwright install chromium` on the bench"}`.

**2. Install hook update** (`install.py:run_after_install`)

- Detect if `playwright` Python package is installed but `chromium` binary is missing → log warning + suggest `playwright install chromium`
- Don't fail install if playwright is absent — feature is opt-in

**3. Site-config flag** `lazychat_enable_screenshot_preview` (default `true` when playwright is detected, `false` otherwise). Lets ops disable on resource-constrained benches.

### Chat-ui side — new `screenshot` Message kind

New Message kind in `packages/types/src/messages.ts`:

- `kind: 'screenshot'`
- `id`, `ts`, `pageName`, `route`
- `pngB64`: `'data:image/png;base64,...'`
- `width`, `height`
- `status`: `'capturing' | 'done' | 'error' | 'stale'`
- `error?`
- `captureMethod`: `'playwright'`
- `capturedAt`
- `refMockupB64?` — populated when user uploaded an HTML mockup

**New renderer `ScreenshotMessage.tsx`:**

- `capturing` state: skeleton + "Capturing /app/<name>..." + elapsed-seconds counter
- `done` state: inline `<img>` (click-to-zoom full-screen), "Re-capture" button, "Open in Desk" button, capture timestamp
- `error` state: "Couldn't capture — {reason}." + "Open in Desk to verify manually" button
- `stale` state: dimmed + "(snapshot is older than current state) — Re-capture"
- When `refMockupB64` is set: "Compare to reference" toggle → side-by-side split-view (M3 wires this further)

**Auto-trigger** (`apps/chat-ui/src/lib/agentRunner.ts` / `commitSlash.ts`):

- After `commit_prepared_action` returns `{ok:true, action:'create_page'}` OR `{ok:true, action:'update_doc', doctype:'Page'}`:
  - Append `screenshot` Message with status `capturing`
  - Fire `inspectRoute({mode:'screenshot', route:'/app/'+pageName, ready_signal:'lazychatReady', timeout_ms:5000, viewport:{width:1440,height:900}})` via host
  - On `inspectRouteResponse`: `replaceMessage` with status `done` + pngB64 (or `error` + reason)
- Mark prior screenshot Messages for this `pageName` as `stale` on each new capture (visual stack of versions)

### Postmessage protocol extensions (`packages/types/src/postmessage.ts`)

- Extend `inspectRoute.captureSpec`: add `mode?: 'dom' | 'screenshot'` (default `'dom'` — back-compat), `ready_signal?: string`, `viewport?: {width, height}`
- Extend `inspectRouteResponse.captured`: add `screenshot_b64?`, `capture_method?`, `width?`, `height?`, `ready_signal_seen?`

### Host-shim wiring (`lazychat_panel.bundle.js`)

Extend `handleInspectRoute` to branch on `captureSpec.mode`. New `handleScreenshotCapture(payload)`:

- POSTs to `lazychat_erpnext.desk_assistant.screenshot.capture` with `route`, `viewport`, `wait_for_dataset`, `timeout_ms`
- Receives base64 PNG response
- Sends `inspectRouteResponse` back to chat-ui

(Note: in M2 the screenshot service runs ON THE BENCH (Playwright) not in the browser, so the host shim's role is simpler than the original M2 sketch — it just proxies the HTTP call.)

### Reference-mockup screenshot capture (M2 prep for M3)

When the user uploads an HTML file containing a full `<html>` document, chat-ui ALSO captures a screenshot of THAT mockup for M3:

- Extend `apps/chat-ui/src/lib/attachments/extractText.ts`: when `isHtml(file)` AND content includes `<html`, ALSO:
  - Create a Blob URL from the HTML content
  - Render via hidden iframe + html2canvas (browser-side, no bench round-trip, no attack surface — the reference doesn't need pixel-perfect; only the CANDIDATE does)
  - Stash as `Attachment.referenceScreenshot: string` (base64 PNG)
- The first `screenshot` Message generated after the upload picks this up via `refMockupB64`

**Implementation note:** Playwright on the bench needs a URL to navigate to, but the user's uploaded HTML doesn't live at a URL. Two options considered:

- (a) POST the HTML to a temp endpoint that writes to a temp file, Playwright navigates `file:///...`, screenshots, deletes — adds a small attack surface (arbitrary HTML render)
- (b) Use html2canvas IN THE BROWSER for the reference mockup specifically

**Chosen: (b)** — html2canvas for reference mockup (browser-side, no bench round-trip, no attack surface), Playwright for candidate (bench-side, pixel-perfect). The vision judge in M3 accepts both since they're comparing OVERALL fidelity, not pixel-for-pixel.

### M2 deliverables summary

| File | Change | LoC est |
|---|---|---|
| `lazychat_erpnext/desk_assistant/screenshot.py` | NEW — Playwright service + whitelisted endpoint | +200 |
| `lazychat_erpnext/install.py` | Playwright detection hook | +30 |
| `pyproject.toml` | Add `playwright` dep (optional extra) | +3 |
| `lazychat_erpnext/lazychat_settings.json` | New `enable_screenshot_preview` field | +10 |
| `lazychat-erpnext/.../public/js/lazychat_panel.bundle.js` | Extend `handleInspectRoute` for screenshot mode | +60 |
| `lazychat-erpnext/.../public/js/html2canvas.min.js` | NEW — vendored (~200 KB) | (binary) |
| `lazychat.ai/packages/types/src/messages.ts` | New `screenshot` Message kind | +20 |
| `lazychat.ai/packages/types/src/postmessage.ts` | Extend `inspectRoute` / `inspectRouteResponse` | +10 |
| `lazychat.ai/apps/chat-ui/src/components/messages/ScreenshotMessage.tsx` | NEW renderer | +120 |
| `lazychat.ai/apps/chat-ui/src/components/MessageList.tsx` | Dispatch case | +3 |
| `lazychat.ai/apps/chat-ui/src/lib/agentRunner.ts` | Auto-trigger orchestrator | +80 |
| `lazychat.ai/apps/chat-ui/src/lib/attachments/extractText.ts` | Reference-mockup screenshot capture | +60 |
| Vitest tests | screenshot trigger / message render / ready-signal poll | +80 |
| `scripts/smoke-test-tools.py` | T## for screenshot.capture endpoint | +40 |

**M2 budget: ~1.5 weeks (Playwright setup is the long pole). ~640 LoC + 1 vendored library + Playwright/Chromium install.**

---

## M3 — LLM-as-judge auto-iterate loop

### Vision judge — model selection

Reuses the existing critic pattern (Cycle 9 M2 — `desk_assistant/critic.py`), upgraded for vision. **Wired through the existing `LLM Provider` doctype config** — admin picks the vision-capable model per Effort tier:

| Effort | Default judge model | Cap iterations |
|---|---|---|
| low | (skip — manual M2 loop only) | 0 |
| medium | (skip — manual M2 loop only) | 0 |
| high | `claude-sonnet-4-6` (vision-capable, cost-effective) | 1 (single fix pass) |
| max | `claude-opus-4-7` (highest visual judgment quality) | 3 |

The model IDs come from `Lazychat Settings.vision_judge_models` — a new JSON field mapping Effort tier → model name. Falls back to Claude Sonnet 4.6 if not configured.

### Prompt structure

Models on the existing `critic.py:build_critic_prompt` shape:

```
SYSTEM: You are a visual UI judge. Compare a REFERENCE design (image) against
a CANDIDATE implementation (image). Identify visual mismatches that hurt
fidelity. Be precise: typography weight/family, spacing in pixels, color hex,
layout structure. Output JSON only.

USER:
  [REFERENCE image attachment]
  [CANDIDATE image attachment]
  Intent: <user's original request, e.g. "build me an MD dashboard">
  Current iteration: <N of cap>
  Page source (truncated): <first 4 KB of HTML + first 4 KB of CSS + first 4 KB of JS>

Output JSON ONLY (no prose):
{
  "score": 0.0-1.0,
  "verdict": "match" | "needs_fixes",
  "mismatches": [
    {
      "category": "typography" | "spacing" | "color" | "layout" | "content" | "interaction",
      "severity": "critical" | "major" | "minor",
      "description": "<2-sentence diagnosis>",
      "selector_hint": "<CSS selector or section name in candidate>",
      "fix_hint": "<concrete CSS or HTML change to attempt>"
    }
  ]
}
```

### Fix-generation step

After the judge returns mismatches AND verdict=`needs_fixes` AND iteration < cap:

- Second LLM call (text-only, NOT vision): takes the mismatch list + current Page doc state + intent → produces `patch_dict` for `prepare_update_doc`
- The patch typically updates one of: `content` (HTML), `style` (CSS), `script` (JS). Usually `style` — most mismatches are visual.

### New Frappe-side endpoints

**`desk_assistant/visual_judge.py`** (new module):

| Method | Purpose |
|---|---|
| `compare(candidate_b64, reference_b64, intent_text, page_source, effort)` | Vision LLM call. Returns `{score, verdict, mismatches}` or `{skipped: true, reason}` on Effort skip / LLM failure. 30s thread-pool timeout (mirrors `critic.py:critique_composition`). |
| `generate_fixes(diff_json, page_doc, intent_text, effort)` | Text-only LLM call. Returns `patch_dict` for `prepare_update_doc`. Skips on Effort < high. |

**`desk_assistant/api.py`** — 2 new whitelisted endpoints:

- `lazychat_visual_judge_compare(...)` — proxy to `visual_judge.compare`
- `lazychat_visual_judge_generate_fixes(...)` — proxy to `visual_judge.generate_fixes`

Both gated System Manager only.

### Chat-ui side — orchestration

**New `visualDiff` Message kind** (`packages/types/src/messages.ts`):

- `kind: 'visualDiff'`
- `id`, `ts`
- `iteration`: 1, 2, 3
- `score`: 0..1
- `verdict`: `'match' | 'needs_fixes' | 'cap_reached'`
- `mismatches[]` with `category`, `severity`, `description`, `selector_hint?`, `fix_hint?`
- `refScreenshotId`, `candidateScreenshotId`, `autoApplied`, `pageName`

**New renderer `VisualDiffMessage.tsx`**:

- Header: "Iteration {N} — score {0.82} (Δ +0.08) — {3 mismatches}"
- Side-by-side mini thumbs: reference (40%) | candidate (40%) | gap-overlay-canvas (20%)
- Click thumbnails → full-screen comparison modal
- Mismatch list — each row: severity dot (red/amber/grey) + category icon + description + "Auto-fix" / "Skip" buttons
- Footer controls: "Stop iterating" / "Approve as-is" / "Continue iterating"
- When `autoApplied: true` (Effort=max): annotation "Auto-applied — see V{N+1}"

**Orchestrator** in `apps/chat-ui/src/lib/agentRunner.ts` — new function `runVisualIterationLoop(sid, pageName)`:

1. Get the latest candidate screenshot for `pageName`
2. Get the reference screenshot (from session attachments)
3. If no reference → skip M3 (M2 manual loop is the experience)
4. Get current Effort tier; if low/medium → skip M3
5. Call `visual_judge.compare(...)` → render `visualDiff` Message
6. If verdict='match' → emit "Done — visual fidelity ≥ {score}" Message + STOP
7. If iteration >= cap → emit "Final score {score} after {cap} iterations — review remaining mismatches manually" + STOP
8. Else:
   - Call `visual_judge.generate_fixes(...)` → patch_dict
   - Stage `prepare_update_doc(Page, patch=patch_dict)`
   - If Effort=max AND action in LOW_RISK → auto-Apply; else render Apply card, wait for user click
   - On Apply success → M2's auto-screenshot fires → new candidate
   - Loop to step 1 (iteration += 1)

### User overrides

At any iteration:

- "Stop iterating" button → halts loop, leaves page in current state
- "Approve as-is" → halts loop + marks the build as complete (no more fix turns)
- "Manually fix this one" on a specific mismatch row → opens composer pre-filled with the mismatch description as a fix prompt

### Effort tier integration

The agent's Effort selector (Cycle 8 ModesPanel) drives M3 cap:

- low/medium: M3 dormant
- high: 1 iteration (single auto-fix pass)
- max: 3 iterations (full convergence loop)

This matches the existing `EFFORT_MAP` pattern in `claude_bridge.py` and the Cycle 9 M2 critic gating.

### M3 deliverables summary

| File | Change | LoC est |
|---|---|---|
| `lazychat_erpnext/desk_assistant/visual_judge.py` | NEW — vision LLM judge + fix generator | +250 |
| `lazychat_erpnext/desk_assistant/api.py` | 2 new whitelisted proxy endpoints | +60 |
| `lazychat_erpnext/lazychat_settings.json` | New `vision_judge_models` JSON field | +10 |
| `lazychat_erpnext/desk_assistant/claude_bridge.py` | "Visual iteration available" awareness block in prompt | +20 |
| `lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts` | Mirror prompt addition | +20 |
| `lazychat.ai/packages/types/src/messages.ts` | New `visualDiff` Message kind | +25 |
| `lazychat.ai/apps/chat-ui/src/components/messages/VisualDiffMessage.tsx` | NEW renderer | +180 |
| `lazychat.ai/apps/chat-ui/src/lib/agentRunner.ts` | `runVisualIterationLoop` orchestrator | +150 |
| `lazychat.ai/apps/chat-ui/src/lib/visualJudgeClient.ts` | NEW — wraps the 2 endpoints | +80 |
| Smoke tests | T## for visual_judge.compare/generate_fixes + Effort gating + skip-on-failure | +120 |

**M3 budget: ~1.5 weeks. ~915 LoC + iterative prompt-tuning work on the Proman dashboard as the calibration case.**

---

## Validation walkthrough (the Proman MD Dashboard, end-to-end)

The proving ground for all 3 milestones. We capture evidence screenshots at each step into `lazychat-erpnext/test/evidence/cycle-13/`.

### Setup

- User logs into the bench at `http://localhost:8000/app`
- Opens the lazychat panel
- Drags the Proman dashboard HTML file into the chat composer
- The HTML attaches as a chip; chat-ui auto-captures the reference screenshot (M2 helper)

### Initial build (M1)

1. User: "Build me an internal MD dashboard from this mockup. Wire 3-4 sections with real data; placeholder the rest."
2. Agent reads the HTML, plans the 12 sections, identifies data needs
3. Agent stages 3-4 `prepare_create_server_script`s for the data endpoints:
   - `get_group_revenue_mtd` — sum of Sales Invoice grand_total grouped by company, current month
   - `get_receivables_aging` — bucketed Sales Invoice outstanding by days-overdue
   - `get_division_kpi_summary` — per-Lazychat Skill record (using existing doctypes as proxy if no real Division doctype)
   - `get_open_decisions` — get_list ToDo for current user, status=Open
4. User clicks Apply on each (or 1 click at Effort=max with auto-Apply on the LOW_RISK creates)
5. Agent stages `prepare_create_page({page_name:'proman-md-dashboard', content:<HTML>, style:<CSS>, script:<JS calling the 4 endpoints>})`
6. Render-preview runs; quality_warnings surface (e.g. "1 hardcoded color found" — the navy brand `#0D1B2A`, which IS appropriate since we want to match the reference, so the warning is acknowledged but not blocking)
7. User clicks Apply → `/app/proman-md-dashboard` is live

### Screenshot capture (M2)

8. Chat-ui auto-fires `inspectRoute(mode='screenshot', route='/app/proman-md-dashboard')`
9. Host shim → Playwright service → captures 1440×900 PNG (~2s latency)
10. `screenshot` Message renders inline; user sees V1

### Vision-judge iteration (M3, at Effort=max)

11. M3 orchestrator triggers `visual_judge.compare(candidate=V1, reference=Proman.png, intent=...)` → score 0.74, 6 mismatches:
    - typography (major): KPI numbers should be `IBM Plex Mono 500`, current is system mono
    - typography (major): sidebar nav font missing `letter-spacing: 0.05em`
    - color (minor): sparkline opacity should be 0.28 (faded) / 0.9 (highlighted), current is 1.0 all
    - layout (minor): RAG pill border-left missing the 2px accent stripe
    - content (minor): "View report" links use `<button>` instead of `<a>` with `target=_blank`
    - interaction (minor): BSC donut chart needs the 3-segment stroke-dasharray, current is empty
12. Agent calls `visual_judge.generate_fixes(...)` → patch_dict with `style` updates
13. Stages `prepare_update_doc(Page, patch=...)` → auto-Apply (Effort=max + page update in LOW_RISK)
14. M2 re-captures V2
15. M3 re-judges V2 → score 0.89, 2 remaining mismatches (sparkline animation absent, BSC donut not quite right)
16. Another fix iteration → V3 → score 0.93 → STOP (converged)

### Final state

- `/app/proman-md-dashboard` exists, looks ~93% faithful to the Proman reference
- 4 sections show real data from the bench
- 8 sections show realistic placeholders (still visually faithful)
- Evidence: screenshots V1, V2, V3 alongside the reference, plus the 2 `visualDiff` Messages from M3

This is the **"drop a mockup, get a working dashboard in 3 clicks"** Claude.ai moment.

---

## Smoke tests

In-process (`scripts/smoke-test-tools.py`):

| Case | What |
|---|---|
| T100a | `prepare_create_page` happy path: stage + Apply, page exists at `/app/<name>` |
| T100b | `prepare_create_page` render-preview rejects unclosed HTML |
| T100c | `prepare_create_page` render-preview rejects unknown doctype in JS |
| T100d | `prepare_create_page` render-preview surfaces quality_warnings (non-blocking) |
| T100e | `prepare_create_server_script` happy path + endpoint reachable via HTTP |
| T100f | `prepare_create_server_script` rejects `import os` |
| T100g | `prepare_create_server_script` rejects `frappe.db.set_value` |
| T100h | `prepare_create_workspace` resolves card/chart targets |
| T100i | `prepare_attach_assets` rejects > 5 MB file |
| T100j | `list_number_cards` returns expected shape |
| T100k | `list_whitelisted_methods` returns expected shape |
| T101a | `screenshot.capture` returns base64 PNG on valid route |
| T101b | `screenshot.capture` returns error on Guest user |
| T101c | `screenshot.capture` returns timeout error when ready_signal never set |
| T102a | `visual_judge.compare` happy path returns valid JSON shape |
| T102b | `visual_judge.compare` returns `{skipped:true}` at Effort=low |
| T102c | `visual_judge.compare` returns `{skipped:true, reason:"..."}` when vision LLM unreachable |
| T102d | `visual_judge.generate_fixes` returns patch_dict shape |

HTTP-wire (`test/curl_smoke.py`): T## per new tool, content-validated.

End-to-end (manual, captured as evidence): the Proman walkthrough above.

---

## Out of scope (deferred to follow-up cycles)

**Cycle 14 (Sub-project A — Mockup ingestion):**

- `analyze_html_mockup(html)` — structured spec extraction (sections, data references, interactions, color palette)
- Reference mockup intake for non-HTML formats (Figma export, Sketch, image-only)

**Cycle 15 (Sub-project C — Semantic data mapping):**

- `resolve_data_intent("Group Revenue MTD")` — natural-language → doctype + filters + aggregation resolver
- Cross-entity data knowledge graph

**Cycle 16 (Sub-project E — PEVR loop integration):**

- Wire the existing `lazychat.ai/apps/chat-ui/src/lib/pevr.ts` primitives into `agentRunner.ts`'s main loop
- Effort-tier budget enforcement at the PEVR state level

**Within Cycle 13:**

- `prepare_create_page` does NOT support **standard** Pages (file-based, deployed via `<app>/<app>/page/<name>/`) — only dynamically-creatable non-standard Pages. Standard Pages require code generation + deploy hooks; defer.
- `prepare_create_server_script` only supports `script_type=API`. DocEvent / Permission Query / Scheduler Event scripts are deferred (those require different validation + commit semantics).
- Visual judge **does not** support animation or interaction comparison (static-snapshot only). Animation regression is a separate problem.
- Playwright capture is on the bench's own ERPNext domain. **Cross-origin URLs are out of scope.**
- The visual-iteration loop is **per-Page** — if the agent stages a Workspace + Pages + Server Scripts together, only the Page gets the visual loop; the rest get the existing manual Apply gates.

---

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Playwright install fails on user's bench | `enable_screenshot_preview=false` graceful degrade; M2 surfaces "screenshot unavailable" Message; M3 dormant. M1 still ships and is useful. |
| Vision judge LLM cost spikes (3 iterations × Claude Opus on every dashboard build) | Effort-tier gating (only max → 3 iter; high → 1 iter); convergence threshold (stops early if score ≥ 0.92); per-session "stop iterating" override. Cost ≤ ~$0.50 per dashboard at Sonnet, ~$2 at Opus. |
| Vision judge produces nonsense fixes that REGRESS the candidate | Score-tracking: if iteration N+1's score is LOWER than N's, revert that fix and halt. Surface the regression to user with the offending diff. |
| render-preview probe rejects valid HTML the user wrote in their mockup | Quality_warnings are non-blocking (soft); only hard-rejects are real syntax errors. User can override by stripping the offending JS construct or using `prepare_create_doc` with `doctype="Page"` as a generic fallback. |
| Frappe sandbox blocks something the agent's Server Script does | safe_exec_dry_run catches at preview; AST scan catches forbidden imports/builtins; if it still slips through, commit-time savepoint rollback prevents persistence. |
| User uploads a 5 MB HTML mockup that breaks chat memory | Already handled by the 50 MB cap in `extractText.ts`; reference screenshot capture has its own browser-memory ceiling (html2canvas tops out around ~10 MB DOM). |

---

## Tech additions

**Frappe app (`lazychat-erpnext`):**

- Python: `lxml`, `tinycss2`, `pyjsparser` (small, well-known), `playwright` (large — ~200 MB Chromium)
- JS: vendored `html2canvas.min.js` (~200 KB) for reference-mockup capture only

**Chat-ui (`lazychat.ai`):**

- No new npm deps in cycle 13 (everything reuses existing primitives: zustand, Radix, lucide-react)

---

## Spec self-review summary

- ✅ No TBD/TODO/placeholder fields
- ✅ Internal consistency: M1 wrappers feed M2 (auto-screenshot trigger), M2 feeds M3 (visual diff input), all gated by Effort tier consistently
- ✅ Scope: ONE cycle, decomposed into 3 milestones that each ship standalone value
- ✅ Ambiguity: hard-blocking vs soft quality_warnings is explicit; html2canvas (reference) vs Playwright (candidate) is explicit; Effort-tier behavior table is explicit
- Open item for the user to decide before plan: the spec proposes the vision-judge model is **configured via `Lazychat Settings`** (admin picks per Effort tier — my recommendation, mirrors existing critic-model config). Alternative is hardcode to Claude Sonnet/Opus (zero configuration, lower flexibility).
