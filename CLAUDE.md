# lazychat-erpnext — Claude project knowledge

Read this BEFORE exploring the repo. Saves ~75% tokens.

## What this repo is

A **Frappe app** (`lazychat_erpnext`) that turns ERPNext into an LLM-driven agentic workspace. Two installation surfaces:

1. **Legacy widget** — vanilla-JS right-dock chat panel (in [public/js/lazychat_erpnext_desk.js](lazychat_erpnext/public/js/lazychat_erpnext_desk.js)). Disabled by default since the lazychat panel landed.
2. **Lazychat panel** (current) — embeds the [lazychat-ai](../lazychat.ai/) React UI as a same-origin iframe inside the Desk via a 280-line vanilla-JS shim ([public/js/lazychat_panel.bundle.js](lazychat_erpnext/public/js/lazychat_panel.bundle.js)). The iframe talks to the Frappe backend via `agentRequest` postMessage → `send_message_stream` SSE → `run_agentic_turn`. Same backend, much richer UI.

Backend is fully built and battle-tested:
- **Multi-provider LLM** ([providers/](lazychat_erpnext/desk_assistant/providers/)): two adapters cover Anthropic + everything OpenAI-compatible (OpenAI, OpenRouter, NVIDIA, Vercel AI Gateway, LM Studio, Groq, Together).
- **Agent loop** ([claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py)) with prompt caching, tool-use loop, max 8 turns.
- **Tool registry** — 101 tools, all run with `frappe.session.user`'s permissions (no god-mode bypass).
- **Two-phase mutation pattern**: agent calls `prepare_*` → returns `preview_token` → user types `/commit TOKEN` in chat → shim calls `commit_prepared_action(token)` → executes inside `frappe.db.savepoint`. The LLM is physically incapable of committing on its own (commit method is NOT in the tool registry).

Default install: lazychat panel ON, legacy widget OFF, dist served from `/assets/lazychat_erpnext/lazychat_dist/index.html` (same-origin, port-free).

## Architecture

```
ERPNext Desk @ <site>/app
├── lazychat_panel.bundle.js  (loaded via app_include_js on every Desk page)
│   ├── mounts iframe + slide-out chrome (FAB, resize handle, theme-aware CSS)
│   ├── postMessage envelope {v:1, src, id, type, payload} per lazychat protocol
│   └── intercepts /commit <token>  →  POST commit_prepared_action
│
├── iframe @ /assets/lazychat_erpnext/lazychat_dist/index.html?frame=sidebar
│   └── lazychat React UI (multi-tab, markdown, mutation previews, theme tokens)
│
└── On user send → agentRequest postMessage:
       shim → POST /api/method/lazychat_erpnext.desk_assistant.api.send_message_stream
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
└── lazychat-erpnext/                                  # THIS repo (Frappe app source)
    ├── lazychat_erpnext/
    │   ├── public/lazychat_dist/                 # bundled chat-ui SPA (COMMITTED; rebuild via scripts/build-lazychat-dist.sh)
    │   ├── public/js/lazychat_panel.bundle.js
    │   ├── public/css/lazychat_panel.css
    │   ├── public/js/lazychat_erpnext_desk.js    # legacy widget (gated off by default)
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
./lazychat-erpnext/scripts/build-lazychat-dist.sh   # auto-finds ../lazychat.ai

# Per bench
BENCH_ROOT=/path/to/that/bench DEPLOY_SITE=site.example \
  ./lazychat-erpnext/scripts/deploy-local.sh
# First-time on a bench that doesn't have the app:
cd /path/to/that/bench
bench get-app file:///path/to/lazychat-erpnext
bench --site site.example install-app lazychat_erpnext
# (after_install runs: seeds LLM Provider/Model, prints welcome banner with next steps)
```

**Defaults work without any site_config edits.** Boot extension reads `lazychat_iframe_src` from `site_config.json` if set; otherwise defaults to bundled dist.

## Tool registry — 101 tools (all permission-scoped to `frappe.session.user`)

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
| `iframe_base_url` | `/assets/lazychat_erpnext/lazychat_dist/index.html` | Where chat-ui loads from — override for remote chat-ui or HMR dev (`http://127.0.0.1:5173`) |
| `iframe_query_params` | `?frame=sidebar` | Appended to base_url |
| `chat_path` | `auto` | `auto` / `browser` / `backend` — see "Two chat paths" above |
| `mcp_endpoint` | `/api/method/lazychat_erpnext.desk_assistant.mcp.handle` | Read-only; browser-LLM path uses this |
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
- `lazychat_erpnext.desk_assistant.api.send_message` — batch JSON `{conversation_id, events, usage}`
- `lazychat_erpnext.desk_assistant.api.send_message_stream` — SSE: `event: text_delta|tool_use|tool_result|usage|done|error`
- `lazychat_erpnext.desk_assistant.api.commit_prepared_action` — apply a staged action by token (NOT exposed to the LLM tool loop)
- `lazychat_erpnext.desk_assistant.api.list_models` — model picker data
- `lazychat_erpnext.desk_assistant.api.discover_remote_models` — fetch /models from a provider
- `lazychat_erpnext.desk_assistant.api.test_llm_provider_connection` — connection probe

**Browser-LLM path:**
- `lazychat_erpnext.desk_assistant.api.save_conversation` — push browser-orchestrated turns into Claude Conversation
- `lazychat_erpnext.desk_assistant.mcp.handle` — JSONRPC MCP transport (initialize / ping / tools/list / tools/call). Same auth as any whitelisted method (cookie session OR Frappe API key+secret). Used by both chat-ui's browser path AND external MCP clients (Claude Desktop, etc).
- `lazychat_erpnext.desk_assistant.mcp.handle_bearer` — same dispatcher, but `Authorization: Bearer <token>` auth (constant-time compare against site_config `lazychat_mcp_bearer_token`) + `Mcp-Session-Id` response header per Streamable HTTP spec (2025-03-26). For claude.ai web Custom Connector and other clients that don't speak Frappe's `token KEY:SECRET` scheme. Run-as user defaults to Administrator; override with site_config `lazychat_mcp_bearer_user`. Existing defense layers (System Manager role, allow_dangerous_tools, /commit) all remain — Bearer auth is just an alternative way to authenticate, not an authorization bypass. Smoke: [test/bearer_smoke.py](test/bearer_smoke.py) (env-var driven, no creds in-file).

## Phase 1 — Doctype Relationship Graph (find_join_path) (2026-05-10)

New tool `find_join_path(from_doctype, to_doctype, max_hops=3)` walks
Frappe's DocField metadata graph (Link + Table fieldtypes) via BFS and
returns the canonical join chain between any two doctypes. Eliminates
the need to hand-maintain canonical SQL templates in the system prompt
for every (from, to) pair the LLM might need.

Routing precedence: curated `_RELATIONSHIP_HINTS` direct hops (e.g. PR↔PI
via `pr_detail`, PI↔PE via Payment Entry Reference + `reference_doctype`
predicate) override graph-discovered routes when both exist. Curated
hops carry the gotcha warning inline (e.g. "DO NOT join on item_code
alone").

Each hop returned: `{from, target, via_field, via_kind, on_template,
warning?, note?}` where `on_template` uses literal `<a>`/`<b>` placeholders
for the FROM and TARGET table aliases (caller substitutes concrete aliases
when assembling SQL). `via_kind` is one of `link / parent_to_child /
child_to_parent / curated`.

Tool registry count: 94 → **95**. Wired in dispatcher
([tools.py:find_join_path](lazychat_erpnext/desk_assistant/tools.py))
+ schema ([tool_schemas.py](lazychat_erpnext/desk_assistant/tool_schemas.py)).
Prompts in `claude_bridge.py` + `routerSystemPrompt.ts` (chat-ui mirror)
both teach `DISCOVERY-FIRST: call find_join_path before writing any
cross-doctype JOIN`.

Companion: `_RELATIONSHIP_HINTS` extended with `Payment Entry Reference →
Purchase Invoice / Sales Invoice` + parent_link_to `Payment Entry` so
PI↔PE / SI↔PE routes return curated canonical hops with the required
`reference_doctype` predicate baked in.

Phase 2 (exemplar admin curation: mark canonical reports per intent class
to boost recall ranking) and Phase 3 (more aggressive compose-test-fix
loop with auto-row-shape diff feedback) are deferred to future cycles.
Phase 1 ships first; we measure how often it fires before building the
next layer.

**Phase 1.1 — coverage audit + reverse-Link traversal (2026-05-11)**:
Added `_incoming_link_edges_for(doctype)` — scans `tabDocField` +
`tabCustom Field` for Link fields whose `options=doctype`, returns
reverse edges. BFS now considers (a) forward Link/Table edges, (b)
reverse-curated edges (from `_RELATIONSHIP_HINTS`), (c) reverse-Link
edges. Customer→Sales Invoice / Item→Sales Invoice Item / Supplier→PO
all resolve in 1 hop. Coverage jumped from **70% → 100%** of 702 ordered
pairs across 27 canonical business doctypes (max_hops=3). See
[scripts/audit-relationship-coverage.py](scripts/audit-relationship-coverage.py)
for the audit harness.

Also extended `_RELATIONSHIP_HINTS`:
- Stock Ledger Entry row_link_to expanded with Delivery Note Item /
  Stock Entry Detail / Purchase Invoice Item / Sales Invoice Item
  (each gated by the appropriate `voucher_type` predicate).
- New `GL Entry` entry — Dynamic Link routes to PI/SI/PE/JE/SE via
  `voucher_no` + `voucher_type`.
- Payment Entry Reference extended with Journal Entry / Purchase Order
  / Sales Order routes (advance-payment flows).

## Doctypes

- `LLM Provider` — name, provider_type (anthropic | openai_compatible), base_url, api_key (Password), extra_headers, enabled
- `LLM Model` — model_label, provider Link, model_id, supports_tools, max_output_tokens, context_window, input_price_per_mtok, output_price_per_mtok, is_default, enabled
- `Claude Conversation` — user, title, history (JSON), last_model, total_input_tokens, total_output_tokens

Seed fixtures in [seed_data.json](lazychat_erpnext/seed_data.json) auto-load via `after_install` + `after_migrate`. Ships disabled-by-default rows for OpenAI/OpenRouter/NVIDIA/Vercel/LM Studio.

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
cp lazychat-erpnext/test/setup_fixtures.py \
   <bench>/apps/lazychat_erpnext/lazychat_erpnext/_setup_fixtures.py
cd <bench> && bench --site <site> execute lazychat_erpnext._setup_fixtures.run

# 2) Run Layer 1
cd ~/Desktop/code-chat
python3 lazychat-erpnext/test/curl_smoke.py
# expected:
#   [curl_smoke] summary: OK=54 | OK_ERROR=11
#   [curl_smoke] tools registered: 65, called: 65
```

`OK_ERROR` = graceful expected error: gated tools (allow_email,
allow_dangerous_tools), probes against deliberately-non-existent
fixtures. Validators per tool live in `test/tool_args.py`.

### Layer 2 — in-process (`scripts/smoke-test-tools.py`)

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py \
   <bench>/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd <bench>
bench --site <site> execute lazychat_erpnext._smoke.run
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
`<bench>/apps/lazychat_erpnext/`. The smoke files live at
`<bench>/apps/.../_smoke.py` and `_setup_fixtures.py` (gitignored, NOT
in source — they get cp'd in for runs only). **Every deploy wipes them.**
Re-run the `cp` commands above before invoking `bench execute` after a
deploy, otherwise the runner errors with `NameError: name
'lazychat_erpnext' is not defined` (because Frappe can't find the
function path).

## Conventions

- **Source-of-truth lives in this repo** at `lazychat_erpnext/`. The bench's `apps/lazychat_erpnext/` is a deploy target — `scripts/deploy-local.sh` rsyncs `--delete`. Edits made directly in the bench will be wiped on next deploy. Always edit source first, then `cp` (or deploy script) to bench.
- Smoke test script `_smoke.py` is gitignored / NOT in source — it's a copy from `scripts/smoke-test-tools.py`. Run `cp scripts/smoke-test-tools.py <bench>/.../lazychat_erpnext/_smoke.py` before `bench execute`.
- Bundled chat-ui dist (`public/lazychat_dist/`) is **committed** to the repo so `bench get-app --branch main` and Frappe Cloud marketplace installs ship a working panel out of the box. After changing the chat-ui, rebuild via `./scripts/build-lazychat-dist.sh` then `git add -A lazychat_erpnext/public/lazychat_dist/` (the `-A` picks up the renamed/removed content-hashed chunks).
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

- `~/frappe-bench` — only Frappe + a `pim` app (custom). NO ERPNext, NO lazychat_erpnext.
- `~/Desktop/agilitas_code/erpnext/frappe-bench` — full ERPNext + india_compliance + india_banking + pim_agilitas + stock_guard + **lazychat_erpnext**. This is the bench `scripts/deploy.env` points to (BENCH_ROOT) and where the real testing happens. Site: `erp.local` (default), serve_default_site=true so `http://localhost:8000/app` works without /etc/hosts editing.

## Lazychat-side companion repo

[../lazychat.ai/CLAUDE.md](../lazychat.ai/CLAUDE.md) documents the chat-ui React app. Key facts:
- Cycle 2 (DONE): postMessage `agentRequest`/`agentChunk`/`agentDone`/`agentError` protocol, `setAgentHandler` host SDK
- Cycle 3c (DONE): extension primitives (`registerMessageComponent`, `registerContextProvider`, `registerCommand`, `setDesignTokens`, `setAttachmentHandler`)
- Vite dev server pinned to port 5173 with `strictPort: true` (no silent port-jump)
- For HMR while editing chat-ui: set `lazychat_iframe_src: "http://127.0.0.1:5173/?frame=sidebar"` in site_config + run `pnpm --filter chat-ui dev`

## Browser-LLM proxy: CSRF, cache-bust + diagnostic playbook (added 2026-05-04)

Two failure modes the same screenshot pattern (`HTTP 400 from <NVIDIA URL>: <Frappe Server Error HTML>`) can hide. Always start by running both checks below.

**1. Stale-bundle / iframe cache trap.** Frappe serves the bundled chat-ui dist with `Cache-Control: max-age=43200` (12h). The shim cache-busts the iframe URL via `?v=<token>`, but the token MUST be the dist's mtime, not the static app version — otherwise a redeploy never invalidates the browser cache and the user keeps replaying broken bundles. The token comes from `boot.py:_deploy_version()` (= `<__version__>.<index.html mtime>`) → injected onto `boot.lazychat_settings.deploy_version` → read by [`lazychat_panel.bundle.js`](lazychat_erpnext/public/js/lazychat_panel.bundle.js#L154-L158). The shim now prefers `settings.deploy_version` first, falls back to `boot.versions.lazychat_erpnext`. Earlier code had the order reversed — symptom: the iframe URL `?v=` stayed at the app version (e.g. `0.2.3`) across deploys and the browser never re-fetched.

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
curl -s "http://localhost:8000/assets/lazychat_erpnext/lazychat_dist/index.html" \
  | grep -oE "index-[A-Za-z0-9_-]+\.js"

# direct probe of the proxy (anonymous): expect 403 Not Permitted (route works, allow_guest=False)
curl -i -X POST "http://localhost:8000/api/method/lazychat_erpnext.desk_assistant.llm_proxy.handle" \
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

**Fix** ([llm_proxy.py:119](lazychat_erpnext/desk_assistant/llm_proxy.py#L119)):
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
([tools.py:_coerce_args](lazychat_erpnext/desk_assistant/tools.py)):
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

Evidence: `lazychat-erpnext/test/evidence/05-chat-ui-tool-call-success-21ms.png`.

## Production triage (2026-05-06) — caps removed + typed report/dashboard wrappers + /commit cross-path fix

Three production bugs surfaced by real-user testing on `erp.local`:

### 1. `get_list` row caps caused wrong totals

User asked "list paid PIs in December 2025" expecting ~774 rows; model
returned 50 (the silent cap), then 169, then 110 across iterations as it
hunted for filter shapes. Same issue: ANY hardcoded ceiling becomes a wall
the model hits and apologizes for. Resolution: removed the cap entirely
([tools.py:204](lazychat_erpnext/desk_assistant/tools.py)).

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
([claude_bridge.py § WRITE / WORKFLOW / COMMS](lazychat_erpnext/desk_assistant/claude_bridge.py)).

### 3. `/commit TOKEN` silently failed on the browser-LLM path

Original symptom in user transcript: model staged `prepare_create_*` →
returned token → user typed `/commit TOKEN` → model narrated *"✅ created!"*
→ but the URL gave a 404 / `getdoctype()` because nothing was actually
written.

Root cause: the panel-shim's `/commit` regex
([lazychat_panel.bundle.js:343](lazychat_erpnext/public/js/lazychat_panel.bundle.js))
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

## Cycle 14.5 — llm_proxy mirrors inbound HTTP method (GET pass-through for /v1/models) (2026-05-15)

Backend-only fix to [`llm_proxy.handle`](lazychat_erpnext/desk_assistant/llm_proxy.py). Unblocks the chat-ui's "Fetch models" button on the BYO custom-model editor. Tag: `cycle-14.5`. Backend `0.4.2`.

### Bug — "Fetch models" returns HTTP 403

User clicks "Fetch models" in the Edit-custom-model dialog → expects the provider's live model list → gets `HTTP 403 FORBIDDEN`. Two compounding bugs:

1. `llm_proxy.handle` was whitelisted with `methods=["POST", "OPTIONS"]` only. The chat-ui's `fetchModels` does `fetch(proxyUrl)` (no explicit method = default GET). Frappe's `@frappe.whitelist` enforces method matching at the auth gate, so the request 403'd before our handler even ran.
2. Even if GET were allowed, the handler hardcoded `requests.post(target_url, ...)`. All providers (Groq, OpenAI, OpenRouter, NVIDIA, Anthropic) expose `/v1/models` as **GET-only**, so the upstream would have 4xx'd anyway.

### Fix

Two-part, both in `llm_proxy.py:handle`:

- Added `"GET"` to the `@frappe.whitelist(methods=...)` list.
- Replaced `requests.post(target_url, ...)` with `requests.request(method, target_url, ...)` to mirror the inbound HTTP method to the upstream. GET requests now have no body forwarded (matches HTTP semantics; POST keeps its body unchanged).

All other behavior unchanged: host allowlist, header filtering, x-target-authorization rename trick, streaming response, timeout/error envelopes.

### Verification

- `curl -X GET .../llm_proxy.handle` now reaches the handler (was method-blocked at the auth gate before).
- Pre-auth tracer confirms `method=GET, target_url=https://httpbin.org/get` reaches the handler body.
- in-process smoke unchanged at 283/0/6 (no surface change to the tool registry).

### Future polish (not in this cycle)

The chat-ui's "Fetch models" button is stateless — every click re-fetches. For providers with stable model lists this is fine; if it becomes annoying later, add a 5-min localStorage cache keyed by endpoint+token-hash.

---

## Cycle 14.4 — Lazychat Settings polish (tool count + Code-field height) (2026-05-15)

Two small UX fixes to `/app/lazychat-settings`. Backend only — chat-ui unchanged. Tag: `cycle-14.4`. Backend `0.4.1`.

### Stale tool count

The Help block's "Both share" bullet read "the same 38 ERPNext tools (tools.py)" — that number was correct in cycle-7, before Cycle 13 added `prepare_create_page`, `prepare_create_workspace`, `prepare_attach_assets`, `prepare_create_server_script`, `list_number_cards`, `list_whitelisted_methods`, etc. Verified actual count in [`tool_schemas.py:TOOL_SCHEMAS`](lazychat_erpnext/desk_assistant/tool_schemas.py): **101 tools**. Updated the help text accordingly.

### Code-field editors way too tall

The two `Code` fields on Lazychat Settings — `llm_proxy_allowed_hosts` and `vision_judge_models` — each rendered as ~600px-tall ACE editors despite usually holding one or two lines of content. Made the form unscannable.

Fix: scoped CSS in [`public/css/lazychat_erpnext_desk.css`](lazychat_erpnext/public/css/lazychat_erpnext_desk.css) constraining those two specific editors to `height: 100px` (min 80, max 140). The `.ace_editor` selector is scoped to this doctype + these two fieldnames only — other Code fields elsewhere in ERPNext (Server Script, Custom Script, etc.) are untouched.

### Verification

Backend: no Python change → in-process smoke unchanged at 283/0/6. Visual: `/app/lazychat-settings` form now compact + correct "101 tools" label.

---

## Cycle 14 — MD Dashboard rebuild + Dashboard-from-Mockup discipline (2026-05-15)

Two coupled deliverables that close the same class of bug: the chat-driven `/app/md-dashboard` from a 90 KB Proman mockup ended up a ₹0 / ₹2 / ₹0 / 100 shell with 9 of 12 sections silently dropped. Three bugs compounded: aggregation via `frappe.client.get_list` + `limit_page_length` truncation, hardcoded `÷ 10⁷` with no unit suffix, and silent scope shrinkage. Cycle 14 fixes the page directly AND adds a playbook discipline so the agent does this right next time. Tag: `cycle-14`. Backend `0.4.0`, chat-ui `0.1.2`.

### Custom doctypes for non-ERP MD data

Four minimal System-Manager-only doctypes seeded idempotently in `install.py`:
- [`MD KPI Score`](lazychat_erpnext/desk_assistant/doctype/md_kpi_score/) — BSC scorecard (54 seed rows from the mockup, 4 perspectives covering Financial / Customer / Internal Process / Learning & Growth)
- [`MD Risk`](lazychat_erpnext/desk_assistant/doctype/md_risk/) — top risks (7 seed)
- [`MD Decision`](lazychat_erpnext/desk_assistant/doctype/md_decision/) — pending decisions (7 seed)
- [`Critical Role`](lazychat_erpnext/desk_assistant/doctype/critical_role/) — critical hiring flags (5 seed)

Each is plain Frappe — Desk forms at `/app/md-kpi-score`, etc. The dashboard reads via `frappe.client.get_list` (small lists, no truncation concern).

### Server-side aggregate endpoint

[`lazychat_dashboard_aggregate(spec)`](lazychat_erpnext/desk_assistant/api.py) replaces `frappe.client.get_list + JS reduce` for any total / count over large tables. Spec is a JSON object with `{doctype, filters, aggregations, group_by}`. Validates field names against `frappe.get_meta(doctype).fields` (rejects unknown), op against `{sum, count, avg, min, max}` (rejects everything else), aggregations capped at 12. System Manager only. Errors return `{ok: false, error}` envelope (consistent with other lazychat endpoints).

The 88,928-row Sales Invoice table on this bench: a `client.get_list` with `limit_page_length: 500` truncates to 0.5% of the data. The new endpoint runs `SELECT SUM(grand_total) FROM \`tabSales Invoice\` WHERE docstatus=1` directly — ~50 ms, correct total ≈ ₹76 Cr.

### `/app/md-dashboard` full 12-section rebuild

Replaced the cycle-13 chat-driven 3-section shell with a hand-crafted 12-section page:

| # | Section | Source |
|---|---|---|
| 1 | Group Snapshot | aggregate over Sales Invoice + Employee |
| 2 | BSC Scorecard | `frappe.db.get_list("MD KPI Score")` grouped by perspective |
| 3 | Division KPI Progress | `frappe.db.get_list("MD KPI Score")` flat |
| 4 | Top Risks | `frappe.db.get_list("MD Risk", {resolved_date: ['is', 'not set']})` |
| 5 | MD Decisions | `frappe.db.get_list("MD Decision", {status: 'Pending'})` |
| 6 | Sales & BD | aggregate Lead, Opportunity, Quotation, Sales Order |
| 7 | Receivables Aging | 4× aggregate Sales Invoice with date-bucket filters |
| 8 | Payables & Procurement | aggregate Purchase Invoice + Purchase Order + Material Request |
| 9 | Operations & Production | aggregate Work Order (group_by status) + Stock Entry + Delivery Note |
| 10 | Finance Snapshot | mirrors sections 1+8, plus GL Entry net |
| 11 | HR & People | aggregate Job Opening + `Critical Role` doctype |
| 12 | Digital Milestones | `frappe.db.get_list("MD KPI Score", {perspective: 'Learning & Growth'})` |

Magnitude-aware `fmtINR(n)` helper renders ` Cr` / ` L` / raw rupees consistently. Auto-refresh every 5 min. `lazychatReady = '1'` fires after `Promise.all` of all 12 section calls.

### Playbook upgrade — `_DASHBOARD_DISCIPLINE_BLOCK`

Mirrored backend ↔ chat-ui (see [chat-ui story](../lazychat.ai/CLAUDE.md) for the chat-ui half). When the user uploads a 5+ section / 20+ KPI mockup, the agent must (1) INVENTORY all sections, (2) CLASSIFY each KPI as ERP-derivable (name doctype + aggregation) / manual entry (propose minimal custom doctype) / not-applicable, (3) AGGREGATE via the new endpoint not `client.get_list + reduce`, (4) handle UNITS magnitude-aware, (5) RENDER ALL sections — silent drops are the most expensive bug class. WRONG/RIGHT example included.

### Verification

- in-process smoke: **283 / 0 / 6** (was 277/0/6, +6 new T100r-w)
- chat-ui vitest: **461 / 0** (unchanged)
- `bench migrate` installs 4 new doctypes cleanly
- E2E: `/app/md-dashboard` shows real ₹76 Cr YTD revenue + 88,928 Sales Invoices + ₹96 Cr creditors + 4 BSC perspective cards with status counts + 7 active risks + 7 pending decisions

---

## Cycle 13.2 — entity-decode auto-fix + Result Ready pill session-scope (2026-05-15)

Two surgical post-ship hardening fixes shipped together as `cycle-13.2` (backend `0.3.1`, chat-ui `0.1.1`). Driven by two real-user reports during the same chat panel test session: (a) "create a hello world website" rendered the literal `<header>` text instead of a real heading; (b) the "Result ready" pill randomly appeared in sessions that hadn't generated any result.

### Fix A — entity-encoded HTML auto-decoded at commit

Agent (Haiku 4.5 via Vercel AI Gateway) generated `prepare_create_page(content="&lt;header&gt;...")` — fully entity-escaped HTML. Both call sites in [`tools.py`](lazychat_erpnext/desk_assistant/tools.py) (`create_page` + `update_doc(Page)` commit branches) wrote that verbatim to disk → `page.main.html("&lt;header&gt;...")` → jQuery `.html()` decoded the entities and displayed the result as visible literal text in the page main wrapper. New helper `_decode_if_fully_entity_escaped()` near the module top: heuristic `&lt;[a-z!/]` match AND no `<[a-z!/]` match → `html.unescape`. Mixed content (real tags + intentional `&lt;` for code samples) → unchanged, author intent wins. Decoder applied to `content`/`style`/`script` fields in both call sites.

Playbook rewrite (mirrored in [`claude_bridge.py`](lazychat_erpnext/desk_assistant/claude_bridge.py) + [chat-ui `routerSystemPrompt.ts`](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts)): rule #2 reworded from "Standard XML entities are fine" to "**HTML entities are for TEXT CONTENT, not tag delimiters**" with explicit WRONG/RIGHT example.

### Fix B — Result Ready pill leaks across sessions

`useUI.lastResultMessageId: string | null` was a single global with no session tag. Multi-session symptom: result emitted in session A → user switches to session B → pill renders in B pointing at a message id that doesn't exist in B's DOM tree. The reader at [`ResultReadyPill.tsx:36-39`](../lazychat.ai/apps/chat-ui/src/components/messages/ResultReadyPill.tsx) fell into `setOffScreen(true)` even when `querySelector` returned null. Mirror fix in chat-ui — see [`../lazychat.ai/CLAUDE.md` Cycle 13.2 section](../lazychat.ai/CLAUDE.md) for full chat-ui story.

### Verification

- in-process smoke: 274 → **277 pass / 0 fail / 6 skip** (3 new T100o/p/q records)
- HTTP-wire smoke: unchanged (no tool-surface change)
- chat-ui vitest: 457 → 461 (+4, all in chat-ui half)
- E2E browser repro: chat panel → "create a hello world website" → load `/app/hello-world` → real `<header>` rendered (NOT visible text).

---

## Cycle 13.1 — post-ship hardening: agentic-build trifecta + iteration-loop fix + client-helpers playbook (2026-05-15)

Cycle 13's M1 shipped functional but had real-world rough edges that only surfaced once the agent (Haiku 4.5 via Vercel AI Gateway) was driven *fully through the chat panel inside ERPNext* — not via Python harness — to build a Number Card AND a website-style Desk Page from casual end-user prompts. Fixes here are commit-shaped on top of `cycle-13`; the cycle's design + smoke baselines stand. Tag: `cycle-13.1`. Companion chat-ui half: `lazychat.ai @ cycle-13.1`. Evidence: [`../2026-05-14-fully-agentic-chat-panel/`](../2026-05-14-fully-agentic-chat-panel/), [`../2026-05-15-chat-driven-page-build/`](../2026-05-15-chat-driven-page-build/).

### Fixed

1. **`prepare_update_doc(Page, patch={content,style,script})` no-op'd silently** — Frappe v15 Page has zero DB content fields (the page.json `page_html` entry is a Section Break label, not a Text field). `commit_prepared` `update` branch now special-cases Page: when patch contains any of `content`/`style`/`script`, the handler reads existing on-disk file trio (`<module>/page/<scrub>/<scrub>.{js,css,html}`), applies the patch (only the keys you touched), and rewrites disk files with `json.dumps()` for safe embedding. Recovers the pre-existing `script` from the JS file's `try{...}catch` block via regex when the patch only touches one of the other two fields. Other patch keys (title/icon/roles/module) still flow through the standard `doc.set` + `doc.save`. Idempotent. Lives in [`tools.py`](lazychat_erpnext/desk_assistant/tools.py) `commit_prepared` `update` branch. Without this, the M1 "iteration loop" the playbook promised was a lie for the doctype it was designed for.

2. **`prepare_create_page` disk-file ordering** — writing the JS/CSS/HTML trio BEFORE `doc.insert()` got silently overwritten by `make_boilerplate` (which `insert()` runs as a side-effect). Flipped: `doc.insert()` first, then overwrite the scaffold with the LLM-generated content. Also: `frappe.modules.scrub` truncates `page_name` to 20 chars so the on-disk dir name diverges from the user-supplied slug for long names — code now uses `doc.name` + `doc.title` after `insert()` returns, never the original payload args.

3. **`safe_provider_api_key()` returned `""` inside ThreadPoolExecutor workers** — the M3 visual-judge submits work to a 30s-bounded threadpool; `frappe.utils.password.get_decrypted_password` needs `frappe.local`, which workers don't inherit. Fixed in [`password_utils.py`](lazychat_erpnext/desk_assistant/password_utils.py): cache plaintext on `provider_doc.__lazychat_plain_api_key__` (`_CACHE_ATTR`); new `warm_provider_api_key(provider_doc)` pre-decrypts in the main thread before submit. [`visual_judge.py`](lazychat_erpnext/desk_assistant/visual_judge.py) `compare()` + `generate_fixes()` both call `warm_provider_api_key()` before the executor. Same bug shape would bite any future async/threaded LLM call — ALWAYS warm before submit.

4. **`roles=["User"]` rejected by Frappe** — `User` isn't a real Frappe role (closest is `All`); `Anonymous` isn't either (it's `Guest`). `prepare_create_page` now validates each requested role against `tabRole`, auto-substitutes the two common confusions, and on miss returns a clean error envelope listing all valid roles (sorted) instead of crashing on `doc.insert()`.

5. **Mojibake in user-supplied HTML** — `ftfy` doesn't fully recover Unicode arrows / `→` / curly quotes when the source double-encodes UTF-8 → cp1252 → UTF-8. For now, manual replacement table when ingesting reference mockups; future runs may need a more aggressive sanitize pass.

6. **Frappe page-loader pre-processed `\'` escapes in JS literals** breaking pages with single-quoted strings inside event handlers / template literals — switched to `json.dumps()` for ALL JS-string embedding (was `repr()`). Eliminates the `SyntaxError: Unexpected identifier 'Courier'` family of bugs.

### Changed — playbook upgrades (mirrored backend ↔ chat-ui)

Both [`claude_bridge.py`](lazychat_erpnext/desk_assistant/claude_bridge.py) `_DESK_PAGE_PLAYBOOK` and [chat-ui's `routerSystemPrompt.ts`](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts) `_SHARED_GUIDANCE` gained ~200 lines of agent-survival guidance. Single source of truth split intentionally: backend is canonical for backend-LLM path, chat-ui is canonical for browser-LLM path; both must be kept byte-aligned (smoke `T100p` will pin a hash diff in a follow-up).

- **Five non-negotiable rules at top** — each banned ES6+ syntax with its ES5 equivalent; numeric HTML entities only (`&#8226;` not `&middot;`); no `innerHTML` with interpolated strings (use `textContent` + `appendChild`); `lazychatReady = '1'` written ONLY after all initial fetches resolve via `Promise.all`; real Frappe role names (validated list, never `User`/`Anonymous`).
- **Casual-prompt cookbook** — table mapping common nouns ("customers", "suppliers", "sales", "stock", "items", "tasks", "employees", "leads", "quotations") to canonical doctypes, default page names, slug patterns, theme tokens, default columns. Hits the "show me my top customers" prompt class without needing 3 turns of clarification.
- **ES5 reference patterns** — copy-paste loading/empty/error pattern + INR `fmtINR()` rewritten in pure ES5 (no template literals, no const, no arrow fns).
- **CLIENT FRAPPE HELPERS — what's real vs Python-only** — table mapping `frappe.utils.format_currency` / `escapeHtml` / `formatdate` / `now_datetime` / `add_days` (all Python-only) → real client equivalents (`Intl.NumberFormat`, `textContent`, `frappe.datetime.str_to_user`, `frappe.datetime.now_datetime`, global `format_currency` shim). Eliminates the `TypeError: frappe.utils.X is not a function` runtime-error family that surfaced repeatedly in the chat-driven Page builds.
- **Iteration patch guidance** — when patching a Page via `prepare_update_doc`, send FULL replacement strings for the keys you touch (the disk-write helper preserves untouched keys but does not merge partial strings).

### Defaults — Cycle 13 ships allow-all

`enable_screenshot_preview = 1` + `vision_judge_models` populated + `allow_dangerous_tools = 1` baked into `boot.py:_SETTINGS_DEFAULTS` so fresh installs work end-to-end. Existing installs keep stored values; flip in `/app/lazychat-settings`.

### Verification

In-process smoke unchanged: 274/0/6 (the 6 fixes don't change tool surface, only commit-handler behavior + system prompt text). HTTP-wire 82/16. chat-ui vitest 457/0. Manually validated end-to-end through the chat panel: a Number Card committed and rendered ([`2026-05-14-fully-agentic-chat-panel/`](../2026-05-14-fully-agentic-chat-panel/)), a Desk Page committed at `/app/top-customers-page` with iteration via `prepare_update_doc(Page, patch={content,style,script})` actually patching disk files ([`2026-05-15-chat-driven-page-build/`](../2026-05-15-chat-driven-page-build/)).

### Open

- Server Script side-effect AST gate (`frappe.sendmail`/`enqueue`/`publish_realtime`) still deferred — read-only-by-construction claim in `prepare_create_server_script` schema slightly overstated.
- One remaining `frappe.utils.escapeHtml` call surfaced in the latest Page build; would self-heal in the next chat turn now that the playbook teaches `textContent` instead. Not gating release.
- Backend ↔ chat-ui playbook hash-diff smoke test (T100p) deferred; today they're aligned manually per commit.

---

## Cycle 13 — Mockup-to-ERPNext: typed UI primitives + Playwright screenshot + LLM-as-judge auto-iterate (2026-05-13)

Three-milestone cycle that turns the LLM into a competent ERPNext dashboard builder: read a mockup like a person, build the equivalent dynamic Page (with real API calls) inside ERPNext, then visually verify against the reference and auto-iterate until convergence. Companion chat-ui story in [../lazychat.ai/CLAUDE.md](../lazychat.ai/CLAUDE.md) "Cycle 13".

### M1 — Typed UI primitives + render-preview + system prompt

6 new tools (TOOL_SCHEMAS **95 → 101**):

| Tool | Risk | Purpose |
|---|---|---|
| `prepare_create_page` | LOW (auto-Apply + AUTO_OPEN) | Stage a Desk Page at `/app/<page_name>`. HTML/CSS/JS render-preview hard-blocks parse errors + references to non-existent doctypes (`frappe.db.get_list`) / methods (`frappe.call`). Soft-warns on hardcoded colors, missing semantic HTML, missing `lazychatReady` marker. System Manager gate at stage + commit. |
| `prepare_create_server_script` | HIGH (explicit Apply only) | Stage a Server Script (`script_type=API`, whitelisted Python endpoint). AST validator rejects forbidden imports (subprocess/os/sys/...), dangerous builtins (open/eval/exec/...), `frappe.db` writes. Same-turn-staged methods exposed via `frappe.local.flags.lazychat_staging_methods` so a sibling `prepare_create_page` can reference them via `frappe.call` without the existence check failing. Gated by `lazychat_allow_dangerous_tools` + System Manager. |
| `prepare_create_workspace` | LOW (auto-Apply + AUTO_OPEN) | Stage a Workspace card-grid dashboard at `/app/<scrub(title)>`. Validates every referenced Number Card / Dashboard Chart / DocType exists. |
| `prepare_attach_assets` | HIGH (explicit Apply) | Upload files (image/font/text/CSS) to a target doctype. 5 MB per-file cap; mime allowlist; caller must have `write` perm on target. |
| `list_number_cards` | discovery | Read-only list of existing Number Cards. Used before staging a new card / Workspace to avoid duplicates. |
| `list_whitelisted_methods` | discovery | Read-only list of `@frappe.whitelist()` methods reachable via `/api/method/<path>`. Walks `frappe.whitelisted` (list of function objects on Frappe v15, not the dict the docs suggest). Use before staging a new Server Script. |

Render-preview validators (graceful-degrade if deps missing):
- [`page_validators.py`](lazychat_erpnext/desk_assistant/page_validators.py) — `validate_html` (lxml.etree strict XML, void tags must be self-closing), `validate_css` (tinycss2 + brace-balance pre-check), `validate_js` (pyjsparser), `validate_js_doctype_refs` (AST walk for `frappe.db.get_list/get_value/exists/get_doc` literal-string args → checks DocType row exists), `validate_js_method_refs` (AST walk for `frappe.call({method:...})` → checks against `frappe.handler.get_method` + same-turn-staged + builtin prefixes), `collect_quality_warnings` (hardcoded-color count w/o `var(--*)`, missing `<header>/<main>/<section>`, missing `lazychatReady` marker).
- [`server_script_validators.py`](lazychat_erpnext/desk_assistant/server_script_validators.py) — `validate_python_ast` + `validate_no_forbidden_imports` + `validate_no_forbidden_builtins` + `validate_no_frappe_writes` + `validate_output_present` + `run_all` orchestrator. Scope is **`frappe.db` writes only**; `frappe.sendmail`/`enqueue`/`publish_realtime` side-effect gating deferred to a follow-up.

New deps in `pyproject.toml`: `lxml>=4.9`, `tinycss2>=1.2`, `pyjsparser>=2.7` (core); `playwright>=1.40` (optional `[project.optional-dependencies] screenshot` extra — see M2).

System prompt addition: **`_DESK_PAGE_PLAYBOOK`** in [`claude_bridge.py`](lazychat_erpnext/desk_assistant/claude_bridge.py) — 6-step workflow + 7 visual-quality rules (theme tokens, typography matching, semantic HTML, real data wiring, loading/empty/error states, `lazychatReady` marker) + anti-patterns + iteration-loop guidance. Mirrored in [chat-ui's `routerSystemPrompt.ts`](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts). chat-ui's `LOW_RISK_ACTIONS` + `AUTO_OPEN_AFTER_APPLY` + `ACTION_TO_LABEL` extended for the 4 new mutations.

### M2 — Playwright screenshot preview

- [`screenshot.py`](lazychat_erpnext/desk_assistant/screenshot.py): `@frappe.whitelist() capture(route, viewport, wait_for_dataset, timeout_ms)`. Lazy browser pool (persistent Chromium launched on first call, reused across requests via `_browser` module global + `_browser_lock`). Per-request: new context with the caller's `frappe.local.session.sid` cookie injected (rendered page sees the SAME permissions as the caller's browser would), navigate, `page.wait_for_function(document.body.dataset[<key>] === '1')` with timeout fallback (proceeds anyway, returns `ready_signal_seen=False`), screenshot, return base64 PNG `data:image/png;base64,...`. Refuses Guest. Route-prefix allowlist: `/app/*` / `/files/*` / `/private/files/*`. Concurrency: single-slot `_capture_lock` + bounded queue `_max_queue_depth=4` (returns `"at capacity"` error when full). 30s ceiling via `timeout_ms` clamp `[500, 20000]`. ALL exceptions wrapped → `{ok: False, error}` (never raises). Gated by `Lazychat Settings.enable_screenshot_preview` (Check field, default `0` — operator must explicitly enable after `./env/bin/pip install playwright && ./env/bin/playwright install chromium`).
- `install.py:_check_playwright_available()` logs a clear actionable warning on `after_install` / `after_migrate` if Playwright is installed but Chromium missing.
- Postmessage protocol extended: `InspectRouteRequest.payload.captureSpec.mode?: 'dom' | 'screenshot'` (default `'dom'` for back-compat with Cycle 9 M4 DOM-capture). Screenshot-mode adds `ready_signal` + `viewport` to the request; response adds `screenshot_b64`, `width`, `height`, `capture_method`, `ready_signal_seen`, `captured_at` to `captured`.
- [`lazychat_panel.bundle.js`](lazychat_erpnext/public/js/lazychat_panel.bundle.js) `handleInspectRoute` branches on `spec.mode === "screenshot"` → POSTs to `screenshot.capture` endpoint (CSRF + cookie auth via `credentials: include`), ships base64 PNG back to chat-ui via `inspectRouteResponse`.
- chat-ui side (sibling repo): new `screenshot` Message kind + `ScreenshotMessage.tsx` renderer (4 states: capturing/done/error/stale) + `triggerScreenshot(sid, pageName, route)` in `agentRunner.ts` auto-fired by `commitSlash.ts` after `create_page` / `update_doc(Page)` commits. html2canvas 1.4.1 vendored at `/assets/lazychat_erpnext/js/html2canvas.min.js` for in-browser reference-mockup capture.

### M3 — LLM-as-judge visual auto-iterate

- [`visual_judge.py`](lazychat_erpnext/desk_assistant/visual_judge.py): `compare(candidate_b64, reference_b64, intent_text, page_source, effort)` + `generate_fixes(diff_json, page_doc, intent_text, effort)`. Both wrapped in `concurrent.futures.ThreadPoolExecutor` with hard timeouts (30s / 60s). **Skip-on-failure pattern**: ANY exception (model unresolved, adapter throws, output not parseable JSON, timeout) returns `{skipped: True, reason: "..."}` — never breaks the calling flow. Mirrors `critic.py:critique_composition` (Cycle 9 M2). Effort gating: `low`/`medium` → skip immediately; `high` → 1-iteration cap, default model `claude-sonnet-4-6`; `max` → 3-iteration cap, default `claude-opus-4-7`.
- `Lazychat Settings.vision_judge_models` Code/JSON field — admin overrides per-Effort model. Default `{"high": "claude-sonnet-4-6", "max": "claude-opus-4-7"}` mirrored in `boot.py:_SETTINGS_DEFAULTS`.
- Vision message blocks use the canonical Anthropic shape: `{type: "image", source: {type: "base64", media_type: "image/png", data: "<b64>"}}`. The OpenAI-compatible adapter's `_to_oai_messages` translator at `providers/openai_compat.py:82-101` already converts to `{type:"image_url", image_url:{url:"data:...;base64,..."}}`. No provider extension needed.
- `compare` output shape: `{score: 0.0-1.0, verdict: "match" | "needs_fixes", mismatches: [{category, severity, description, selector_hint, fix_hint}]}` validated minimally; `_extract_json_block` tolerates bare JSON, ```json fenced```, and prose-embedded JSON (some models can't resist Markdown even when told "JSON ONLY").
- `generate_fixes` output shape: `{patch: {style?, content?, script?}}` — patch keys whitelisted to those three (defends against LLMs emitting `route`/`parent_page`/etc).
- Whitelisted endpoints in `api.py`: `lazychat_visual_judge_compare` + `lazychat_visual_judge_generate_fixes` (System Manager only, defense-in-depth on top of module-level Effort gating). `lazychat_get_page_doc(name)` returns the `content`/`style`/`script` fields the orchestrator feeds into `generate_fixes` (permission-scoped to `Page.read`).
- chat-ui side: `visualDiff` Message kind + `VisualDiffMessage.tsx` renderer + `visualJudgeClient.ts` wrapper + `runVisualIterationLoop(sid, pageName)` orchestrator in `agentRunner.ts` (kicked off by `triggerScreenshot`'s `onResp` post-success when ref mockup is present + Effort≥high). Loop converges at `score >= 0.92` OR `iter >= cap` OR `verdict='match'` OR any `{skipped}` envelope.
- System prompt: **`_VISUAL_ITERATION_BLOCK`** appended after the playbook (both repos) — tells the LLM the loop is system-orchestrated, NOT a tool to invoke directly; reinforces "produce the best first cut" as the primary job.

### Smoke

In-process: **274 pass / 0 fail / 6 skip** (T100a–n M1 typed wrappers + render-preview, T101a–d M2 screenshot, T102a–d M3 visual judge). The 6 skips are by-design: T100h/h'/i/j when `lazychat_allow_dangerous_tools=false`, T101b/c/d when Playwright/Chromium not installed (`is_available()` probe).

HTTP-wire: OK=82 / OK_ERROR=16 (101 tools registered + called). 6 new tools all validate.

chat-ui: 457/0 vitest pass (78 files, +16 from baseline), typecheck clean across all 3 workspaces.

### Skip-on-failure path verified (no Playwright + no vision LLM on this bench)

T101b/c/d cleanly skip via `is_available()` probe; T102b/c/d cleanly skip via `resolve_model("claude-sonnet-4-6")` raising `ValidationError`. Calling flows never break. UX degradation: screenshot Message stuck at `error` state with clear "Playwright not installed" hint; `visualDiff` Message simply not appended (the loop exits silently with `console.info`).

### How to enable on a bench

**Cycle 13 ships with allow-all defaults.** Fresh installs get `enable_screenshot_preview = 1`, `vision_judge_models` populated, `allow_dangerous_tools = 1` out of the box (graceful-degrade everywhere — missing deps return clean `{ok:false, error:...}` envelopes rather than breaking flows). Existing installs keep their stored values; flip in `/app/lazychat-settings` if needed.

The only operator step is installing the optional Playwright + Chromium binaries for the screenshot service to actually render anything (otherwise `screenshot.capture` returns `{ok:false, error:"playwright not installed — ..."}`):

```bash
cd $BENCH_ROOT
./env/bin/pip install playwright
./env/bin/playwright install chromium
```

For the M3 visual-judge to issue real vision calls, admin must add an `LLM Model` row with `model_id` matching one of `vision_judge_models` (defaults `claude-sonnet-4-6` for high, `claude-opus-4-7` for max) bound to a `LLM Provider` with a valid API key. Missing this just makes `visual_judge.compare` skip with `{skipped:true, reason:"no provider configured for ..."}` — the loop is invisible when off.

### Screenshot service — bench-local URL

The Playwright capture runs ON the bench worker, so it talks to gunicorn directly via `http://127.0.0.1:<webserver_port>` (default 8000). Using `frappe.utils.get_url()` would produce hostnames like `erp.local` that headless Chromium can't resolve via DNS (`ERR_NAME_NOT_RESOLVED`). 127.0.0.1 always works for same-machine bench-side capture, both in dev (`bench serve`) and prod (gunicorn behind nginx — still listens on 127.0.0.1). The session cookie domain is set to `127.0.0.1` to match.

### `is_available()` is import-only

`screenshot.is_available()` checks ONLY `import playwright.sync_api` — NOT `sync_playwright().start()`. The probe would conflict with the persistent browser pool from `_get_browser()` (a second `sync_playwright()` call after the first capture hangs or fails). Chromium presence is verified at capture time via the actual browser launch; a missing binary surfaces as `{ok:false, error:"capture failed: Error: ..."}`.

### Validation walkthrough (Proman MD Dashboard)

Drop the 30 KB Proman MD Dashboard HTML mockup into the composer at Effort=max. The chat-ui's `extractText.ts` captures a reference-screenshot via html2canvas silently. The LLM uses `list_whitelisted_methods` + `list_number_cards` + `describe_doctype` + `find_join_path` first (discovery), then stages 3× `prepare_create_server_script` + 1× `prepare_create_page`. Apply each → M2 auto-screenshots `/app/proman-md-dashboard` (V1) → M3 compares → `visualDiff` Message → `generate_fixes` → `prepare_update_doc(Page, patch:{style:...})` auto-Applies at Effort=max+LOW_RISK → M2 re-screenshots (V2) → loop continues to V3 → convergence at `score >= 0.92` OR `iter >= 3` cap. The Page persists at `/app/proman-md-dashboard` with 3 sections wired to real ERPNext data.

### Open follow-ups (from final code review)

1. `page_validators.py:224` — `from frappe.handler import get_method` import may fail on some Frappe versions; mirror the defensive try-once pattern from `tools.py:list_whitelisted_methods`.
2. `screenshot.py:100` cookie `httpOnly: True` is cosmetic on Playwright's `add_cookies` (doesn't affect security boundary in same-origin headless Chromium).
3. `screenshot.py` browser pool needs an `atexit` hook to avoid Chromium leaks on long-lived workers.
4. `visual_judge.py:_extract_json_block` greedy-match could glue two top-level JSON objects in chatty prose; prefer the fenced-block path first.
5. Server Script side-effect AST gate (`frappe.sendmail` / `enqueue` / `publish_realtime`) deferred — the "READ-ONLY by construction" claim in `prepare_create_server_script`'s schema is slightly overstated until that lands.

---

## Cycle 12 — M2: Critic helper refactor + 7-tool expansion (2026-05-10)

Two-pillar cycle:

**Pillar 1 — Helper extraction.** New `_attach_critic_feedback(response_dict, *, args, action, default_intent, payload, evidence)` helper in [`tools.py`](lazychat_erpnext/desk_assistant/tools.py) near `_dangerous_tools_enabled`. Mutates `response_dict["critic_feedback"]` in place — either with the verdict or with the canonical `{skipped: True, reason}` shape on failure. The 5 existing call sites from M1 (`prepare_create_doc`, `prepare_update_doc`, `prepare_run_sql`, `prepare_run_python`, `prepare_create_report`) refactored to use it; behavior byte-identical (T93a-d still pass).

**Pillar 2 — Expansion to 7 more high-value mutations.** Critic now grades:

| Tool | Evidence shape |
|---|---|
| `prepare_submit_doc` | `{is_submittable, current_state, has_workflow}` (workflow_state read defensively, falls back to None) |
| `prepare_send_email` | `{recipients_sample[:3], subject_words[:8], content_preview[:200]}` (privacy-capped) |
| `prepare_workflow_action` | `{action, current_state, allowed_actions, next_state}` (reuses doc + transitions captured during validation) |
| `prepare_delete_doc` | `{doctype, incoming_link_count}` (cheap fixed-cost blast-radius signal) |
| `prepare_bulk_update` | `{affected_count, patch_fields, filter_keys}` (no raw filter/patch values) |
| `prepare_rename_doc` | `{old_name, new_name, merge, link_refs_count}` |
| `prepare_revert_doc` | `{fields_being_reverted[:20], change_count}` |

Each new site is gated on `cycle9_enabled` (mirrors M1's `prepare_run_python` — minimal opt-in wrapper, no verification_brief / exemplars / payload validators; just the critic). Critic only runs at Effort=high (haiku) or max (sonnet); low/medium skip per `EFFORT_MAP`.

**Smoke**: 236 → **244** (+8: T94a/b/c/d/e/f/g per-tool + T94h roll-call drift detector that source-greps `_attach_critic_feedback` calls in all 12 expected dispatcher branches). HTTP-wire 94/94 unchanged (no new tools, no schema changes).

**Side fix**: T89m (`composition.append_iteration`) wrapped in try/except so a Redis-session-expiry race during `bench execute` no longer aborts the smoke runner before reaching T94 cases.

**Evidence**: [test/evidence/cycle-12-m2/01-critic-feedback-7-new-tools.txt](test/evidence/cycle-12-m2/01-critic-feedback-7-new-tools.txt) — bench-execute output for all 8 T94 cases passing.

**Out of scope (deferred):**
- Verification briefs / exemplars on the 7 new tools.
- Critic on remaining ~28 prepare_* tools (kb / dashboard / number_card / scheduled_job / etc.) — mostly low-risk creators where critic adds little value.
- Refactor into a Python decorator (helper-call form is simpler).
- chat-ui rendering changes — existing Cycle 11 M3 amber strip already handles all 12 tools' `critic_feedback` identically.

## Cycle 12 — M1: Critic coverage expansion (4 prepare_* tools) (2026-05-09)

Extends M3's `critique_composition` wiring (in `prepare_create_report` only)
to four more prepare_* tools so the chat-ui's amber critic strip can warn
the user about misalignment in CRUD/SQL/Python flows. Server-only cycle.
No chat-ui changes — the existing `criticFeedback` field in
`mcpPreviewAction` (M3) renders all four tools' verdicts identically.

Each tool gets a tool-specific evidence shape (smallest meaningful blob the
critic can grade):

| Tool | Evidence shape |
|---|---|
| `prepare_create_doc` | `{doctype, fields_set: list(values.keys())}` — shape only, no raw values (privacy) |
| `prepare_update_doc` | `{before_values: get_value(dt, dn, patch_fields), patch_fields}` — BEFORE state lets critic flag dangerous patches |
| `prepare_run_sql` | `{query: query[:2000], limit}` — no execute-probe sample (raw-SQL gate doesn't run one) |
| `prepare_run_python` | `{code: code[:1500], ast_summary: {imports[:20], calls[:30]}}` — stdlib AST scan; no dry-run |

All four follow the M3 pattern: try/except critique_composition, append
`critic_feedback` to response_dict, gracefully degrade to
`{skipped: True, reason}` on critic LLM failure or Effort tier skip. All
four are gated on `cycle9_enabled` (verified: with flag OFF,
`critic_feedback` is absent from response).

`prepare_run_python` was the only one without a `cycle9_enabled` wrapper
before this cycle — added a minimal one with JUST the critic call (no
verification_brief, no exemplars; those can come later if needed).

**Smoke**: 232 → **236** (+4: T93a/b/c/d, all asserting `critic_feedback`
field presence in each tool's response). HTTP-wire 94/94 unchanged.

**Effort gating**: same as M3 — `low`/`medium` skip critic;
`high`/`max` invoke it (haiku/sonnet).

**Evidence**: [test/evidence/cycle-12-m1/01-critic-feedback-all-tools.txt](test/evidence/cycle-12-m1/01-critic-feedback-all-tools.txt) — bench-execute output for all 4 tools showing `critic_feedback` present.

**Out of scope (deferred):**
- Other prepare_* tools (`prepare_send_email`, `prepare_delete_doc`,
  `prepare_workflow_action`, etc.) — defense-in-depth via the existing
  gates; critic adds noise without much value here.
- `prepare_run_python` dry-run sandbox (would let critic see actual
  output, not just AST) — separate cycle.

## Cycle 11 — M4: Live tool progress + visible inactivity (2026-05-09)

Eliminates the "response gets stuck and slow" UX dead-zone reported by the
user. Server side: 1 file changed.

- `desk_assistant/critic.py:critique_composition` — wraps the
  `adapter.chat(...)` call with a deterministic 30s timeout via
  `concurrent.futures.ThreadPoolExecutor + Future.result(timeout=30)`.
  Without this, a hung critic LLM (network stall, slow upstream) blocked
  the parent `prepare_*` response indefinitely; with it, the call returns
  `{skipped: True, reason: "critic LLM call timed out after 30s"}` so the
  chat-ui's "verifier skipped" tag fires reliably. Stdlib only — no new
  dependency.

**Smoke**: 231 → **232** (+1: T92d critique_composition returns
`{skipped: True, reason}` when critic LLM unavailable). HTTP-wire 94/94
unchanged.

Companion chat-ui story (per-tool elapsed in LiveStatus + 2-strike SSE
inactivity policy + critic phase visibility) in
[../lazychat.ai/CLAUDE.md](../lazychat.ai/CLAUDE.md) "Cycle 11 — M4".

## Cycle 11 — M3: SQL pre-flight hard gate + critic visibility (2026-05-09)

Two independent fixes shipped together. Both gated on `cycle9_enabled` (no
behavior change when off). Companion chat-ui work in
[../lazychat.ai/CLAUDE.md](../lazychat.ai/CLAUDE.md) "Cycle 11 — M3".

### A. Structured SQL gate error response

`prepare_create_report` (Query Report path) ALREADY ran `_validate_select_sql`
+ `_probe_select_sql_explain` + `_probe_select_sql_execute` as gates (lines
3458-3470). M3 tightens the FAILURE shape from a flat `{"error": "<msg>"}`
to:

```python
{
  "ok": False,
  "error": "<formatted message>",
  "sql_error": "<raw db error>",
  "sql_phase": "validate" | "explain" | "execute",
  "suggestion": "<actionable hint>",
}
```

So the LLM can route on `sql_phase` and apply targeted fixes — call
`describe_doctype` if `sql_phase === "explain"` (table/column doesn't exist),
fix DML keywords if `sql_phase === "validate"`, etc. Documented in
`tool_schemas.py:prepare_create_report.description` so the LLM sees this
contract via `tools/list`.

### B. Critic verdict surfaced via `critic_feedback`

`critique_composition` already existed in `desk_assistant/critic.py` from
Cycle 9 M2 but was NEVER CALLED. M3 wires it into `prepare_create_report`'s
response when `cycle9_enabled` is true:

```python
# Inside cycle9_enabled guard, after exemplars block, before return:
try:
  from lazychat_erpnext.desk_assistant.critic import critique_composition
  response_dict["critic_feedback"] = critique_composition(
    intent_summary, "create_report",
    {report_name, ref_doctype, report_type, query},
    {sample_columns, sample_rows[:3]},
    effort=args.get("_effort") or "medium",
  )
except Exception as e:
  response_dict["critic_feedback"] = {"skipped": True, "reason": ...}
```

Returns `{verdict: 'ok'|'mismatch', severity, mismatches[], suggested_revisions[], model}`
on success or `{skipped: True, reason}` when the Effort tier skips critic
(low/medium) or the critic LLM fails. Defense-in-depth try/except so a
critic crash NEVER breaks `prepare_create_report`.

The chat-ui's `MCPPreviewActionCard` renders an amber strip listing
mismatches when `verdict === 'mismatch'` (defense-in-depth: user CAN still
click Apply, but they see the risk first). When `skipped: true`, a small
grey tag surfaces "verifier skipped" so the user knows the critic didn't run.

**Smoke**: 228 → **231** (+3: T92a sql_phase=explain, T92b sql_phase=validate,
T92c critic_feedback presence). HTTP-wire 94/94 unchanged (no new tools).

**Effort gating** (mirrors `critic_model_for_effort` in critic.py):
- `low` / `medium` → critic skipped (returns `{skipped: True, reason: "effort=X skips critic"}`).
- `high` → claude-haiku-4-5 (cheap, fast).
- `max` → claude-sonnet-4-6 (higher quality).

**Visual evidence**: [test/evidence/cycle-11-m3/01-amber-critic-strip-rendered.png](test/evidence/cycle-11-m3/01-amber-critic-strip-rendered.png) — Apply card with amber "Verifier flagged (medium)" strip listing 2 mismatches, Apply/Cancel buttons below.

## Cycle 11 — M2: Stage-and-redirect form prefill (kills HTTP 414) (2026-05-09)

Replaces inline `_lz_items=<base64-json>` URL convention with a server-staged
token. For Query Report HTML buttons that prefill a new-doc form, the token-
based URL stays under 100 chars regardless of payload size — eliminates HTTP
414 "Request-URI Too Long" for 50+ item variance reports.

**New endpoints in `desk_assistant/api.py`:**
- `prepare_form_prefill(doctype, parent_fields, items, ttl)` — stages payload in
  `frappe.cache()` with 22-char `secrets.token_urlsafe(16)` token, 5-min TTL
  (clamped to [60, 3600]). Re-checks `frappe.has_permission(dt, ptype="create")`.
  Returns `{ok, token, url}` where `url = "/app/<scrub>/new?_lz_token=<22-char>"`.
- `fetch_form_prefill(token)` — single-use (consumes on first read), user-bound
  (refuses cross-user reads via `_retrieve_prefill` user-binding check).

Helpers `_stage_prefill` / `_retrieve_prefill` mirror the existing
`_stage_action` / `_retrieve_action` pattern (`tools.py:644-665`) with a
distinct cache prefix `lazychat:prefill:` (vs `lazychat_prep:`).

**New tool wrapper in `tools.py`:** `prepare_form_prefill` is a thin re-export
registered in `tool_schemas.py`. Schema description teaches the LLM to ALWAYS
prefer this over `_lz_items` URL when items count >= 5 OR payload could exceed
~1 KB. `fetch_form_prefill` is NOT exposed as a tool (LLM can stage but not
retrieve).

**Persistent Client Script (`install.py`):** the helper auto-installed on
Purchase Invoice / Sales Invoice / Purchase Receipt / Delivery Note gains a
`_lz_token` decoder branch. Reads `?_lz_token=` from URL, calls
`frappe.call("lazychat_erpnext.desk_assistant.api.fetch_form_prefill",
{token})`, caches the payload on `frm.__lz_token_payload` (single-use
server-side, but Make Return reapply needs a second invocation), applies
parent_fields via `frm.set_value` and items via `applyItems(frm, rows)`.
Race guard: `frm.__lz_token_fetching` flag prevents the 5 form events
(`onload_post_render`, `refresh`, `return_against`, `supplier`, `customer`)
from dispatching parallel fetches that would consume the single-use token
twice. Legacy `_lz_items` decoder retained with `console.warn` deprecation
notice.

**Prompts updated:** `claude_bridge.py` AUTO-FILL block teaches
`prepare_form_prefill` first; chat-ui mirror at
`lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts:69` updated identically.

**Smoke**: 225 → 228 (+3: T91a/b/c covering round-trip, single-use semantics,
cross-user denial via Guest). HTTP-wire: 93 → 94 (+1: `prepare_form_prefill`
validator).

### M2.1: Frappe v15 URL-stripping fix (panel-shim IIFE capture)

T7 ship-gate revealed Frappe v15 redirects `/app/<dt>/new?<params>` to
`/app/<dt>/new-<dt>-<random>` and **strips the entire query string** before
form `onload` fires. This broke BOTH the new `_lz_token` AND the pre-existing
`_lz_items` URL conventions — by the time the persistent Client Script's
`lazychatPrefill` runs, `window.location.search` is empty.

**Fix (M2.1, shipped same day):** the panel-shim
[`lazychat_panel.bundle.js`](lazychat_erpnext/public/js/lazychat_panel.bundle.js)
loads via `app_include_js` at HTML-parse time — BEFORE Frappe's router
redirects. Added an IIFE-time capture:

```js
try {
  if (typeof window !== "undefined" && window.__lazychat_initial_search === undefined) {
    window.__lazychat_initial_search = window.location.search || "";
  }
} catch (_) {}
```

The persistent Client Script's IIFE then prefers `window.__lazychat_initial_search`
over the (empty) live URL. Falls back to live URL if the global isn't set
(e.g., if the panel-shim is disabled).

This fixes BOTH paths in one stroke — `_lz_token` AND legacy `_lz_items`.
Verified end-to-end via Playwright:
[evidence](test/evidence/cycle-11-m2/01-pi-prefilled-via-lz-token.png) shows
`Supplier: ACME-M21` + `Is Return ✓` populated on a fresh PI form after
navigation to `/app/purchase-invoice/new?_lz_token=...` — even though
`window.location.search` is empty by the time the Client Script reads it.

**Manual verification (T7) — ALL PASS:**
- ✅ `prepare_form_prefill` endpoint round-trip (stage + fetch + single-use + cross-user denial) — verified via `bench execute` and HTTP curl.
- ✅ URL is tiny (`?_lz_token=22-char`, total length ~46 chars).
- ✅ Tool registry count incremented to 94.
- ✅ Server smoke 228/0/2; HTTP-wire 94/94.
- ✅ Form prefill DOES visually populate — supplier + is_return + items table all flow through to the new-doc form.
- ✅ Legacy `_lz_items` path also fixed by the same panel-shim capture.

**SPA navigation caveat (acceptable):** The panel-shim IIFE captures only at
full page load. For in-app `frappe.set_route` clicks (no page reload), the
captured value is from the original page load. Workaround: emit
`<a href="/app/<dt>/new?_lz_token=...">` anchor links (which Frappe does NOT
intercept on `/new` routes — verified during T7), so the click triggers a
full reload and the IIFE re-captures. This matches the canonical Query
Report HTML cell pattern.

## Cycle 10 — chat-ui admin panel + allow-all defaults (2026-05-09)

User principle: *"reduce cognitive load on user erp side. we should fully
control all configuration within the chat ... move all ERPNext-side
configuration outside of erp into lazychat.ai ui."* Cycle 10 ships:

**Allow-all defaults (Pillar 2)** — `lazychat_settings.json` flips 4
boolean defaults from `"0"` to `"1"`: `allow_email`, `allow_email_setup`,
`allow_dangerous_tools`, `cycle9_enabled`. Mirrored in `boot.py:_SETTINGS_DEFAULTS`.
Defense-in-depth (System Manager role check at tool dispatch + /commit
confirmation per call) preserved. Frappe applies new defaults to NEW
rows only — existing installs keep their stored values. site_config
overrides still win. Smoke T89a updated to assert "is wired (boolean)"
rather than asserting the specific value.

**6 new whitelisted endpoints (Pillar 1)** in `desk_assistant/api.py` —
all System Manager only (read snapshot is wider but masks api_key):

- `get_lazychat_admin_snapshot()` — single round-trip read of settings +
  providers + models + is_system_manager + settings_shadowed (per-field
  flag indicating site_config is overriding the doctype value).
- `update_lazychat_settings(field, value)` — patches one whitelisted
  field. Coerces booleans, validates `chat_path` enum, JSON-parses
  `llm_proxy_allowed_hosts`. Returns `{ok, field, value, shadowed_by_site_config}`.
- `upsert_llm_provider(name, fields)` — create or update. Blank/`****`
  api_key treated as "don't change" (lets editor save other fields
  without re-entering the key).
- `delete_llm_provider(name)` — refuses if any LLM Model still
  references it; returns `blocking_models` list when blocked.
- `upsert_llm_model(name, fields)` — single-default invariant enforced
  via raw SQL `UPDATE … SET is_default = 0 WHERE name != %s`.
- `delete_llm_model(name)` — straightforward delete.

Helper at top of new section: `_require_system_manager()` /
`_is_system_manager()`. All endpoints reuse `frappe.has_permission` +
`doc.save(ignore_permissions=False)` so Frappe-level perms re-check too.

**Panel-shim init payload (Pillar 5a)** — `public/js/lazychat_panel.bundle.js`
adds `isSystemManager` + `userRoles` to the init payload (around line
688). New `bridge.on("settingsChanged", ...)` handler that posts back a
`reloadRequired` envelope when an iframe-affecting field changes
(`iframe_base_url` / `iframe_query_params` / `legacy_widget_enabled`).
Other fields (allow_* gates, `cycle9_enabled`, `chat_path`) take effect
on next request — server reads `get_lazychat_settings()` per-call.

**Smoke**: 217 → 225 (+8 cases T89y/z + T90a-f). HTTP-wire 93/93
(endpoints aren't MCP tools, so curl_smoke unchanged). chat-ui side
companion (sibling repo): adminConfig store + AdminSettingsPanel +
3 tabs + CommandPalette gated entry. See lazychat.ai CLAUDE.md
"Cycle 10 — chat-ui admin panel".

## Cycle 9 — M4: Live form grounding + PEVR primitives (2026-05-09)

Server side: panel-shim handler that opens a hidden iframe, captures DOM
state per a captureSpec, returns the result via existing bridge.send.

`public/js/lazychat_panel.bundle.js` — three new functions registered
via the existing `bridge.on("inspectRoute", ...)` pattern (NOT the
spec's hypothetical addEventListener switch — the bundle uses
`makeBridge` with `bridge.on/send` already):

- `handleInspectRoute(payload)` — creates `<iframe display:none>` at
  the requested route, polls every 200ms for `cur_frm.is_new()` to
  return truthy, captures whitelisted state per spec, posts
  `inspectRouteResponse` via `bridge.send(...)`. Default 5s timeout
  (`spec.timeout_ms` overrides). Cleans up iframe on success + timeout.
  Try/catch around cross-origin / not-yet-ready cur_frm access.
- `capturePerSpec(cf, spec, url)` — whitelisted DOM read: form_fields
  from cf.doc, child_table rows (with optional count + child_row_fields),
  inner-toolbar buttons. NO arbitrary access — spec keys only.

Iframe is same-origin (Frappe Desk), so cur_frm is readable. Whitelist-
only capture means LLM can't request arbitrary DOM through the spec.

Smoke 217/0/2 unchanged (pure JS shim addition, no Python tests). Tools
93/93 unchanged.

## Cycle 9 — M3: Schema knowledge graph + cross-session exemplar memory (2026-05-09)

Two new server-side modules + new doctype + commit-side learning hook:

- `desk_assistant/schema_graph.py` — per-conversation Redis cache for
  describe_doctype results (30-min TTL). `describe_doctype` was promoted
  from inline-in-dispatcher to a standalone function with optional
  `conversation_id` kwarg. Cache hit returns `{**cached, "_from_cache": True}`
  flag. Doctype-naive callers (e.g. `_doctype_relationships` from M1.3)
  use the standalone function without conversation_id, so they see the
  full meta-fetch path. T89t/u cover round-trip + isolation.

- `Lazychat Exemplar` doctype (NEW) — cross-session learning store.
  Fields: intent_signature, action, target_doctype, payload_template
  (anonymized JSON), success_count, reject_count, trust_score, last_used,
  created_by_user. Autoname `LZE-<sig>-<########>`. Permissions: System
  Manager full + All read.

- `tools.py:_intent_signature(action, target_doctype, intent_text)` —
  builds compact key `<action>:<target_doctype>:<sha1_12char>` from
  filtered+sorted+deduped intent keywords (12-word stopword set).

- `tools.py:_anonymize_payload(payload)` — recursively replaces
  dict/list values with `<value>` / `<bool>` / `<number>` markers,
  preserving structure. Used before persisting an exemplar so no real
  field values leak into the cross-session store.

- `tools.py:recall_exemplars(action, target_doctype, intent_text, limit=3)` —
  exact-signature match first, falls back to action+doctype broad match;
  ranks by trust_score desc + last_used desc; deduplicates on name.

- `tools.py:persist_exemplar(action, target_doctype, payload, intent_text)` —
  increments existing on signature collision (success_count++ + last_used);
  creates new row otherwise. Called from `commit_prepared_action` success
  path inside a try/except — persist failure NEVER breaks a commit.

- `prepare_*` responses (when cycle9_enabled) augmented with
  `examples_from_history: List[ExemplarRow]` — recalled at compose time
  and gated by `EFFORT_MAP[effort]["exemplar_top_n"]` (low: 0, medium: 1,
  high: 3, max: 5). Wired into prepare_create_report, prepare_create_doc,
  prepare_update_doc, prepare_run_sql.

Smoke 214 → 217 (+3: T89t/u/v/w/x). Tools 93 unchanged. chat-ui 369
unchanged (server-side cycle).

Behind cycle9_enabled flag (default false). When off, M3 changes are
inert: no schema cache reads, no exemplar recall, no persist on commit.

## Cycle 9 — M2: Iterative test-driven loop + composer-critic dual-LLM (2026-05-09)

Three new server-side modules + augmented prepare_* responses:

- `desk_assistant/composition.py` — Redis-backed composition session.
  Each session represents one user-intent compose flow; up to 5
  iterations of (compose → probe → analyze) accumulate against the
  same intent_hash. 90s TTL; user-scoped key. Public API:
  `open_or_resume_session`, `append_iteration`, `finalize_session`,
  `get_session`. T89l/m cover round-trip + cap.

- `desk_assistant/critic.py` — composer-critic dual-LLM. The composer
  is the chat session's main model; the critic is a separate model
  (haiku at high Effort, sonnet at max). `build_critic_prompt` builds
  a structured prompt with USER INTENT + COMPOSED PAYLOAD + EVIDENCE
  + JSON schema for the verdict. `parse_critic_verdict` tolerates
  bare JSON, fenced JSON, and prose-embedded JSON. `critique_composition`
  uses the canonical `resolve_model(...)` + `adapter.chat(...)` pattern
  from claude_bridge.py; ALL exceptions return `{skipped: True, reason: …}`
  rather than throwing. T89n-r cover prompt structure, parser, gating.

- `verification_brief` block on every successful `prepare_*` response
  (when cycle9_enabled): `{user_intent_summary, what_was_composed,
  sample_evidence, review_checklist}`. The chat-ui's verdict-retry
  hook reads this block to decide whether the LLM should self-review.
  Wired into prepare_create_report, prepare_create_doc,
  prepare_update_doc, prepare_run_sql. T89s covers presence.

- `EFFORT_MAP` extended (claude_bridge.py): every Cycle 9 capability
  gated by Effort level. low=skip critic / medium=skip / high=haiku /
  max=sonnet. iter_cap goes 1/2/3/5; reflect_retries 0/1/1/2; apply
  threshold 0.50/0.65/0.75/0.85. Mirrors apps/chat-ui/src/lib/effortConfig.ts.

Smoke 211 → 212 (+1: T89s). Tools 93 unchanged. chat-ui 364 → 369
(+5: 4 verdictParser + 3 agentRunner.iterative + 2 effortConfig
extensions; rebalanced to 369 net).

Behind cycle9_enabled flag (default false). When off, M2 changes
are inert. When on, every prepare_* gets verification_brief; critic
runs on Effort ≥ high; iterative-loop retry budget enforced via
`useStreams.verdictRetries`.

## Cycle 9 — M1: Discovery primitives + hard validation gates (2026-05-08)

Replaced the 60-line verbatim variance-report SQL template + 30-line
Report.javascript example with two new discovery tools:

- `get_form_prefill_capabilities(doctype)` — returns the live `_lz_items`
  whitelist (parent fields + item-row fields + URL pattern) read from
  install.py module-level constants. Single source of truth.
- `get_doctype_relationships(doctype)` — wraps describe_doctype with
  curated row-link hints for ERPNext's most-mismatched pairs (PR↔PI,
  SO↔SI, SLE↔PR, PR↔PO, SI↔DN). Surfaces the canonical join warnings
  that previously lived in the prompt as verbatim text.

Universal `_validate_prepare_payload` runs at staging time on every
`prepare_*` tool when `cycle9_enabled = true`. Catches:
- Unknown fields with did-you-mean suggestions (difflib).
- Unknown Link targets with search_link hints.
- External URLs in Query Report HTML cells.
- Malformed `_lz_items` base64 in URL params.
- Non-whitelisted keys in `_lz_items` payloads.

Wired into 14 of 18 typed prepare_create_* wrappers + prepare_update_doc.
The 4 skipped wrappers (kb / email_group / email_account / number_card)
have arg-name vs Frappe-field mismatches that would break existing tests
if validated naively — deferred for follow-up.

Feature-flagged: `Lazychat Settings.cycle9_enabled` (default false).
When off, M1 changes are inert except the prompt slim — that's a one-way
change.

Smoke 195 → 204 (+9 new T cases: T89a-T89k). Tools 91 → 93 (+2). chat-ui
360/360 (no change — server-side cycle).

Prompt slim: claude_bridge.py dropped 167 lines (~19% character
reduction); routerSystemPrompt.ts dropped 1 line (~7.8% character
reduction — its content was already condensed bullets, not multi-line
fences).

## Cycle 8c — Panel-shim grayscale filter for `pushTheme` (2026-05-08)

Companion to lazychat.ai "Cycle 8c". Frappe's dark theme sets `--primary-color` to gray-900 (`#171717`); pushing this as the chat-ui brand accent rendered everything near-black. The shim's [`pushTheme()`](lazychat_erpnext/public/js/lazychat_panel.bundle.js) now calls a new `isGrayscale(color)` helper (R≈G≈B within 12 units) and skips the `setThemeTokens` push when the resolved primary is grayscale. Logs `[lazychat] skipped pushing grayscale primary: <hex>` for triage. The chat-ui side has matching defense-in-depth in [`extensions.ts`](../lazychat.ai/apps/chat-ui/src/store/extensions.ts) that filters grayscale tokens at `setThemeTokens` and `onRehydrateStorage` time. End result: in dark mode, chat-ui's own warm-orange `--color-primary` default (`#d97757` from theme.css) shows through instead of Frappe's UI-color near-black. Distinct host brand colors (purples, blues, custom hues) pass through unchanged.

Manual test: set Frappe theme primary, switch Desk to dark mode, hard-reload Desk → chat-panel accent dots / Apply pills / focus rings should be warm orange (chat-ui default), NOT near-black. DevTools → Application → Local Storage → `lazychat:extensions:v1` → `state.themeTokens` should be `{}` (the grayscale token was correctly filtered out).

## Cycle 8 — Real Modes + Effort backend (2026-05-08)

The Cycle-1 ModesPanel radios + 4-step Effort dot scale in chat-ui became real working features. See `../lazychat.ai/CLAUDE.md` "Cycle 8" for the chat-ui half. Backend half ships in [`api.py`](lazychat_erpnext/desk_assistant/api.py) + [`claude_bridge.py`](lazychat_erpnext/desk_assistant/claude_bridge.py) — pure additive, zero regression to the 154 in-process / 91 HTTP-wire smoke gates.

### Passthrough kwargs

`send_message_stream(...)` accepts three new keyword args (all optional, defaults preserve pre-Cycle-8 behavior):
- `mode: str = "edit-auto"` — clamped to `{ask, edit-auto, plan, auto}`; falls back to `edit-auto` on unknown.
- `effort: str = "medium"` — clamped to `{low, medium, high, max}`; falls back to `medium`.
- `plan_resumed: bool = False` — set by chat-ui when continuing after the user clicked Approve on a Plan card; suppresses the PLAN_MODE_BLOCK on the resumed turn.

`run_agentic_turn(..., mode, effort, plan_resumed)` reads these and routes them:

### `EFFORT_MAP` ([claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py))

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

- `bench --site erp.local execute lazychat_erpnext._smoke.run` → 154/0/2 (no regression on existing flows; defaults preserve pre-Cycle-8 behavior).
- `python3 lazychat-erpnext/test/curl_smoke.py` → 91/91 tools registered+called.
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

**`run_sql_select`** ([tools.py](lazychat_erpnext/desk_assistant/tools.py))
- Auto-executes SELECT (or `WITH ... SELECT`) SQL and returns rows in the
  same tool result. No /commit, no Apply card, no preview_token.
- Same security envelope as `prepare_run_sql`:
  1. site_config `lazychat_allow_dangerous_tools=true`
  2. caller has System Manager role
  3. `_validate_select_sql` regex (rejects DML/DDL keywords + multi-statement)
- Same `_wrap_db_error` structured-hint response on failure.
- Row cap 200 default, 1000 max.

**`run_python_readonly`** ([tools.py](lazychat_erpnext/desk_assistant/tools.py))
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

System prompt in [claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py)
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

## Variance-report buttons round 2 — full auto-fill + signature-reapply + report-level button (2026-05-08)

User's repeated complaint: "click button to create new doc — still not able to pass all details". Three concrete failures uncovered after the round-1 ship:

**Failure A — Make Return clobber race.** When `return_against=<PI>` is set on a new Purchase Invoice, ERPNext's Make Return logic auto-fetches ALL items from the original PI and overwrites the items table — clobbering the `_lz_items` payload our helper had just injected. The original helper exited early on its `_alreadyApplied` flag, so the post-clobber items stayed as the auto-fetched original (every line, full qty, full rate) instead of the variance line we wanted.

**Failure B — missing parent fields in URL.** Canonical template only set `is_return` + `return_against` + `_lz_items`. It never explicitly set `supplier` — relying on `return_against` auto-fetch to pull supplier. Async race; supplier sometimes blank on save.

**Failure C — no top-right report button.** User asked for a "Debit Note" button in the report's top-right (in addition to per-row Qty/Rate buttons) for bulk processing. Frappe's `Report.javascript` field DOES support this for non-standard reports (`frappe.query_reports[<name>] = { onload: function(report) { report.page.add_inner_button(...) } }`), but the typed wrapper didn't accept a `javascript` arg.

### Fix A — signature-based reapply in form helper

Rewrote [`install.py:_LAZYCHAT_FORM_HELPER_SCRIPT`](lazychat_erpnext/install.py). Removed the `_alreadyApplied` flag. New `_sig(rows)` and `_frmSig(items)` compute a stable item-signature (`item_code|qty|rate|pr_detail`). On every `refresh` event, if the signatures don't match, the helper clears `frm.doc.items` and re-injects from `_lz_items`. Result: even if Frappe's Make Return logic clobbers our items 100ms after we set them, the next `refresh` (which Frappe fires after Make Return settles) re-applies the lazychat payload. Also bound to `return_against` / `supplier` / `customer` change events with a `setTimeout(50)` deferral to win the auto-fetch race.

### Fix B — explicit supplier + richer item data + per-row Combined button

Updated canonical SQL template in [claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py). Each button URL now carries `&supplier=<value>` parent param explicitly. `_lz_items` payload encodes `item_code`, `item_name`, `description`, `qty`, `rate`, `uom`, `pr_detail`, `purchase_receipt`, `purchase_invoice`, `purchase_invoice_item` per row — full traceability back to the original receipt + invoice line. Added a third per-row "Combined DN" button when both qty and rate differ; its `_lz_items` is a 2-element array (qty-variance row + rate-variance row at received qty). Stale single-button-per-row template removed from prompt.

Helper script's `PARENT_WHITELIST` covers `supplier`, `customer`, `is_return`, `return_against`, `posting_date`, `due_date`, `set_warehouse`, `company`, `cost_center`, `project`, `currency`. `ITEM_WHITELIST` extended to: `item_code`, `item_name`, `description`, `qty`, `rate`, `amount`, `uom`, `stock_uom`, `conversion_factor`, `warehouse`, `cost_center`, `expense_account`, `income_account`, `project`, `tax_rate`, plus reference back-links `purchase_receipt`, `pr_detail`, `purchase_invoice`, `purchase_invoice_item`, `sales_order`, `so_detail`, `sales_invoice`, `sales_invoice_item`, `delivery_note`, `dn_detail`.

### Fix C — top-right report button via `Report.javascript`

`prepare_create_report` ([tools.py](lazychat_erpnext/desk_assistant/tools.py)) now accepts an optional `javascript` arg for `Query Report` / `Script Report`. At commit, it's persisted to the Report doc's `javascript` field. Frappe loads this on report open for non-standard reports (it's how `frappe.query_reports[<name>] = { onload: ... }` gets registered). Schema description in [tool_schemas.py](lazychat_erpnext/desk_assistant/tool_schemas.py) walks the LLM through the canonical pattern (filter `report.data` to rows with both diffs, build `_lz_items` from row fieldnames, base64-encode, `window.open(/app/purchase-invoice/new?...)`). Prompt block in [claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py) shows a verbatim button-handler example.

### Smoke

[scripts/smoke-test-tools.py](scripts/smoke-test-tools.py): T88z (`prepare_create_report` accepts `javascript` arg), T88aa (form helper body contains `_sig`/`_frmSig`/`PARENT_WHITELIST`/`ITEM_WHITELIST`/supplier handling). 193 in-process / 91 HTTP-wire / 360 chat-ui all green (was 191/91/360 → +2).

End-to-end: variance-report buttons now produce URLs with `?is_return=1&supplier=<sup>&return_against=<PI>&_lz_items=<b64>`. Click → new PI form opens, Frappe sets parent fields, Make Return auto-fetches items (race), our helper detects clobber via signature mismatch on the `refresh` event, clears + re-applies our specific variance row(s) with full back-links and item metadata. User can review and Save without manual entry.

## Client Script auto-name + persistent form-helper for variance-report buttons (2026-05-08)

Two paired fixes for the recurring "click Debit Note button → empty Items table → GST HSN error" failure mode in the canonical PR-vs-PI variance flow.

**Bug 1 — `prepare_create_client_script` "Please set the document name"**: Frappe's Client Script doctype uses `autoname: Prompt`, which requires explicit `name` at insert time. The wrapper schema said "auto-names if omitted" (wrong) and the commit handler accepted a name-less payload, producing `frappe.exceptions.MandatoryError: Please set the document name`. Real-user trigger: the LLM tried to install a per-report Client Script for items prefill; both attempts failed.

Fix in [tools.py](lazychat_erpnext/desk_assistant/tools.py): `prepare_create_client_script` now auto-derives `name = "<DocType> <View> (lazychat <6char-hash>)"` when omitted (deterministic on the script body so re-staging the same script collides cleanly), with a `(2)`/`(3)` collision-suffix loop. Schema description in [tool_schemas.py](lazychat_erpnext/desk_assistant/tool_schemas.py) corrected to spell out the autoname=Prompt requirement.

**Bug 2 — Items child table can't be set via URL params**: Frappe's new-form route handler reads URL params for parent fields only — `?items[0][item_code]=...` is silently ignored. The variance report's "Debit Note ↗" button was correctly setting `is_return=1`, `return_against`, and `supplier`, but the Items child table stayed empty → user got "GST HSN Code is mandatory for Overseas Purchase Invoice" the moment they tried to save. This is a hard platform limitation; URL-only prefill cannot reach child rows.

Fix: ship a persistent helper Client Script via `install.py` `seed_lazychat_form_helpers()`. Seeded at both `after_install` and `after_migrate` (idempotent — rewrites only when body differs). One Client Script per target doctype: `Purchase Invoice`, `Sales Invoice`, `Purchase Receipt`, `Delivery Note`. Each script reads `_lz_items` (URL-safe base64-encoded JSON array) on `onload_post_render` + `refresh`, populates `frm.doc.items` with whitelisted fields (`item_code`, `qty`, `rate`, `amount`, `uom`, `warehouse`, `purchase_receipt`, `pr_detail`, `sales_order`, `so_detail`, `description`), and triggers ERPNext's `item_code` handler so taxes/HSN/UOM auto-fill. Defense rules:
- Only fills when items table is empty — never clobbers user edits.
- Whitelist keys only — LLM cannot inject arbitrary doc fields.
- Sets `is_return=1` and `return_against=<value>` from URL params only when not already set.
- Idempotent flag (`frm.__lz_helper_applied`) prevents double-fill on `refresh` re-fires.

System prompt in [claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py) + chat-ui mirror in [routerSystemPrompt.ts](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts) teach the LLM the URL convention and update the canonical variance-report SQL template to embed `&_lz_items=<TO_BASE64(JSON)>` per button. Explicit "DO NOT generate per-report Client Scripts — the persistent helper already handles this" rule prevents the LLM from re-discovering the broken auto-author pattern.

**Smoke** ([scripts/smoke-test-tools.py](scripts/smoke-test-tools.py)): T88w (auto-derived name pattern), T88x (explicit name passes through), T88y (all 4 helper scripts installed + enabled + dt-correct + script body contains `_lz_items`). 191 in-process / 91 HTTP-wire / 360 chat-ui all green (was 188/91/360 → +3 in-process).

End-to-end: variance report renders Debit Note buttons whose URLs encode the line-item delta. Clicking lands on `/app/purchase-invoice/new` with `is_return=1` + `return_against` set (parent fields, native Frappe path) AND the items table prefilled by the helper script. The user can review and Save without hitting HSN-mandatory or empty-items errors.

## Real-execution probe for Query Report SELECT at preview time (2026-05-08)

User's complaint after multiple report-failure replays: *"can't we have something to check directly DB query so we'll be 100% confident on output?"* — every prior gate (`_validate_select_sql` regex, `_probe_select_sql_explain`) accepted queries that EXPLAIN parses cleanly but execution rejects, OR that produce wrong-shaped data with no error at all.

**New 3rd-layer gate** in [tools.py](lazychat_erpnext/desk_assistant/tools.py): `_probe_select_sql_execute(query, sample_size=5, timeout_sec=8)`. Wraps the LLM-supplied SELECT in `SELECT * FROM (<query>) AS _lz_probe LIMIT N` and runs it under a `SET STATEMENT MAX_STATEMENT_TIME=8 FOR ...` server-side statement timeout. Reuses `_strip_leading_sql_comments` + `_SQL_PLACEHOLDER_RE` + `_wrap_db_error` from the EXPLAIN probe. Returns `{ok: True, rows, columns, row_count_capped}` on success or `{ok: False, error, hint}` with a timeout-specific hint when MariaDB raises codes 1969/3024.

Wired into both:
- `prepare_create_report` Query Report branch — runs after the EXPLAIN probe, blocks staging on failure, captures `sample_rows` + `sample_columns` into the preview response.
- `commit_prepared_action` create_report path — re-runs at commit (sample_size=1) so a stale/altered token can't ship a query that fails at report-open time.

The preview response now includes `sample_rows` / `sample_columns` / `sample_truncated` keys (Query Report only — empty for other types). The chat-ui's Apply card renders these as a compact table; see sibling repo's [`Cycle 8g` section](../lazychat.ai/CLAUDE.md) for the visual rendering.

**Smoke** ([scripts/smoke-test-tools.py](scripts/smoke-test-tools.py)): T88s (happy path — sample_rows + sample_columns include "name"), T88t (probe runs runtime queries without crashing), T88v (sample_columns matches SELECT aliases and `rows[0].keys()`). 188 in-process / 91 HTTP-wire all green (was 185 → +3).

End-to-end: stages a Query Report with the canonical PR↔PI variance template → preview returns 5 sample rows → user/Apply card displays them → commit succeeds → `query-report` route renders all 6,882 rows.

## prepare_update_doc redirects to typed-create wrapper on non-existent target (2026-05-08)

Stale-state regression — multi-turn chat where the LLM "remembered" creating a Report we'd deleted between sessions. LLM called `prepare_update_doc({doctype:'Report', name:'X'})`, the doc didn't exist, the wrapper returned a bare `"X not found"` error, and the LLM hallucinated **"Perfect! I've updated..."** in its narration anyway (TOOL-ERROR HONESTY rule isn't bullet-proof against model drift).

**Fix** — `prepare_update_doc` now does an existence pre-check at preview time. On miss, returns a structured hint that explicitly redirects to the typed CREATE wrapper:

```
{dt} 'X' does not exist. To create a NEW {dt}, use the typed wrapper '{prepare_create_report}' (prepare_update_doc only modifies an existing doc). If you previously thought you created this doc, the create may have failed silently — check the chat for a Failed Apply card before assuming it exists.
```

For doctypes without a typed wrapper, the hint nudges toward `prepare_create_doc`. Either way the LLM has an actionable next step instead of an opaque "not found".

**Smoke** (T88r in [scripts/smoke-test-tools.py](scripts/smoke-test-tools.py)): `prepare_update_doc({doctype:'Report', name:'_lz_smoke_does_not_exist_xyz'})` returns an error containing both "does not exist" and "prepare_create_report". 185 in-process / 91 HTTP-wire all green.

End-to-end probe (`PR vs PI Variance Probe`): canonical SQL template stages → commits → opens at `/app/query-report/<name>` → returns **6,882 rows** with all 11 columns including HTML link buttons. Pipeline confirmed sound.

## Query/Script Report URL routing fix — `/app/query-report/<name>` (2026-05-08)

Production bug: clicking the post-Apply "Open Report →" button on a created Query Report (or Script Report) opened `/app/report/<name>`, which Frappe's router treats as Report Builder only — landed the user on **"Sorry! I could not find what you were looking for"** (and triggered a `TypeError: getdoctype() missing 1 required positional argument: 'doctype'` in the backend trace).

**Cause** — two paths in [tools.py](lazychat_erpnext/desk_assistant/tools.py) generated the wrong URL for Query/Script Reports:
1. `prepare_create_report` preview `open_url` (line ~2803): used `/app/query-report/` for Query Reports but `/app/report/` for Script Reports — but Frappe routes Script Reports at `/app/query-report/` too. Only Report Builder reports use `/app/report/<name>`.
2. `commit_prepared_action` response `link` (line ~4928): used the generic `f"/app/{frappe.scrub(doc.doctype)}/{doc.name}"` pattern, which produces `/app/report/<name>` for any Report doc regardless of `report_type`.

**Fix** — both paths now special-case the Report doctype:
- Preview: `if report_type == "Report Builder" → /app/report/{name}` else `/app/query-report/{name}`. Covers Query Report AND Script Report.
- Commit: same logic on the doc's `report_type` attribute, falls back to the generic scrub pattern for non-Report doctypes (unchanged behavior).

**Smoke** (T88p, T88q in [scripts/smoke-test-tools.py](scripts/smoke-test-tools.py)): preview `open_url` for Query Report AND Script Report both start with `/app/query-report/`. 184 in-process / 91 HTTP-wire / 355 chat-ui all green.

Real-user trigger 2026-05-08: replays of "report with debit-note option per line item" prompt produced reports the LLM thought were saved correctly, but clicking Open dead-ended at the not-found page. Now clicking Open lands on the actual report.

## Canonical PR↔PI variance-report SQL template in system prompt (2026-05-08)

After the alias-redirect + linkage-knowledge fix landed, the LLM correctly used `pii.pr_detail = pri.name` BUT still produced reports with: (a) loose `WHERE` filter that matched non-variance rows, (b) missing `pi.docstatus = 1`, (c) un-COALESCE'd NULL receipts producing dropouts, (d) overflowing button labels visibly truncated to "Create Debit Note (Q". User shot this in the foot 5+ times running the same prompt.

**Fix** — added a verbatim **canonical Query Report SQL template** to `_system_prompt` in [claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py) under CHILD-TABLE LINKS, plus 5 explicit quality rules:
1. Filter to actual variances: `WHERE (pii.qty <> COALESCE(pri.qty, 0) OR pii.rate <> COALESCE(pri.rate, 0))`.
2. `pi.docstatus = 1` on the parent invoice — never include drafts.
3. `COALESCE(pri.X, 0)` on every receipt-side reference — services/direct-invoice items have NULL pri.* and naive arithmetic drops them out.
4. Short button labels (≤12 chars: "Debit Note ↗") — Frappe Query Report columns auto-size to content; long labels visibly truncate.
5. Empty string `''` for the non-action ELSE branch (cleaner than `'-'` on button columns).

The chat-ui [routerSystemPrompt.ts](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts) gets a condensed mirror of the 5 rules under the existing PR↔PI section.

Pure prompt addition, no code/schema/test churn. 182 in-process / 91 HTTP-wire / 355 chat-ui all green. Bad reports deleted from the bench.

## Debit/Credit Note alias redirect + PR↔PI item-linkage in prompt (2026-05-08)

Real-user replay of the canonical "report with debit-note option per line item" prompt produced a broken Query Report: receipt_qty / qty_variance / create_dn_qty / receipt_rate / rate_variance / create_dn_rate columns all blank or `-`. AND the chat showed `describe_doctype({"doctype":"Debit Note"}) Failed after 36ms: {"error": "invalid doctype"}` mid-turn.

Two LLM-knowledge gaps, both fixed at the data layer + prompt layer:

### Gap 1 — "Debit Note" / "Credit Note" aren't doctypes

ERPNext has no separate `Debit Note` doctype. A debit note is a Purchase Invoice with `is_return=1` and `return_against=<original PI name>` (analogously, Credit Note ≡ Sales Invoice with `is_return=1`). The LLM doesn't know this and bounces off `invalid doctype` repeatedly.

**Fix** — new `_DOCTYPE_ALIASES` constant in [tools.py](lazychat_erpnext/desk_assistant/tools.py) + `describe_doctype` returns a structured redirect when the requested doctype is one of: `Debit Note`, `Credit Note`, `Purchase Return`, `Sales Return`. Response shape: `{"error": "invalid doctype", "redirect": "Purchase Invoice", "hint": "Debit Note is NOT a separate doctype ... use prepare_create_doc({doctype:'Purchase Invoice', values:{is_return:1, return_against:'<PI-name>', ...}}) ..."}`. Lookup is case-insensitive (`.title()` normalization). Unknown doctypes still get the bare `invalid doctype` — no false-positive aliasing.

### Gap 2 — wrong PR↔PI row linkage produces blank columns

The user's deployed report joined on `pri.purchase_invoice = pii.parent AND pri.item_code = pii.item_code`. Both fields exist but the join is wrong:
- `Purchase Receipt Item.purchase_invoice` is sparsely populated (only set when PR was created from PI; most receipts come first, no back-ref).
- Joining by `item_code` alone matches across receipts, producing Cartesian/wrong rows.

**Canonical row-to-row link**: `Purchase Invoice Item.pr_detail` → `Purchase Receipt Item.name` (or equivalently `Purchase Receipt Item.purchase_invoice_item` → `Purchase Invoice Item.name`).

**Fix** — system prompt addition in [claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py) and chat-ui mirror in [routerSystemPrompt.ts](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts). Two new blocks under `CHILD-TABLE LINKS`:
- **ITEM-LEVEL PR↔PI LINKAGE**: explicit table of the four directional links + canonical join pattern + explicit "DO NOT join on item_code alone" / "DO NOT rely on pri.purchase_invoice alone" warnings.
- **DEBIT NOTE / CREDIT NOTE**: spell out the `is_return=1` flag + URL pattern for HTML link buttons (`/app/purchase-invoice/new?is_return=1&return_against=<PI-name>`) + explicit "NEVER call describe_doctype('Debit Note')" rule (it returns the redirect hint anyway, but better to skip it).

### Tests (4 new, in-process)

[scripts/smoke-test-tools.py](scripts/smoke-test-tools.py): T88l (Debit Note → Purchase Invoice redirect with `is_return` in hint), T88m (Credit Note → Sales Invoice), T88n (case-insensitive: "debit note" lowercase still redirects), T88o (genuinely unknown doctype gets bare `invalid doctype` with no false-positive `redirect`/`hint`).

Suite: 178 → **182** in-process. 91 HTTP-wire / 355 chat-ui unchanged (no chat-ui code change — the prompt itself is what teaches the LLM).

Manual replay verification: replay the user's prompt; LLM (a) doesn't bounce off `Debit Note` lookups, (b) joins PI items to PR items via `pii.pr_detail = pri.name`, (c) populated receipt columns are now non-blank.

## MariaDB LIMIT-in-IN guard + EXPLAIN-probe 1235 surfacing (2026-05-08)

Real-user replay of "report with debit-note option per line item" prompt: LLM staged a Query Report whose JOIN's `ON` clause used `pri.parent IN (SELECT DISTINCT prci.parent FROM ... WHERE ... LIMIT 1)`. Preview-time gates (`_validate_select_sql` regex + `_probe_select_sql_explain`) accepted it. Opening the report → `pymysql.err.NotSupportedError: (1235, "This version of MariaDB doesn't yet support 'LIMIT & IN/ALL/ANY/SOME subquery'")`.

Two-layer fix in [tools.py](lazychat_erpnext/desk_assistant/tools.py):

**Layer 1 — static regex** in `_validate_select_sql` after the string-literal stripper. Matches `\b(IN|ANY|ALL|SOME)\s*\(\s*SELECT\b[^()]*\bLIMIT\b` against the defanged SQL. Rejects with: *"MariaDB does not support LIMIT inside IN/ANY/ALL/SOME subqueries (NotSupportedError 1235). Rewrite using a JOIN on a derived table: `SELECT a.* FROM tabA a JOIN (SELECT name FROM tabB LIMIT N) b ON a.name = b.name`."*

**Layer 2 — `_wrap_db_error` classifies 1235 as `syntax`**. Direct `mariadb -e EXPLAIN ...` against the offending SQL DOES raise 1235 — but the probe at [_probe_select_sql_explain](lazychat_erpnext/desk_assistant/tools.py) only re-raises `error_kind in ("schema", "syntax")`. Without classification, the probe silently swallowed `NotSupportedError(1235)` (`error_kind: "other"` → `return None`). Now `_wrap_db_error` detects `"1235"` in the message OR the textual pattern `"LIMIT" + ("IN/ALL/ANY/SOME" or "subquery")` and returns the same JOIN-rewrite hint with `error_kind: "syntax"`. The probe surfaces it; the LLM sees the actionable message at preview.

This catches subquery shapes the static regex misses (e.g. nested derived tables) — defense in depth.

Smoke ([scripts/smoke-test-tools.py](scripts/smoke-test-tools.py)): T88j (regex rejects `IN (SELECT ... LIMIT 1)` at preview), T88k (`_wrap_db_error` returns `error_kind: "syntax"` + rewrite hint for synthesized `(1235, ...)` exception). 178 in-process / 91 HTTP-wire all green (was 176 → +2).

## SQL string-literal-aware DML/DDL validator (2026-05-08)

Companion to the Script-Report safe_exec validation below. The user's "report with debit-note buttons" prompt was hitting a separate validator bug: `_validate_select_sql`'s DML/DDL regex `\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|...)\b` matched `Create` inside `CONCAT('<a class="btn">Create DN</a>')`, rejecting legitimate Query Reports with HTML link columns. The LLM kept falling back to Script Report as a workaround.

Fix ([tools.py](lazychat_erpnext/desk_assistant/tools.py)): new `_strip_sql_string_literals(sql)` helper replaces single-quoted string contents with empty literals (`''`) before applying the DML regex. Handles SQL's single-quote-doubling escape (`'It''s ok'` is one literal). Backtick identifiers are NOT stripped (legitimately can't carry DML keywords as values; LLM uses backticks for table names). The original SQL still flows to EXPLAIN unmodified.

Smoke ([scripts/smoke-test-tools.py](scripts/smoke-test-tools.py)): T88f (`Create` inside `CONCAT(...)` accepted), T88g (`UPDATE/DELETE/DROP` inside string accepted), T88h (real `DROP TABLE` still rejected — caught by SELECT-prefix check), T88i (multi-statement still rejected). 176 in-process / 91 HTTP-wire all green (was 172 → +4).

Manual evidence ([test/evidence/2026-05-08-tour/07-query-report-with-html-buttons-applied.jpeg](test/evidence/2026-05-08-tour/07-query-report-with-html-buttons-applied.jpeg)): replayed user's "i need a report with debit note create option..." prompt. LLM staged a **Query Report** named "Purchase Receipt vs Invoice Reconciliation" with proper `CONCAT('<a class="btn btn-xs btn-primary" href="/app/purchase-invoice/new?...&is_return=1">Create Debit Note</a>')` for both qty and rate variances. Apply card → Applied · create_report + prominent **Open Report →** button. Zero `/commit TOKEN` visible. Zero hallucination loop. The Script Report fallback is no longer needed for this canonical flow.

## Script-Report safe_exec validation + auto-open + commit-leak scrub (2026-05-08)

Real-user transcript triage: LLM staged `prepare_create_report({report_type:"Script Report", script:"import frappe\n..."})`. AST passed (syntax ok, `def execute` defined). Report shipped. User opened it → `Loading...` forever. Backend trace: `ImportError: __import__ not found` on line 1. Frappe's `safe_exec` (RestrictedPython + FrappeTransformer) blocks ALL imports — `frappe`, `_`, `json` are pre-injected as globals; `import frappe` fails before `execute()` runs. Same Cycle-6 hallucination shape (Apply succeeded → user opened → broken).

Three-pillar fix:

**Pillar 1 — `_validate_script_report_body` ([tools.py](lazychat_erpnext/desk_assistant/tools.py)):** new AST validator runs at preview time, rejects: top-level `import` / `from ... import` (FORBIDDEN under safe_exec); calls to `__import__`, `compile`, `exec`, `eval`, `open`, `input`, `breakpoint`; write-side `frappe.db.{set_value, set_many, delete, sql_ddl, multisql, commit, rollback, savepoint, release_savepoint}`; side-effect `frappe.{sendmail, publish_realtime, publish_progress, enqueue, enqueue_doc, delete_doc, rename_doc, copy_doc}`. Each rejection returns an actionable hint pointing at the `safe_exec` rule and the canonical alternative (e.g. "Use `frappe.db.get_list` or `frappe.qb` for queries"). After AST passes, defense-in-depth: actually runs `frappe.utils.safe_exec.safe_exec(script, None, {filters: {}, data: None, result: None}, script_filename="lazychat-preview-probe")` to catch runtime errors AST can't see. Wrapped in try/except so safe_exec import failure degrades gracefully. Schema description in [tool_schemas.py](lazychat_erpnext/desk_assistant/tool_schemas.py) rewritten to spell out the rules + canonical pattern verbatim — schema descriptions are visible to the LLM via `tools/list`, the most direct way to teach it. System prompt ([claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py)) now explicitly steers the LLM toward Query Report with HTML link columns when buttons are needed; Script Report only when Python is genuinely required.

**Pillar 2 — Post-Apply UX (chat-ui):** [MCPPreviewActionCard.tsx](../lazychat.ai/apps/chat-ui/src/components/messages/MCPPreviewActionCard.tsx) + [commitSlash.ts](../lazychat.ai/apps/chat-ui/src/lib/commitSlash.ts) — new `AUTO_OPEN_AFTER_APPLY` whitelist (create_report, create_dashboard, create_kb, create_calendar_event, create_note, create_print_format) auto-opens the result URL in a new tab on commit success via `postToHost(navigateDesk { openInNewTab: true })` (or `window.open` fallback). The previously-tiny "Open Report/<name>" link replaced with a prominent styled button: bordered, hover-accent, `target="_blank"`, "Open Report →" with `ACTION_TO_LABEL` mapping for human doctype names. Best-effort auto-open + always-available prominent button = both layers user requested.

**Pillar 3 — `/commit` leak scrub (chat-ui):** new `scrubCommitLeak(text)` exported helper in [agent.ts](../lazychat.ai/apps/chat-ui/src/lib/agent.ts) regex-strips lines containing `/commit <8+ chars>` (with or without "Reply with " prefix). Applied at all `cb.onDone` finalization points (`_runCore` non-streaming + streaming + `_streamToolTurn` MCP path). Defense-in-depth against the system-prompt rule: even when a model regresses and emits "Reply with /commit dx4VAVRntky38tCnPXCCqg", the user never sees it. Token may flash during streaming but the final `done`/`narration` message renders scrubbed. System prompt ([claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py) + [routerSystemPrompt.ts](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts)) also strengthened with **CRITICAL COMMIT-INSTRUCTION FORBIDDEN** block.

Smoke ([scripts/smoke-test-tools.py](scripts/smoke-test-tools.py)): T88a (rejects `import frappe`), T88b (rejects `from frappe import _`), T88c (rejects `frappe.db.set_value`), T88d (rejects `__import__`), T88e (happy path — clean `def execute(filters=None)` with `frappe.db.get_list`). Updated `prepare_create_doc` fixture to use ToDo (no typed wrapper) instead of Note. **172 in-process / 91 HTTP-wire / 345 chat-ui all green** (was 167/91/336 → +5 + 0 + +9 new tests).

Manual verification: replayed user's exact "i need a report with debit note create option..." prompt. LLM tried Query Report twice (both rejected by `_validate_select_sql` "DML/DDL" regex — false positive on `Create` substring inside HTML link content; documented as a known follow-up — see "Out of scope" below). Pivoted to Script Report; wrote a clean body with NO imports (passed AST validator + safe_exec dry-run); Apply card rendered cleanly; clicking Apply transitioned to "Applied" badge + prominent "Open Report →" button (`/app/report/Receipt%20vs%20Invoice%20Variance%20with%20Debit%20Note`, target=_blank). Zero `/commit TOKEN` visible in chat. Evidence: [test/evidence/2026-05-08-tour/05-script-report-validated-no-commit-leak.jpeg](test/evidence/2026-05-08-tour/05-script-report-validated-no-commit-leak.jpeg) + [06-applied-with-open-report-button.jpeg](test/evidence/2026-05-08-tour/06-applied-with-open-report-button.jpeg).

**Known follow-up (out of scope this round):** `_validate_select_sql`'s DML/DDL regex matches keywords inside SQL string literals (e.g. `CONCAT('<a class="btn">Create DN</a>')` rejected because `Create` matches `\bCREATE\b`). Should tokenize SQL or strip string literals before regex matching. Until then, the LLM falls back to Script Report (which now validates cleanly thanks to Pillar 1).

## Block generic `prepare_create_doc` for typed-wrapper doctypes (2026-05-08)

Production triage from real chat transcript: LLM bypassed `prepare_create_report` and called `prepare_create_doc({doctype:"Report", values:{javascript:"..."}})`, got `IntegrityError 1062` (duplicate name), narrated success anyway, sent user to a dead Apply card. Same shape across multiple doctypes.

Fix ([tools.py](lazychat_erpnext/desk_assistant/tools.py)): new `_TYPED_WRAPPER_FOR_DOCTYPE` map covers Report, Custom Field, Client Script, Notification, Print Format, Email Template/Group/Account, Newsletter, Assignment Rule, Auto Email Report, Auto Repeat, Milestone Tracker, Number Card, Dashboard, Knowledge Base, Note, Event, Scheduled Job Type. `prepare_create_doc` now refuses for these and returns `"Use the typed wrapper '<name>' INSTEAD..."`. The LLM gets actionable redirect at preview time and uses the wrapper, which has actionable validation. Server Script deliberately stays on the generic path (no schema-able typed wrapper for arbitrary Python script bodies; gated by allow_dangerous_tools + System Manager).

Also added: **pre-flight duplicate detection** in `prepare_create_report`. `frappe.db.exists("Report", report_name)` runs at preview, returns "Report 'X' already exists. Use prepare_update_doc to modify..." instead of letting the LLM ship a duplicate that fails at commit-time IntegrityError 1062. Updated T5 + T85-T89 smoke cases to use typed wrappers (the path that's now enforced).

System prompt updated ([claude_bridge.py](lazychat_erpnext/desk_assistant/claude_bridge.py) + [routerSystemPrompt.ts](../lazychat.ai/apps/chat-ui/src/lib/routerSystemPrompt.ts)): TOOL-ERROR HONESTY rule explicitly forbids "Perfect! I've staged..." narration after a Failed card; if error says "Use typed wrapper X", retry IMMEDIATELY with that wrapper; if "already exists", switch to prepare_update_doc; ANTI-LOOP rule stops the third re-stage when the same error fires twice. Both the Frappe-LLM and chat-ui-LLM paths get this.

Smoke: T87h (prepare_create_doc rejects doctype=Report → redirect), T87i (×4: Custom Field / Client Script / Notification / Print Format → typed wrappers), T87j (prepare_create_report duplicate-name pre-detection). 167 in-process / 91 HTTP-wire / 336 chat-ui all green.

Manual evidence: [test/evidence/2026-05-08-tour/04-script-report-with-real-body-staged.jpeg](test/evidence/2026-05-08-tour/04-script-report-with-real-body-staged.jpeg) — replayed user's exact "i need a report with debit note create option..." prompt; LLM emitted `prepare_create_report({report_type:"Script Report", script:"def execute(filters=None):..."})` directly with a real Python body, Apply card + sticky chip rendered cleanly. Zero hallucination loop.

## Script Report `script` body required (2026-05-08)

Production bug observed in real chat transcript: LLM staged `prepare_create_report({report_type:"Script Report"})` with NO `script` arg → wrapper accepted → empty Report row created → user opened it → **blank page**. LLM had no way to know the body was empty so narrated "interactive buttons added" while nothing functional shipped. Same Cycle 6 hallucination shape, just for Script Reports.

Fix ([tools.py](lazychat_erpnext/desk_assistant/tools.py)): wrapper now requires non-empty `script` arg whenever `report_type=="Script Report"`. AST-validated for Python syntax + must contain `def execute` symbol. At commit, payload's script is persisted to the Report's `report_script` field with `script_type="Python"`. Tool schema updated ([tool_schemas.py](lazychat_erpnext/desk_assistant/tool_schemas.py)) so the model sees the requirement and either supplies a body or falls back to Query Report. Defense-in-depth re-check at commit too.

Smoke ([scripts/smoke-test-tools.py](scripts/smoke-test-tools.py)): T87e (missing body rejected), T87f (valid body stages), T87g (whitespace-only rejected). 161 in-process / 91 HTTP-wire still 100% green.

## EXPLAIN-probe for `prepare_create_report` Query Reports (2026-05-08)

Production bug: an LLM-staged Query Report with `FROM tabPurchase_Order` (underscored, fictional) passed the regex-only `_validate_select_sql` and shipped to disk. User clicked Apply → row stored → opened the report → 1146 "Table doesn't exist" with no recovery path. Same gap for unknown columns (1054).

Fix ([tools.py](lazychat_erpnext/desk_assistant/tools.py)): new `_probe_select_sql_explain(query)` runs `EXPLAIN <query>` against the live DB inside `prepare_create_report` (Query Report path), with `%(filter_name)s` placeholders substituted to `NULL` so legitimate parameterized reports pass. On schema/syntax failure, returns `_wrap_db_error`'s structured hint — LLM sees "Table `tabpurchase_order` doesn't exist. ERPNext doctype tables are `tab<Doctype Name>` (with the space, no underscore)…" in the same turn and re-stages. Permission/transient errors pass through (don't fail-close on DB locks). Same probe also runs at `commit_prepared` time as defense-in-depth (line ~4148 in `tools.py`).

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
   [tools.py:4048-4054](lazychat_erpnext/desk_assistant/tools.py),
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
  [`_validate_select_sql`](lazychat_erpnext/desk_assistant/tools.py).
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
  >>> from lazychat_erpnext.desk_assistant.tools import _wrap_db_error
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

### Iframe element tightening ([lazychat_panel.bundle.js:509-528](lazychat_erpnext/public/js/lazychat_panel.bundle.js))

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

- `^~ /assets/lazychat_erpnext/lazychat_dist/assets/` → `Cache-Control: public, max-age=31536000, immutable` (Vite's content-hash filenames make this safe).
- `= /assets/lazychat_erpnext/lazychat_dist/index.html` → `Cache-Control: no-cache, must-revalidate` + a strict CSP including `frame-ancestors`, `Permissions-Policy`, `Referrer-Policy`, `X-Content-Type-Options`. `frame-ancestors` value is a placeholder (`https://erp.example.com`); each operator must edit it.
- Both serve precompressed `.br` / `.gz` sidecars when the client supports them. Falls back to dynamic `gzip` for anything without a sidecar.
- Add either to the `nginx.conf` template (persists across `bench setup nginx`) or via `include /etc/nginx/conf.d/lazychat.conf` in the Frappe-generated server block.

**Once this nginx config is live**, the `?v=` cache-bust in [lazychat_panel.bundle.js:154-158](lazychat_erpnext/public/js/lazychat_panel.bundle.js) becomes redundant and can be deleted (the no-cache header on `index.html` does the revalidation; the immutable header on hashed assets does the long-term caching).

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
3. If task is "tune system prompt": [claude_bridge.py:27-60](lazychat_erpnext/desk_assistant/claude_bridge.py#L27)
4. If task is "iframe / panel UI changes": [public/js/lazychat_panel.bundle.js](lazychat_erpnext/public/js/lazychat_panel.bundle.js) + [public/css/lazychat_panel.css](lazychat_erpnext/public/css/lazychat_panel.css)
5. If task is "different LLM provider": Desk → LLM Provider doctype, no code change
6. If task is "deploy to a new ERPNext bench": `./scripts/deploy-local.sh` with `BENCH_ROOT` + `DEPLOY_SITE` env

## Sub-projects status

| # | Sub-project | Status |
|---|---|---|
| MCP wire | JSONRPC-over-HTTP MCP transport at `/api/method/lazychat_erpnext.desk_assistant.mcp.handle` (initialize / ping / tools/list / tools/call) — Claude Desktop and other MCP clients can connect via Frappe API key+secret; chat-ui's browser-LLM path also calls it. See [desk_assistant/mcp.py](lazychat_erpnext/desk_assistant/mcp.py). Smoke covered T52–T59. | **DONE** |
| Theme sync | `pushTheme()` reads Frappe's resolved theme mode → posts `setTheme`. Also posts `setThemeTokens` with ONLY `--color-primary` (brand accent). **Surface tokens (bg/fg/border) are intentionally NOT pushed** — `setThemeTokens` writes inline styles on `<html>` which override `[data-theme="dark"]` CSS rules, so pushing surface tokens locked the iframe's theme and prevented the user's dark/light toggle from working. Fixed 2026-05-05. `MutationObserver` on parent `<html data-theme>` re-pushes on Frappe desk theme toggle. | **DONE** |
| Route context | `deskRoute()` reads `cur_frm.doc` (name/doctype/title/workflow_state/status/dirty) on Form view + `cur_list.get_checked_items()` on List view. `_route_context_summary()` in `claude_bridge.py` prepends a briefing to the system prompt so the LLM auto-grounds "this doc" / "summarize" queries. Smoke covered T48–T51. | **DONE** |
| Lazychat Settings doctype | Single doctype at `/app/lazychat-settings` (System Manager edit) — 8 fields: enabled, iframe_base_url, iframe_query_params, chat_path (auto/browser/backend), mcp_endpoint, legacy_widget_enabled, allow_email, allow_dangerous_tools. Replaces site_config flag scattering; site_config still wins as advanced override. boot.py `get_lazychat_settings()` is the unified resolver. T60–T64 cover defaults, boot-extension shape, fallback behavior, validation, save_conversation. | **DONE** (commit 55b432f) |
| Browser-LLM path with tools | chat-ui (lazychat.ai repo) gained a JSONRPC MCP client — `mcp-client.ts` fetches tool defs from our wire endpoint and `agent.ts:runChatWithMcp` runs a **streaming** tool-use loop (`_streamToolTurn`) with the user's BYO LLM — text deltas stream in real time, tool_use blocks accumulate silently, `> _Got results, thinking…_` separator posted between rounds. `mcp-client.ts:mcpResultToText` caps tool results at **12,000 chars** to prevent context overflow. Empty final text and max-turns (8) both raise `cb.onError()` (not silent `cb.onDone()`). agentRunner does 3-way routing based on `chatPath` setting AND active model. See [lazychat.ai/CLAUDE.md](../lazychat.ai/CLAUDE.md) for the chat-ui side. | **DONE** (lazychat.ai db300ce + streaming update 2026-05-05; chat-ui dist bundled here) |
| save_conversation endpoint | `/api/method/lazychat_erpnext.desk_assistant.api.save_conversation` — chat-ui pushes turns from the browser-LLM path to `Claude Conversation` so admins have one unified history regardless of who orchestrated the LLM. T63 covers it. | **DONE** |
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

**Both paths share `tools.py` (101 tools, 1 implementation, 0 drift)**, both run with `frappe.session.user`'s permissions, both write to `Claude Conversation` (backend in `run_agentic_turn`; browser via `save_conversation`).

**Nothing is deprecated.** `LLM Provider`, `LLM Model`, `send_message_stream`, `run_agentic_turn`, `claude_bridge.py`, `providers/`, the legacy widget JS — all serve the backend path. Removing them would lose a real production deployment shape (org with shared keys).

## Commit conventions

- Conventional commits: `feat(scope): ...`, `fix(...)`, `chore(...)`, `test(...)`, `docs(...)`.
- **Never auto-commit. Never auto-push.** Wait for user to explicitly say "commit" / "push" / "ship".
- **Never** add `Co-Authored-By: Claude` trailer.
- macOS dev: `RESTART_BENCH=0` in `scripts/deploy.env` (no Supervisor locally → `bench restart` errors noisily).
