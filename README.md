# lazychat-mcp-erpnext

A **Frappe app** that drops a rich, multi-provider AI chat panel into the right side of your ERPNext desk. Built on top of the [lazychat-ai](https://github.com/soumyasethy/lazychat.ai) React UI embedded as a same-origin iframe, with a tool-calling backend that talks to your real ERPNext data through 38 permission-scoped tools.

> **End-user reference:** see **[CAPABILITIES.md](./CAPABILITIES.md)** for what you can ask the agent today, the full tool catalog with examples, and the roadmap (voice input, clickable Desk navigation, file upload/download, smart CSV/PDF export with field picker, inline charts, user-defined skills, async/scheduled jobs, realtime doc-change watches).

```
┌─────────────────────────────────────────────────┐ ┌──────────┐
│  ERPNext Desk                                   │ │  Chat    │
│  ┌─────────────────────────────────────────┐   │ │          │
│  │ Sales Invoice SI-001                     │   │ │ [msgs]   │
│  │ Customer: Acme                           │   │ │          │
│  │ Amount: ₹12,000                          │   │ │ /commit  │
│  └─────────────────────────────────────────┘   │ │ [input]  │
└─────────────────────────────────────────────────┘ └──────────┘
```

## What you get

- **Real ERPNext data** — every tool runs as `frappe.session.user`, so `frappe.get_list`/`frappe.has_permission` enforce role-based filters automatically. No god-mode bypass.
- **38 tools** across reads, mutations, workflow, analytics, reports, ERPNext domain (stock, accounts, outstanding, sales summary, item price), file extraction, and gated power tools (raw SQL / Python).
- **Two chat paths, admin-selectable** — Browser-LLM (key in browser, chat-ui orchestrates LLM, calls our MCP wire endpoint for tools) OR Backend-LLM (key in `LLM Provider` doctype, server orchestrates LLM, executes tools in-process). Both share the same 38 tools and per-user permission scoping.
- **Two-phase mutations** — the LLM stages `prepare_*`, you type `/commit TOKEN` to apply. The commit method is NOT in the tool registry, so the LLM is physically incapable of self-committing.
- **Multi-provider LLM** — Anthropic (native), plus any OpenAI-compatible API (OpenAI, OpenRouter, NVIDIA, Vercel AI Gateway, LM Studio, Groq, Together). For backend path: configure via `LLM Provider` doctype. For browser path: configure in chat-ui's BYO model picker (key in browser localStorage, never touches server).
- **SSE streaming** — token-level streaming via `send_message_stream` (backend path); non-streaming with tool-call status messages (browser path with tools).
- **Persistent chat** — conversations stored in the `Claude Conversation` doctype, survive page reloads. Both paths write to the same audit log.
- **Same-origin** — chat-ui dist is bundled inside the app and served from `/assets/lazychat_mcp_erpnext/lazychat_dist/`. No CORS, no port hardcoding, no separate dev server needed in production.
- **Single admin surface** — `Desk → Lazychat Settings`: enable/disable, iframe URL, chat path, security gates. Site_config flags still work as advanced overrides.

## Install

### One-time per machine: build the chat-ui dist

```bash
git clone git@github.com:soumyasethy/soumyasethy/lazychat.ai.git ../lazychat.ai
cd lazychat-mcp-erpnext
./scripts/build-lazychat-dist.sh   # auto-finds ../lazychat.ai
```

This runs `pnpm --filter chat-ui build` and bundles the dist into the Frappe app's `public/lazychat_dist/`.

### Per ERPNext bench

```bash
# If you've cloned this repo locally
BENCH_ROOT=/path/to/your/frappe-bench DEPLOY_SITE=your.site \
  ./scripts/deploy-local.sh

# OR direct git install on a fresh bench
cd /path/to/your/frappe-bench
bench get-app https://github.com/soumyasethy/lazychat-mcp-erpnext --branch main
bench --site your.site install-app lazychat_mcp_erpnext
```

The `after_install` hook auto-seeds default LLM Provider/Model rows, prints a welcome banner with next steps, and verifies the bundled dist is in place.

### Fresh bench, no Node/pnpm required (recommended for non-dev installs)

The `release` branch is force-pushed by CI on every tag (`.github/workflows/release.yml`)
and ships with `public/lazychat_dist/` already built. Installers don't need Node, pnpm,
or this `code-chat` workspace:

```bash
cd /path/to/your/frappe-bench
bench get-app https://github.com/soumyasethy/lazychat-mcp-erpnext --branch release
bench --site your.site install-app lazychat_mcp_erpnext
```

To pull a later release:

```bash
cd /path/to/your/frappe-bench
bench update --pull --apps lazychat_mcp_erpnext
bench --site your.site clear-cache
```

### Push to a remote bench you own (SSH)

For staging boxes / teammate machines you can SSH to. Run from your dev machine:

```bash
# One-time, on the remote bench
ssh user@host "cd /home/frappe/frappe-bench && \
  bench get-app https://github.com/soumyasethy/lazychat-mcp-erpnext --branch release && \
  bench --site site.example install-app lazychat_mcp_erpnext"

# Subsequent updates from your dev workspace
cd ~/Desktop/code-chat
sh build.sh --remote user@host:/home/frappe/frappe-bench --remote-site site.example
# Or fan out
for h in stage1.example stage2.example; do
  sh build.sh --remote "deploy@$h:/home/frappe/frappe-bench" --remote-site "$h"
done
```

`build.sh --remote` builds the dist locally, `rsync`s the app to the remote bench, runs
`bench build --app lazychat_mcp_erpnext` and `bench --site … clear-cache` over SSH.
See [scripts/deploy-remote.sh](./scripts/deploy-remote.sh) for env knobs (`SSH_OPTS`,
`REMOTE_RESTART`, etc).

### Configure (pick a chat path)

Open `Desk → Lazychat Settings` (or `/app/lazychat-settings`). Set **Chat Path**:

**Option A: Browser-LLM (single-user / power-user — key in browser)**
1. `Lazychat Settings → Chat Path = browser → Save`
2. Reload Desk → open the chat panel → model picker → "Add custom model"
3. Fill the endpoint (Anthropic, NVIDIA, OpenAI, OpenRouter, local LM Studio…) + paste API key
4. Send a message — chat-ui calls the LLM directly with your key and dispatches tool_use blocks back to ERPNext via MCP. Key never reaches the server.

**Option B: Backend-LLM (org / shared key)**
1. `Lazychat Settings → Chat Path = backend → Save`
2. `Desk → LLM Provider → Anthropic → set API Key → Save`
3. (Optional) `Desk → LLM Model` to add NVIDIA/OpenAI/OpenRouter rows; mark one `is_default = 1`
4. Reload Desk → chat panel uses the default model via `send_message_stream` → `run_agentic_turn`. Audit lives in `Claude Conversation`.

**Option C: Auto (default)**
Leave `chat_path = auto`. chat-ui inspects active model: custom model → browser path; built-in → backend path. Users can switch per-conversation.

## Configuration

**Primary admin surface: `Desk → Lazychat Settings`** (System Manager edit). 8 fields covering the panel, chat path, legacy widget, and security gates. Help text in the form explains each.

**Advanced overrides via `site_config.json`** (these win over the doctype values, kept for backward compat):

```json
{
  "lazychat_iframe_src": "http://127.0.0.1:5173/?frame=sidebar",
  "lazychat_panel_enabled": true,
  "lazychat_legacy_widget_enabled": false,
  "lazychat_allow_email": true,
  "lazychat_allow_dangerous_tools": true
}
```

| Setting | Default | Effect |
|---|---|---|
| `enabled` | `true` | Master switch |
| `iframe_base_url` | bundled dist path | Override for remote chat-ui or HMR dev (`http://127.0.0.1:5173`) |
| `chat_path` | `auto` | `auto` / `browser` / `backend` |
| `allow_email` | `false` | Enable `prepare_send_email` |
| `allow_dangerous_tools` | `false` | Enable `prepare_run_sql` + `prepare_run_python` (still gated by System Manager role + `/commit`) |

## Tool catalog (38 tools)

| Category | Tools |
|---|---|
| **Discovery** | search_doctype, search_global, search_link |
| **Reads** | get_list, get_doc, get_value, count_doc, describe_doctype, get_current_context, get_doctype_links |
| **Workflow** | list_workflow_actions, get_pending_approvals |
| **Analytics** | aggregate, get_sales_summary, dashboard_chart_data, number_card_value, list_user_dashboards |
| **Reports** | list_reports, report_requirements, run_report |
| **Files** | extract_file_content |
| **ERPNext domain** | get_stock_balance, get_account_balance, get_outstanding, get_open_invoices, get_item_price, get_company_defaults |
| **Mutations / Comms** (two-phase via `/commit`) | prepare_create_doc, prepare_update_doc, prepare_submit_doc, prepare_delete_doc, prepare_workflow_action, prepare_add_comment, prepare_assign_to, prepare_send_email, prepare_share_doc |
| **Power tools** (gated + two-phase) | prepare_run_sql, prepare_run_python |

## External MCP clients (Claude Desktop, agent SDKs, custom integrations)

The same 38 tools are exposed over the **Model Context Protocol (JSONRPC over HTTP)** at:

```
POST /api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle
Authorization: token <API_KEY>:<API_SECRET>
Content-Type: application/json
```

Generate the API key/secret per user in `Desk → User → <user> → API Access`. Each call runs as that user — `frappe.has_permission` filters apply, no god-mode bypass.

**Methods supported:** `initialize`, `ping`, `tools/list`, `tools/call`. Notifications (no `id`) are accepted.

### Quick check from your terminal

```bash
SITE=https://your-site.example
KEY=...
SECRET=...

# 1. Handshake
curl -s "$SITE/api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle" \
  -H "Authorization: token $KEY:$SECRET" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize"}' | jq

# 2. List tools (expect 38)
curl -s "$SITE/api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle" \
  -H "Authorization: token $KEY:$SECRET" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | jq '.result.tools | length'

# 3. Call a tool
curl -s "$SITE/api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle" \
  -H "Authorization: token $KEY:$SECRET" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_list","arguments":{"doctype":"Customer","limit":3}}}' | jq
```

### Claude Desktop / Cursor / etc

Point your MCP client config at the URL with the API key as a header:

```json
{
  "mcpServers": {
    "erpnext": {
      "url": "https://your-site.example/api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle",
      "headers": {
        "Authorization": "token YOUR_KEY:YOUR_SECRET"
      }
    }
  }
}
```

(Exact config field names vary by client. The endpoint is plain JSONRPC-over-HTTP — no SSE upgrade or session-id header required for this minimal transport.)

## Smoke test

Verify all 38 tools work against your live data:

```bash
cp scripts/smoke-test-tools.py /path/to/your/frappe-bench/apps/lazychat_mcp_erpnext/lazychat_mcp_erpnext/_smoke.py
cd /path/to/your/frappe-bench
bench --site your.site execute lazychat_mcp_erpnext._smoke.run
```

Expected: `=== 53 pass, 0 fail, 0 skip ===` (with cleanup of any test docs created).

## Architecture

```
                      ┌─── Lazychat Settings (Single doctype) ───┐
                      │ enabled, iframe_base_url, chat_path,     │
                      │ allow_email, allow_dangerous_tools, ...  │
                      └────────┬─────────────────────────────────┘
                               │ via boot.py → frappe.boot
                               ▼
ERPNext Desk @ <site>/app
├── lazychat_panel.bundle.js  (loaded via app_include_js on every Desk page)
│   ├── mounts iframe + slide-out chrome (FAB, resize handle, theme-aware CSS)
│   └── on init postMessage sends: chatPath, mcpEndpoint, mcpAuth, saveEndpoint
│
└── iframe → chat-ui (lazychat React UI)
    │
    ├── ╭─── BROWSER-LLM PATH ─────────────────────────────────╮
    │   │ chat-ui owns the LLM call:                            │
    │   │ 1. agent.ts:runChatWithMcp uses BYO endpoint+key     │
    │   │ 2. fetches tool defs once via mcp.handle (5min cache)│
    │   │ 3. attaches tools to LLM payload (OpenAI/Anthropic)  │
    │   │ 4. on tool_use → mcp.handle tools/call → tool_result │
    │   │ 5. loop max 8 turns                                   │
    │   │ 6. POST save_conversation for audit                   │
    │   ╰────────────────────────────────────────────────────╯
    │
    └── ╭─── BACKEND-LLM PATH (existing, unchanged) ───────────╮
        │ Backend owns the LLM call:                            │
        │ 1. agentRunner emits agentRequest postMessage         │
        │ 2. shim → POST send_message_stream                    │
        │ 3. run_agentic_turn resolves LLM Model doctype        │
        │ 4. providers/{anthropic,openai_compat}.py call LLM    │
        │ 5. on tool_use → execute_tool in-process              │
        │ 6. SSE events back → shim → agentChunk postMessage    │
        ╰─────────────────────────────────────────────────────╯
```

**Both paths share** `tools.py` (38 tools, 1 implementation), `frappe.has_permission` (per-user scoping), and `Claude Conversation` doctype (one audit log).

For deeper architecture + conventions, see [CLAUDE.md](CLAUDE.md).

## License

MIT
