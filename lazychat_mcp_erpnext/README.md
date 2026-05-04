# Lazychat MCP ERPNext (ERPNext desk)

Multi-provider LLM chat panel fixed to the **right side** of the Frappe / ERPNext desk. Implements the architecture from `erpnext_claude_multi_provider_extension.md`: **LLM Provider**, **LLM Model**, Anthropic + OpenAI-compatible adapters, read-only desk tools, and a collapsible UI.

## Install (bench)

1. Copy or clone this folder into your bench apps directory (or symlink):

   `cp -r lazychat_mcp_erpnext /path/to/frappe-bench/apps/`

2. Install the app on the site:

   ```bash
   cd /path/to/frappe-bench
   bench get-app /path/to/lazychat_mcp_erpnext   # if not already under apps/
   bench --site yoursite install-app lazychat_mcp_erpnext
   bench build --app lazychat_mcp_erpnext
   bench clear-cache
   ```

3. Open **Desk → LLM Provider**, edit **Anthropic**, paste your **API Key**, save.

4. Open **LLM Model**, confirm the default row (or add rows for OpenRouter / OpenAI with the right `model_id`).

5. Reload Desk (`/app`). You should see a vertical **AI** tab on the **right**; click it to expand the assistant.

## UI behaviour

- **Right dock**: `position: fixed`, full height below the top bar (~48px), ~400px wide.
- **Collapse**: **×** in the header or click the **AI** tab again (open state is stored in `localStorage`).
- **Model picker**: loads from `lazychat_mcp_erpnext.desk_assistant.api.list_models` (only providers with an API key, or localhost endpoints without a key).

## API (whitelisted)

- `lazychat_mcp_erpnext.desk_assistant.api.send_message` — body: `message`, optional `conversation_id`, `context` (JSON string), `model_label`.
- `lazychat_mcp_erpnext.desk_assistant.api.list_models` — for the dropdown.

## Security notes

- Tools are **read-only** (`get_list`, `get_doc`, `get_current_context`). Extend `tools.py` carefully if you add writes.
- API keys live in **LLM Provider** (encrypted password field).

## Lazychat panel (new UI)

The legacy right-dock widget is being replaced by [lazychat-ai](../../lazychat.ai/), a richer React UI embedded as an iframe. The Python backend (agent loop, providers, tools, conversations) is unchanged — only the front-end swaps.

### Architecture

```
ERPNext Desk (any site)
├── lazychat_mcp_erpnext app (this repo, installed via bench)
│   ├── public/js/lazychat_panel.bundle.js     ← shim: mounts iframe + postMessage proxy
│   ├── public/css/lazychat_panel.css          ← slide-out + FAB styling
│   ├── public/lazychat_dist/                  ← bundled chat-ui SPA (built via scripts)
│   ├── desk_assistant/boot.py                 ← exposes lazychat flags to frappe.boot
│   ├── desk_assistant/api.py                  ← send_message (batch) + send_message_stream (SSE)
│   └── desk_assistant/tools.py                ← real ERPNext tool registry (frappe.get_list etc)
└── nginx → /assets/lazychat_mcp_erpnext/lazychat_dist/index.html  (same-origin iframe src)
```

The shim auto-detects SSE; falls back to batch event-replay on 404.

### Build the bundled UI (one-time per machine)

The chat-ui dist is **not committed** — build it locally before deploying:

```bash
cd /path/to/lazychat-mcp-erpnext
./scripts/build-lazychat-dist.sh
# auto-discovers ../lazychat.ai; override with LAZYCHAT_REPO=/abs/path
```

This runs `pnpm --filter chat-ui build` and rsyncs the output into `lazychat_mcp_erpnext/public/lazychat_dist/`.

### Install on any ERPNext bench

```bash
# Per-bench install (idempotent)
BENCH_ROOT=/path/to/that/bench DEPLOY_SITE=site.example ./scripts/deploy-local.sh
# Or, for a fresh bench that doesn't have the app yet:
cd /path/to/that/bench
bench get-app file:///path/to/lazychat-mcp-erpnext
bench --site site.example install-app lazychat_mcp_erpnext
bench --site site.example clear-cache
```

The app's defaults work without any site_config edits:
- `lazychat_panel_enabled` defaults to `true`
- `lazychat_legacy_widget_enabled` defaults to `false` (old widget hidden)
- `lazychat_iframe_src` defaults to `/assets/lazychat_mcp_erpnext/lazychat_dist/index.html?frame=sidebar` — the bundled SPA, same-origin, no port dependency. To get fresh chat-ui changes here, rebuild via `./scripts/build-lazychat-dist.sh` and re-deploy.

**Active chat-ui dev (HMR) opt-in:** to point the iframe at the running vite dev server instead of the bundled dist (so chat-ui edits hot-reload), add to the site's `site_config.json`:

```json
{ "lazychat_iframe_src": "http://127.0.0.1:5173/?frame=sidebar" }
```

then `pnpm --filter chat-ui dev` from `lazychat.ai`. The dev server is pinned to port 5173 via `strictPort: true` — if 5173 is busy (stale process from another lazychat clone), vite will exit with a clear "Port 5173 is in use" error rather than silently picking 5174. Kill the stale process and retry.

To override (e.g. host the chat-ui on a separate domain), add to the site's `site_config.json`:
```json
{
  "lazychat_iframe_src": "https://chat.example.com/?frame=sidebar",
  "lazychat_legacy_widget_enabled": true
}
```

### How chat-ui talks to ERPNext (real data)

1. User types in chat-ui → posts `agentRequest` envelope to parent window via postMessage.
2. `lazychat_panel.bundle.js` (loaded by `app_include_js` on every Desk page) catches it.
3. Shim calls `frappe.call('lazychat_mcp_erpnext.desk_assistant.api.send_message_stream', ...)` over the same Frappe session cookie + CSRF token (same-origin).
4. `run_agentic_turn` runs the Anthropic tool loop. Each `tool_use` dispatches to `tools.py` → `frappe.get_list(...)` / `frappe.get_doc(...)` against the real site DB, respecting `frappe.session.user`'s permissions.
5. Events stream back as SSE; shim re-emits them as `agentChunk` postMessages; chat-ui renders.

### Whitelisted endpoints

- `lazychat_mcp_erpnext.desk_assistant.api.send_message` — batch JSON `{conversation_id, events, usage}`
- `lazychat_mcp_erpnext.desk_assistant.api.send_message_stream` — SSE: `event: text_delta|tool_use|tool_result|usage|done|error`
- `lazychat_mcp_erpnext.desk_assistant.api.list_models` — model picker

### Per-user permissions

All tool calls run inside the request-binding `frappe.session.user`. `frappe.get_list` / `frappe.has_permission` enforce role-based filters and doc-level perms automatically — there is no god-key bypass.

## License

MIT
