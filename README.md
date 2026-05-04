# lazychat-mcp-erpnext

A **Frappe app** that drops a rich, multi-provider AI chat panel into the right side of your ERPNext desk. Built on top of the [lazychat-ai](https://github.com/soumyasethy/lazychat.ai) React UI embedded as a same-origin iframe, with a tool-calling backend that talks to your real ERPNext data through 38 permission-scoped tools.

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
- **Two-phase mutations** — the LLM stages `prepare_*`, you type `/commit TOKEN` to apply. The commit method is NOT in the tool registry, so the LLM is physically incapable of self-committing.
- **Multi-provider LLM** — Anthropic (native), plus any OpenAI-compatible API (OpenAI, OpenRouter, NVIDIA, Vercel AI Gateway, LM Studio, Groq, Together). Configure via the `LLM Provider` doctype.
- **SSE streaming** — token-level streaming via `send_message_stream`; falls back to batch if SSE is blocked by your reverse proxy.
- **Persistent chat** — conversations stored in the `Claude Conversation` doctype, survive page reloads.
- **Same-origin** — chat-ui dist is bundled inside the app and served from `/assets/lazychat_mcp_erpnext/lazychat_dist/`. No CORS, no port hardcoding, no separate dev server needed in production.

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

### Configure your LLM

1. `Desk → LLM Provider → Anthropic → set API Key → Save`
2. (Optional) Enable other providers and create their `LLM Model` rows.
3. Reload the desk. Click the chat-bubble bottom-right.

## Optional `site_config.json` flags

All defaults work out of the box. Override only if needed:

```json
{
  "lazychat_iframe_src": "http://127.0.0.1:5173/?frame=sidebar",
  "lazychat_allow_email": true,
  "lazychat_allow_dangerous_tools": true
}
```

| Flag | What it does |
|---|---|
| `lazychat_iframe_src` | Override the iframe src — point at a running chat-ui dev server for HMR while editing the React UI |
| `lazychat_allow_email` | Enable `prepare_send_email` tool (off by default to prevent accidental mass-mail) |
| `lazychat_allow_dangerous_tools` | Enable `prepare_run_sql` + `prepare_run_python` (still gated by System Manager role + `/commit` confirmation) |

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
ERPNext Desk @ <site>/app
├── lazychat_panel.bundle.js  (loaded via app_include_js on every Desk page)
│   ├── mounts iframe + slide-out chrome (FAB, resize handle, theme-aware CSS)
│   ├── postMessage envelope per lazychat protocol
│   └── intercepts /commit <token>  →  POST commit_prepared_action
│
├── iframe @ /assets/lazychat_mcp_erpnext/lazychat_dist/index.html?frame=sidebar
│   └── lazychat React UI (multi-tab, markdown, mutation previews, theme tokens)
│
└── On user send → agentRequest postMessage:
       shim → POST /api/method/lazychat_mcp_erpnext.desk_assistant.api.send_message_stream
                 → run_agentic_turn (Anthropic Messages API streaming)
                     → on tool_use: tools.py.execute_tool (with frappe.set_user)
                         → frappe.get_list / get_doc / etc — REAL ERPNext data
                     → SSE events back: text_delta / tool_use / tool_result / done
                 → shim re-emits as agentChunk → chat-ui streams in
```

For deeper architecture + conventions, see [CLAUDE.md](CLAUDE.md).

## License

MIT
