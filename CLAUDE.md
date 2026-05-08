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

## Tool registry — 87 tools (all permission-scoped to `frappe.session.user`)

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

## Cycle 8c — Panel-shim grayscale filter for `pushTheme` (2026-05-08)

Companion to lazychat.ai "Cycle 8c". Frappe's dark theme sets `--primary-color` to gray-900 (`#171717`); pushing this as the chat-ui brand accent rendered everything near-black. The shim's [`pushTheme()`](lazychat_mcp_erpnext/lazychat_mcp_erpnext/public/js/lazychat_panel.bundle.js) now calls a new `isGrayscale(color)` helper (R≈G≈B within 12 units) and skips the `setThemeTokens` push when the resolved primary is grayscale. Logs `[lazychat] skipped pushing grayscale primary: <hex>` for triage. The chat-ui side has matching defense-in-depth in [`extensions.ts`](../lazychat.ai/apps/chat-ui/src/store/extensions.ts) that filters grayscale tokens at `setThemeTokens` and `onRehydrateStorage` time. End result: in dark mode, chat-ui's own warm-orange `--color-primary` default (`#d97757` from theme.css) shows through instead of Frappe's UI-color near-black. Distinct host brand colors (purples, blues, custom hues) pass through unchanged.

Manual test: set Frappe theme primary, switch Desk to dark mode, hard-reload Desk → chat-panel accent dots / Apply pills / focus rings should be warm orange (chat-ui default), NOT near-black. DevTools → Application → Local Storage → `lazychat:extensions:v1` → `state.themeTokens` should be `{}` (the grayscale token was correctly filtered out).

## Cycle 8 — Real Modes + Effort backend (2026-05-08)

The Cycle-1 ModesPanel radios + 4-step Effort dot scale in chat-ui became real working features. See `../lazychat.ai/CLAUDE.md` "Cycle 8" for the chat-ui half. Backend half ships in [`api.py`](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/api.py) + [`claude_bridge.py`](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/claude_bridge.py) — pure additive, zero regression to the 154 in-process / 91 HTTP-wire smoke gates.

### Passthrough kwargs

`send_message_stream(...)` accepts three new keyword args (all optional, defaults preserve pre-Cycle-8 behavior):
- `mode: str = "edit-auto"` — clamped to `{ask, edit-auto, plan, auto}`; falls back to `edit-auto` on unknown.
- `effort: str = "medium"` — clamped to `{low, medium, high, max}`; falls back to `medium`.
- `plan_resumed: bool = False` — set by chat-ui when continuing after the user clicked Approve on a Plan card; suppresses the PLAN_MODE_BLOCK on the resumed turn.

`run_agentic_turn(..., mode, effort, plan_resumed)` reads these and routes them:

### `EFFORT_MAP` ([claude_bridge.py](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/claude_bridge.py))

```python
EFFORT_MAP = {
    "low":    {"max_turns": 8,  "thinking_budget": 0},
    "medium": {"max_turns": 16, "thinking_budget": 0},
    "high":   {"max_turns": 32, "thinking_budget": 4000},
    "max":    {"max_turns": 64, "thinking_budget": 16000},
}
```

`run_agentic_turn` reads `EFFORT_MAP[effort]["max_turns"]` for the agent loop ceiling. For Plan mode's first turn (`mode == "plan" and not plan_resumed`), turn budget is capped at **1** so the model emits the plan and stops — even on Anthropic where `tool_use` blocks aren't strictly suppressible by prompt alone, the single-turn cap makes the gate hard.

`thinking_budget > 0` is wired for Anthropic adapter integration (`thinking={"type":"enabled","budget_tokens":N}` kwarg) — currently informational; adapter-side wire-up is incremental.

### Mode-specific prompt blocks

Two module-level constants in `claude_bridge.py` mirror the chat-ui's `routerSystemPrompt.ts`:
- **`PLAN_MODE_BLOCK`** — instructs the LLM that turn 1 must be a numbered plan only, no `tool_use`. Appended by `_system_prompt(...)` when `mode == "plan" and not plan_resumed`.
- **`ASK_MODE_BLOCK`** — nudges toward staging tools (`prepare_*`) for any mutation; reads/analytics auto-execute. Appended when `mode == "ask"`.

Edit-auto mode appends neither (vanilla prompt). Auto mode is resolved chat-ui-side before the request reaches Frappe — backend never sees `mode == "auto"`.

### Two-phase mutation security boundary — UNCHANGED

The chat-ui's auto-Apply (3s countdown for LOW_RISK actions in Edit-auto) hits the SAME `commit_prepared_action` endpoint as a manual click. No new auto-commit path on the backend; LLM still cannot commit on its own. Permission re-check, savepoint, and 5-min token TTL all preserved.

### Verification

- `bench --site erp.local execute lazychat_mcp_erpnext._smoke.run` → 154/0/2 (no regression on existing flows; defaults preserve pre-Cycle-8 behavior).
- `python3 lazychat-mcp-erpnext/test/curl_smoke.py` → 91/91 tools registered+called.
- The chat-ui's new 7 unit tests for `effortConfig` + 10 for `autoModeClassifier` are in the lazychat.ai repo. Total chat-ui suite: 308/308 green.

## Cycle 7 — Compound-question delivery: read-execute tools + plan-first prompting (2026-05-07)

The platform-grade follow-up to the self-correcting `/commit` work below. The
canonical user prompt that exposed this:

> *"List me POs that have more than 100 line items and in which stock ledger
> entry is not matching the purchase receipt if yes give me the PRs and missing
> items, else give the list of POs → PR → PI"*

Even with the schema-first / structured-error / auto-retry plumbing from
"Self-correcting /commit" below, the platform STILL couldn't answer this
because `prepare_run_sql` was the only auto-callable SQL tool and it was
two-phase: stage → user clicks Apply → next turn sees data. For a compound
analytical question the LLM cannot complete the analysis in a single agentic
loop — it stages, the turn ends without rows, the user has to click, and
typically the model fills the empty turn with hallucinated conclusions ("no
POs match") drawn from "typical ERP patterns" instead of the database.

The actual data: 18 POs match (top: `PO-I-26-000003` with 789 line items).

### The new tools — separate read-path from mutation-path

**`run_sql_select`** ([tools.py](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/tools.py))
- Auto-executes SELECT (or `WITH ... SELECT`) SQL and returns rows in the
  same tool result. No /commit, no Apply card, no preview_token.
- Same security envelope as `prepare_run_sql`:
  1. site_config `lazychat_allow_dangerous_tools=true`
  2. caller has System Manager role
  3. `_validate_select_sql` regex (rejects DML/DDL keywords + multi-statement)
- Same `_wrap_db_error` structured-hint response on failure.
- Row cap 200 default, 1000 max.

**`run_python_readonly`** ([tools.py](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/tools.py))
For analytical Python that goes beyond what SQL alone can express (pandas
pivots, multi-pass computations, group-then-filter chains). Two layers of
read-only enforcement:
1. **Static AST scan** (`_validate_python_readonly`) rejects:
   - Imports of `subprocess`, `os`, `sys`, `shutil`, `socket`, `urllib`,
     `requests`, `http`, `smtplib`, `ftplib`, `telnetlib`, `ssl`, `ctypes`,
     `multiprocessing` (modules whose side-effects are NOT DB-rollbackable).
   - Calls to dangerous built-ins by name: `open`, dynamic-code primitives
     (compile / eval / dynamic exec), `__import__`, `input`, `breakpoint`.
   - Explicit `frappe.db.{set_value,set_many,delete,sql_ddl,multisql,commit,
     rollback,savepoint,release_savepoint}` and `frappe.{sendmail,
     publish_realtime,publish_progress,enqueue,enqueue_doc,delete_doc,
     rename_doc,copy_doc}` — i.e. things that have non-DB side-effects
     (email, redis publish, queue spawn) the savepoint can't undo.
2. **Runtime savepoint** that ALWAYS rolls back. Even if the AST scan misses
   something (e.g. `note.save()` — chain root isn't `frappe`), the
   `frappe.db.rollback(save_point=…)` after the code runs ensures no DB write
   persists. Smoke T47k specifically tests this defense-in-depth.

Both new tools are gated identically to the prepare_* variants
(`allow_dangerous_tools` + System Manager + per-tool validators).

### Tool-choice routing (the actually-deliver-it part)

System prompt in [claude_bridge.py](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/claude_bridge.py)
+ [routerSystemPrompt.ts](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts)
direct the LLM:

- **For analysis** (data needed back this turn) → `run_sql_select` /
  `run_python_readonly` / `get_list` / `count_doc` / `aggregate`.
- **For mutations** (creating docs, sending emails) → `prepare_*` variants
  with the inline Apply gate.
- **NEVER** use `prepare_run_sql` / `prepare_run_python` for analysis — those
  STAGE the action and the LLM's turn ends without data, so completion
  becomes impossible in one loop.

### Plan-first / completeness / evidence-or-say-so prompt rules

Three blocks added to the shared guidance to push compound multi-stage
behaviour:

- **COMPOUND QUESTIONS** — emit a numbered Plan as the first content message
  before any tool call, then execute step-by-step, then synthesize. Mirrors
  Claude Code's TodoWrite pattern.
- **COMPLETENESS** — before the final assistant turn, re-read the user's
  message and confirm every clause is answered. If even one clause is
  unanswered (e.g. the user asked "if X then A else B" and only the X check
  ran), KEEP going with another tool call instead of declaring Done with a
  partial answer.
- **EVIDENCE-OR-SAY-SO** — a negative answer ("no X matches") REQUIRES a
  successful `count_doc` / `aggregate` / `run_sql_select` with `COUNT(*)`
  returning 0. Forbids "based on typical ERP patterns" / sample-of-one
  generalizations — exactly the failure mode that produced the hallucinated
  "no POs with >100 items" answer.

### `_validate_select_sql` leading-comment tolerance

LLMs frequently prefix queries with `-- get PRs linked to ...` for
self-narration. The previous strict "must start with SELECT/WITH/("
check rejected these on the first attempt. `_strip_leading_sql_comments`
now eats `--` line comments and `/* */` block comments at the start of the
query before the prefix check, while leaving in-query comments alone (those
are MariaDB's job).

### Iteration budget — chat-ui side

[`agent.ts`](../lazychat.ai/apps/chat-ui/src/lib/agent.ts) raises
`MAX_MCP_TURNS` from 8 → 16. A typical compound query needs 3-4
describe_doctype rounds + 2-3 data-fetching rounds + 1-2 comparison rounds +
1 synthesis round = 7-10 turns minimum. The old 8-turn cap forced the LLM to
declare Done with a partial answer. The COMPLETENESS rule pushes the LLM to
use these turns; the headroom lets it actually do so.

### Smoke coverage (`scripts/smoke-test-tools.py`)

- **T47a** — `run_sql_select` returns rows in the same call (no /commit).
- **T47b** — `run_sql_select` tolerates leading `-- comment`.
- **T47c** — `run_sql_select` tolerates leading `/* comment */`.
- **T47d** — `run_sql_select` rejects DML.
- **T47e** — `run_python_readonly` returns `_result` immediately.
- **T47f** — blocks `import subprocess`.
- **T47g** — blocks `import os`.
- **T47h** — blocks `frappe.db.set_value`.
- **T47i** — blocks `frappe.delete_doc`.
- **T47j** — blocks file-open calls.
- **T47k** — savepoint defense-in-depth: `note.insert()` (escapes AST scan
  because chain root isn't `frappe`) is rolled back; the Note doesn't
  persist. This is the test that proves the layered model actually closes
  the gap.

### End-to-end verification

In the embedded panel, the canonical user prompt now flows: numbered plan →
6 describe_doctype calls → 4+ chained `run_sql_select` calls returning real
data → "Excellent! Found 18 POs with >100 items" → PR linkage query (2.2 KB)
→ SLE comparison query (5.7s, 22.3 KB) → "Mismatches found! There are
significant stock ledger discrepancies." Compare against the pre-Cycle-7
hallucinated "no POs match" output.

Evidence:
- [`test/evidence/cycle7-self-correcting-commit/12-PLATFORM-DELIVERS-real-data-no-hallucination.png`](test/evidence/cycle7-self-correcting-commit/12-PLATFORM-DELIVERS-real-data-no-hallucination.png)

## Script Report `script` body required (2026-05-08)

Production bug observed in real chat transcript: LLM staged `prepare_create_report({report_type:"Script Report"})` with NO `script` arg → wrapper accepted → empty Report row created → user opened it → **blank page**. LLM had no way to know the body was empty so narrated "interactive buttons added" while nothing functional shipped. Same Cycle 6 hallucination shape, just for Script Reports.

Fix ([tools.py](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/tools.py)): wrapper now requires non-empty `script` arg whenever `report_type=="Script Report"`. AST-validated for Python syntax + must contain `def execute` symbol. At commit, payload's script is persisted to the Report's `report_script` field with `script_type="Python"`. Tool schema updated ([tool_schemas.py](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/tool_schemas.py)) so the model sees the requirement and either supplies a body or falls back to Query Report. Defense-in-depth re-check at commit too.

Smoke ([scripts/smoke-test-tools.py](scripts/smoke-test-tools.py)): T87e (missing body rejected), T87f (valid body stages), T87g (whitespace-only rejected). 161 in-process / 91 HTTP-wire still 100% green.

## EXPLAIN-probe for `prepare_create_report` Query Reports (2026-05-08)

Production bug: an LLM-staged Query Report with `FROM tabPurchase_Order` (underscored, fictional) passed the regex-only `_validate_select_sql` and shipped to disk. User clicked Apply → row stored → opened the report → 1146 "Table doesn't exist" with no recovery path. Same gap for unknown columns (1054).

Fix ([tools.py](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/tools.py)): new `_probe_select_sql_explain(query)` runs `EXPLAIN <query>` against the live DB inside `prepare_create_report` (Query Report path), with `%(filter_name)s` placeholders substituted to `NULL` so legitimate parameterized reports pass. On schema/syntax failure, returns `_wrap_db_error`'s structured hint — LLM sees "Table `tabpurchase_order` doesn't exist. ERPNext doctype tables are `tab<Doctype Name>` (with the space, no underscore)…" in the same turn and re-stages. Permission/transient errors pass through (don't fail-close on DB locks). Same probe also runs at `commit_prepared` time as defense-in-depth (line ~4148 in `tools.py`).

Smoke coverage ([scripts/smoke-test-tools.py](scripts/smoke-test-tools.py)): T87a (bad table rejected), T87b (valid SQL passes), T87c (unknown column rejected), T87d (`%(name)s` placeholder tolerated). 158 in-process / 91 HTTP-wire still 100% green.

Out of scope: probe doesn't catch logic bugs (correct schema, wrong join keys producing zero rows). Doesn't run on `prepare_run_sql` / `run_sql_select` since those execute the query directly — DB errors already surface naturally.

## Self-correcting `/commit` for run_sql / run_python (2026-05-07)

Before this change: when `prepare_run_sql` / `prepare_run_python` failed at
`/commit` time with a DB error (the canonical case being
`OperationalError: (1054, "Unknown column 'pr.purchase_order' in 'WHERE'")`),
the chat dead-ended. The error rendered as a red card; clicking Retry
re-ran the same broken script because the LLM never saw the failure in its
turn history. Three independent gaps stacked:

1. `tools.py:3367` (now wrapped) ran `frappe.db.sql(query)` with no inner
   try/except. The OperationalError fell through to the outer handler at
   [tools.py:4048-4054](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/tools.py),
   which returned `{ok: false, error: str(e), action}` — a flat opaque
   string with no diagnostic context.
2. The chat-ui's `messagesToTurns` (in `agent.ts`) only emitted
   `user`/`narration`/`done` kinds when building the LLM context. The
   `error` kind that `commitSlash.ts` writes was silently dropped, so the
   LLM had no idea the previous `/commit` failed.
3. The system prompt was silent on schema-verification (call
   `describe_doctype` first) and ERPNext's child-table linkage convention
   (PO↔PR is `Purchase Receipt Item.purchase_order`, NOT a column on
   `Purchase Receipt`).

### Fixes

- **`tools.py` `_wrap_db_error(e, query, action)`** — new helper near
  [`_validate_select_sql`](lazychat_mcp_erpnext/lazychat_mcp_erpnext/desk_assistant/tools.py).
  Detects MySQL error codes 1054 (unknown column), 1146 (table not found),
  1064 (syntax), 1142 (permission) and emits a structured response:
  ```python
  {
    "ok": False, "action": ...,
    "error": "OperationalError: (1054, ...)",
    "error_kind": "schema" | "syntax" | "permission" | "other",
    "hint": "<actionable text>",
    "query": "<first 1000 chars>",
  }
  ```
  For 1054, the hint is **schema-aware**: looks up the offending column in
  `_CHILD_TABLE_LINKS` and points at the right child-table location. For
  the user's exact bug (`pr.purchase_order`), the hint emits:
  > Column `pr.purchase_order` does not exist (in `WHERE`). In ERPNext,
  > `purchase_order` typically lives on the CHILD table — try
  > `Purchase Receipt Item / Purchase Invoice Item` instead. Example:
  > `SELECT … FROM tabPurchase Receipt pr JOIN tabPurchase Receipt Item pri ON pri.parent = pr.name WHERE pri.purchase_order = …`
  > Run `describe_doctype` on the parent and inspect its child-table
  > fields ('table' fieldtype) before retrying.

  Wrapped at the `frappe.db.sql` call site for `run_sql`. For `run_python`,
  the existing outer `except Exception as e` now routes through the same
  helper when the exception is DB-flavored (OperationalError /
  ProgrammingError / message contains 1054/1064/1146).

- **`claude_bridge.py` system prompt** — replaces the 4-line
  `prepare_run_sql` / `prepare_run_python` block with: SCHEMA-FIRST rule
  (always call describe_doctype before non-trivial SQL), CHILD-TABLE LINKS
  table covering the 6 most common cross-doc references, and an explicit
  ERROR RECOVERY block telling the model the `[lazychat:tool-error]`
  prefix means "read the hint, re-verify schema, re-stage with corrections,
  do NOT regenerate the same query unchanged".

- **`tool_schemas.py`** — mirror the prompt's two new pieces (schema-first;
  child-table-link convention) into the tool descriptions for
  `prepare_run_sql` and `prepare_run_python` so the guidance also surfaces
  during tool selection.

- **chat-ui side** (sibling repo): `agent.ts:messagesToTurns` adds a
  branch for `kind === 'error'` that emits a synthetic `[lazychat:tool-error]`
  user turn carrying the structured error + hint. `commitSlash.ts` now
  writes the canonical `error` Message shape (was using a non-typed
  `as unknown as Message` cast that left `message` undefined), formats
  the structured fields into the message, then auto-triggers `startStream`
  for `run_sql`/`run_python` failures (NOT mutations) with a sliding
  10-message / 3-error cap to prevent infinite loops on unrecoverable
  errors. Manual `Try again` button stays as a fallback when auto-retry
  caps out.

### Verification

- The exact production failure (`Unknown column 'pr.purchase_order'`) now
  produces the 491-character schema-aware hint via the bench console:
  ```
  bench --site erp.local console
  >>> from lazychat_mcp_erpnext.desk_assistant.tools import _wrap_db_error
  >>> e = SimpleNamespace(__class__=type('OperationalError',(Exception,),{}))
  >>> _wrap_db_error(e, "...", "run_sql")["hint"]
  ```
- Smoke: T44–T47 (run_sql happy path + DML rejection + run_python sum) all
  green; the structured-error wrap doesn't regress the success path.
- chat-ui: `messagesToTurns` regression test (`agent.multipart.test.ts`)
  asserts the `[lazychat:tool-error]` user turn shape; `commitSlash.test.ts`
  covers the canonical-shape error write, auto-retry on run_sql/run_python,
  no-retry on mutations, no-retry on success, and the 3-error cap.

### Out of scope

- Auto-retrying mutations (`prepare_create_*`, `prepare_update_doc`, etc.) —
  those failures are usually validation / business-logic errors where
  re-staging without user input is dangerous.
- Schema-aware SQL pre-validation (parsing the query and checking columns
  before staging) — would need a doctype-field index; separate larger
  effort.

## Production-grade iframe perf overhaul (2026-05-07)

End-to-end perf pass on the embedded iframe. Companion changes in [../lazychat.ai/CLAUDE.md](../lazychat.ai/CLAUDE.md) Cycle 6. **First-paint critical bytes ~186 KB brotli (~221 KB gz)** down from ~321 KB-gz single-bundle baseline (~70% drop behind nginx).

### Iframe element tightening ([lazychat_panel.bundle.js:509-528](lazychat_mcp_erpnext/lazychat_mcp_erpnext/public/js/lazychat_panel.bundle.js))

- `iframe.title = "Lazy Chat assistant"` (a11y).
- `iframe.loading = "eager"` — explicit because the FAB-triggered open is what reveals the iframe and we want it fully booted on first reveal.
- `iframe.referrerPolicy = "same-origin"`.
- `iframe.sandbox = "allow-same-origin allow-scripts allow-popups allow-forms allow-downloads allow-modals"`. **`allow-same-origin` is mandatory** — same-origin production iframe needs `frappe.csrf_token`/`frappe.boot`/localStorage, and our origin-pinned `postMessage` validation depends on a non-`null` origin. `allow-popups` lets `target="_blank"` external links open. `allow-downloads` covers CSV exports.
- `?v=<deploy_token>` cache-bust on the iframe URL **kept** with a "SAFE TO REMOVE once nginx ships" code comment. Required because Frappe's Werkzeug serves `index.html` with `Cache-Control: max-age=43200` — without `?v=`, redeploys never invalidate the entry HTML and the browser keeps loading the OLD asset hashes.

### Build pipeline — precompressed sidecars ([scripts/build-lazychat-dist.sh](scripts/build-lazychat-dist.sh))

Post-rsync pass over `*.{js,css,svg,json,html,map}` in `public/lazychat_dist/`:

- Brotli `-q 11` `.br` sidecars when the `brotli` CLI is present (graceful warning + skip when missing).
- Gzip `-9 -n` `.gz` sidecars (always; `gzip` is on every macOS/Linux box).
- Files <1 KB skipped (compression overhead exceeds savings).
- Source-newer-than-sidecar check via `-nt` so re-runs only recompress changed files.
- `SKIP_PRECOMPRESS=1` short-circuit for fast dev rebuilds.

Pairs with `brotli_static on; gzip_static on;` in the nginx config.

### Production nginx sample ([scripts/nginx-lazychat.conf.example](scripts/nginx-lazychat.conf.example))

Two `location` blocks for the dist path, plus an embedded README:

- `^~ /assets/lazychat_mcp_erpnext/lazychat_dist/assets/` → `Cache-Control: public, max-age=31536000, immutable` (Vite's content-hash filenames make this safe).
- `= /assets/lazychat_mcp_erpnext/lazychat_dist/index.html` → `Cache-Control: no-cache, must-revalidate` + a strict CSP including `frame-ancestors`, `Permissions-Policy`, `Referrer-Policy`, `X-Content-Type-Options`. `frame-ancestors` value is a placeholder (`https://erp.example.com`); each operator must edit it.
- Both serve precompressed `.br` / `.gz` sidecars when the client supports them. Falls back to dynamic `gzip` for anything without a sidecar.
- Add either to the `nginx.conf` template (persists across `bench setup nginx`) or via `include /etc/nginx/conf.d/lazychat.conf` in the Frappe-generated server block.

**Once this nginx config is live**, the `?v=` cache-bust in [lazychat_panel.bundle.js:154-158](lazychat_mcp_erpnext/lazychat_mcp_erpnext/public/js/lazychat_panel.bundle.js) becomes redundant and can be deleted (the no-cache header on `index.html` does the revalidation; the immutable header on hashed assets does the long-term caching).

### Lighthouse CI ([scripts/lighthouse-iframe.sh](scripts/lighthouse-iframe.sh))

On-demand performance budget enforcement. Runs `npx lighthouse` headless against the iframe URL, parses the JSON result with stdlib Python, asserts FCP/LCP/TBT/CLS/perf-score floors. Defaults: perf ≥85, FCP ≤1500 ms, LCP ≤2500 ms, TBT ≤300 ms, CLS ≤0.05. Override per-env via `SITE_URL`, `PERF_MIN`, `FCP_MAX_MS`, etc. HTML report under `lighthouse-out/lighthouse.html`. Wire into CI as a non-blocking job until budgets are hardened.

### What stays unchanged

- The two-phase mutation pattern.
- The 87-tool registry shape.
- The `send_message_stream` / `mcp.handle` API surface.
- All gating (System Manager + `/commit` + site flags).

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
