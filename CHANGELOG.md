# Changelog

All notable changes to **lazychat_erpnext** are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses cycle-tagged releases (`cycle-N[-mM]`) rather than strict semver — the version number bumps roughly track the chapters in [CLAUDE.md](CLAUDE.md), where each cycle's design notes live.

The companion chat-ui ships from [`lazychat.ai`](https://github.com/soumyasethy/lazychat.ai); cross-repo changes are noted as "(chat-ui mirror in lazychat.ai)".

## [Unreleased]

## [0.4.1] — Cycle 14.4 — Lazychat Settings polish (tool count + Code-field height) — 2026-05-15

Two small UX fixes to the [`/app/lazychat-settings`](lazychat_erpnext/desk_assistant/doctype/lazychat_settings/lazychat_settings.json) form. Backend only — chat-ui unchanged. Tag: `cycle-14.4`.

### Fixed

- **Stale tool-count in Help block.** The "Both share" bullet read "the same 38 ERPNext tools" — that was the cycle-7 number. Actual count after Cycle 13 (`prepare_create_page`, `prepare_create_workspace`, `prepare_attach_assets`, etc.) is **101 tools** in `tool_schemas.py`. Updated to "the same 101 ERPNext tools" with a one-line description of what's covered.
- **Code-field editors way too tall** in Lazychat Settings. The two `Code` fields (Allowed Upstream Hosts JSON array, Vision-Judge Models JSON object) each rendered as ~600px-tall ACE editors despite usually holding a single line of content. Added scoped CSS in `lazychat_erpnext_desk.css` that constrains those two specific editors to `height: 100px` (min 80, max 140) so the form scans cleanly. Other Code fields elsewhere in ERPNext are untouched.

### Verification

- Backend: no Python change → smoke unchanged at 283/0/6.
- Visual: `/app/lazychat-settings` now shows compact JSON editors + correct "101 tools" label.

### Commits in this release

```
<sha> fix(cycle-14.4): help_html says 101 tools (was 38)
<sha> fix(cycle-14.4): constrain Lazychat Settings Code-field heights
<sha> docs(cycle-14.4): CHANGELOG + CLAUDE.md + version bump → 0.4.1
```

## [0.4.0] — Cycle 14 — MD Dashboard rebuild + Dashboard-from-Mockup discipline — 2026-05-15

Two coupled fixes that close the same class of bug. Companion chat-ui release: `lazychat.ai 0.1.2`.

### Added
- 4 minimal custom doctypes for non-ERP MD-facing data: `MD KPI Score` (BSC, 54 seed), `MD Risk` (7 seed), `MD Decision` (7 seed), `Critical Role` (5 seed). System Manager only. Seeded idempotently via `_seed_md_dashboard()` in `install.py`.
- Server-side aggregate endpoint `lazychat_dashboard_aggregate(spec)` in `api.py`: SUM/COUNT/AVG/MIN/MAX with optional GROUP BY. Validates field names against doctype meta and op against `{sum,count,avg,min,max}`. System Manager only. Replaces the broken `frappe.client.get_list + JS reduce` pattern.
- `/app/md-dashboard` full 12-section rebuild (Group Snapshot · BSC · Division KPIs · Risks · Decisions · Sales · Receivables · Payables · Operations · Finance · HR · Digital). Magnitude-aware `fmtINR` helper (` Cr` / ` L` / raw rupees). Auto-refresh every 5 min. `lazychatReady = '1'` after `Promise.all` of 12 section calls.
- 6 new in-process smoke tests (T100r through T100w): aggregate sum matches direct SQL, rejects unknown field, rejects unknown op, MD doctype seed counts, group_by returns rows, System Manager gate.

### Changed
- Playbook DASHBOARD-FROM-MOCKUP DISCIPLINE block in `claude_bridge.py` (mirrored in chat-ui `routerSystemPrompt.ts`): for any 5+ section / 20+ KPI mockup, agent must INVENTORY → CLASSIFY → AGGREGATE via the new endpoint → handle UNITS magnitude-aware → RENDER ALL sections.
- `/app/md-dashboard` Page roles tightened from `All` to `System Manager` only.

### Verification
- in-process smoke: 277 → 283 pass / 0 fail / 6 skip
- chat-ui vitest: 461 / 0 (unchanged)
- bench migrate clean (4 new doctypes installed)
- E2E: `/app/md-dashboard` shows real ₹76 Cr YTD revenue, 88,928 Sales Invoices, ₹96 Cr creditors, 4 BSC perspective cards, 7 risks, 7 decisions

### Commits in this release

```
<sha> feat(cycle-14): 4 MD custom doctypes + idempotent seed
<sha> feat(cycle-14): lazychat_dashboard_aggregate endpoint w/ field-meta + op-whitelist
<sha> feat(cycle-14): /app/md-dashboard 12-section rebuild
<sha> feat(cycle-14): playbook DASHBOARD-FROM-MOCKUP DISCIPLINE block
<sha> test(cycle-14): T100r-w smoke for aggregate + seed
<sha> docs(cycle-14): CHANGELOG + CLAUDE.md + version bump → 0.4.0
```

## [0.3.1] — Cycle 13.2 — entity-decode + pill session-scope — 2026-05-15

Two surgical post-ship fixes on top of cycle-13.1. Companion chat-ui release: `lazychat.ai 0.1.1`.

### Fixed

- **Page renders HTML source as visible literal text** — agent-generated `prepare_create_page` payloads sometimes arrived entity-encoded (`&lt;header&gt;` instead of `<header>`), and the commit handler wrote those entities verbatim to the on-disk `.html` file + into the JS wrapper's `page.main.html(...)` call. The browser then displayed the literal `<header>` text inside the page. Defensive sanitizer `_decode_if_fully_entity_escaped()` in [`tools.py`](lazychat_erpnext/desk_assistant/tools.py) now auto-decodes when content is fully entity-escaped (has `&lt;tag` AND zero real `<tag` matches). Mixed content with intentional `&lt;` (e.g. code samples wrapped in `<pre>`) is left untouched. Applied to both `create_page` and `update_doc(Page)` commit branches.
- **Playbook clarification** mirrored in `claude_bridge.py` and chat-ui `routerSystemPrompt.ts`: rule #2 rewritten with role-explicit wording — entities are for escaping characters in TEXT CONTENT, never for tag delimiters. WRONG/RIGHT examples added so future LLM versions don't repeat the hallucination.

### Added

- Smoke tests T100o (entity-decode happy path), T100p (mixed content preserved), T100q (update_doc(Page) entity-decode).

### Verification

- in-process smoke: 277 pass / 0 fail / 6 skip (was 274 / 0 / 6)
- HTTP-wire smoke: unchanged (no tool-surface change)

### Commits in this release

```
<sha> feat(cycle-13.2): _decode_if_fully_entity_escaped helper in tools.py
<sha> feat(cycle-13.2): wire entity-decode into create_page commit
<sha> feat(cycle-13.2): wire entity-decode into update_doc(Page) commit
<sha> feat(cycle-13.2): playbook rewrite — entities for text content only
<sha> test(cycle-13.2): T100o/p/q smoke for entity-decode
<sha> docs(cycle-13.2): CHANGELOG + CLAUDE.md + version bump → 0.3.1
```

## [0.3.0] — Cycle 13: Mockup-to-ERPNext + agentic-build hardening — 2026-05-15

The headline release for Cycle 13. Three milestones (M1+M2+M3) plus a post-ship hardening pass driven by an end-to-end agentic test that surfaced 6 real defects.

### Added

#### M1 — Typed UI primitives + render-preview + system prompt

- 6 new tools (`TOOL_SCHEMAS` 95 → 101):
  - **`prepare_create_page`** — stage a Desk Page at `/app/<page_name>` with full HTML/CSS/JS render-preview validation. Hard-rejects unparseable HTML/CSS/JS, references to non-existent doctypes (`frappe.db.get_list`) or methods (`frappe.call`). Surfaces non-blocking quality warnings (hardcoded colors, missing semantic HTML, missing `lazychatReady` marker). LOW_RISK + AUTO_OPEN.
  - **`prepare_create_server_script`** — stage a `script_type=API` whitelisted Python endpoint. AST validator rejects forbidden imports (subprocess/os/sys/...), dangerous builtins (open/eval/exec/compile/__import__), `frappe.db` writes (set_value/delete/sql_ddl/...). Same-turn-staged methods exposed via `frappe.local.flags.lazychat_staging_methods` so a sibling `prepare_create_page` can `frappe.call` them. Gated by `lazychat_allow_dangerous_tools` + System Manager.
  - **`prepare_create_workspace`** — stage a Frappe Workspace card-grid dashboard. Validates Number Card / Dashboard Chart / DocType references exist. LOW_RISK + AUTO_OPEN.
  - **`prepare_attach_assets`** — upload files (image / font / text / CSS) to a target doctype. 5 MB per-file cap; mime allowlist; caller must have write perm.
  - **`list_number_cards`** — read-only discovery of existing Number Cards.
  - **`list_whitelisted_methods`** — read-only discovery of `@frappe.whitelist()` methods reachable via `/api/method/<path>`. Walks `frappe.whitelisted` (Frappe v15-aware).
- Render-preview validators ([`page_validators.py`](lazychat_erpnext/desk_assistant/page_validators.py)): HTML well-formedness (lxml), CSS syntax (tinycss2), JS AST (pyjsparser) including doctype-ref + method-ref existence checks. Soft warnings via `collect_quality_warnings`.
- Server Script AST validators ([`server_script_validators.py`](lazychat_erpnext/desk_assistant/server_script_validators.py)).
- System prompt: **"Building Desk Pages & Dashboards" playbook** in `claude_bridge.py` with 6-step workflow + 7 visual-quality rules + anti-patterns. Mirrored in chat-ui `routerSystemPrompt.ts`.

#### M2 — Playwright screenshot preview

- [`screenshot.py`](lazychat_erpnext/desk_assistant/screenshot.py) — `@frappe.whitelist()` `capture(route, viewport, wait_for_dataset, timeout_ms)`. Lazy persistent Chromium browser pool. Per-request: new context with caller's `sid` cookie injected, navigate to `http://127.0.0.1:<port>` (always reachable from same machine — avoids DNS-resolvable hostname requirement), `page.wait_for_function(document.body.dataset[<key>] === '1')` with timeout fallback. Concurrency: single-slot lock + bounded queue (default 4). Refuses Guest. Gated by `Lazychat Settings.enable_screenshot_preview`. **(post-ship: default flipped to ON, see Cycle 13.1)**
- Postmessage protocol extended: `InspectRouteRequest.payload.captureSpec.mode?: 'dom' | 'screenshot'` (default `'dom'`, back-compat with Cycle 9 M4). Screenshot-mode response carries `screenshot_b64`, `width`, `height`, `capture_method`, `ready_signal_seen`, `captured_at`.
- Panel-shim `handleInspectRoute` branches on `mode === 'screenshot'` → POSTs to `screenshot.capture` with CSRF + cookie auth.
- chat-ui mirror: new `screenshot` Message kind + `ScreenshotMessage.tsx` (capturing/done/error/stale states) + `triggerScreenshot(sid, pageName, route)` auto-fired by `commitSlash.ts` after `create_page` / `update_doc(Page)` Apply. html2canvas 1.4.1 vendored at `/assets/lazychat_erpnext/js/html2canvas.min.js` for in-browser reference-mockup capture.

#### M3 — LLM-as-judge visual auto-iterate

- [`visual_judge.py`](lazychat_erpnext/desk_assistant/visual_judge.py) — `compare()` + `generate_fixes()`. Vision LLM call wrapped in `concurrent.futures.ThreadPoolExecutor` with 30s/60s timeouts. **Skip-on-failure pattern**: any exception (model unresolved, adapter throws, output not parseable, timeout) returns `{skipped: True, reason}` — never breaks the calling flow.
- Effort gating: `low`/`medium` skip; `high` 1-iter cap (default `claude-sonnet-4-6`); `max` 3-iter cap (default `claude-opus-4-7`).
- `Lazychat Settings.vision_judge_models` Code/JSON field — admin overrides per-Effort model. Default mirrored in `boot.py:_SETTINGS_DEFAULTS`.
- Whitelisted endpoints: `lazychat_visual_judge_compare`, `lazychat_visual_judge_generate_fixes`, `lazychat_get_page_doc` — all System Manager only.
- chat-ui mirror: `visualDiff` Message kind + `VisualDiffMessage.tsx` + `visualJudgeClient.ts` + `runVisualIterationLoop` orchestrator + Visual Iteration awareness block in system prompt.

### Changed

- `Tool registry — 87 tools` → `101 tools` in CLAUDE.md.
- `Lazychat Settings` doctype gains `enable_screenshot_preview`, `vision_judge_models` fields.
- `pyproject.toml` adds `lxml>=4.9`, `tinycss2>=1.2`, `pyjsparser>=2.7` to `dependencies` and `playwright>=1.40` to `[project.optional-dependencies] screenshot`.

### Fixed (Cycle 13.1 — post-ship hardening, surfaced by end-to-end agentic build with claude-haiku-4.5 via Vercel AI Gateway)

These six fixes shipped between the initial Cycle 13 ship and `0.3.0`. Together they make the chat-panel-driven agentic build path actually work first-try for a real user typing a casual prompt.

1. **`prepare_create_page` commit handler ordering**: handler wrote `<page>.{js,css,html}` BEFORE `doc.insert()`, but Frappe's `Page.insert()` runs `make_boilerplate` which OVERWRITES those files with a default scaffold. User content was silently discarded; pages rendered as empty Desk shells. Fix: `doc.insert()` first, then overwrite with real content.
2. **Frappe truncates `page_name` to 20 chars** but our code kept using the original. Files written to `customer_outstanding_dashboard/` while Frappe's loader read from `customer_outstanding/` (the truncated `doc.name`). Fix: after `doc.insert()`, use `doc.name` + `doc.title` (Frappe-normalized) as the disk-path basis.
3. **JS string literals in the page wrapper**: Python's `!r` (repr) escape style isn't pipeline-safe — Frappe's page-loader pre-processing corrupted `'Courier New'` into unescaped quotes → `SyntaxError: Unexpected identifier Courier`. Fix: use `json.dumps()` for embedding user content/title/name into the JS wrapper (JSON string format is a strict subset of JS string format).
4. **Role-name validation in `prepare_create_page`**: agents pass `roles=['User']` but Frappe's actual role is `'All'`. Commit died with opaque "Could not find Row #1: Role: User". Fix: validate each requested role exists; auto-substitute common confusions (`User` → `All`, `Anonymous` → `Guest`); on miss, return clear error with valid role names so the agent self-corrects.
5. **`safe_provider_api_key()` returned `""` inside ThreadPoolExecutor workers**: `frappe.utils.password.get_decrypted_password` needs `frappe.local` context, but worker threads don't inherit it. Result: `Authorization: Bearer ` (empty) → 401 from any provider → every M3 visual-judge call silently skipped. Fix: `safe_provider_api_key()` now caches plaintext on `provider_doc.__lazychat_plain_api_key__` on first decrypt; subsequent calls (worker threads) read the cache. New `warm_provider_api_key()` is the explicit "decrypt me before the threadpool handoff" entry point. Both `visual_judge.compare()` and `generate_fixes()` warm the key in the main thread before submitting.
6. **`prepare_update_doc(Page, patch={content,style,script})` silently no-op'd**: the `update` branch in `commit_prepared` did `doc.set(field, v); doc.save()` regardless of doctype. For Frappe v15 Page, content/style/script aren't real DB fields (same root cause as the create_page fix). The "iteration loop" the playbook promises was therefore broken. Fix: when `payload['doctype'] == 'Page'` and patch contains any of `content`/`style`/`script`, the handler reads existing on-disk files, applies only the patched fields, and rewrites the disk-file trio. When the patch doesn't include `script`, the existing script body is recovered from the existing JS file's `try{...}catch` block via regex.

### Defaults flipped to ON (Cycle 13.1)

- `Lazychat Settings.enable_screenshot_preview` 0 → 1 — joins existing allow-all defaults from Cycle 10. Graceful-degrade: returns `{ok:false, error:'playwright not installed...'}` when the dep isn't on the bench. Install Playwright + Chromium to actually enable rendering.

### System prompt upgrades (Cycle 13.1)

The "Building Desk Pages" playbook gained 200+ lines of agent guidance (`claude_bridge.py` + `routerSystemPrompt.ts` mirror):

- **Five non-negotiable rules at the top** (was buried before): ES5-only with every banned syntax → ES5 equivalent listed; numeric HTML entities only (no `&middot;`/`&mdash;`); no `innerHTML` with interpolated values; `lazychatReady = '1'` after `Promise.all`; real Frappe role names.
- **Casual-prompt cookbook** — noun-to-doctype table covering common asks (customers, suppliers, sales, stock, items, tasks, employees, leads, quotations); default heuristics for title/slug/layout/theme/columns when the user under-specifies.
- **ES5 reference patterns** — loading/empty/error pattern + INR `fmtINR()` rewritten in pure ES5 (the previous example used `const`, arrow fns, template literals → LLMs mimicked → validator rejected → retry).
- **CLIENT-SIDE FRAPPE HELPERS — what's real vs Python-only** — table mapping `frappe.utils.X` (server-only) → real client equivalents (`Intl.NumberFormat`, `textContent`, `frappe.datetime.*`, global `format_currency`). Plus the namespace cheat sheet (`frappe.db.* / frappe.call / frappe.datetime.* / frappe.defaults.* / frappe.ui.* / frappe.boot.*` — NOT `frappe.utils.*`).
- **Iteration patch guidance** — when patching a Page, send FULL replacement strings for any field you touch (commit handler overwrites; doesn't diff/merge).

Result: a casual prompt like *"build me a dashboard page showing my top 10 suppliers we owe money to"* now yields a working `/app/<slug>` page in ~26s, first try, no validator retries — fetching real `Purchase Invoice` data with proper INR lakh/crore formatting.

### Verification gates

- In-process smoke: **274 pass / 0 fail / 6 skip** (T100a–n M1 typed wrappers + render-preview, T101a–d M2 screenshot, T102a–d M3 visual judge — the 6 skips are the `lazychat_allow_dangerous_tools=false` Server Script cases on this bench)
- HTTP-wire smoke: 6 new tools all OK or OK_ERROR (gated tools as designed)
- chat-ui vitest: 457 pass / 0 fail (78 files, +16 from baseline)
- chat-ui typecheck: clean across all 3 workspaces

### Commits in this release

```
988dddc fix(cycle-13/m1): prepare_update_doc(Page) writes disk files + playbook teaches client-vs-server frappe helpers
c3714c4 feat(cycle-13/m1): playbook upgrade — casual-prompt cookbook + loud ES5-only emphasis
11657f9 fix(cycle-13/m1): make prepare_create_page commit handler agent-proof
e5fd837 fix(cycle-13/m3): pre-warm provider api_key before submitting to ThreadPoolExecutor
3eba6ab fix(cycle-13/m1): prepare_create_page writes disk files (Frappe Page has no DB content field)
75772ae feat(cycle-13): activate screenshot preview by default + fix capture bugs
290b7f3 chore(cycle-13): rebundle chat-ui dist + ship cycle-13 spec & plan
ec47ad1 docs(cycle-13): add Cycle 13 section to CLAUDE.md + bump tool count to 101
71ba1c5 feat(cycle-13/m3): add visual-iteration awareness block to system prompt
96e40a9 feat(cycle-13/m3): lazychat_get_page_doc whitelisted read endpoint
c322001 feat(cycle-13/m3): whitelist visual_judge endpoints
7b3b137 feat(cycle-13/m3): visual_judge.generate_fixes — text LLM producing patch_dict
075f41d feat(cycle-13/m3): visual_judge.compare — vision LLM call with skip-on-failure
eeba38a feat(cycle-13/m3): visual_judge.py skeleton + vision_judge_models setting
6aaffb1 chore(cycle-13/m2): vendor html2canvas 1.4.1 for in-browser reference capture
3085c93 feat(cycle-13/m2): panel-shim handles inspectRoute screenshot mode
1341929 feat(cycle-13/m2): screenshot.capture — Playwright service with session-cookie injection
07bb70e feat(cycle-13/m2): scaffold Playwright screenshot service module
0672ad0 test(cycle-13/m1): HTTP-wire smoke validators for the 6 new tools
38e0aeb feat(cycle-13/m1): add Building Desk Pages playbook to system prompt
7d9df88 feat(cycle-13/m1): list_whitelisted_methods discovery tool
ab55a35 feat(cycle-13/m1): list_number_cards discovery tool
68cf855 feat(cycle-13/m1): prepare_attach_assets typed wrapper
cd26bec feat(cycle-13/m1): prepare_create_workspace typed wrapper
3bf7208 feat(cycle-13/m1): prepare_create_server_script typed wrapper + AST validation
9a57c73 feat(cycle-13/m1): prepare_create_page typed wrapper + render-preview
8c3d5c8 feat(cycle-13/m1): implement HTML/CSS/JS + Server Script AST validators
ed130db chore(cycle-13/m1): address M1.1 code-quality review
22ffdc1 feat(cycle-13/m1): scaffold render-preview validator modules
```

## Earlier history

Earlier cycles (12, 11, 10, 9, 8, 7, …) are documented in [CLAUDE.md](CLAUDE.md). Per-cycle git tags exist (`cycle-12-m2`, `cycle-12-m1`, `cycle-11-m4`, …) — `git log --oneline <prev-tag>..<tag>` to see commits per cycle.

[Unreleased]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-14.4...HEAD
[0.4.1]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-14...cycle-14.4
[0.4.0]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-13.2...cycle-14
[0.3.1]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-13.1...cycle-13.2
[0.3.0]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-12-m2...cycle-13.1
