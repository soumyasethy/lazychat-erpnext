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

## Tool registry — 38 tools (all permission-scoped to `frappe.session.user`)

| Category | Tools |
|---|---|
| Discovery (3) | search_doctype, search_global, search_link |
| Basic reads (6) | get_list, get_doc, get_value, count_doc, describe_doctype, get_current_context |
| Relationships (1) | get_doctype_links |
| Workflow reads (2) | list_workflow_actions, get_pending_approvals |
| Analytics (5) | aggregate, get_sales_summary, dashboard_chart_data, number_card_value, list_user_dashboards |
| Reports (3) | list_reports, report_requirements, run_report |
| Files (1) | extract_file_content |
| ERPNext domain (6) | get_stock_balance, get_account_balance, get_outstanding, get_open_invoices, get_item_price, get_company_defaults |
| Mutations / Comms (9) | prepare_create_doc, prepare_update_doc, prepare_submit_doc, prepare_delete_doc, prepare_workflow_action, prepare_add_comment, prepare_assign_to, prepare_send_email, prepare_share_doc |
| Power tools (2, gated) | prepare_run_sql, prepare_run_python |

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

## site_config.json flags (all optional, all default safe)

| Flag | Default | What it does |
|---|---|---|
| `lazychat_panel_enabled` | `true` | Mount the slide-out at all |
| `lazychat_legacy_widget_enabled` | `false` | Show the OLD widget (off when lazychat is on) |
| `lazychat_iframe_src` | (bundled dist path) | Override iframe src — set to `http://127.0.0.1:5173/?frame=sidebar` for chat-ui HMR dev |
| `lazychat_allow_email` | `false` | Enable `prepare_send_email` |
| `lazychat_allow_dangerous_tools` | `false` | Enable `prepare_run_sql` + `prepare_run_python` (still gated by System Manager role + /commit) |

## API surface (whitelisted methods)

- `lazychat_mcp_erpnext.desk_assistant.api.send_message` — batch JSON `{conversation_id, events, usage}`
- `lazychat_mcp_erpnext.desk_assistant.api.send_message_stream` — SSE: `event: text_delta|tool_use|tool_result|usage|done|error`
- `lazychat_mcp_erpnext.desk_assistant.api.commit_prepared_action` — apply a staged action by token (NOT exposed to the LLM tool loop)
- `lazychat_mcp_erpnext.desk_assistant.api.list_models` — model picker data
- `lazychat_mcp_erpnext.desk_assistant.api.discover_remote_models` — fetch /models from a provider
- `lazychat_mcp_erpnext.desk_assistant.api.test_llm_provider_connection` — connection probe

## Doctypes

- `LLM Provider` — name, provider_type (anthropic | openai_compatible), base_url, api_key (Password), extra_headers, enabled
- `LLM Model` — model_label, provider Link, model_id, supports_tools, max_output_tokens, context_window, input_price_per_mtok, output_price_per_mtok, is_default, enabled
- `Claude Conversation` — user, title, history (JSON), last_model, total_input_tokens, total_output_tokens

Seed fixtures in [seed_data.json](lazychat_mcp_erpnext/lazychat_mcp_erpnext/seed_data.json) auto-load via `after_install` + `after_migrate`. Ships disabled-by-default rows for OpenAI/OpenRouter/NVIDIA/Vercel/LM Studio.

## Smoke test

```bash
cp lazychat-mcp-erpnext/scripts/smoke-test-tools.py <bench>/apps/lazychat_mcp_erpnext/lazychat_mcp_erpnext/_smoke.py
cd <bench>
bench --site <site> execute lazychat_mcp_erpnext._smoke.run
```

Currently asserts **53 cases** across all 38 tools against real ERPNext data:
- Reads (T1–T4, T19–T31, T34–T39): exercise every read tool against actual rows
- Mutations (T5–T8, T10–T13, T33, T40–T41): create + update + comment + assign + share + delete (each with cleanup)
- Workflow + analytics (T9, T14–T16): real Workflow Action / Dashboard Chart / Number Card
- Edge cases (T17–T18, T32): invalid token, unknown tool, gated email
- Power tools (T42–T47): rejection when flag off, execution when flag on (monkey-patched in test)
- Cleanup at end removes all created Comments / ToDos / Notes

When adding a new tool: add a corresponding T## case in `scripts/smoke-test-tools.py`, sync to bench (`cp`), re-run. Target = always 100% pass.

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

## Sub-projects deferred

| # | Sub-project | Status |
|---|---|---|
| MCP wire | Real MCP Streamable HTTP transport at `/api/method/lazychat_mcp_erpnext.mcp.handle` for external Claude Desktop / agent clients | not started |
| Theme sync | Push Frappe Desk theme tokens → lazychat via `setDesignTokens` so chat matches Desk colors | not started |
| Route context | `frappe.router.on('change')` → `setContext` postMessage → chat sees current Doctype/docname automatically | not started |
| Analytics extras | `analyze_business_data` (pandas-based) heavy analytics | deferred |
| Visualization mutations | `create_dashboard`, `create_dashboard_chart` specialized creators (vs the generic `prepare_create_doc`) | deferred |

## Commit conventions

- Conventional commits: `feat(scope): ...`, `fix(...)`, `chore(...)`, `test(...)`, `docs(...)`.
- **Never auto-commit. Never auto-push.** Wait for user to explicitly say "commit" / "push" / "ship".
- **Never** add `Co-Authored-By: Claude` trailer.
- macOS dev: `RESTART_BENCH=0` in `scripts/deploy.env` (no Supervisor locally → `bench restart` errors noisily).
