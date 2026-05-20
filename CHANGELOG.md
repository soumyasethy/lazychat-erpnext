# Changelog

All notable changes to **lazychat_erpnext** are documented here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses cycle-tagged releases (`cycle-N[-mM]`) rather than strict semver — the version number bumps roughly track the chapters in [CLAUDE.md](CLAUDE.md), where each cycle's design notes live.

The companion chat-ui ships from [`lazychat.ai`](https://github.com/soumyasethy/lazychat.ai); cross-repo changes are noted as "(chat-ui mirror in lazychat.ai)".

## [Unreleased]

## [0.5.8] — Cycle 18 — Panel minimize state + edit-auto hands-free (host half) — 2026-05-19

Host-shim companion to lazychat.ai cycle-18 (instant edit-auto apply → same-tab navigate → minimize). No backend/tool changes. (chat-ui mirror in lazychat.ai)

### Changed

- **`public/js/lazychat_panel.bundle.js`** — the boolean `maximizeChanged` handler is replaced by a `panelStateChanged` handler that reads `payload.state` ∈ `normal | minimized | maximized` and toggles the mutually-exclusive `lazychat-maximized` / `lazychat-minimized` classes on `#lazychat-panel`.
- **`public/css/lazychat_panel.css`** — new `.lazychat-minimized` rule collapses the docked panel to a 64px circular launcher bubble pinned bottom-right (`top/left: auto`, `border-radius: 9999px`, `overflow: hidden`, drop shadow) and hides the resize handle. The chat-ui paints the bubble inside the shrunken iframe; clicking it posts `panelStateChanged{state:'normal'}` to restore the docked width.
- **Rebuilt `public/lazychat_dist/`** with chat-ui 0.3.0 (instant edit-auto apply + nav + minimize).

### Safety

- In `edit-auto`, destructive mutations now commit instantly with no `/commit` confirmation on the chat-ui side. The server-side two-phase boundary is unchanged — `commit_prepared_action` still re-checks permissions inside a savepoint — but the user-facing confirm step is gone in edit-auto. `ask` mode remains the safe path.

## [0.5.7] — Cycle 17.4 + 17.5 — Effort-tuned retry budgets + Custom Field Link options validation — 2026-05-19

### Added (Cycle 17.4 — Effort-tuned silent-retry budgets)

- **`EFFORT_MAP` in [`claude_bridge.py`](lazychat_erpnext/desk_assistant/claude_bridge.py) gains `runtime_silent_retry_cap` per tier**: low=1, medium=2, high=5, max=8. The cap governs how many silent re-stages the agent should attempt on `sql_phase=runtime` errors before surfacing "I tried N approaches" to the user.
- **`_system_prompt(context, supports_tools, mode, plan_resumed, effort)` now threads the live Effort tier into the system prompt** via an `ACTIVE EFFORT TIER: <tier>. Your silent-retry budget is N attempt(s)...` block at the top. Lets the agent cite the exact cap from rule #11c. Falls back to medium (2) if Effort is unknown.
- **System prompt rule #11c updated** with explicit per-tier budgets so the agent knows when to stop retrying without needing to read EFFORT_MAP directly. Mirrored in chat-ui's [`routerSystemPrompt.ts`](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts).
- **`run_agentic_turn` call site updated** to pass `effort=effort` into `_system_prompt` (previously didn't).

### Added (Cycle 17.5 — Custom Field Link/Table options validation)

- **`prepare_create_custom_field` now validates that `options` references an existing DocType** for `Link` / `Table` / `Table MultiSelect` fieldtypes. Closes the silent-success failure shape where the agent writes `options="Customerr"` (typo) — the Apply at the DB layer succeeds, but the field can't autocomplete to anything, leaving the user with a broken form field and no error to diagnose it.
- **Nearest-match suggestion** via `difflib.get_close_matches` (cutoff=0.55, top 3) — when the agent's options are a typo of a real DocType, the error message includes the suggestions so the agent's next-turn fix is one re-stage away.
- **Why static validation instead of savepoint runtime check?** MariaDB InnoDB's `ALTER TABLE` (which `Custom Field.insert()` triggers via Frappe's `updatedb`) causes implicit COMMIT, breaking the savepoint mechanism cycle 17.0/17.3 use for Reports. We can't safely INSERT a Custom Field inside a savepoint and roll back. Static check is what we can safely do; covers the most common bug class. Future work could use Frappe's `frappe.flags.in_test` to skip schema-sync side effects, enabling savepoint-safe Custom Field runtime checks.

### Verification

- In-process smoke: 317 → **321 pass** / 5 fail (pre-existing) / 6 skip. +4 new T108a-d:
  - T108a — `EFFORT_MAP` has correct retry caps (1/2/5/8) per tier
  - T108b — `_system_prompt` injects live Effort + retry budget into the prompt text
  - T108c — Link field with hallucinated options DocType rejected with nearest-match suggestion
  - T108d — Link field with valid options (e.g. `options="Customer"`) passes (regression guard)
- HTTP-wire smoke: 91/91 unchanged.

### Deferred (still queued)

- **Cycle 17.6 — Anti-pivot enforcement** (detect when agent stages a new Report after just hitting `sql_phase=dependency` and refuse cross-type retries). Today's visual test showed the prompt-only DEPENDENCY ORDER rule works as designed — the agent correctly emitted the user-facing DEPENDENCY CHECKPOINT message and ended the turn cleanly. Server-side enforcement is defense-in-depth for cases where a different model doesn't follow the prompt rule; deferred until we see it fail in the wild.
- **Cycle 17.7 — Coverage extension** to Print Format (cycle 13.2 already dry-renders html; wrap in the runtime-check envelope), Notification, Workflow, Page (cycle-13 screenshot service is the runtime check), Dashboard (render each chart).
- **Cycle 17.8 — Auto-upgrade to claude-opus on retry #4** for runtime-class errors at Effort=max. Requires LLM provider swap logic.

## [0.5.6] — Cycle 17.3 — Pre-Apply runtime verification for Script Reports + in-DB convention fix — 2026-05-19

### Added

- **Extended cycle 17.0's savepoint runtime check to Script Reports** — closes the gap surfaced by cycle 17.2's chat-ui test where the agent pivoted from Query Report to Script Report when Query failed, bypassing the runtime check entirely. The Script Report committed and ran without traceback but `def execute()` returned `None`, producing an empty report.
- **New shared helper `_runtime_verify_report_in_savepoint(rep_values, filter_defs, javascript)`** in [`tools.py`](lazychat_erpnext/desk_assistant/tools.py) — extracts the cycle 17.0 savepoint dry-run logic so both Query Report and Script Report branches reuse it. Returns the same runtime-check envelope. Caller passes the `rep_values` dict (different keys for Query vs Script: `query` vs `report_script` + `script_type=Python`).
- **Return-shape validation in `_runtime_check_query_report`** — when `frappe.desk.query_report.run` returns `{"result": None}` (the agent's `def execute()` was defined but never called), surface as `sql_phase=runtime` with a hint explaining the IN-DB Script Report convention. Empty result list `[]` is treated as success (the report ran but found no matching rows).
- **`_validate_script_report_body` now accepts BOTH conventions** — file-based (`def execute(filters=None)`) AND in-DB (top-level `columns = [...]` + `result = [...]` assignments). Previous validator rejected the in-DB convention with "script must define a top-level `def execute(filters=None)`" — but Frappe's safe_exec for in-DB scripts DOES NOT auto-call functions, so `def execute()` alone produces the null-result bug. The new validator accepts either; the runtime check catches the def-without-call case at safe_exec runtime with an actionable hint.

### Changed

- **`tool_schemas.py` `prepare_create_report.script` description rewritten** to teach the IN-DB convention as the canonical pattern. Old description told the LLM to use `def execute(filters=None): return columns, data` which produces silent null-result bugs for in-DB Script Reports (since safe_exec runs the script but never calls the function). New description shows the top-level `columns` + `result` pattern + flags the def-without-call pattern as WRONG with an explicit example.
- **T87f, T88e smoke cases updated** to use the in-DB convention (top-level vars) — their old `def execute()` scripts now correctly fail the runtime check (which is the new desired behavior).

### Verification

- In-process smoke: 315 → **317 pass** / 5 fail (3 pre-existing httpbin + 1 pre-existing flaky T92c critic_feedback + 1 pre-existing T88q open_url) / 6 skip. +3 new T107a-c:
  - T107a — Script Report with top-level `columns`/`result` vars passes runtime check (verified preview_token, no error)
  - T107b — Script Report defining `def execute()` without calling it → caught at runtime check with `sql_phase=runtime` + hint pointing to the in-DB pattern
  - T107c — Script Report with top-level runtime exception → caught (either by safe_exec dry-run or savepoint runtime check)
- HTTP-wire smoke: 91/91 unchanged.

### Chrome DevTools MCP visual verify — cycle 17.1 dependency-checkpoint landed PERFECTLY

Sent the original Cash Discount Enhancement prompt with v4 report name. Live agent behavior:

1. ✅ Agent staged 5 Custom Fields (cycle 16 cascade + DELIVERABLE DISCIPLINE rule firing).
2. ✅ Agent tried to stage Report → hit `sql_phase=dependency` (cycle 17.1 dep check fired because SQL referenced staged-but-not-applied custom fields).
3. ✅ Agent acknowledged the system signal: *"Perfect — the system identified the dependency."*
4. ✅ Agent wrote a textbook-perfect DEPENDENCY CHECKPOINT message with checkmarks for staged fields, hourglass for pending, and clear "Please click Apply on each Custom Field card above (in order, top-to-bottom). Once all 5 are applied... I'll create the Cash Discount AP Report v4 in your next message."
5. ✅ Agent ended the turn cleanly — waiting for user to click Apply.
6. ✅ NO Notes-as-code fallback (cycle 16 anti-pattern stayed prevented).
7. ✅ Agent also pivoted Server Script → Query Report cleanly when the Server Script gate blocked, with proper user-facing explanation.

Screenshot: [`.github/assets/cycle-16/09-cycle-17-dependency-checkpoint-working.png`](.github/assets/cycle-16/09-cycle-17-dependency-checkpoint-working.png).

This is the FIRST run where the cycle 16 + 17.x architecture works end-to-end as designed. User flow: prompt → wait → see ONE clear dependency-checkpoint message → click Apply on staged Custom Fields → reply "done" → Report appears in next turn (runtime-verified, deps satisfied, Apply card guaranteed working).

## [0.5.5] — Cycle 17.1 — Dependency-aware refusal + Cycle 17.2 chat-ui retry-card polish — 2026-05-19

### Added (Cycle 17.1 backend)

- **Pre-runtime dependency check** for Query Reports — closes the gap surfaced by cycle 17.0 chat-ui test: when a Report's SQL references Custom Fields that are STAGED in the session but not yet APPLIED to the live DocType, the savepoint runtime check used to fail with "Unknown column", and the agent would burn its 5 silent retries on an unfixable bug before falling back to creating a Note. **MariaDB InnoDB's `ALTER TABLE` (which Custom Field insert triggers) causes implicit COMMIT, breaking the savepoint** — so we cannot transiently materialize staged Custom Fields. Instead, new `_check_sql_dependencies_satisfied(query, ref_doctypes)` helper scans the SQL for token-boundary references to any staged-in-session Custom Field fieldnames, and returns a structured refusal: `{ok: false, sql_phase: "dependency", staged_dependencies: [{dt, fieldname, label}, …], hint: "Apply the staged Custom Fields above first, then re-stage the Report next turn"}`. The agent sees this AS A NON-RETRYABLE error and tells the user to click Apply on the Custom Fields first.
- **New system prompt rule #12 — DEPENDENCY ORDER** — added to `_system_prompt` in [`claude_bridge.py`](lazychat_erpnext/desk_assistant/claude_bridge.py) and mirrored in [chat-ui's `routerSystemPrompt.ts`](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts). Tells the LLM: when `sql_phase: "dependency"` arrives, STOP retrying this turn (no agent-side fix is possible), tell the user in plain text to Apply the listed Custom Fields, end the turn, wait for user follow-up. This is the ONE case where the agent SHOULD narrate a checkpoint (the OPPOSITE of cycle 17.0 rule #11 silent-retry).
- **Helpers extracted for reuse**: `_session_staged_custom_field_payloads(dt)` returns full Custom Field payload dicts (sibling to cycle 16's `_session_staged_custom_field_names`); `_extract_doctype_refs_from_sql(sql)` regex-extracts `` `tab<Name>` `` table references.

### Added (Cycle 17.2 chat-ui polish)

- **`mcpTool` Message kind gains `sqlPhase` field** in [`packages/types/src/messages.ts`](../lazychat.ai/packages/types/src/messages.ts) — carries `'runtime' | 'dependency' | 'validate' | 'explain' | 'execute'` extracted from the tool result envelope.
- **`agentRunner.ts onToolEnd`** detects `sql_phase` in the error envelope and threads it through to the `mcpTool` message at replace time.
- **`MCPToolBlock` rendering** now branches on `sqlPhase`:
  - `runtime` / `validate` / `explain` / `execute` errors → muted dot + italic "Verifying… (agent is refining the runtime — will retry automatically)" instead of loud "Failed after Xms". This hides the silent-retry loop from the user.
  - `dependency` errors → orange-asterisk dot + bold "Waiting for Apply — this artifact depends on staged Custom Fields. Apply them above first, then ask again." with collapsible details. Surfaces user-actionable blockers prominently.
  - Other error kinds → unchanged "Failed after Xms" rendering.

### Verification

- In-process smoke: 312 → **315 pass** / 4 fail (T66/T67/T68 pre-existing httpbin + T92c pre-existing flaky duplicate-name) / 6 skip. +3 new T106a-d (T106c was pre-existing):
  - T106a — `_extract_doctype_refs_from_sql` finds backtick-quoted table names
  - T106b — end-to-end: stage CF → stage Report referencing it → returns `sql_phase=dependency` + `staged_dependencies` list (deps_count=1)
  - T106c — Report SQL referencing non-staged missing column → correctly routes to `sql_phase=explain` (NOT dependency, since it's a real typo not a staged-but-not-applied case)
  - T106d — dep check pass-through when no staged CFs reference the SQL
- chat-ui vitest: **475/475 pass**, typecheck clean across all 3 workspaces.
- Chrome DevTools MCP live test (`claude-haiku-latest`, fresh-name prompt "Cash Discount AP Report v3"): backend 0.5.5 + new chat-ui bundle live. Agent stayed on artifact path (16 Custom Field stages, 5 Report attempts, 2 Notes). Final Apply card was a Script Report — agent pivoted to Script Report path when Query Report hit issues. **Note**: cycle 17.0/17.1 savepoint runtime check + dep refusal only wires `Query Report`, not `Script Report` (which uses safe_exec dry-run instead). The Script Report committed and runs without traceback (cycle 17 architecture working as designed for the path it covers), but the agent's Python `def execute()` returns null — a Python-correctness issue, not a Frappe-runtime issue. Cycle 17.3 follow-up: extend runtime-check coverage to Script Report (run via `frappe.desk.query_report.run` which executes both kinds identically).

### Out of scope (deferred follow-ups)

- **Cycle 17.3 — extend runtime check to Script Report + Custom Field + Print Format + Notification + Workflow + Page + Dashboard**. Per the cycle 17 design matrix. Today only Query Report is covered.
- **Cycle 17.4 — Effort-tuned silent-retry budgets** (low=1, medium=2, high=5, max=8 + auto-upgrade to claude-opus on retry #4).
- **Cycle 17.5 — agent-side enforcement of "stop pivoting to a different tool when the dep error says to wait for user"**. Today the prompt rule #12 says "end turn" but the agent sometimes switches to a different report type or creates a Note as a workaround.

## [0.5.4] — Cycle 17.0 — Pre-Apply runtime verification (savepoint dry-run for Query Reports) — 2026-05-19

### Added

- **Pre-Apply runtime verification for `prepare_create_report` Query Reports** — closes the architectural gap that drove cycles 16/16.1: today's stage-time validators catch *some* bugs (regex, EXPLAIN, NULL-substituted EXECUTE probes), but anything pymysql's `mogrify` only sees when given real filter values stayed invisible until the user opened the report and got a traceback. New mechanism:
  1. After existing validators pass, server opens a `frappe.db.savepoint`.
  2. INSERTs the Report doc + injects filters into `Report.javascript` (mirrors what the real commit handler does).
  3. Calls `frappe.desk.query_report.run(name, filters=<synthesized defaults>)` — the EXACT path Frappe uses when the user opens the report.
  4. ROLLBACKs the savepoint regardless of outcome — the dry-committed Report row never persists.
  5. Returns either a verified-working `preview_token` (with REAL sample rows from the runtime check, not NULL-substituted probe rows) OR `{ok: false, sql_phase: "runtime", traceback, hint}` so the LLM re-stages in the same loop.
- Three new helper functions in [`tools.py`](lazychat_erpnext/desk_assistant/tools.py):
  - `_inject_query_report_filters_into_javascript(doc, filter_defs)` — extracted from cycle 16.1 commit handler so dry-run and real commit stay byte-aligned.
  - `_synthesize_default_filters(filter_defs)` — type-aware default-value generator (Date → today, Link → first existing doc of linked DocType, Select → first option, Int/Float/Currency/Check → 0, Data/Text → ""). Honors literal `default` values from filter defs but skips JS-side function expressions.
  - `_runtime_check_query_report(report_name, filter_defs)` — invokes `frappe.desk.query_report.run`, maps `ValueError`/`KeyError`/`OperationalError`/`PermissionError` to actionable hints, returns `{ok, sample_rows?, error?, traceback?, hint?}`.
- **System prompt rule #11 — RUNTIME-RETRY DISCIPLINE** — added to `_system_prompt` in [`claude_bridge.py`](lazychat_erpnext/desk_assistant/claude_bridge.py) and mirrored in [chat-ui's `routerSystemPrompt.ts`](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts). Tells the LLM: when `sql_phase: "runtime"`, do NOT narrate the failure to the user (retry should be invisible), read the hint, re-stage in the same turn, cap attempts at 5 per artifact, then surface a brief blocker summary if still failing.

### Verification

- In-process smoke: 307 → **312 pass** / 3 fail (pre-existing httpbin) / 6 skip. +5 new T105a-e:
  - T105a — happy-path runtime check passes, returns verified preview_token
  - T105b — `_runtime_check_query_report` returns structured `{ok:false, hint, traceback}` for missing report
  - T105c — savepoint rolls back dry-committed Report (no DB persist before user clicks Apply)
  - T105d — `_synthesize_default_filters` per-fieldtype defaults (Date/Link/Select/Int/Float/Check/Data + literal default override)
  - T105e — e2e: runtime-verified `prepare_create_report` → `commit_prepared` → `frappe.desk.query_report.run` returns rows
- HTTP-wire smoke: 91/91 unchanged.
- Chrome DevTools MCP live test (`claude-haiku-latest`, fresh-name prompt "Cash Discount AP Report v2"): agent issued `prepare_create_report` **6 times**, each iteration consuming the runtime error hint to refine the SQL ("Perfect! Let me fix the SQL escaping and try again" → "The issue is with line breaks" → "The issue is with the alias"). The retry mechanism IS firing as designed. **Architectural gap surfaced**: when the SQL depends on Custom Fields that are still STAGED but not yet COMMITTED, the runtime check fails on schema-missing (the staged Custom Fields don't exist in the live DocType meta the savepoint runtime check queries). Agent eventually pivoted to creating a Note (cycle-16 anti-pattern reappeared after retry exhaustion). Two follow-ups noted in CLAUDE.md Cycle 17.0 "Open follow-ups".

## [0.5.3] — Cycle 16.1 — SQL `%`-escape + filter-completeness guards + end-to-end RUN methodology — 2026-05-19

### Fixed

- **LLM-generated Query Reports commit successfully but throw `ValueError: unsupported format character` at report-run time** — surfaced by running the Cycle 16 Cash Discount Report end-to-end (user opened the report and Frappe tried to execute the SQL). Agent emitted `CASE WHEN ... THEN '30-Day: Apply 2%'` with bare `%` in a string literal. Frappe's `report.execute_query_report(filters)` calls `frappe.db.sql(query, filters)`; pymysql's `mogrify` does Python `query % args` substitution BEFORE the SQL hits MariaDB, and the bare `%'` raises `ValueError: unsupported format character ''' (0x27)`. The EXPLAIN-probe and EXECUTE-probe both passed because they don't pass a filters dict — pymysql skips `%` substitution when args is omitted. New `_validate_sql_percent_escaping(query)` in [`tools.py`](lazychat_erpnext/desk_assistant/tools.py) scans for `%` not part of `%(name)s` or `%%`, refuses with actionable hint pointing to the escape rule. Wired into `prepare_create_report` Query Report branch BEFORE EXPLAIN, and into the commit handler for defense-in-depth.
- **LLM-generated Query Reports with `%(name)s` placeholders but no matching filter field definitions throw `KeyError: 'from_date'` at report-run time** — same Cash Discount Report symptom, second bug. Agent ships SQL with `WHERE posting_date BETWEEN %(from_date)s AND %(to_date)s AND company = %(company)s` but the staged `filters` arg defaults to `{}` (empty dict). Frappe commits the Report row, then at open-time invokes the report with `filters={}` → pymysql can't find `from_date` → KeyError traceback. New `_validate_sql_filter_completeness(query, filters_arg)` extracts all `%(name)s` placeholders from query, normalizes the `filters` arg (accepts both `list` of filter-field dicts and legacy `dict`), refuses when any placeholder lacks a matching definition. Returns example shape of correct `filters` arg in the hint. Wired in both stage + commit.
- **Even after the stage-time guard accepts a Query Report with proper filter defs, Frappe's Desk filter form was empty** — discovered during chrome-devtools MCP verification: `frappe.query_report.filters` array was `[]`. Root cause: Frappe Query Reports read their filter definitions from `Report.javascript` (`frappe.query_reports[<name>].filters = [...]`), NOT from `Report.json` (which is Report Builder's convention). The commit handler was writing to `.json`, which Query Reports ignore. Fix: commit handler now auto-injects an additional `frappe.query_reports[<name>].filters = <filters>` assignment into `Report.javascript` for Query Reports, preserving any existing javascript (e.g. `onload` handlers with inner buttons) verbatim by appending after it. T104l smoke verifies the assignment lands in the saved doc.
- **Cycle 16 verification methodology missed both bugs above** — Cycle 16 only verified "Report row exists in DB + page-shell renders title", not "report actually RUNS without traceback". New T104k smoke case enforces the proper end-to-end methodology: stage `prepare_create_report` → `commit_prepared` → `frappe.desk.query_report.run(report_name, filters={…})` → assert `result` is a list. Any future regression that breaks runtime execution (not just DB write) is now caught at smoke time.

### Changed

- T87d updated to pass a matching `filters` definition with its `%(customer)s` placeholder — its old expectation (tolerate placeholders without defs) was the bug Cycle 16.1 fixes.

### Verification

- In-process smoke: 299 → **307 pass** / 3 fail (pre-existing httpbin.org-dependent T66/T67/T68 unchanged) / 6 skip. +7 new cases T104e-l:
  - T104e — bare `%` in CASE string rejected
  - T104f — proper `%%` + `%(name)s` accepted
  - T104g — empty filters arg rejected when placeholders present
  - T104h — complete filter defs accepted
  - T104i — end-to-end via `prepare_create_report`: bare `%` rejected at stage with `sql_phase=validate`
  - T104j — end-to-end via `prepare_create_report`: unmatched placeholders rejected at stage with `sql_phase=validate`
  - **T104k — end-to-end stage → commit → RUN succeeds without ValueError/KeyError** (row_count=4 against real ToDo data)
  - **T104l — commit handler auto-injects `filters` into `Report.javascript`** (verified saved doc has `frappe.query_reports[<name>].filters = [...]` assignment)
- HTTP-wire smoke: 91/91 unchanged (no tool surface change, no schema change).
- Chrome DevTools MCP end-to-end: navigated to `/app/query-report/Cash Discount Report - AP`, set filters (Company=Agilitas Brands, From=2025-12-01, To=2025-12-31), triggered `frappe.query_report.refresh()` → **53 rows rendered in the datatable with zero errors** (after applying both fixes: `%` → `%%` SQL escape + filters injected into `Report.javascript`). Screenshot evidence: [`.github/assets/cycle-16/06-report-working-53-rows.png`](.github/assets/cycle-16/06-report-working-53-rows.png).

## [0.5.2] — Cycle 16 — Deliverable Discipline — 2026-05-19

### Fixed

- **Agent dumps Python/JS as `prepare_create_note` "implementation guide" Notes when it can't build the actual artifact** — surfaced by real-user replay of a "Cash Discount Report for AP" prompt on `claude-haiku-latest`. Agent staged ONE Custom Field, then 5 cascading Custom Fields failed validation (Bug B below), then pivoted to creating two Notes titled "Cash Discount Enhancement - Complete Implementation Guide" and "Cash Discount - Server-Side Python Implementation" each dumping `FILE 1: hooks.py` / `FILE 2: hooks.py` style Python code. Useless artifacts on a running ERPNext — the user can't paste hooks.py into a Note and have it execute. The actual Report was only created after the user typed "where is report?" five turns later. New heuristic guard in `prepare_create_note`: if body matches `(import frappe|def execute\(|hooks\s*=|@frappe\.whitelist|frappe\.db\.(get_list|sql|get_value|set_value)|class \w+\(Document\))` 2+ times AND title hints implementation/guide/server-side/hooks/FILE-N → refuse with structured redirect to `prepare_create_server_script` / `prepare_create_report` / `prepare_create_custom_field`. False-positive risk minimized by requiring both signals (code-shape AND implementation-y title).
- **Custom Field cascade fails because `insert_after` validates against live DocType only** — when the LLM stages a coherent group (Section Break → 30 Days % → 60 Days % → 90 Days % → Column Break → Enable Check), only the first one validates; subsequent calls fail with "insert_after '<staged-sibling>' is not a fieldname on <dt>" because the live DocType meta doesn't have them yet (only Redis-staged). New helper `_session_staged_custom_field_names(dt)` scans `lazychat:prep:*` keys for the current user's staged `create_custom_field` actions on the same `dt`, returns the set of staged `fieldname`s. Validator unions live + staged. Implementation handles Frappe's `make_key` site-name prefix correctly (`get_keys` returns prefixed bytes; `get_value` expects unprefixed keys — strip the `<db_name>|` prefix before lookup).
- **Agent papers over real-tool failure with work-shaped output** — DELIVERABLE DISCIPLINE prompt rule (rule #10) added to `_system_prompt` and mirrored in chat-ui's `routerSystemPrompt.ts` `_SHARED_GUIDANCE`. Tells the agent: (a) stage dependencies first, primary artifact LAST so it's the final Apply card; (b) NEVER use `prepare_create_note` as substitute for a real artifact — Notes are for human text; (c) if a tool fails twice on the same target, STOP and tell the user what blocked you; (d) for compound business requests, emit a numbered Plan up front naming each artifact.

### Verification

- In-process smoke: 295 → **299 pass** (+4 new T104a-d cases). 3 pre-existing network-dependent fails (T66/T67/T68 against httpbin.org) unchanged, unrelated to cycle-16.
- Live chrome-devtools MCP replay of the exact Cash Discount Report prompt on `claude-haiku-latest`: **zero `prepare_create_note` calls** (compared to 2 in the original screenshots). Agent stayed on artifact-building throughout (12 Custom Field stages, 5 DocType stages, multiple `describe_doctype` discovery calls). Cascade insert_after validation passed for in-order staged siblings. Token budget exhausted before report completion is a separate orthogonal issue (Effort=medium ceiling) — the Notes-dump anti-pattern is eliminated.
- Round-trip via bench execute: helper sees 7 staged Custom Fields across the test session; refuse-code-dump fires with correct error+hint envelope; normal-text Note still accepts.

## [0.5.1] — Cycle 15.1 — Print Format `custom_format=1` hotfix — 2026-05-19

### Fixed

- **`prepare_create_print_format` produced Print Formats that silently fell back to the default fieldgroup layout** — surfaced by browser-replay testing the cycle-15 flow. The commit handler created the doc with `print_format_type='Jinja'` and a populated `html` field, but didn't set `custom_format=1`. Frappe ignores the `html` field when `custom_format=0` and renders the standard layout — the agent reported success and the URL opened (cycle-15 fix), but the actual `?format=...` print preview never showed the LLM-authored template. One-line fix in `commit_prepared(action='create_print_format')` adds `custom_format: 1` to the inserted doc. Verified end-to-end via Chrome DevTools MCP against a real Purchase Order — template now renders correctly on first commit.

### Verification

- Round-trip in bench console: `prepare_create_print_format` → commit → read back: `custom_format == 1` ✓.
- Visual: `/printview?doctype=Purchase+Order&name=PO-C-26-000002&format=Purchase+Order+-+Agilitas` shows the LLM-written template (header, order details, supplier section, items table, grand total) instead of the default layout. Evidence at [`.github/assets/cycle-15/06-template-rendered-on-real-PO-after-custom-format-fix.png`](.github/assets/cycle-15/06-template-rendered-on-real-PO-after-custom-format-fix.png).

## [0.5.0] — Cycle 15 — Apply-path hardening — 2026-05-16

### Fixed

- **URL slug 404 on typed-create Apply** — commit response `link` field used `frappe.scrub()` (underscores) instead of Frappe Desk's URL slug (hyphens). Added `_doctype_url_slug(doctype)` helper, replaced 4 call sites (commit response link, preview open_url for print format, revert handler, form-prefill capabilities). Print Format / Sales Invoice / Purchase Order and other multi-word doctypes now navigate correctly after Apply.
- **Agent loops on duplicate-create** — typed `prepare_create_*` wrappers now pre-check existence and return a structured `prepare_update_doc` redirect on duplicate. New `_exists_redirect_to_update()` helper applied to 14 wrappers (Print Format, Report, KB, Note, Email Template, Email Group, Milestone Tracker, Number Card, Dashboard, Scheduled Job, Custom Field, Page, Workspace, Server Script). Calendar Event and Client Script intentionally skipped (hash autoname + suffix-loop respectively handle their cases differently).
- **`PREP_TTL_SEC` too short** — bumped from 300 (5 min) to 1800 (30 min). Multi-turn agent loops survive realistic latency budgets. `_retrieve_action` refactored to distinguish three error categories (malformed / missing-or-expired / wrong-user) with actionable messages.
- **Agent emits ghost CTAs** — `MAX_TURNS` default bumped from 8 to 16 (aligns with chat-ui's effort=medium budget). New CTA HONESTY system-prompt rule forbids "Click Apply" text without an accompanying `prepare_*` tool call in the same turn.

### Changed

- Tool-schema descriptions for typed `prepare_create_*` wrappers updated to spell out the duplicate-handling contract.
- System prompt gained DUPLICATE PIVOT + CTA HONESTY rules (mirrored in chat-ui's `routerSystemPrompt.ts`).

### Smoke

- In-process: 283 → 293 / 0 fail (+10 new T103a-T103o cases; 5 pre-existing fails T66/T67/T68/T101b/T101d unchanged, unrelated to cycle-15).
- HTTP-wire: 91/91 unchanged (no new tools, no schema changes).
- Chat-ui vitest: 472 → 475 (+3 ghost-CTA detection).

## [0.4.3] — Cycle 14.6 — backfill stale tool counts in user-facing docs — 2026-05-15

Pure docs/text fix. No Python code change. Tag: `cycle-14.6`.

### Fixed

- Stale tool-count strings across 4 files that still referenced the old `38` / `94` / `95` numbers from earlier cycles (Cycle 7 had 38, marketing video referenced 94, Cycle 11 had 95). All now say **`101`** to match `tool_schemas.py:TOOL_SCHEMAS`:
  - `README.md` — 4 mentions ("Tool catalog — all 95", "all 95 tools available", "all 95 tools registered", "all 95 tools")
  - `CLAUDE.md` — 2 lines (top-of-file "Tool registry — 38 tools" + the dual-path section's "Both paths share tools.py (38 tools, 1 implementation, 0 drift)")
  - `lazychat_settings/lazychat_settings.json` — covered in cycle-14.4 already
  - `lazychat_skill/lazychat_skill.json` — `allowed_tools` field description: "Leave empty to allow all 38 tools" → "all 101 tools"
  - `.github/assets/architecture.svg` — diagram label "tools.py · 94 tools" → "tools.py · 101 tools"

The historical CHANGELOG entries (cycle-13 noting "95 → 101", cycle-14.4 explaining the help_html fix) remain unchanged — they're correct point-in-time records.

### Verification

- `grep -rn "38 tools|94 tools|95 tools" .` returns only the historical CHANGELOG/spec/test-evidence entries that describe the upgrade path. No live user-facing string still says the wrong number.

### Commits in this release

```
<sha> docs(cycle-14.6): backfill 38/94/95 → 101 across README + CLAUDE.md + lazychat_skill + architecture.svg + version bump → 0.4.3
```

## [0.4.2] — Cycle 14.5 — llm_proxy mirrors inbound HTTP method (GET pass-through for /v1/models) — 2026-05-15

Backend-only fix to [`llm_proxy.handle`](lazychat_erpnext/desk_assistant/llm_proxy.py). Unblocks the chat-ui's "Fetch models" button on the BYO custom-model editor. Tag: `cycle-14.5`.

### Fixed

- **"Fetch models" returned HTTP 403** when the user clicked it on any cross-origin endpoint (Groq, OpenAI, OpenRouter, NVIDIA, etc.). Two compounding bugs:
  1. `llm_proxy.handle` was whitelisted with `methods=["POST", "OPTIONS"]` only. The chat-ui's `fetchModels` does `fetch(proxyUrl)` (no explicit method = default GET), so Frappe rejected the request at the auth gate before the handler ran.
  2. Even if GET were allowed, the handler hardcoded `requests.post(target_url, ...)` for the upstream call. All providers expose `/v1/models` as GET-only, so the upstream would have 4xx'd anyway.

  Fix:
  - Added `"GET"` to the `@frappe.whitelist(methods=...)` list.
  - Replaced `requests.post(...)` with `requests.request(method, ...)` to mirror the inbound HTTP method to the upstream. GET requests now have no body forwarded (matches HTTP semantics).
  - All other behavior unchanged (host allowlist, header filtering, x-target-authorization rename, streaming response, timeout/error envelopes).

### Verification

- Backend: no smoke surface change; in-process smoke unchanged at 283/0/6.
- Manual: `curl -X GET http://localhost:8000/api/method/lazychat_erpnext.desk_assistant.llm_proxy.handle -H 'x-target-url: https://httpbin.org/get'` now reaches the handler (was 403-method-not-allowed pre-fix; now 403-not-authenticated for unauth'd guest requests, which is the correct behavior).
- E2E: in the chat-ui Model picker → Edit → click "Fetch models" → Groq returns the live model list → user can pick from a dropdown instead of typing the model id by hand.

### Commits in this release

```
<sha> fix(cycle-14.5): llm_proxy allows GET + mirrors inbound HTTP method
<sha> docs(cycle-14.5): CHANGELOG + CLAUDE.md + version bump → 0.4.2
```

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

[Unreleased]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-15...HEAD
[0.5.7]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-17.3...cycle-17.5
[0.5.6]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-17.1...cycle-17.3
[0.5.5]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-17.0...cycle-17.1
[0.5.4]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-16.1...cycle-17.0
[0.5.3]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-16...cycle-16.1
[0.5.2]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-15.1...cycle-16
[0.5.1]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-15...cycle-15.1
[0.5.0]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-14.6...cycle-15
[0.4.3]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-14.5...cycle-14.6
[0.4.2]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-14.4...cycle-14.5
[0.4.1]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-14...cycle-14.4
[0.4.0]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-13.2...cycle-14
[0.3.1]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-13.1...cycle-13.2
[0.3.0]: https://github.com/soumyasethy/lazychat-erpnext/compare/cycle-12-m2...cycle-13.1
