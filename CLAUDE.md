# lazychat-mcp-erpnext — Claude project knowledge

Read this BEFORE exploring the repo. Saves ~75% tokens.

## What this repo is

A **Frappe app** (`lazychat_mcp_erpnext`) that turns ERPNext into an LLM-driven agentic workspace. Two installation surfaces:

1. **Legacy widget** — vanilla-JS right-dock chat panel (in [public/js/lazychat_mcp_erpnext_desk.js](lazychat_mcp_erpnext/lazychat_mcp_erpnext/public/js/lazychat_mcp_erpnext_desk.js)). Disabled by default since the lazychat panel landed.
2. **Lazychat panel** (current) — embeds the [lazychat-ai](../lazychat.ai/) React UI as a same-origin iframe inside the Desk via a 280-line vanilla-JS shim ([public/js/lazychat_panel.bundle.js](lazychat_mcp_erpnext/lazychat_mcp_erpnext/public/js/lazychat_panel.bundle.js)). The iframe talks to the Frappe backend via `agentRequest` postMessage → `send_message_stream` SSE → `run_agentic_turn`. Same backend, much richer UI.

Backend is fully built and battle-tested:
- **Multi-provider LLM** ([providers/](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/providers/)): two adapters cover Anthropic + everything OpenAI-compatible (OpenAI, OpenRouter, NVIDIA, Vercel AI Gateway, LM Studio, Groq, Together).
- **Agent loop** ([claude_bridge.py](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/claude_bridge.py)) with prompt caching, tool-use loop, max 8 turns.
- **Tool registry** — 38 tools, all run with `frappe.session.user`'s permissions (no god-mode bypass).
- **Two-phase mutation pattern**: agent calls `prepare_*` → returns `preview_token` → user types `/commit TOKEN` in chat → shim calls `commit_prepared_action(token)` → executes inside `frappe.db.savepoint`. The LLM is physically incapable of committing on its own (commit method is NOT in the tool registry).

Default install: lazychat panel ON, legacy widget OFF, dist served from `/assets/lazychat_mcp_erpnext/lazychat_dist/index.html` (same-origin, port-free).

## Architecture

```
ERPNext Desk @ <site>/app
├── lazychat_panel.bundle.js  (loaded via app_include_js on every Desk page)
│   ├── mounts iframe + slide-out chrome (FAB, resize handle, theme-aware CSS)
│   ├── postMessage envelope {v:1, src, id, type, payload} per lazychat protocol
│   └── intercepts /commit <token>  →  POST commit_prepared_action
│
├── iframe @ /assets/lazychat_mcp_erpnext/lazychat_dist/index.html?frame=sidebar
│   └── lazychat React UI (multi-tab, markdown, mutation previews, theme tokens)
│
└── On user send → agentRequest postMessage:
       shim → POST /api/method/lazychat_mcp_erpnext.desk_assistant.api.send_message_stream
                 → run_agentic_turn (Anthropic Messages API streaming)
                     → on tool_use: tools.py.execute_tool (with frappe.set_user)
                         → frappe.get_list / frappe.get_doc / etc — REAL ERPNext data
                     → SSE events back: text_delta / tool_use / tool_result / done
                 → shim re-emits as agentChunk postMessage → chat-ui streams in
```

## Source-of-truth + multi-bench install

```
~/Desktop/code-chat/
├── lazychat.ai/                                  # chat-ui React source (separate repo)
│   └── apps/chat-ui/dist/                        (built by `pnpm build`)
└── lazychat-mcp-erpnext/                                  # THIS repo (Frappe app source)
    ├── lazychat_mcp_erpnext/lazychat_mcp_erpnext/
    │   ├── public/lazychat_dist/                 # bundled chat-ui (gitignored, built locally)
    │   ├── public/js/lazychat_panel.bundle.js
    │   ├── public/css/lazychat_panel.css
    │   ├── public/js/lazychat_mcp_erpnext_desk.js    # legacy widget (gated off by default)
    │   ├── desk_assistant/{api,boot,claude_bridge,tools,tool_schemas}.py
    │   ├── desk_assistant/providers/             # LLM adapters
    │   ├── seed_data.json                        # LLM Provider/Model fixtures
    │   ├── install.py                            # after_install + after_migrate hooks
    │   ├── hooks.py                              # app_include_js/css, extend_bootinfo
    │   └── _smoke.py                             # 53-assertion smoke test (NOT shipped — `cp` from scripts/)
    └── scripts/
        ├── build-lazychat-dist.sh                # builds chat-ui, rsyncs into app
        ├── deploy-local.sh                       # rsyncs source → bench, optional bench restart
        └── smoke-test-tools.py                   # source for _smoke.py
```

**Install on a fresh ERPNext bench:**
```bash
# One-time per machine: build chat-ui dist
cd ~/Desktop/code-chat
./lazychat-mcp-erpnext/scripts/build-lazychat-dist.sh   # auto-finds ../lazychat.ai

# Per bench
BENCH_ROOT=/path/to/that/bench DEPLOY_SITE=site.example \
  ./lazychat-mcp-erpnext/scripts/deploy-local.sh
# First-time on a bench that doesn't have the app:
cd /path/to/that/bench
bench get-app file:///path/to/lazychat-mcp-erpnext
bench --site site.example install-app lazychat_mcp_erpnext
# (after_install runs: seeds LLM Provider/Model, prints welcome banner with next steps)
```

**Defaults work without any site_config edits.** Boot extension reads `lazychat_iframe_src` from `site_config.json` if set; otherwise defaults to bundled dist.

## Tool registry — 69 tools (all permission-scoped to `frappe.session.user`)

The registry has grown well past the original 38 documented in earlier
revisions. **Treat `tool_schemas.py:TOOL_SCHEMAS` as the source of truth**;
T54 in the smoke test compares `len(TOOL_SCHEMAS)` to the live MCP
`tools/list` count, so the assertion stays correct as tools are added.

| Category | Count | Examples |
|---|---|---|
| Discovery / reads | 10 | get_list, get_doc, get_value, count_doc, describe_doctype, get_current_context, get_doctype_links, search_doctype, search_global, search_link |
| Aggregation / analytics | 8 | aggregate, dashboard_chart_data, number_card_value, list_user_dashboards, get_sales_summary, get_pending_approvals, list_my_jobs, get_open_invoices |
| Reports | 3 | list_reports, report_requirements, run_report |
| Workflow | 2 | list_workflow_actions, prepare_workflow_action |
| ERPNext domain | 7 | get_stock_balance, get_account_balance, get_outstanding, get_item_price, get_company_defaults, get_user_info, get_audit_trail |
| Files | 3 | list_attachments, get_file_url, extract_file_content |
| Subscriptions / charts / jobs | 5 | subscribe_doc_changes, unsubscribe_doc_changes, list_my_subscriptions, make_chart, cancel_job |
| Mutations (`prepare_*`) | 19 | create / update / submit / delete / comment / assign / share / upload / import_csv / rename / revert / send_email / workflow / run_sql / run_python / **create_report / create_scheduled_job / create_number_card / create_dashboard** (typed wrappers, 2026-05-06) |
| Exports | 2 | export_list_to_csv, export_doc_pdf |
| Knowledge Base (Tier H) | 6 | list_knowledge_bases, get_kb_files, search_kb, reindex_kb, prepare_create_kb, prepare_add_file_to_kb |
| Skills (Tier E) | 3 | list_skills, activate_skill, deactivate_skill |
| Misc | 1 | get_system_info, list_doc_versions, list_my_jobs |

**Defensive arg coercion** (added 2026-05-05): `tools.py:_coerce_args()`
runs at the top of `execute_tool` before dispatch. Non-tool-trained models
(seed-oss-36b, smaller open-weight models) routinely emit `tool_calls`
with everything stringified — `filters: "{}"`, `fields: "['name']"`,
`limit: "1"` — even when the schema declares them as objects/arrays/ints.
Without this normalizer, `frappe.get_all(fields="['name']")` generates
broken SQL because the string is interpreted as a single weird field name.
The coercer JSON-parses well-known schema-shaped keys (filters, fields,
values, patch, spec, …) and int-coerces well-known integer keys (limit,
max_chunks, …). Idempotent — already-typed args pass through unchanged.
T75 + T76 cover the regression.

**`get_doc` child-table truncation** (added 2026-05-05): `tools.py:get_doc` calls `_trim_doc(doc.as_dict(), max_child_rows=25)` before returning. Without this, Sales Orders with 50+ line items produced 20–50 KB JSON blobs that overflowed LLM context windows and caused the agent to stall silently. `_trim_doc` keeps all scalar header fields, trims each list (child table) to 25 rows, and injects a `"_note"` key summarising what was trimmed and telling the LLM to use `get_list` for the full data. The 12,000-char `mcpResultToText` cap in `mcp-client.ts` serves as a second-layer safety net on the browser-LLM path.

**Two-phase mutation flow** (prevents LLM from self-committing):
1. LLM calls `prepare_*` → tool stages action to Redis with token (5-min TTL, bound to user) → returns `{preview_token, summary, diff?, confirm_with: '/commit TOKEN'}`
2. Agent narrates the preview, tells user "Reply with `/commit TOKEN`"
3. User types `/commit <token>` → shim's regex catches it → POSTs `commit_prepared_action(token)` (NOT in the tool registry, LLM can't call it)
4. Server re-checks permissions, runs inside `frappe.db.savepoint`, consumes token

**Power tool gating** (defense in depth, all required):
1. Site flag: `"lazychat_allow_dangerous_tools": true` in site_config.json
2. Caller has `System Manager` role
3. `/commit` confirmation per call
4. SQL: regex-validated SELECT-only, no DML/DDL, no multi-statement
5. Python: timeout, captured stdout, runs as the calling user

**Email gating**: `prepare_send_email` requires `"lazychat_allow_email": true` in site_config.

## Configuration: Lazychat Settings doctype (primary) + site_config (advanced override)

**Primary admin surface: `/app/lazychat-settings`** (System Manager edit). Fields:

| Field | Default | What it does |
|---|---|---|
| `enabled` | `true` | Mount the panel at all (master switch) |
| `iframe_base_url` | `/assets/lazychat_mcp_erpnext/lazychat_dist/index.html` | Where chat-ui loads from — override for remote chat-ui or HMR dev (`http://127.0.0.1:5173`) |
| `iframe_query_params` | `?frame=sidebar` | Appended to base_url |
| `chat_path` | `auto` | `auto` / `browser` / `backend` — see "Two chat paths" above |
| `mcp_endpoint` | `/api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle` | Read-only; browser-LLM path uses this |
| `legacy_widget_enabled` | `false` | Mount the OLD vanilla-JS widget INSTEAD of the iframe (mutually exclusive) |
| `allow_email` | `false` | Enable `prepare_send_email` |
| `allow_dangerous_tools` | `false` | Enable `prepare_run_sql` + `prepare_run_python` (still gated by System Manager role + `/commit`) |

**Advanced overrides via `site_config.json`** (these win over the doctype values — backward compat for installs that set them before the doctype existed):

```json
{
  "lazychat_iframe_src": "...",
  "lazychat_panel_enabled": true,
  "lazychat_legacy_widget_enabled": false,
  "lazychat_allow_email": false,
  "lazychat_allow_dangerous_tools": false
}
```

`boot.py:get_lazychat_settings()` is the single resolver — reads doctype, then layers site_config overrides, then exposes under `frappe.boot.lazychat_settings` for the panel shim and under the same dict for `tools.py` gates. **Use this helper anywhere on the server side** that needs settings; do NOT call `frappe.get_site_config()` directly for these flags.

## API surface (whitelisted methods)

**Backend-LLM path (existing):**
- `lazychat_mcp_erpnext.desk_assistant.api.send_message` — batch JSON `{conversation_id, events, usage}`
- `lazychat_mcp_erpnext.desk_assistant.api.send_message_stream` — SSE: `event: text_delta|tool_use|tool_result|usage|done|error`
- `lazychat_mcp_erpnext.desk_assistant.api.commit_prepared_action` — apply a staged action by token (NOT exposed to the LLM tool loop)
- `lazychat_mcp_erpnext.desk_assistant.api.list_models` — model picker data
- `lazychat_mcp_erpnext.desk_assistant.api.discover_remote_models` — fetch /models from a provider
- `lazychat_mcp_erpnext.desk_assistant.api.test_llm_provider_connection` — connection probe

**Browser-LLM path:**
- `lazychat_mcp_erpnext.desk_assistant.api.save_conversation` — push browser-orchestrated turns into Claude Conversation
- `lazychat_mcp_erpnext.desk_assistant.mcp.handle` — JSONRPC MCP transport (initialize / ping / tools/list / tools/call). Same auth as any whitelisted method (cookie session OR Frappe API key+secret). Used by both chat-ui's browser path AND external MCP clients (Claude Desktop, etc).

## Doctypes

- `LLM Provider` — name, provider_type (anthropic | openai_compatible), base_url, api_key (Password), extra_headers, enabled
- `LLM Model` — model_label, provider Link, model_id, supports_tools, max_output_tokens, context_window, input_price_per_mtok, output_price_per_mtok, is_default, enabled
- `Claude Conversation` — user, title, history (JSON), last_model, total_input_tokens, total_output_tokens

Seed fixtures in [seed_data.json](lazychat_mcp_erpnext/lazychat_mcp_erpnext/seed_data.json) auto-load via `after_install` + `after_migrate`. Ships disabled-by-default rows for OpenAI/OpenRouter/NVIDIA/Vercel/LM Studio.

## Smoke test — two layers (added 2026-05-05)

A two-layer harness covers every tool. Both must be green to ship.

### Layer 1 — HTTP MCP wire (`test/curl_smoke.py`, all 65 tools)

Pure-stdlib HTTP smoke that hits `POST /api/method/.../mcp.handle`
directly, with real fixtures and per-tool content validators (not just
"HTTP 200"). Catches drift the in-process Layer 2 can't see — CSRF/auth,
JSONRPC envelope shape, content-type, body-shape regressions.

```bash
# 1) Provision fixtures (idempotent — Note + File + KB + queued Job, plus
#    resolves real Customer / SO / Item / Chart / Card / Report /
#    Workflow / PrintFormat / company / file_url from existing site data)
cp lazychat-mcp-erpnext/test/setup_fixtures.py \
   <bench>/apps/lazychat_mcp_erpnext/lazychat_mcp_erpnext/_setup_fixtures.py
cd <bench> && bench --site <site> execute lazychat_mcp_erpnext._setup_fixtures.run

# 2) Run Layer 1
cd ~/Desktop/code-chat
python3 lazychat-mcp-erpnext/test/curl_smoke.py
# expected:
#   [curl_smoke] summary: OK=54 | OK_ERROR=11
#   [curl_smoke] tools registered: 65, called: 65
```

`OK_ERROR` = graceful expected error: gated tools (allow_email,
allow_dangerous_tools), probes against deliberately-non-existent
fixtures. Validators per tool live in `test/tool_args.py`.

### Layer 2 — in-process (`scripts/smoke-test-tools.py`)

```bash
cp lazychat-mcp-erpnext/scripts/smoke-test-tools.py \
   <bench>/apps/lazychat_mcp_erpnext/lazychat_mcp_erpnext/_smoke.py
cd <bench>
bench --site <site> execute lazychat_mcp_erpnext._smoke.run
# expected: === 84 pass, 0 fail, 0 skip ===
```

Currently 84 cases — exercises read/mutation/workflow/analytics/MCP-wire/
settings paths in-process (calls `execute_tool()` directly, bypassing
HTTP). Critical recent additions:

- **T54** unhardcoded "38" → `len(TOOL_SCHEMAS)` (future-proof).
- **T67** rewritten to verify the actual llm_proxy security model — strip
  Frappe-internal `Authorization`/`X-Frappe-CSRF-Token`, rewrite
  `x-target-authorization` → `Authorization` upstream.
- **T69-T72** for the 3 newest tools (`list_attachments`, `get_file_url`,
  `make_chart`).
- **T73-T74** cancel_job idempotency regression.
- **T75-T76** stringified-args coercion regression (the seed-oss-36b
  arg-shape bug — see Tool Registry section above).

Target = always 100% pass. When adding a new tool: add a T## case AND
its `tool_args.py` entry + validator, then re-run both layers.

### Deploy gotcha — rsync wipes the bench-side smoke files

`scripts/deploy-local.sh` runs `rsync --delete` from the source repo into
`<bench>/apps/lazychat_mcp_erpnext/`. The smoke files live at
`<bench>/apps/.../_smoke.py` and `_setup_fixtures.py` (gitignored, NOT
in source — they get cp'd in for runs only). **Every deploy wipes them.**
Re-run the `cp` commands above before invoking `bench execute` after a
deploy, otherwise the runner errors with `NameError: name
'lazychat_mcp_erpnext' is not defined` (because Frappe can't find the
function path).

## Conventions

- **Source-of-truth lives in this repo** at `lazychat_mcp_erpnext/`. The bench's `apps/lazychat_mcp_erpnext/` is a deploy target — `scripts/deploy-local.sh` rsyncs `--delete`. Edits made directly in the bench will be wiped on next deploy. Always edit source first, then `cp` (or deploy script) to bench.
- Smoke test script `_smoke.py` is gitignored / NOT in source — it's a copy from `scripts/smoke-test-tools.py`. Run `cp scripts/smoke-test-tools.py <bench>/.../lazychat_mcp_erpnext/_smoke.py` before `bench execute`.
- Bundled chat-ui dist (`public/lazychat_dist/`) is **gitignored**. Rebuild via `./scripts/build-lazychat-dist.sh` before deploying.
- Two-phase mutations: every state-changing tool MUST be `prepare_*` + a corresponding action handler in `commit_prepared`. Never expose direct mutation tools.
- Permission scoping: every tool calls `frappe.has_permission(...)` BEFORE any DB access. Re-check at commit time.
- Tool errors return `{"error": "human-readable message"}` not exceptions. The agent loop reads `error` and apologizes/retries.
- New tool checklist:
  1. Add implementation in `tools.py` with permission check + try/except
  2. Register schema in `tool_schemas.py`
  3. If mutating: add commit handler in `commit_prepared`
  4. Mention in system prompt (`claude_bridge.py` `_system_prompt`)
  5. Add T## smoke case
  6. Sync, re-run smoke

## Two-bench reality on this machine

- `~/frappe-bench` — only Frappe + a `pim` app (custom). NO ERPNext, NO lazychat_mcp_erpnext.
- `~/Desktop/agilitas_code/erpnext/frappe-bench` — full ERPNext + india_compliance + india_banking + pim_agilitas + stock_guard + **lazychat_mcp_erpnext**. This is the bench `scripts/deploy.env` points to (BENCH_ROOT) and where the real testing happens. Site: `erp.local` (default), serve_default_site=true so `http://localhost:8000/app` works without /etc/hosts editing.

## Lazychat-side companion repo

[../lazychat.ai/CLAUDE.md](../lazychat.ai/CLAUDE.md) documents the chat-ui React app. Key facts:
- Cycle 2 (DONE): postMessage `agentRequest`/`agentChunk`/`agentDone`/`agentError` protocol, `setAgentHandler` host SDK
- Cycle 3c (DONE): extension primitives (`registerMessageComponent`, `registerContextProvider`, `registerCommand`, `setDesignTokens`, `setAttachmentHandler`)
- Vite dev server pinned to port 5173 with `strictPort: true` (no silent port-jump)
- For HMR while editing chat-ui: set `lazychat_iframe_src: "http://127.0.0.1:5173/?frame=sidebar"` in site_config + run `pnpm --filter chat-ui dev`

## Browser-LLM proxy: CSRF, cache-bust + diagnostic playbook (added 2026-05-04)

Two failure modes the same screenshot pattern (`HTTP 400 from <NVIDIA URL>: <Frappe Server Error HTML>`) can hide. Always start by running both checks below.

**1. Stale-bundle / iframe cache trap.** Frappe serves the bundled chat-ui dist with `Cache-Control: max-age=43200` (12h). The shim cache-busts the iframe URL via `?v=<token>`, but the token MUST be the dist's mtime, not the static app version — otherwise a redeploy never invalidates the browser cache and the user keeps replaying broken bundles. The token comes from `boot.py:_deploy_version()` (= `<__version__>.<index.html mtime>`) → injected onto `boot.lazychat_settings.deploy_version` → read by [`lazychat_panel.bundle.js`](lazychat_mcp_erpnext/lazychat_mcp_erpnext/public/js/lazychat_panel.bundle.js#L154-L158). The shim now prefers `settings.deploy_version` first, falls back to `boot.versions.lazychat_mcp_erpnext`. Earlier code had the order reversed — symptom: the iframe URL `?v=` stayed at the app version (e.g. `0.2.3`) across deploys and the browser never re-fetched.

**2. CSRF on the same-origin LLM proxy.** The shim's `init` payload carries `mcpAuth: { csrf: frappe.csrf_token }`. chat-ui's `agent.ts:resolveFetchTarget()` and `mcp-client.ts:bP()` both attach it as `X-Frappe-CSRF-Token`. If either path forgets it, Frappe rejects the POST with `CSRFTokenError` (HTTP 400, HTML body — `<meta name="title" content="Server Error">`). The proxy itself strips `x-frappe-csrf-token` from `_DENY_HEADERS` before forwarding, so attaching it is always safe.

### Diagnostic SQL (run via `bench --site <site> mariadb`)

```sql
-- Did the proxy handler actually run? (entry-level diagnostic in llm_proxy.py:186)
SELECT name, LEFT(error, 600), creation FROM `tabError Log`
 WHERE error LIKE '%lazychat llm_proxy: entry%' ORDER BY creation DESC LIMIT 5\G

-- Browser hitting the dev fallback path? (means stale bundle / lost llmProxyUrl)
SELECT name, LEFT(error, 400), creation FROM `tabError Log`
 WHERE error LIKE '%legacy /llm-proxy hit%' ORDER BY creation DESC LIMIT 5\G

-- Pre-auth trace from before_request hook (fires before CSRF/auth, captures rejected POSTs too)
SELECT name, LEFT(error, 800), creation FROM `tabError Log`
 WHERE error LIKE '%lazychat llm_proxy:%' ORDER BY creation DESC LIMIT 10\G
```

If the **entry diagnostic fires but request still 4xx**: read the body from chat-ui — the proxy returns plain text for `Missing x-target-url` / `Target host '...' not in allowlist` / `Target URL must be http(s)`. Fix at the source (chat-ui model picker or Lazychat Settings → llm_proxy_allowed_hosts).

If the **entry diagnostic does NOT fire but the pre-auth trace shows the path was hit with `has_x_frappe_csrf_token=False`**: chat-ui isn't sending the CSRF header. Either bundle is stale (mode 1 above) or the in-iframe code lost it.

If **neither fires but the user sees the 400+HTML**: chat-ui is hitting the wrong path entirely — usually `/llm-proxy` (relative dev fallback) instead of `/api/method/...handle`. Means the `init` postMessage's `llmProxyUrl` didn't reach `useEmbedConfig` — check the iframe load order and look for `[lazychat-diag] resolveFetchTarget` in the iframe console.

### Quick verify after a chat-ui change + deploy

```bash
# bundle should contain the CSRF assignment
grep -c "X-Frappe-CSRF-Token" .../public/lazychat_dist/assets/index-*.js
# expect: 2 (one from mcp-client.ts, one from agent.ts:resolveFetchTarget)

# iframe HTML returns the new content-hash
curl -s "http://localhost:8000/assets/lazychat_mcp_erpnext/lazychat_dist/index.html" \
  | grep -oE "index-[A-Za-z0-9_-]+\.js"

# direct probe of the proxy (anonymous): expect 403 Not Permitted (route works, allow_guest=False)
curl -i -X POST "http://localhost:8000/api/method/lazychat_mcp_erpnext.desk_assistant.llm_proxy.handle" \
  -H "x-target-url: https://integrate.api.nvidia.com/v1/chat/completions" \
  -d '{}' 2>&1 | head -3
```

## "Tool dispatch sits at IN forever" — three stacked bugs (resolved 2026-05-05)

The single most expensive debug session in this repo's life — symptom
was "every prompt hangs at the IN block, no result, eventually 60s
timeout". Three independent bugs stacked. All resolved; documenting so
the next time something looks similar you start with the right tier.

**Why this is hard to see**: each layer below ALSO works in isolation —
the backend is fast (curl returns in <50ms), the chat-ui's mcpRpc works
when called from a parent-injected probe, the LLM emits real
`tool_calls`. The bugs only fire in combination. Diagnose by binary-
searching with the harness:

| Symptom | Tier where bug lives |
|---|---|
| `python3 test/curl_smoke.py` shows `TOOL_ERROR` or `WIRE_ERROR` | backend `tools.py` impl OR `mcp.handle` plumbing |
| Layer 1 green but `bench execute _smoke.run` fails | something Frappe does only on the wire (rare) |
| Both green but iframe panel hangs at IN forever | one of the three below |

### Tier 1 — HTTP/1.1 connection-pool starvation in Chrome (server-side fix)

`bench serve` returns `Connection: keep-alive` on every response, including
streamed SSE from `llm_proxy.handle`. Chrome holds the socket in the
per-origin pool (max 6 connections per origin) for ~60s after the LLM
stream completes. Combined with ERPNext's background polls
(notification_log, route_history, fiscal_year, etc.) the pool fills.
The chat-ui's `mcpCallTool` POST that follows the LLM stream end up
queued waiting for a slot, eventually rejected with
`TypeError: Failed to fetch` ~55s later. The chat-ui surfaces this as
the AbortSignal.timeout firing at 60s.

**Fix** ([llm_proxy.py:119](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/llm_proxy.py#L119)):
emit `Connection: close` on every llm_proxy response. Chrome releases
the socket the instant the upstream completes, freeing a pool slot for
the immediate tool-dispatch fetch that follows. Keep-alive on a
streaming proxy buys nothing — every LLM turn opens a fresh connection
upstream anyway.

### Tier 2 — system-prompt marker conflict (chat-ui-side fix in lazychat.ai)

The chat-ui's `routerSystemPrompt.ts` taught the LLM TWO ways to invoke
tools simultaneously:
1. `[[lazychat:tool kind="..." status="..."]]` markdown marker — pure
   rendering hint, the UI shows a card but nothing dispatches.
2. The provider's native `tool_calls` (OpenAI) / `tool_use` (Anthropic)
   field — what the chat-ui's `_streamToolTurn` parser actually picks
   up and routes to mcpCallTool.

Non-tool-trained models (seed-oss-36b, smaller open-weight) routinely
pick the marker form because it's more prominent in the prompt and
matches the way the rest of the response is "styled". UI shows IN block
forever, no real `tool_calls` ever arrives.

**Fix** (lazychat.ai `fix(prompt)` commit `be01aaa`): split the prompt
into MCP_PROMPT (no marker, explicit "use the native protocol field"
instruction) and LEGACY_PROMPT (keeps the marker for the standalone
Cycle 1 chat-ui where there's no real dispatch). `agentRunner.ts`
computes `mcpToolsActive` from the embed config and picks the right
variant per turn.

### Tier 3 — stringified tool args (server-side fix)

Even with Tier 2 fixed, models like seed-oss-36b stringify everything
in `tool_calls.function.arguments` — `filters: "{}"`, `fields: "['name']"`,
`limit: "1"` — even when the schema declares them as objects/arrays/ints.
`frappe.get_all(fields="['name']")` then generates broken SQL because
the string is interpreted as a single weird field name.

**Fix**
([tools.py:_coerce_args](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/tools.py)):
runs at the top of every `execute_tool` dispatch. JSON-parses well-known
schema-shaped keys (filters, fields, values, patch, spec, …), int-coerces
well-known integer keys (limit, max_chunks, …). Idempotent on already-
typed args. T75/T76 cover the regression.

### End-to-end verification

After all three fixes are deployed, the canonical test is:
1. Open the embedded panel at `http://localhost:8000/app/home`.
2. Send `Use get_list to fetch 1 customer with name`.
3. Expected: tool card shows `Returned in <100>ms · <N> B` with a result
   preview. Backend curl, in-process smoke, AND the panel UI all work.

Evidence: `lazychat-mcp-erpnext/test/evidence/05-chat-ui-tool-call-success-21ms.png`.

## Production triage (2026-05-06) — caps removed + typed report/dashboard wrappers + /commit cross-path fix

Three production bugs surfaced by real-user testing on `erp.local`:

### 1. `get_list` row caps caused wrong totals

User asked "list paid PIs in December 2025" expecting ~774 rows; model
returned 50 (the silent cap), then 169, then 110 across iterations as it
hunted for filter shapes. Same issue: ANY hardcoded ceiling becomes a wall
the model hits and apologizes for. Resolution: removed the cap entirely
([tools.py:204](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/tools.py)).

- `limit` not provided → 20 (cheap schema probes)
- explicit `limit` → honored verbatim, no upper bound
- `limit ≤ 0` → unbounded (`limit_page_length=0` in Frappe)

Same shape on `extract_file_content` (default 20k chars, no cap, `<=0` reads
the whole file) and `export_list_to_csv` (default 5000 rows, no cap, `<=0`
unbounded). The chat-ui's `mcpResultToText` 250 KB byte budget is the only
remaining truncation point — and it emits a clear `[Result truncated to N
chars]` notice so the model knows to pivot to `count_doc` / `aggregate` /
`export_list_to_csv` for bulk work. System prompt updated to drill in:
*"NEVER trust len(rows) from get_list — always count_doc first."*

### 2. Report creation looped with `getdoctype()` errors

Generic `prepare_create_doc({doctype:"Report"})` let the model store an
incomplete Report row (no `ref_doctype`, wrong `report_type`,
`is_standard:"Yes"` by accident). Frappe's report-loader exploded at open
time with `TypeError: getdoctype() missing 1 required positional argument:
'doctype'` — by which point the model had no way to recover.

Resolution: 4 new typed wrappers that validate fields BEFORE staging:

- **`prepare_create_report`** — validates ref_doctype exists, report_type is
  one of the 3 enum values, Query Reports' `query` passes the same SELECT
  regex as `prepare_run_sql`. Always sets `is_standard:"No"`.
- **`prepare_create_scheduled_job`** — validates frequency enum + cron_format
  shape; requires System Manager.
- **`prepare_create_number_card`** — validates function enum + requires
  `aggregate_field` for non-Count functions.
- **`prepare_create_dashboard`** — validates each referenced chart/card
  exists before staging.

Each has a matching commit handler in `commit_prepared`. System prompt
documents the wrappers as the preferred path for those four doctypes
([claude_bridge.py § WRITE / WORKFLOW / COMMS](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/claude_bridge.py)).

### 3. `/commit TOKEN` silently failed on the browser-LLM path

Original symptom in user transcript: model staged `prepare_create_*` →
returned token → user typed `/commit TOKEN` → model narrated *"✅ created!"*
→ but the URL gave a 404 / `getdoctype()` because nothing was actually
written.

Root cause: the panel-shim's `/commit` regex
([lazychat_panel.bundle.js:343](lazychat_mcp_erpnext/lazychat_mcp_erpnext/public/js/lazychat_panel.bundle.js))
only fires on the **backend-LLM `agentRequest` path** (line 660). On the
**browser-LLM path** (any custom model — seed-oss-36b, claude-haiku via
API key, NVIDIA), `/commit TOKEN` was a regular user message routed to the
LLM as plain text. The LLM has no `commit_prepared_action` tool in the
registry (intentional — server-side gate), so it just hallucinated success.

Fix lives chat-ui side, not here:
[lazychat.ai/apps/chat-ui/src/lib/commitSlash.ts](../lazychat.ai/apps/chat-ui/src/lib/commitSlash.ts)
intercepts `/commit TOKEN` in `App.tsx:onSend` BEFORE LLM routing, POSTs
directly to `commit_prepared_action` with the CSRF token, renders the
result as a `Done`/`error` message bubble. Now `/commit` works identically
on either path.

When debugging *"my report URL gave 404 even though the chat said it was
created"*: confirm the chat-ui bundle was rebuilt after this fix landed
(`?v=` query in iframe URL should be > `1778066844`).

## Where to go next

When user opens a new task in this repo:
1. Read this file (you are reading it).
2. If task is "add a new tool":
   - Read `tools.py` + `tool_schemas.py` + the new-tool checklist above
   - Pattern-match on the closest existing tool (read or prepare_*)
   - Add smoke case
3. If task is "tune system prompt": [claude_bridge.py:27-60](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/claude_bridge.py#L27)
4. If task is "iframe / panel UI changes": [public/js/lazychat_panel.bundle.js](lazychat_mcp_erpnext/lazychat_mcp_erpnext/public/js/lazychat_panel.bundle.js) + [public/css/lazychat_panel.css](lazychat_mcp_erpnext/lazychat_mcp_erpnext/public/css/lazychat_panel.css)
5. If task is "different LLM provider": Desk → LLM Provider doctype, no code change
6. If task is "deploy to a new ERPNext bench": `./scripts/deploy-local.sh` with `BENCH_ROOT` + `DEPLOY_SITE` env

## Sub-projects status

| # | Sub-project | Status |
|---|---|---|
| MCP wire | JSONRPC-over-HTTP MCP transport at `/api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle` (initialize / ping / tools/list / tools/call) — Claude Desktop and other MCP clients can connect via Frappe API key+secret; chat-ui's browser-LLM path also calls it. See [desk_assistant/mcp.py](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/mcp.py). Smoke covered T52–T59. | **DONE** |
| Theme sync | `pushTheme()` reads Frappe's resolved theme mode → posts `setTheme`. Also posts `setThemeTokens` with ONLY `--color-primary` (brand accent). **Surface tokens (bg/fg/border) are intentionally NOT pushed** — `setThemeTokens` writes inline styles on `<html>` which override `[data-theme="dark"]` CSS rules, so pushing surface tokens locked the iframe's theme and prevented the user's dark/light toggle from working. Fixed 2026-05-05. `MutationObserver` on parent `<html data-theme>` re-pushes on Frappe desk theme toggle. | **DONE** |
| Route context | `deskRoute()` reads `cur_frm.doc` (name/doctype/title/workflow_state/status/dirty) on Form view + `cur_list.get_checked_items()` on List view. `_route_context_summary()` in `claude_bridge.py` prepends a briefing to the system prompt so the LLM auto-grounds "this doc" / "summarize" queries. Smoke covered T48–T51. | **DONE** |
| Lazychat Settings doctype | Single doctype at `/app/lazychat-settings` (System Manager edit) — 8 fields: enabled, iframe_base_url, iframe_query_params, chat_path (auto/browser/backend), mcp_endpoint, legacy_widget_enabled, allow_email, allow_dangerous_tools. Replaces site_config flag scattering; site_config still wins as advanced override. boot.py `get_lazychat_settings()` is the unified resolver. T60–T64 cover defaults, boot-extension shape, fallback behavior, validation, save_conversation. | **DONE** (commit 55b432f) |
| Browser-LLM path with tools | chat-ui (lazychat.ai repo) gained a JSONRPC MCP client — `mcp-client.ts` fetches tool defs from our wire endpoint and `agent.ts:runChatWithMcp` runs a **streaming** tool-use loop (`_streamToolTurn`) with the user's BYO LLM — text deltas stream in real time, tool_use blocks accumulate silently, `> _Got results, thinking…_` separator posted between rounds. `mcp-client.ts:mcpResultToText` caps tool results at **12,000 chars** to prevent context overflow. Empty final text and max-turns (8) both raise `cb.onError()` (not silent `cb.onDone()`). agentRunner does 3-way routing based on `chatPath` setting AND active model. See [lazychat.ai/CLAUDE.md](../lazychat.ai/CLAUDE.md) for the chat-ui side. | **DONE** (lazychat.ai db300ce + streaming update 2026-05-05; chat-ui dist bundled here) |
| save_conversation endpoint | `/api/method/lazychat_mcp_erpnext.desk_assistant.api.save_conversation` — chat-ui pushes turns from the browser-LLM path to `Claude Conversation` so admins have one unified history regardless of who orchestrated the LLM. T63 covers it. | **DONE** |
| 2-layer test harness | `test/curl_smoke.py` (HTTP MCP wire, all 65 tools, content-validated) + extended `scripts/smoke-test-tools.py` (in-process, 84 cases). Provisioned by `test/setup_fixtures.py` (idempotent: Note + File + KB + queued Job + resolves real Customer/SO/Item/Chart/Card/Report from existing site data). Per-tool validators in `test/tool_args.py`. See "Smoke test" section above. | **DONE** (2026-05-05) |
| Chat-ui hang root cause | Three stacked bugs (Connection: keep-alive pool starvation + system-prompt marker conflict + stringified args) — fully diagnosed and fixed end-to-end. Panel went from "stuck at IN forever" with seed-oss-36b to `Returned in 21ms · 56 B`. See "Tool dispatch sits at IN forever" section above. | **DONE** (2026-05-05) |
| Analytics extras | `analyze_business_data` (pandas-based) heavy analytics | deferred |
| Visualization mutations | `create_dashboard`, `create_dashboard_chart` specialized creators (vs the generic `prepare_create_doc`) | deferred |
| Streamable-HTTP MCP upgrade | SSE upgrade + `Mcp-Session-Id` header support for server-initiated notifications + progress | deferred (current sync JSONRPC is sufficient for tool-call clients) |

## Two chat paths (architecture)

Both paths are operational and admin-selectable via `Lazychat Settings → Chat Path`:

| Path | LLM owned by | Tools dispatched by | Use when |
|---|---|---|---|
| **Backend-LLM** | Frappe (LLM Provider doctype) | `run_agentic_turn` calls `execute_tool` in-process | Org deployments, shared keys, central audit |
| **Browser-LLM** | chat-ui (BYO key in browser localStorage) | chat-ui calls `mcp.handle` JSONRPC for each tool_use | Single-user / power-user, key never touches server |

`chat_path = auto` (default): chat-ui inspects active model — custom model in picker → browser path; built-in model → backend path. Effortless for end users.

**Both paths share `tools.py` (38 tools, 1 implementation, 0 drift)**, both run with `frappe.session.user`'s permissions, both write to `Claude Conversation` (backend in `run_agentic_turn`; browser via `save_conversation`).

**Nothing is deprecated.** `LLM Provider`, `LLM Model`, `send_message_stream`, `run_agentic_turn`, `claude_bridge.py`, `providers/`, the legacy widget JS — all serve the backend path. Removing them would lose a real production deployment shape (org with shared keys).

## Commit conventions

- Conventional commits: `feat(scope): ...`, `fix(...)`, `chore(...)`, `test(...)`, `docs(...)`.
- **Never auto-commit. Never auto-push.** Wait for user to explicitly say "commit" / "push" / "ship".
- **Never** add `Co-Authored-By: Claude` trailer.
- macOS dev: `RESTART_BENCH=0` in `scripts/deploy.env` (no Supervisor locally → `bench restart` errors noisily).
