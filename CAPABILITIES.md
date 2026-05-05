# Lazychat for ERPNext — Capabilities & Roadmap

A reference for what the agent can do **today**, what's **shipping next**, and what's on the **roadmap** for becoming a fully agentic ERPNext platform.

---

## TL;DR — current state

- **62 permission-scoped tools** (read, write, workflow, analytics, reports, files + list/resolve attachments + **chat-side upload**, ERPNext domain, gated power tools + **bulk CSV import**, skills, knowledge base + vector embeddings + hybrid retrieval + chat-ui management + citations, system diagnostics, admin, audit trail, file exports (CSV / PDF) + **interactive field picker**, background-job control, inline charts (Vega-Lite))
- **2 chat paths** — Browser-LLM (BYO key in browser) or Backend-LLM (shared key in `LLM Provider` doctype)
- **Multi-provider LLM** — Anthropic native + any OpenAI-compatible endpoint (OpenAI, NVIDIA, OpenRouter, LM Studio, Groq, Together, Vercel AI Gateway, …)
- **Two-phase mutations** — `prepare_*` → `/commit TOKEN` so the LLM can never silently mutate
- **Voice input** (Chrome / Edge / Safari) — click the mic, speak, review the transcript, then send
- **Clickable Desk navigation** — agent emits `[SO26001040](/app/sales-order/SO26001040)` markdown; clicking SPA-navigates the Desk without reloading the chat
- **Live tool-call cards** — each MCP tool call shows args, ticking elapsed timer, final duration, result preview (pretty-printed JSON, shiki-highlighted)
- **Skills (Tier E, COMPLETE)** — focused agent personas with optional tool-subset restriction. Toggle from the `/` palette, **create new ones inline** with the form, **deactivate via chip × above the input bar**. Four starter skills seeded: *AR Collections*, *Item Onboarding*, *Stock Reconciliation*, *Approval Bot*. Active set persists per-user across tabs (Redis, 7-day TTL).
- **Knowledge Base (Tier H, slice 1)** — attach PDF / XLSX / CSV / TXT / MD / DOCX files to a `Lazychat Knowledge Base` doctype row, ask the agent to find answers in them. Multi-format text extraction; keyword paragraph search MVP (vector embeddings on the roadmap).
- **System diagnostics** — `get_system_info` (Frappe + ERPNext + every installed app's version, country, time zone, currency, Python version) and `get_user_info` (your email, full name, roles, time zone). Now the agent can answer "what version are we running?" and "what apps are installed?" from its own tool calls.

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

> "What files are attached to SO26001040?"
> "Read the contents of the attached PDF."
> "Give me the link to the invoice attached to SI-001."

Tools:
- `list_attachments(doctype, name)` — every File row attached to a parent doc, with absolute URL ready to cite.
- `get_file_url(file)` — resolve a File doctype name OR a relative `file_url` to its absolute URL with metadata; permission-checked via the parent doc.
- `extract_file_content` — up to 20k chars of text from any attached File.

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

### Knowledge Base

> *"What's our return policy on damaged goods?"* (answered from your HR/policies PDF)
> *"Which SKUs are tagged 'Premium' in the catalog?"* (answered from a Product Master XLSX)
> *"Summarise the contract clauses about late-payment penalties."* (answered from contract PDFs)

**Setup (in chat — recommended):**
1. Open the `/` palette → scroll to **Knowledge Bases** → click **+ Create knowledge base**.
2. Fill title + (optional) description, click **Save** — slug auto-derives from the title (kebab-case). The KB appears in the list immediately.
3. Click the ↗ icon on the new KB row → opens the KB doc in the Desk so you can drop files into the **Attachments** sidebar.
4. Ask the agent — it'll call `search_kb` automatically when the question looks answerable from internal docs and **cite each source with a clickable link** like `[hr-handbook.pdf](/files/hr-handbook.pdf)` (Tier-A interceptor opens it in a new tab).

**Setup (Desk admin path):**
1. `Desk → New Lazychat Knowledge Base` (System Manager). Set the slug, title, description; check `is_public` if everyone in the org should be able to query it.
2. Save the doc. The standard Frappe **Attachments** sidebar appears — upload your files there. Supported formats:
   - **Text** — `.txt`, `.md`, `.csv`, `.tsv`, `.json`, `.yaml`, `.log`, `.html`, `.xml`, `.sql`, `.py`, `.js`, `.ts`
   - **PDF** — `.pdf` (uses `pdfplumber` → `pypdf` fallback)
   - **Excel** — `.xlsx`, `.xlsm` (uses `openpyxl`)
   - **Word** — `.docx` (uses `python-docx`)
3. Ask the agent anything — it'll call `search_kb` automatically when the question looks answerable from internal docs.

Tools: `list_knowledge_bases`, `get_kb_files`, `search_kb`. Search is **keyword paragraph match across all visible KBs by default** (or one named KB). For each match returns a snippet centred on the first hit + the source file URL (clickable per Tier A).

**Indexing pipeline (Tier H2 shipped):** when you attach a file to a `Lazychat Knowledge Base` doc, a Frappe `on_update` hook fires and enqueues a background job (`frappe.enqueue`). The job extracts text, splits it into ~500-token chunks with 50-token overlap, and POSTs to your configured LLM provider's `/v1/embeddings` endpoint with model `text-embedding-3-small`. Embeddings are stored as base64-encoded float32 in the `Lazychat KB Chunk` doctype. Content-hash dedupe means re-uploading an unchanged file skips embedding entirely.

**Hybrid retrieval:** every `search_kb` call computes a query embedding (one API call), scores all chunks by cosine similarity (top 20), runs the existing keyword paragraph match (top 20), and fuses the two rankings via Reciprocal Rank Fusion (k=60) → top 5. Falls back to keyword-only when no chunk has been embedded yet (e.g. first-time setup, no provider configured) — graceful degradation, no errors.

**Provider lookup:** mirrors the chat path. The first enabled `LLM Provider` row of `provider_type=openai_compatible` with a non-empty API key is used. If you can chat, you can embed — no extra config. Override the default `text-embedding-3-small` by adding an `extra_headers` row with `header_key=lazychat_embedding_model, header_value=<model-id>` on the provider doc.

**Reindexing:** for KBs that had files attached BEFORE Tier H2 shipped, ask the agent *"reindex my product catalog"* — it'll call `reindex_kb` which enqueues a background job per file. Watch progress with *"list my background jobs"* (`list_my_jobs`).

**Status surfacing:** `get_kb_files` now returns per-file `embedding_status` (`indexed` / `partial` / `keyword_only` / `pending`) + `chunk_count` so admins can spot files that didn't embed.

### System diagnostics

> *"Which version of ERPNext are we running?"* → `get_system_info` returns frappe, erpnext, and every installed app's version.
> *"What apps are installed?"* → same tool — full list with versions.
> *"Who am I logged in as?"* → `get_user_info` returns email, full name, roles, time zone, language.

These were missing — the agent used to say "I don't have access to system-level info" because no tool exposed it. Now it does.

### Upload files from chat (Tier B-upload)

> *"Attach an updated contract PDF to PO-2026-00042."*
> *"Add this approval letter to the issue."*

The agent calls `prepare_upload_file(target_doctype, target_name, accept?)`, which stages an attach action and tells the user to type `/upload TOKEN`. The panel shim intercepts that slash command, opens a native file picker, uploads via `/api/method/upload_file`, and finishes the attach in one step. The user sees: *Opening picker → Uploading 245 KB → Attached → [PO-2026-00042](/app/purchase-order/PO-2026-00042)*.

### Smart CSV export with field picker (Tier G)

> *"Export the Item master to CSV — let me pick the columns."*
> *"CSV of all open Sales Orders."*

When you call `export_list_to_csv` without specifying `fields`, the agent gets back a field-picker preview. The chat-ui renders an **inline checkbox card** with every doctype field (default-checked per the doctype's `in_list_view` flags), a search filter, "All / None / Defaults" presets, and a row-count estimate based on the active filters. Click **Generate CSV** → the chat-ui POSTs the selection to `commit_prepared_action` → backend writes the actual CSV to `/private/files/` → file appears as a clickable download button right under the picker. **No more 30-column dump CSVs you didn't want.**

### Bulk CSV import (Tier C-import, gated)

> *"Import this customer CSV — file_url=/files/customers-2026-q4.csv."*

The agent calls `prepare_import_csv(doctype, csv_file_url, import_type?)`. Gated identically to `prepare_run_sql` / `prepare_run_python` (System Manager + `allow_dangerous_tools` + `/commit`). On commit, a Frappe `Data Import` doctype row is created and `start_import()` is called — the actual row inserts happen async in the background queue. Watch progress via `list_my_jobs`.

### Inline charts

> *"Plot last 6 months sales by month."*
> *"Bar chart of open SO count per customer, top 10."*
> *"Show me a pie of items by item_group."*

The agent calls `aggregate` (or `dashboard_chart_data` / `get_list` / `run_report`) to fetch real numbers, optionally calls `make_chart(spec)` for tool-card visibility, then emits `[[lazychat:artifact kind="chart"]]<vega-lite-v5-json>[[/lazychat:artifact]]` in its reply. The chat-ui detects the spec, lazy-loads `react-vega` (first-chart only — subsequent charts reuse the cached chunk), and renders an interactive Vega-Lite chart inline. Theme follows your Desk light/dark setting.

Specs are capped at 150 rows; for larger datasets the agent rolls up via `aggregate` first. No external network calls — `data.values` is inlined into the spec.

### Voice

Click the mic icon in the input bar. Permission prompt appears once. Speak; the transcript streams into the input bar live. Click the mic again to stop. **You review and edit the text, then press Enter to send.** Works in Chrome, Edge, Safari (Firefox doesn't ship the Web Speech API yet).

### Skills (focus the agent for a workflow)

Open the `/` command palette (or Cmd+K). The **Skills** section lists everything you can activate. Each skill is a packaged persona — a system-prompt snippet plus an optional tool-subset whitelist that restricts what the agent can call while the skill is on. Multiple skills can stack.

**Seeded starter pack (4):**

- **AR Collections** — receivables follow-up. Restricts the agent to outstanding/invoice reads + email/comment staging. Drafts polite 7-day-out follow-ups; never escalates without you asking.
- **Item Onboarding** — guides creation of new Items with the right defaults. Restricts to describe/search/list reads + `prepare_create_doc`.
- **Stock Reconciliation** — investigate physical-vs-system variances. Drives a 5-step flow: stock balance → SLE drilldown → cross-warehouse aggregation (gated SQL) → root-cause hypothesis → propose reconciling entry. Tools restricted to stock + aggregate + gated `prepare_run_sql`.
- **Approval Bot** — process pending approvals. Renders them as a clickable Desk-link table, then walks the user through `get_doc` → `list_workflow_actions` → `prepare_workflow_action` for each one, with optional `prepare_add_comment` for the audit trail.

**Manage your own:** open the `/` palette → scroll to **Skills** → click **+ Create skill**. Inline form takes title, description, system prompt, and an optional comma-separated `allowed_tools` whitelist. Save commits in one click (no separate `/commit` step — you ARE the confirmation since the form is direct UI). The new skill appears in the list immediately and can be toggled on. For advanced fields (examples, public flag), use `Desk → New Lazychat Skill` (System Manager).

**Active-skill chips:** every skill that's currently on shows as a chip above the input bar with a one-click `×` to deactivate. No need to re-open the palette to turn one off.

**How activation works under the hood:**
- Toggling a skill calls `activate_skill` / `deactivate_skill` over MCP.
- The active set is stored in Redis under `lazychat:skills:active:<user>` (7-day TTL, refreshed on each touch).
- Every agent turn re-reads the set: the system prompt gains a `--- Active skill: <Title> ---` block per active skill, and the MCP `tools/list` response is filtered to the union of `allowed_tools` across active skills (server-side enforcement, not client-trusted — the LLM physically cannot see hidden tools).

---

## Full tool catalog (38)

| Category | Tools | Count |
|---|---|---|
| **Discovery** | `search_doctype`, `search_global`, `search_link` | 3 |
| **Reads** | `get_list`, `get_doc`, `get_value`, `count_doc`, `describe_doctype`, `get_current_context`, `get_doctype_links` | 7 |
| **Workflow** | `list_workflow_actions`, `get_pending_approvals` | 2 |
| **Analytics** | `aggregate`, `get_sales_summary`, `dashboard_chart_data`, `number_card_value`, `list_user_dashboards` | 5 |
| **Reports** | `list_reports`, `report_requirements`, `run_report` | 3 |
| **Files** | `extract_file_content`, `list_attachments`, `get_file_url`, `prepare_upload_file` | 4 |
| **ERPNext domain** | `get_stock_balance`, `get_account_balance`, `get_outstanding`, `get_open_invoices`, `get_item_price`, `get_company_defaults` | 6 |
| **Mutations / Comms** *(two-phase, `/commit` required)* | `prepare_create_doc`, `prepare_update_doc`, `prepare_submit_doc`, `prepare_delete_doc`, `prepare_workflow_action`, `prepare_add_comment`, `prepare_assign_to`, `prepare_send_email`, `prepare_share_doc` | 9 |
| **Power tools** *(gated + two-phase)* | `prepare_run_sql`, `prepare_run_python`, `prepare_import_csv` | 3 |
| **Skills** *(meta — configure the agent itself)* | `list_skills`, `activate_skill`, `deactivate_skill` | 3 |
| **Knowledge Base** | `list_knowledge_bases`, `get_kb_files`, `search_kb` | 3 |
| **System diagnostics** | `get_system_info`, `get_user_info` | 2 |
| **Admin** *(rename, version history, revert)* | `prepare_rename_doc`, `list_doc_versions`, `prepare_revert_doc` | 3 |
| **Audit Trail** | `get_audit_trail` | 1 |
| **File exports** | `export_list_to_csv`, `export_doc_pdf` | 2 |
| **Background jobs** | `list_my_jobs`, `cancel_job` | 2 |
| **KB management** *(write)* | `prepare_create_kb`, `prepare_add_file_to_kb` | 2 |
| **Charts** *(inline Vega-Lite)* | `make_chart` | 1 |
| **KB indexing** *(reindex existing files)* | `reindex_kb` | 1 |
| **Total** | | **62** |

Every tool runs as `frappe.session.user`. `frappe.has_permission(...)` is checked **before** any DB access. There is no god-mode bypass.

---

## Frappe / ERPNext admin coverage

Coverage map for the standard admin/dev surface in Frappe + ERPNext. Most items work today via the **generic** `prepare_create_doc` / `prepare_update_doc` / `get_list` / `get_doc` tools — Frappe is doctype-driven, so once a thing is a doctype the agent can already CRUD it within the user's Frappe permissions. A handful needed dedicated tools for ergonomics or because they're not pure doctype operations.

| Capability | Status | How |
|---|---|---|
| **Workflow** (transitions on a doc) | ✅ direct | `list_workflow_actions`, `get_pending_approvals`, `prepare_workflow_action` |
| **Workflow Builder** (designing new state machines) | ✅ generic | `prepare_create_doc("Workflow", values={...})` + child tables Workflow State / Workflow Document State / Workflow Transition. Use `describe_doctype("Workflow")` to learn the schema, then create. (A `prepare_create_workflow` ergonomic wrapper is in the Tier I backlog but not blocking — generic works fully today.) |
| **Query Report** (Report Type=Query Report, raw SQL) | ✅ direct | `list_reports`, `report_requirements`, `run_report` |
| **Script Report** (Report Type=Script Report, Python) | ✅ direct | Same — `run_report` dispatches to whichever report type |
| **Report Builder in UI** (drag-drop column picker) | ✅ generic | `prepare_create_doc("Report", values={"report_type": "Report Builder", ...})`. Visual picker is Desk-only UI; Report doctype is fully createable from the agent. |
| **Rename Tool** | ✅ direct | `prepare_rename_doc(doctype, name, new_name, merge?)` → `/commit`. Wraps `frappe.rename_doc()`. |
| **Print Format** | ✅ direct (render) + generic (design) | Render: `export_doc_pdf(doctype, name, print_format?)` via `frappe.get_print` + `frappe.utils.pdf.get_pdf`, returns clickable PDF URL. Design: `prepare_create_doc("Print Format", ...)`. |
| **Server Script** | ✅ generic + revert | `prepare_create_doc("Server Script", ...)` + `list_doc_versions` + `prepare_revert_doc` for undo. |
| **Client Script** | ✅ generic + revert | Same — `prepare_create_doc("Client Script", ...)` + version history + revert. |
| **Role Permission Manager** | ✅ generic | `prepare_create_doc("Custom DocPerm", values={"role": ..., "parent": ..., "read": 1, ...})` for per-role rules; `prepare_create_doc("Role")` for new roles. |
| **Property Setter** | ✅ generic | `prepare_create_doc("Property Setter", values={"doc_type": ..., "field_name": ..., "property": ..., "value": ...})`. Use `describe_doctype` first to find the right field. |
| **Custom Field** | ✅ generic | `prepare_create_doc("Custom Field", values={"dt": ..., "fieldname": ..., "fieldtype": ..., "label": ...})`. |
| **Role Permission** (DocPerm) | ✅ generic | Same as Role Permission Manager. |
| **Error Log** | ✅ generic read | `get_list("Error Log", filters={"creation": [">", "..."]}, fields=["error", "method"])`. Used in the iframe-cache debug playbook in CLAUDE.md. |
| **System Console** | ✅ direct | `prepare_run_python` (gated: `allow_dangerous_tools` + System Manager + `/commit`). Same execution surface as `/app/system-console`. |
| **Access Log** | ✅ generic read | `get_list("Access Log", ...)`. |
| **Activity Log** | ✅ generic read | `get_list("Activity Log", ...)` plus surfaces in `get_audit_trail` filtered to a single doc. |
| **Scheduled Job Type** | ✅ generic | `get_list("Scheduled Job Type")` for inspection; `prepare_create_doc("Scheduled Job Type", values={"method": ..., "frequency": "Cron", "cron_format": ..., ...})` for create. (Tier D adds cron-validating `schedule_recurring`; not blocking.) |
| **RQ Job** | ✅ direct | `list_my_jobs(limit?)` returns the user's queued/running/finished jobs newest-first with status, queue, started_at, ended_at, exc_info. `cancel_job(job_id)` cancels a queued or running job (Frappe v15+ `stop_job`, fallback `cancel`). For cross-user, `get_list("RQ Job")`. |
| **RQ Workers** | 🟡 read only | Worker processes are bench-managed (`bench worker`); not a doctype. Visible counts via `prepare_run_sql` against the RQ-internal tables (gated). Out of scope for tool exposure by design — worker control belongs at the OS layer, not the agent. |
| **Data Import** | ✅ generic | `prepare_create_doc("Data Import", values={"reference_doctype": ..., "import_file": <File URL>, "import_type": "Insert New Records"})` then submit. (Tier C's `prepare_import_csv` will add a column-mapping picker UX; generic works fully today for the import action itself.) |
| **Data Export** | ✅ direct | `export_list_to_csv(doctype, fields, filters?, limit?)` writes CSV to `/private/files/`, returns clickable download URL. Cap 5000 rows. Tier G's smart field-picker UX is the planned ergonomic upgrade. |
| **Document version history** | ✅ direct | `list_doc_versions(doctype, name)` — Version rows newest-first with field-level diffs. |
| **Document revert** | ✅ direct | `prepare_revert_doc(doctype, name, version_id)` → `/commit`. Scalar fields only; child-table revisions need manual `prepare_update_doc`. |
| **Audit Trail** | ✅ direct | `get_audit_trail(doctype, name)` — unified timeline aggregating Version + Comment + Activity Log + creation/modified metadata, sorted newest-first. Drives "who edited X?" / "show me the audit trail of X" queries. |

**Key:** ✅ direct = dedicated tool · ✅ generic = works via `prepare_create_doc` / `get_list` etc. · 🟡 read only = exposed enough for inspection but not action (by design).

**Coverage of the 23-item admin surface: 22 ✅ direct or generic-full · 1 🟡 read-only by design (RQ Workers — OS layer, not a doctype).**

## What's shipping right now (in flight)

| Tier | Status | Highlights |
|---|---|---|
| **0 — File-URL hallucination guard** | ✅ shipped | `get_doc` resolves relative file paths via `frappe.utils.get_url` and emits `<field>_url` siblings. Prompt explicitly forbids inventing paths. |
| **A — Clickable Desk navigation** | ✅ shipped | New `navigateDesk` postMessage envelope; `<a>` interceptor in chat-ui; panel shim calls `frappe.set_route()`. |
| **Voice input** | ✅ shipped | Web Speech API via the mic button; live interim transcript; review-before-send. |
| **MCP timeouts + observability** | ✅ shipped | 45 s SSE inactivity guard, 30 s tool-call timeout, 15 s tools/list timeout, live `mcpTool` cards with elapsed timer. |
| **DATA FAITHFULNESS prompt** | ✅ shipped | Forces enumeration of every row, markdown tables for tabular data, verbatim numerics. |
| **Tier E — Skills system (COMPLETE)** | ✅ shipped | All 4 slices: `Lazychat Skill` doctype + 3 backend tools + Redis active set + system-prompt composer + `tools/list` filter + chat-ui Skills palette + **inline + Create skill form** + **active-skill chips above InputBar with one-click deactivate** + 4 starter skills seeded (AR Collections, Item Onboarding, Stock Reconciliation, Approval Bot). |
| **H1 — Knowledge Base (slice 1)** | ✅ shipped | New `Lazychat Knowledge Base` doctype + multi-format extractor (txt/md/csv/json/yaml/pdf/xlsx/docx) + 3 backend tools (`list_knowledge_bases`, `get_kb_files`, `search_kb`). Keyword paragraph search MVP, no embeddings yet. KB creation + file attachment via Desk. |
| **System diagnostics** | ✅ shipped | `get_system_info` (Frappe + ERPNext + installed apps + site config) and `get_user_info` (current user profile + roles). Agent can now self-introspect. |
| **H3 — KB chat-ui palette + citations** | ✅ shipped | New `Lazychat Knowledge Bases` section in `/` palette (mirrors Skills). Inline `+ Create knowledge base` form chains `prepare_create_kb` + commit in one round-trip. Each KB row has an ↗ button that navigates the parent ERPNext window (Tier A) to the KB doc so you can drop files into the standard Attachments sidebar. New `prepare_add_file_to_kb` tool re-attaches an existing File doctype row to a KB. Both system prompts teach the citation format: `[<file_name>](<file_url>)` with verbatim quotes. |
| **F — Inline charts (Vega-Lite)** | ✅ shipped | New `make_chart(spec, title?)` tool validates a Vega-Lite v5 spec and echoes it. New `'chart'` ContentKind in `contentDetector.ts` (detects via `$schema` URL or shape keys after JSON.parse). New `ChartBlock` component with `React.lazy` + `<Suspense>` — the ~500 KB `react-vega` + `vega-lite` bundle only fetches the first time a chart appears in the chat. Both system prompts teach the agent to: (a) call data tool first, (b) optionally call `make_chart` for tool-card visibility, (c) emit `[[lazychat:artifact kind="chart"]]<spec>[[/lazychat:artifact]]` with inline `data.values`, (d) caption in prose afterward. |
| **H2 — KB vector embeddings + hybrid retrieval** | ✅ shipped | New `Lazychat KB Chunk` doctype (parent_kb, file_doc, chunk_index, text, content_hash, embedding_model, embedding_blob — base64 little-endian float32). New `embeddings.py` module: paragraph-aware chunker (~500 tokens with 50-token overlap), provider lookup mirroring chat path, batched `/v1/embeddings` POST, hybrid retrieval (cosine top-20 + keyword top-20, RRF-fused to top-5). New File doctype `on_update` hook auto-indexes attachments on Lazychat Knowledge Base via `frappe.enqueue`. Content-hash dedupe makes re-indexing idempotent. New `reindex_kb(kb_name)` tool for first-time setup of existing KBs. `search_kb` now delegates to `hybrid_search` when chunks exist, falls back to keyword paragraph match otherwise. `get_kb_files` extended with `embedding_status` (`indexed | partial | keyword_only | pending`) + `chunk_count` per file. |
| **B-upload — Chat-side file picker** | ✅ shipped | New `prepare_upload_file(target_doctype, target_name, accept?)` two-phase tool. Returns `{file_picker: true, accept, confirm_with: "/upload TOKEN"}` so the agent narrates the next step. Panel shim's new `/upload TOKEN` slash command opens a native `<input type=file>`, POSTs to Frappe's `/api/method/upload_file`, then calls `commit_prepared_action(token, file_url)` — the new commit handler `attach_file` re-points the freshly-uploaded File row to the target doc. `commit_prepared` signature extended to accept `**extras` so future commit actions can pass runtime params. |
| **C-import — Bulk CSV import** | ✅ shipped | New `prepare_import_csv(doctype, csv_file_url, import_type?)` gated tool (allow_dangerous_tools + System Manager + /commit). Commit handler creates a `Data Import` doctype row and calls `start_import()` — actual row inserts happen async; watch via `list_my_jobs`. |
| **G — Interactive field picker for CSV export** | ✅ shipped | `export_list_to_csv` extended: when called with no `fields` arg, returns a field-picker preview with a `preview_token` + every doctype field annotated with `default_selected` from `in_list_view`, plus a `row_count_estimate` based on the active filters. New `mcpFieldPicker` Message kind on the type union; new `FieldPickerCard.tsx` renders a scrollable checkbox UI with search + All/None/Defaults presets + row count + Generate button. On Generate, the card calls `commit_prepared_action({token, fields: [...]})` directly — the new `export_csv` commit action runs the actual export and returns `{file_url, row_count}` which the card surfaces as a clickable download button. |

---

## Roadmap — toward a truly agentic platform

Each tier is independently shippable; the user can stop at any cutpoint.

### Tier B — Files

> "Show me the attachments on SO26001040." (✅ shipped) • "Download the PDF for invoice SI-007." (✅ via `export_doc_pdf`) • "Attach this file to SO-001." (planned)

| Tool | Status | What it does |
|---|---|---|
| `list_attachments(doctype, name)` | ✅ shipped | All `File` doctype rows linked to a parent doc, with absolute URLs ready to cite |
| `get_file_url(file)` | ✅ shipped | Resolve a File (by name or relative URL) to its public/private absolute URL via `frappe.utils.get_url`, permission-checked through the parent doc |
| `export_doc_pdf(doctype, name, print_format?)` | ✅ shipped | Renders a doc via Print Format → PDF, returns clickable URL (covers the original "get_download_url" use case) |
| `prepare_upload_file(target_doctype, target_name, accept?)` | ✅ shipped | Two-phase via the panel shim's `/upload TOKEN` slash command: opens native file picker → POSTs to Frappe's `/api/method/upload_file` → commits the staged attach with the new file_url. No new postMessage protocol needed — handled entirely as a slash command. |

### Tier C — Export & Import (✅ all shipped)

> "Export all open Sales Orders to CSV." • "Generate a PDF of SI-007." • "Import this CSV as new Items."

| Tool | Status | What it does |
|---|---|---|
| `export_list_to_csv(doctype, filters?, fields?, limit?)` | ✅ shipped | CSV up to 5000 rows; returns clickable download URL. With no `fields` → returns a field-picker preview (Tier G UI) instead of immediately writing. |
| `export_doc_pdf(doctype, name, print_format?)` | ✅ shipped | Renders Frappe print format → PDF, returns clickable URL |
| `prepare_import_csv(doctype, csv_file_url, import_type?)` | ✅ shipped | Bulk insert/update via Frappe Data Import. Gated (allow_dangerous_tools + System Manager + `/commit`). On commit, creates Data Import row + calls `start_import()`; rows inserted async via background queue. |

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

### Tier E — Skills / extensions system (✅ COMPLETE)

All four planned slices shipped:

- **Slice 1** — `Lazychat Skill` doctype, 3 backend tools (list/activate/deactivate), per-user Redis active set, system-prompt composition, `tools/list` filtering, chat-ui Skills palette with optimistic toggles, 2 starter skills seeded.
- **Slice 2** — inline `+ Create skill` form in the `/` palette. Reuses `prepare_create_doc` under the hood; `useSkills.create()` chains prepare+commit in one round-trip (the user IS the confirmation since the form is in-app, not LLM-staged).
- **Slice 3** — `SkillChips` component above the InputBar shows one chip per active skill with a one-click `×` to deactivate. Mirrors `EditingChip` / `QueuedChip` patterns.
- **Slice 4** — starter pack expanded to 4 skills: AR Collections, Item Onboarding, Stock Reconciliation, Approval Bot.

**Future (deferred):** marketplace-style discovery (JSON manifest + GitHub repo distribution); per-skill memory (skill-scoped session state); skill-driven custom slash commands.

### Tier F — Charts / data exploration (NEW, planned)

> "Plot sales by month for FY26." • "Show me a stacked bar of POs by supplier and status."

| New tool | What it does |
|---|---|
| `make_chart(type, data, title, options?)` | Returns a Vega-Lite or Recharts spec; chat-ui renders inline as an interactive chart |
| `explore_data(doctype, dimensions, measures)` | Combines `aggregate` + `make_chart` into a one-shot data-explore turn |

Renderer: extend the existing `[[lazychat:artifact]]` marker support so `kind="chart"` mounts a Recharts component (already a peer of LinkCard/Markdown). The agent gets a system-prompt block teaching the chart spec format. Also exposes a "Save chart" button that creates a `Dashboard Chart` doctype row.

### Tier H — Knowledge Base with vector embeddings (✅ slice 1 shipped, slice 2 planned)

**Slice 1 (shipped May 5):** keyword paragraph search across attached files. New `Lazychat Knowledge Base` doctype + multi-format extractor (txt/md/csv/json/yaml/pdf/xlsx/docx) + 3 backend tools. KB creation + file attachment via Desk's standard sidebar.

**Slice 3 (shipped May 5):** chat-ui Knowledge Bases palette section (mirrors Skills) + inline `+ Create knowledge base` form (`prepare_create_kb` + commit in one round-trip) + `prepare_add_file_to_kb` for re-attaching existing files + per-row ↗ to open the KB in Desk for upload. Both system prompts teach the `[file](/files/file)` citation format with verbatim quoting and forbid path fabrication.

**Slice 2 (planned, ~3–4 days):** vector embeddings for semantic search.

- New `Lazychat KB Chunk` child doctype storing `(file, chunk_index, text, embedding_blob, embedding_model)`. Indexing happens on file attach (Frappe `on_update` hook on the File doctype). Re-indexes on file modify.
- Embeddings generated via the user's configured LLM provider's `/embeddings` endpoint (OpenAI text-embedding-3-small as default for OpenAI-compatible providers; Voyage / Cohere supported via the existing provider-adapter pattern). Falls back to local sentence-transformers if a small embedding model is configured.
- `search_kb` upgraded: when chunks have embeddings, ranks by cosine similarity (top-K with score threshold). Falls back to keyword search when embeddings are missing.
- Hybrid retrieval: combines vector similarity + keyword filter (BM25-lite) for higher precision than either alone.
- Optional: cross-encoder reranker for the top-20 → top-5 narrowing (defer if scope creeps).

**Slice 3 (planned, ~2 days):** chat-ui Knowledge Bases panel.

- New `/kb` palette section listing KBs + file counts + a "+ Create KB" button (mirrors Skills slice 2 pattern).
- `prepare_create_kb` and `prepare_add_file_to_kb` two-phase tools so the agent can offer to spin up a new KB from the chat.
- Citation rendering: when the agent quotes from a `search_kb` result, render the source as a clickable Tier-A markdown link (`[hr-handbook.pdf #page-12](/files/...)`).

### Tier G — Smart export UX with field picker (✅ shipped)

Your original ask: *"I want to article master export and fields name selection which fields we want export … smooth and csv file download option like Claude and ChatGPT do."*

Shipped UX:
1. You: *"Export the Item master to CSV."*
2. Agent calls `export_list_to_csv(doctype="Item")` with no `fields` → tool stages a token + returns the field-picker preview.
3. Chat-ui renders the new `<FieldPickerCard>` inline: scrollable checkbox list with every Item field, default-checked per `in_list_view`, search filter (live), All / None / Defaults presets, row-count estimate.
4. You tick checkboxes → click **Generate CSV (N)** → card POSTs `commit_prepared_action({token, fields: [...]})` → backend writes the actual CSV → card flips to a "CSV ready · X rows · Y fields" state with a clickable download button.

Reused the existing two-phase pattern + the same `commit_prepared_action` endpoint extended with a `fields` extra. New component lives at [FieldPickerCard.tsx](/Users/<you>/Desktop/code-chat/lazychat.ai/apps/chat-ui/src/components/messages/FieldPickerCard.tsx).

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
- **Skills slice 1 only** — skill creation today is via `Desk → New Lazychat Skill`; inline `/skills create` form ships in slice 2 (Tier E).
- **No inline charts** — agent can describe data but can't draw it (Tier F).
- **`get_doc` truncates child tables to 25 rows** server-side; for full data the agent uses `get_list`. The `_note` field tells it when truncation happened.
- **Browser-LLM tool result cap is 60 KB** (after May 5 bump from 12 KB). For very large docs the result still gets truncated with a notice.
- **Voice input** needs Chrome/Edge/Safari — Firefox doesn't ship the Web Speech API.

---

## Feedback / requests

Open an issue at [github.com/soumyasethy/lazychat-mcp-erpnext](https://github.com/soumyasethy/lazychat-mcp-erpnext/issues). For chat-UI behavior specifically, [github.com/soumyasethy/lazychat.ai](https://github.com/soumyasethy/lazychat.ai/issues).
