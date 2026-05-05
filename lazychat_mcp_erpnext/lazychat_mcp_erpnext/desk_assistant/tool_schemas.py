TOOL_SCHEMAS = [
	{
		"name": "get_list",
		"description": "List documents with filters. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string", "description": "DocType name"},
				"filters": {"type": "object", "description": "Field filters as JSON object"},
				"fields": {
					"type": "array",
					"items": {"type": "string"},
					"description": "Fields to return",
				},
				"limit": {"type": "integer", "default": 20},
			},
			"required": ["doctype"],
		},
	},
	{
		"name": "get_doc",
		"description": "Fetch a single document by name if the user can read it.",
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
			},
			"required": ["doctype", "name"],
		},
	},
	{
		"name": "get_current_context",
		"description": "Return the ERPNext desk context passed from the widget (doctype, docname, route).",
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "describe_doctype",
		"description": "Return field metadata (name, fieldtype, label, options, reqd) for a DocType so you know which values to provide before staging a create or update. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {"doctype": {"type": "string"}},
			"required": ["doctype"],
		},
	},
	{
		"name": "prepare_create_doc",
		"description": (
			"STAGE creating a new document. Does NOT actually create. Returns "
			"{preview_token, summary, preview, confirm_with}. After calling, "
			"narrate the preview to the user and tell them EXACTLY: "
			"'Reply with `/commit TOKEN` to apply, or anything else to cancel.' "
			"Never call any commit tool yourself — the /commit slash command is "
			"handled outside the agent loop."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"values": {
					"type": "object",
					"description": "Field name → value map. For child tables use a list of dicts.",
				},
			},
			"required": ["doctype", "values"],
		},
	},
	{
		"name": "prepare_update_doc",
		"description": (
			"STAGE updating an existing document. Does NOT actually update. Returns "
			"{preview_token, summary, diff, confirm_with}. After calling, narrate "
			"the diff and ask the user to '/commit TOKEN'."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
				"patch": {
					"type": "object",
					"description": "Field name → new value map. Only include changed fields.",
				},
			},
			"required": ["doctype", "name", "patch"],
		},
	},
	{
		"name": "prepare_submit_doc",
		"description": (
			"STAGE submitting (workflow-submit, docstatus 0→1) an existing document. "
			"Does NOT actually submit. Returns {preview_token, summary, confirm_with}. "
			"Ask the user to '/commit TOKEN'."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
			},
			"required": ["doctype", "name"],
		},
	},
	{
		"name": "list_workflow_actions",
		"description": (
			"List workflow transitions available from the current state of a document. "
			"Read-only. Returns {current_state, transitions: [{action, next_state, allowed_role}]}."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
			},
			"required": ["doctype", "name"],
		},
	},
	{
		"name": "prepare_workflow_action",
		"description": (
			"STAGE applying a workflow action (e.g. 'Approve', 'Reject') to a document. "
			"Validates the action is allowed from the current state. Does NOT actually apply. "
			"Returns {preview_token, summary, confirm_with}. Ask the user to '/commit TOKEN'."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
				"action": {"type": "string", "description": "The workflow action label as returned by list_workflow_actions"},
			},
			"required": ["doctype", "name", "action"],
		},
	},
	{
		"name": "prepare_add_comment",
		"description": (
			"STAGE adding a comment to a document's activity log. Does NOT actually add. "
			"Returns {preview_token, summary, preview, confirm_with}. Ask the user to '/commit TOKEN'."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
				"text": {"type": "string"},
			},
			"required": ["doctype", "name", "text"],
		},
	},
	{
		"name": "prepare_assign_to",
		"description": (
			"STAGE assigning a document to a Frappe User (creates a ToDo). Does NOT actually assign. "
			"Returns {preview_token, summary, confirm_with}. Ask the user to '/commit TOKEN'."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
				"user": {"type": "string", "description": "User email/id (must exist in User doctype)"},
				"description": {"type": "string", "description": "Optional ToDo description"},
			},
			"required": ["doctype", "name", "user"],
		},
	},
	{
		"name": "aggregate",
		"description": (
			"Group-and-aggregate a doctype. Read-only. Useful for analytics like "
			"'top customers by sales this quarter' (group_by=customer, function=sum, field=grand_total). "
			"Returns {rows: [{group_by_value, value}]} sorted desc by value."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"function": {"type": "string", "enum": ["sum", "avg", "count", "min", "max"]},
				"field": {"type": "string", "description": "Field to aggregate (use 'name' for count)"},
				"group_by": {"type": "string", "description": "Optional field to group by"},
				"filters": {"type": "object", "description": "Field filters as JSON object"},
				"limit": {"type": "integer", "default": 50},
			},
			"required": ["doctype", "function", "field"],
		},
	},
	{
		"name": "dashboard_chart_data",
		"description": "Return the rendered data of an existing Frappe Dashboard Chart by name. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {"name": {"type": "string"}},
			"required": ["name"],
		},
	},
	{
		"name": "number_card_value",
		"description": "Return the current value of a Frappe Number Card by name. Only Document Type cards are supported. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {"name": {"type": "string"}},
			"required": ["name"],
		},
	},
	{
		"name": "search_global",
		"description": "Full-text search across all doctypes' indexed content. Read-only. Use when the user mentions a name/term you don't know the exact ID for.",
		"input_schema": {
			"type": "object",
			"properties": {
				"query": {"type": "string"},
				"doctypes": {"type": "array", "items": {"type": "string"}, "description": "Optional doctype filter"},
				"limit": {"type": "integer", "default": 20},
			},
			"required": ["query"],
		},
	},
	{
		"name": "count_doc",
		"description": "Fast row count for a doctype with optional filters. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"filters": {"type": "object"},
			},
			"required": ["doctype"],
		},
	},
	{
		"name": "get_value",
		"description": "Get a single field value from a doc. Faster than get_doc for one field. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
				"fieldname": {"type": "string"},
			},
			"required": ["doctype", "name", "fieldname"],
		},
	},
	{
		"name": "get_doctype_links",
		"description": "Find documents in OTHER doctypes that link to this doc (e.g. invoices for a customer, payments for an invoice). Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
			},
			"required": ["doctype", "name"],
		},
	},
	{
		"name": "list_reports",
		"description": "List available Frappe Reports (Query / Script / Report Builder). Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {"module": {"type": "string", "description": "Optional module filter"}},
		},
	},
	{
		"name": "run_report",
		"description": "Execute a Frappe Report by name with optional filters. Returns columns + rows (truncated to 200). Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"name": {"type": "string"},
				"filters": {"type": "object"},
			},
			"required": ["name"],
		},
	},
	{
		"name": "get_stock_balance",
		"description": "ERPNext: stock balance (qty) for an item, optionally at a specific warehouse and date. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"item_code": {"type": "string"},
				"warehouse": {"type": "string"},
				"posting_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
			},
			"required": ["item_code"],
		},
	},
	{
		"name": "get_account_balance",
		"description": "ERPNext: balance on a chart-of-accounts Account, optionally as of a date. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"account": {"type": "string"},
				"date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
			},
			"required": ["account"],
		},
	},
	{
		"name": "get_outstanding",
		"description": "ERPNext: list of submitted invoices with outstanding > 0 for a Customer (receivables) or Supplier (payables). Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"party_type": {"type": "string", "enum": ["Customer", "Supplier"]},
				"party": {"type": "string"},
			},
			"required": ["party_type", "party"],
		},
	},
	{
		"name": "get_open_invoices",
		"description": "ERPNext: open Sales/Purchase Invoices (docstatus=1, outstanding>0). If party omitted, returns all. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"party_type": {"type": "string", "enum": ["Customer", "Supplier"]},
				"party": {"type": "string"},
				"limit": {"type": "integer", "default": 50},
			},
			"required": ["party_type"],
		},
	},
	{
		"name": "get_sales_summary",
		"description": "ERPNext: aggregate Sales Invoice grand_total grouped by customer/owner/company/currency/status/posting_date in a date window. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"group_by": {"type": "string", "enum": ["customer", "owner", "company", "currency", "status", "posting_date"]},
				"from_date": {"type": "string"},
				"to_date": {"type": "string"},
				"customer": {"type": "string"},
				"limit": {"type": "integer", "default": 50},
			},
		},
	},
	{
		"name": "get_item_price",
		"description": "ERPNext: price list rates for an item across all (or a specific) Price List. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"item_code": {"type": "string"},
				"price_list": {"type": "string"},
			},
			"required": ["item_code"],
		},
	},
	{
		"name": "get_company_defaults",
		"description": "Return current user's defaults: company, currency, fiscal year, language, timezone, plus user roles. Read-only.",
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "prepare_send_email",
		"description": (
			"STAGE sending an email via Frappe (and optionally link to a doc's communication log). "
			"Does NOT actually send. Returns {preview_token, summary, preview, confirm_with}. "
			"Ask the user to '/commit TOKEN'. NOTE: gated by site_config 'lazychat_allow_email' = true."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"recipients": {"type": "array", "items": {"type": "string"}, "description": "Email addresses"},
				"subject": {"type": "string"},
				"content": {"type": "string", "description": "HTML or plain text body"},
				"doctype": {"type": "string", "description": "Optional reference doctype"},
				"name": {"type": "string", "description": "Optional reference doc name"},
			},
			"required": ["recipients", "subject"],
		},
	},
	{
		"name": "prepare_delete_doc",
		"description": (
			"STAGE deleting a document (irreversible). Does NOT actually delete. "
			"Returns {preview_token, summary, confirm_with}. Ask the user to '/commit TOKEN'. "
			"Will fail at commit if other docs link to this one."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
			},
			"required": ["doctype", "name"],
		},
	},
	{
		"name": "search_doctype",
		"description": "Find DocTypes whose NAME matches a query (e.g. user says 'invoices' → returns Sales Invoice, Purchase Invoice, etc). Different from search_global which searches doc CONTENT.",
		"input_schema": {
			"type": "object",
			"properties": {
				"query": {"type": "string"},
				"limit": {"type": "integer", "default": 20},
			},
			"required": ["query"],
		},
	},
	{
		"name": "search_link",
		"description": "Autocomplete-style search for a target doc by partial name in a Link field's target doctype. Use to resolve a fuzzy user reference like 'find Customer Acme' → returns matching Customer names.",
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string", "description": "Target doctype to search in"},
				"query": {"type": "string", "description": "Partial text to match"},
				"limit": {"type": "integer", "default": 10},
			},
			"required": ["doctype"],
		},
	},
	{
		"name": "get_pending_approvals",
		"description": "List Workflow Actions awaiting decision by the current user (or named user, if you are System Manager). Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {
				"user": {"type": "string", "description": "Optional — defaults to current user"},
				"limit": {"type": "integer", "default": 50},
			},
		},
	},
	{
		"name": "report_requirements",
		"description": "Get a Report's metadata + filter requirements. Call BEFORE run_report so you know what filters to supply. Read-only.",
		"input_schema": {
			"type": "object",
			"properties": {"name": {"type": "string"}},
			"required": ["name"],
		},
	},
	{
		"name": "list_user_dashboards",
		"description": "List Frappe Dashboards visible to the current user (owned + shared + default-public). Read-only.",
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "extract_file_content",
		"description": (
			"Read text content from a File doctype (by File.name OR file_url). "
			"UTF-8 text only — returns error for binary. Permission inherited from the attached doc. "
			"Read-only."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"file": {"type": "string", "description": "File doc name or file_url"},
				"max_chars": {"type": "integer", "default": 20000},
			},
			"required": ["file"],
		},
	},
	{
		"name": "prepare_run_sql",
		"description": (
			"STAGE running a raw SELECT (or WITH ... SELECT) SQL query against the Frappe DB. "
			"Does NOT actually execute. Returns {preview_token, summary, preview, confirm_with}. "
			"Show the user the EXACT query and ask them to '/commit TOKEN'. "
			"REQUIRES: site_config 'lazychat_allow_dangerous_tools'=true AND System Manager role. "
			"WARNING: bypasses Frappe per-user permission filters — use only when get_list/aggregate cannot express the query."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"query": {"type": "string", "description": "SELECT-only SQL query"},
				"limit": {"type": "integer", "default": 200, "description": "Max rows to return (capped at 1000)"},
			},
			"required": ["query"],
		},
	},
	{
		"name": "prepare_run_python",
		"description": (
			"STAGE running Python code with FULL access to frappe (and pandas/numpy if installed). "
			"Does NOT actually execute. Returns {preview_token, summary, preview, confirm_with}. "
			"Show the user the EXACT code and ask them to '/commit TOKEN'. "
			"REQUIRES: site_config 'lazychat_allow_dangerous_tools'=true AND System Manager role. "
			"Set the result by assigning to `_result` (or write a single expression to return its value). "
			"Print statements are captured to stdout."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"code": {"type": "string"},
				"timeout": {"type": "integer", "default": 30},
			},
			"required": ["code"],
		},
	},
	{
		"name": "prepare_share_doc",
		"description": (
			"STAGE sharing a document with a Frappe User (read-only by default). "
			"Does NOT actually share. Returns {preview_token, summary, confirm_with}. Ask user to '/commit TOKEN'."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
				"user": {"type": "string", "description": "User email/id"},
				"read": {"type": "boolean", "default": True},
				"write": {"type": "boolean", "default": False},
			},
			"required": ["doctype", "name", "user"],
		},
	},
	{
		"name": "get_audit_trail",
		"description": (
			"Aggregate every 'who-changed-what-when' event for a single document into one timeline: "
			"creation, scalar field changes (Version doctype), comments + workflow notes (Comment doctype), "
			"and Activity Log entries tied to the doc. Returns events sorted newest-first with kind, ts, "
			"user, and a summary (or field list / snippet). Use this when the user asks 'who edited X?', "
			"'audit trail of X', 'show changes to X', or wants accountability before approving."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
				"limit": {"type": "integer", "default": 100, "description": "Cap per source (Version/Comment/Activity); cap 200."},
			},
			"required": ["doctype", "name"],
		},
	},
	{
		"name": "export_list_to_csv",
		"description": (
			"Export a doctype list to a downloadable CSV file. Writes to /private/files/ with a timestamped name "
			"and returns {file_url, absolute_url, file_name, row_count}. Permission-checked at the doctype level. "
			"Cap 5000 rows. Surface the absolute_url as a markdown link in the chat so the user can click to download."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"filters": {"type": "object"},
				"fields": {"type": "array", "items": {"type": "string"}, "description": "Columns to include. Required."},
				"limit": {"type": "integer", "default": 1000, "description": "Cap 5000."},
			},
			"required": ["doctype", "fields"],
		},
	},
	{
		"name": "export_doc_pdf",
		"description": (
			"Render a single document via its Print Format and save as PDF in /private/files/. Returns "
			"{file_url, absolute_url, file_name, size_bytes}. If print_format omitted, uses the doctype's default. "
			"Surface the absolute_url as a markdown link. Permission: Read on the source doc."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
				"print_format": {"type": "string", "description": "Optional Print Format name; default = doctype default."},
			},
			"required": ["doctype", "name"],
		},
	},
	{
		"name": "list_my_jobs",
		"description": (
			"List background jobs (RQ Job doctype rows) queued by the calling user, newest-first. "
			"Each row: {name (job_id), status, queue, job_name, creation, started_at, ended_at, exc_info}. "
			"Read-only. For cross-user job listing use get_list('RQ Job', ...) directly."
		),
		"input_schema": {
			"type": "object",
			"properties": {"limit": {"type": "integer", "default": 20, "description": "Cap 100."}},
		},
	},
	{
		"name": "cancel_job",
		"description": (
			"Cancel a queued or running RQ Job by id. Requires Write permission on the RQ Job row. "
			"Returns the new status. Direct action — no /commit needed (cancellation is reversible: "
			"just re-queue the underlying method)."
		),
		"input_schema": {
			"type": "object",
			"properties": {"job_id": {"type": "string", "description": "RQ Job doctype name (= job id)."}},
			"required": ["job_id"],
		},
	},
	{
		"name": "prepare_rename_doc",
		"description": (
			"STAGE renaming a document. Wraps Frappe's rename tool. Returns "
			"{preview_token, summary, confirm_with}. After staging, ask the user "
			"to '/commit TOKEN' to apply. If new_name already exists and merge=true, "
			"records linking to the old name will point at the merged doc instead. "
			"Requires Write permission on the source doc."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string", "description": "Current doc name"},
				"new_name": {"type": "string"},
				"merge": {"type": "boolean", "default": False, "description": "If new_name exists, merge into it instead of failing."},
			},
			"required": ["doctype", "name", "new_name"],
		},
	},
	{
		"name": "list_doc_versions",
		"description": (
			"List the change-history (Version doctype rows) for a single document, "
			"newest first. Each entry includes the version_id, who made the change, "
			"when, and which scalar field values were modified (with old/new). Use "
			"before prepare_revert_doc to let the user pick which version to undo. "
			"Read-only."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
				"limit": {"type": "integer", "default": 20, "description": "Max versions returned (cap 50)."},
			},
			"required": ["doctype", "name"],
		},
	},
	{
		"name": "prepare_revert_doc",
		"description": (
			"STAGE reverting a document to its state BEFORE a specific version was "
			"recorded. Returns {preview_token, summary, diff, confirm_with}. The "
			"`diff` shows current value vs. revert-target so the user can confirm. "
			"Only handles scalar field changes — child-table revisions need a manual "
			"prepare_update_doc. After staging, ask the user to '/commit TOKEN' to apply."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"name": {"type": "string"},
				"version_id": {"type": "string", "description": "From list_doc_versions[].version_id."},
			},
			"required": ["doctype", "name", "version_id"],
		},
	},
	{
		"name": "get_system_info",
		"description": (
			"Return what's running on this site: Frappe version, ERPNext version (if installed), "
			"every installed app with its version, site name, country, time zone, language, "
			"date format, currency, Python version. Use this when the user asks 'what version', "
			"'what's installed', 'system info', etc."
		),
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "get_user_info",
		"description": (
			"Return the calling user's profile: email/id, full name, language, time zone, "
			"enabled flag, and full role list. Useful for 'who am I', 'what permissions do I have', "
			"or to tailor an answer to the user's role."
		),
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "list_knowledge_bases",
		"description": (
			"List Lazychat Knowledge Base rows the user can see (own + public, enabled). "
			"Each KB carries attached files (PDF/XLSX/CSV/TXT/MD/DOCX) the agent can search. "
			"Returns rows with {name, title, description, is_public, file_count}. Read-only."
		),
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "get_kb_files",
		"description": (
			"List the files attached to a specific Knowledge Base by kb_name (slug). "
			"Returns rows with {name, file_name, file_url, file_size, file_type}. Read-only."
		),
		"input_schema": {
			"type": "object",
			"properties": {"kb_name": {"type": "string", "description": "Knowledge Base slug, e.g. 'product-catalog'"}},
			"required": ["kb_name"],
		},
	},
	{
		"name": "search_kb",
		"description": (
			"Keyword paragraph search across files attached to one or all visible Knowledge Bases. "
			"Returns up to max_chunks paragraphs that contain ALL query terms (case-insensitive), "
			"each with its source file name + URL. Multi-format extraction: txt/md/csv/json/yaml, "
			"pdf, xlsx, docx. When kb_name is omitted, searches across every KB the user can see. "
			"Use this whenever the user asks something that might be answered from internal docs."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"query": {"type": "string", "description": "Free-text keyword query."},
				"kb_name": {"type": "string", "description": "Optional. Restrict to one KB by slug."},
				"max_chunks": {"type": "integer", "default": 8, "description": "Max paragraphs returned (cap 20)."},
			},
			"required": ["query"],
		},
	},
	{
		"name": "prepare_create_kb",
		"description": (
			"STAGE creating a new Lazychat Knowledge Base. Returns "
			"{preview_token, summary, confirm_with}. After staging, ask the user to "
			"'/commit TOKEN' to apply. is_public=true is System Manager only. If "
			"`slug` is omitted it's auto-derived from `title` (lowercase, kebab-case)."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"title": {"type": "string", "description": "Human-friendly name."},
				"slug": {"type": "string", "description": "Optional kebab-case slug. Auto-derived from title if omitted."},
				"description": {"type": "string"},
				"is_public": {"type": "boolean", "default": False},
			},
			"required": ["title"],
		},
	},
	{
		"name": "prepare_add_file_to_kb",
		"description": (
			"STAGE re-attaching an existing File doctype row to a Lazychat Knowledge "
			"Base. Use when the file is already uploaded somewhere in Frappe (got its "
			"file_url from list_attachments, get_doc, or a manual upload) and the user "
			"wants to add it to a KB. Two-phase via /commit. To upload a NEW file, use "
			"the Desk attachment sidebar on the KB doc directly (no chat-side upload yet)."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"kb_name": {"type": "string", "description": "Slug of the target KB."},
				"file_url": {"type": "string", "description": "/files/... or /private/files/... — must already exist as a File doctype row."},
			},
			"required": ["kb_name", "file_url"],
		},
	},
	{
		"name": "list_skills",
		"description": (
			"List the user's installed skills (own + public). Each skill is a focused "
			"agent persona — system prompt + optional tool subset — that the user can "
			"activate to specialise the agent. Returns rows with {name, title, description, "
			"is_public, allowed_tools, active}. Read-only; does not change state."
		),
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "activate_skill",
		"description": (
			"Activate a skill so its system prompt is appended to the base prompt "
			"and (if it declares allowed_tools) the agent's tool view is restricted "
			"to that subset. Multiple skills can stack. Effect persists for the user "
			"across tabs and sessions until deactivate_skill or the 7-day TTL expires."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"skill_name": {"type": "string", "description": "Skill slug, e.g. 'ar-collections'"}
			},
			"required": ["skill_name"],
		},
	},
	{
		"name": "deactivate_skill",
		"description": "Remove a skill from the user's active set. No-op if it wasn't active.",
		"input_schema": {
			"type": "object",
			"properties": {
				"skill_name": {"type": "string"}
			},
			"required": ["skill_name"],
		},
	},
]
