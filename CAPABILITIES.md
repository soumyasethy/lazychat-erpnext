# Lazychat for ERPNext — Capabilities & Roadmap

A reference for what the agent can do **today**, what's **shipping next**, and what's on the **roadmap** for becoming a fully agentic ERPNext platform.

---

## TL;DR — current state

- **38 permission-scoped tools** (read, write, workflow, analytics, reports, files, ERPNext domain, gated power tools)
- **2 chat paths** — Browser-LLM (BYO key in browser) or Backend-LLM (shared key in `LLM Provider` doctype)
- **Multi-provider LLM** — Anthropic native + any OpenAI-compatible endpoint (OpenAI, NVIDIA, OpenRouter, LM Studio, Groq, Together, Vercel AI Gateway, …)
- **Two-phase mutations** — `prepare_*` → `/commit TOKEN` so the LLM can never silently mutate
- **Voice input** (Chrome / Edge / Safari) — click the mic, speak, review the transcript, then send
- **Clickable Desk navigation** — agent emits `[SO26001040](/app/sales-order/SO26001040)` markdown; clicking SPA-navigates the Desk without reloading the chat
- **Live tool-call cards** — each MCP tool call shows args, ticking elapsed timer, final duration, result preview (pretty-printed JSON, shiki-highlighted)

---

## What you can ask the agent today

### Discover & search

> "Find a customer named Acme."
> "Search the system for 'overdue invoice'."
> "What doctypes exist for procurement?"

Tools: `search_doctype`, `search_global`, `search_link`.

### Read documents and lists

> "Show me Sales Order SO26001040 — list every line item with qty and amount."
> "List the 10 most recent overdue invoices for Acme."
> "How many open Sales Orders does the Mumbai branch have?"
> "Describe the Item doctype — what fields does it have?"

Tools: `get_list`, `get_doc`, `get_value`, `count_doc`, `describe_doctype`, `get_current_context`, `get_doctype_links`.

### Workflow & approvals

> "What approvals are pending for me?"
> "What workflow actions are valid on PUR-ORD-2026-00042 right now?"

Tools: `list_workflow_actions`, `get_pending_approvals`.

### Analytics and reports

> "Total sales by month for FY26."
> "Run the Stock Ledger report for Item L1001140207, last 30 days."
> "Show me my dashboards and their charts."

Tools: `aggregate`, `get_sales_summary`, `dashboard_chart_data`, `number_card_value`, `list_user_dashboards`, `list_reports`, `report_requirements`, `run_report`.

### ERPNext domain shortcuts

> "Stock balance of Item L1001140207 in Warehouse X."
> "Outstanding receivables for Acme."
> "Open invoices for Bharti."
> "What's the company default currency / fiscal year?"

Tools: `get_stock_balance`, `get_account_balance`, `get_outstanding`, `get_open_invoices`, `get_item_price`, `get_company_defaults`.

### Files (read)

> "Read the contents of the attached PDF."

Tools: `extract_file_content` (returns up to 20k chars of text from any attached File).

### Mutations & communications (two-phase, always)

> "Create a new Customer named 'Bharti Foods', credit limit ₹50 lakh."
> "Update SO-2026-0042 — set delivery_date to 2026-06-15."
> "Submit PO-0099."
> "Add a comment on Sales Invoice SI-001: 'Customer paid by cheque'."
> "Assign me to Issue ISS-031."
> "Email the customer the rendered invoice PDF." *(requires `allow_email` flag)*

Tools: `prepare_create_doc`, `prepare_update_doc`, `prepare_submit_doc`, `prepare_delete_doc`, `prepare_workflow_action`, `prepare_add_comment`, `prepare_assign_to`, `prepare_send_email`, `prepare_share_doc`.

**How it works:** the agent stages the change and replies with a preview + a token. **You** type `/commit TOKEN` to actually apply it. The commit method is not in the LLM's tool registry, so the model is physically incapable of mutating without your confirmation.

### Power tools (gated)

> "Run this SELECT … to find duplicate item codes."
> "Run this Python snippet to compute custom analytics."

Tools: `prepare_run_sql`, `prepare_run_python`. Require **all of**: `lazychat_allow_dangerous_tools` site flag + `System Manager` role + `/commit` confirmation. SQL is regex-validated SELECT-only.

### Navigation

> "Show me SO26001040 in the Desk."

The agent emits a clickable Desk link — click to SPA-navigate. Cmd-click opens in a new tab. Files (`/files/...`) always open in a new tab so the chat survives.

### Voice

Click the mic icon in the input bar. Permission prompt appears once. Speak; the transcript streams into the input bar live. Click the mic again to stop. **You review and edit the text, then press Enter to send.** Works in Chrome, Edge, Safari (Firefox doesn't ship the Web Speech API yet).

---

## Full tool catalog (38)

| Category | Tools | Count |
|---|---|---|
| **Discovery** | `search_doctype`, `search_global`, `search_link` | 3 |
| **Reads** | `get_list`, `get_doc`, `get_value`, `count_doc`, `describe_doctype`, `get_current_context`, `get_doctype_links` | 7 |
| **Workflow** | `list_workflow_actions`, `get_pending_approvals` | 2 |
| **Analytics** | `aggregate`, `get_sales_summary`, `dashboard_chart_data`, `number_card_value`, `list_user_dashboards` | 5 |
| **Reports** | `list_reports`, `report_requirements`, `run_report` | 3 |
| **Files** | `extract_file_content` | 1 |
| **ERPNext domain** | `get_stock_balance`, `get_account_balance`, `get_outstanding`, `get_open_invoices`, `get_item_price`, `get_company_defaults` | 6 |
| **Mutations / Comms** *(two-phase, `/commit` required)* | `prepare_create_doc`, `prepare_update_doc`, `prepare_submit_doc`, `prepare_delete_doc`, `prepare_workflow_action`, `prepare_add_comment`, `prepare_assign_to`, `prepare_send_email`, `prepare_share_doc` | 9 |
| **Power tools** *(gated + two-phase)* | `prepare_run_sql`, `prepare_run_python` | 2 |
| **Total** | | **38** |

Every tool runs as `frappe.session.user`. `frappe.has_permission(...)` is checked **before** any DB access. There is no god-mode bypass.

---

## What's shipping right now (in flight)

| Tier | Status | Highlights |
|---|---|---|
| **0 — File-URL hallucination guard** | ✅ shipped | `get_doc` resolves relative file paths via `frappe.utils.get_url` and emits `<field>_url` siblings. Prompt explicitly forbids inventing paths. |
| **A — Clickable Desk navigation** | ✅ shipped | New `navigateDesk` postMessage envelope; `<a>` interceptor in chat-ui; panel shim calls `frappe.set_route()`. |
| **Voice input** | ✅ shipped | Web Speech API via the mic button; live interim transcript; review-before-send. |
| **MCP timeouts + observability** | ✅ shipped | 45 s SSE inactivity guard, 30 s tool-call timeout, 15 s tools/list timeout, live `mcpTool` cards with elapsed timer. |
| **DATA FAITHFULNESS prompt** | ✅ shipped | Forces enumeration of every row, markdown tables for tabular data, verbatim numerics. |

---

## Roadmap — toward a truly agentic platform

Each tier is independently shippable; the user can stop at any cutpoint.

### Tier B — Files (~3 days)

> "Show me the attachments on SO26001040." • "Attach this file to SO-001." • "Download the PDF for invoice SI-007."

| New tool | What it does |
|---|---|
| `list_attachments(doctype, name)` | All `File` doctype rows linked to a parent doc, with absolute URLs |
| `get_file_url(file_name)` | Resolve a File to its public/private URL via `frappe.utils.get_url` |
| `get_download_url(doctype, name, format?)` | Print-format download URL the user can click |
| `prepare_upload_file(target_doctype, target_name, accept?)` | Two-phase upload via chat-ui file picker (postMessage roundtrip) |

### Tier C — Export & Import (~3 days)

> "Export all open Sales Orders to CSV." • "Generate a PDF of SI-007." • "Import this CSV as new Items."

| New tool | What it does |
|---|---|
| `export_list_to_csv(doctype, filters, fields, limit?)` | CSV up to 5000 rows; returns clickable download URL |
| `export_doc_pdf(doctype, name, print_format?)` | Renders Frappe print format, returns PDF URL |
| `prepare_import_csv(doctype, csv_url, mapping?)` | Bulk insert via Frappe Data Import (gated + `/commit`) |

### Tier D — Async / Scheduled / Realtime (~2 weeks, splittable)

> "Queue a job to recompute stock balances and notify me when done." • "Schedule the daily AR report at 8 am." • "Watch SO-001 for status changes."

| New tool | What it does |
|---|---|
| `enqueue_background_job(method, args?, queue?)` | `frappe.enqueue` wrapper, returns job_id |
| `schedule_recurring(method, cron, args?)` | Creates / updates `Scheduled Job Type` |
| `list_my_jobs()` | Read-only RQ + scheduled job inspection |
| `cancel_job(job_id)` | Cancel a queued or running job |
| `subscribe_doc_changes(doctype, name)` | Realtime watch (Redis pub/sub → SSE → chat toast) |

Plus: chat-ui SSE subscriber + new `useRealtime` store + extended `mcpTool` cards that subscribe to job_ids and tick to "Job complete".

### Tier E — Skills / extensions system (NEW, planned)

Inspired by Claude Code's *superpowers* — let users **package an instruction + tool subset + examples** as a reusable skill, surfaced via the `/` command palette in chat-ui. The agent loads active skills into its system prompt.

Design (draft):
- **Storage** — new `Lazychat Skill` doctype (name, description, system_prompt, allowed_tools[], examples[], enabled).
- **Discovery** — type `/skills` in chat to list installed skills; `/skills create` opens a form; `/skills add <name>` activates one for the current conversation.
- **Composition** — multiple skills can stack; their `system_prompt` snippets append to the base prompt.
- **Built-in starter pack** — *Approval Bot* (only workflow + comment tools, focused prompt), *AR Collections* (outstanding + email tools), *Stock Reconciliation* (stock + SQL tools, gated), *Item Onboarding* (smart-export + create-doc).
- **Marketplace path** (future) — JSON manifest + GitHub repo distribution.

### Tier F — Charts / data exploration (NEW, planned)

> "Plot sales by month for FY26." • "Show me a stacked bar of POs by supplier and status."

| New tool | What it does |
|---|---|
| `make_chart(type, data, title, options?)` | Returns a Vega-Lite or Recharts spec; chat-ui renders inline as an interactive chart |
| `explore_data(doctype, dimensions, measures)` | Combines `aggregate` + `make_chart` into a one-shot data-explore turn |

Renderer: extend the existing `[[lazychat:artifact]]` marker support so `kind="chart"` mounts a Recharts component (already a peer of LinkCard/Markdown). The agent gets a system-prompt block teaching the chart spec format. Also exposes a "Save chart" button that creates a `Dashboard Chart` doctype row.

### Tier G — Smart export UX with field picker (NEW, your specific ask)

You said: *"I want to article master export and fields name selection which fields we want export … smooth and csv file download option like Claude and ChatGPT do."*

UX:
1. You: *"Export the Item master to CSV."*
2. Agent calls `export_list_to_csv` with no `fields` → tool returns a **field-picker preview** (preview_token + the doctype's fields with checkboxes pre-selected for `name`, `item_code`, `item_name`, `item_group`, `stock_uom`).
3. Chat-ui renders an inline **Field Picker card** (new `mcpFieldPicker` message kind): scrollable list with checkboxes, search box, "select all / none", row-count estimate.
4. You toggle checkboxes, click **Generate CSV** → chat-ui posts `/commit TOKEN fields=[...]` → backend runs the actual export → returns clickable `[items-2026-05-05.csv](/files/lazychat-exports/<uuid>.csv)` download link (Tier A interceptor opens it in a new tab).

Reuses the existing two-phase pattern; the new piece is the **field-picker rendering component**.

### Larger context handling (continuous improvement)

Today the chat-ui already trims conversation history (`trimToContextBudget` in `lib/tokens.ts`) and the MCP `mcpResultToText` cap was raised from 12 KB → 60 KB on May 5 to stop mid-row truncation of Sales Order line items.

Next steps:
- **Per-model context budgets** in the model picker (currently one `max_tokens` field; add `max_context_tokens` field with sensible defaults per known model).
- **Context usage indicator** in the input bar (visible "X% of context used" hint when over 50%).
- **Smart pruning** — drop oldest tool results before user messages; keep system prompt + last user turn always.

---

## How to extend

| Want | Read |
|---|---|
| Add a new tool | [CLAUDE.md](./CLAUDE.md) → "New tool checklist" |
| Add a chat-ui component | [lazychat.ai/CLAUDE.md](../lazychat.ai/CLAUDE.md) → "Message kinds" |
| Wire a new postMessage envelope | `packages/types/src/postmessage.ts` (lazychat.ai) + `public/js/lazychat_panel.bundle.js` (this repo) |
| Add a system-prompt rule | `routerSystemPrompt.ts` (browser path) + `claude_bridge._system_prompt` (backend path) — keep them in sync |
| Test end-to-end | Smoke test: `cp scripts/smoke-test-tools.py <bench>/apps/.../_smoke.py && bench --site <site> execute lazychat_mcp_erpnext._smoke.run` (currently 72 cases) |

---

## Limits today (be honest)

- **No file upload** from chat → backend yet (Tier B).
- **No CSV/PDF export** beyond the gated `prepare_run_python` workaround (Tier C).
- **No async jobs / scheduled tasks / realtime subscriptions** (Tier D).
- **No user-defined skills** (Tier E).
- **No inline charts** — agent can describe data but can't draw it (Tier F).
- **`get_doc` truncates child tables to 25 rows** server-side; for full data the agent uses `get_list`. The `_note` field tells it when truncation happened.
- **Browser-LLM tool result cap is 60 KB** (after May 5 bump from 12 KB). For very large docs the result still gets truncated with a notice.
- **Voice input** needs Chrome/Edge/Safari — Firefox doesn't ship the Web Speech API.

---

## Feedback / requests

Open an issue at [github.com/soumyasethy/lazychat-mcp-erpnext](https://github.com/soumyasethy/lazychat-mcp-erpnext/issues). For chat-UI behavior specifically, [github.com/soumyasethy/lazychat.ai](https://github.com/soumyasethy/lazychat.ai/issues).
