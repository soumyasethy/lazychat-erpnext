TOOL_SCHEMAS = [
	{
		"name": "get_list",
		"description": (
			"List documents with filters. Read-only. Default limit 20 (cheap schema "
			"probes). Pass an explicit limit when the user wants more rows — there is "
			"NO upper bound; the chat-ui truncates display at ~250 KB if the result "
			"won't fit your context window (with a clear notice). For TOTALS/COUNTS "
			"NEVER trust len(rows): always call count_doc or aggregate. For TRUE BULK "
			"that exceeds your context, use export_list_to_csv (writes a file, no "
			"context cost). Pass limit=0 (or negative) for unbounded fetch."
		),
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
				"limit": {
					"type": "integer",
					"default": 20,
					"description": "Rows to fetch. Default 20. Pass a larger explicit value (e.g. 5000) for analytics. Use <= 0 for unbounded.",
				},
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
		"name": "get_form_prefill_capabilities",
		"description": (
			"Return the live _lz_items URL-prefill whitelist for a doctype "
			"(parent fields + item child-row fields the persistent helper "
			"Client Script honors). Call this BEFORE composing a Query Report "
			"with HTML buttons that prefill a new doc — the response tells you "
			"exactly which fields you can encode in the URL. Returns "
			"{doctype, helper_installed, is_supported_target, url_pattern, "
			"parent_whitelist, item_whitelist, example_payload}. Doctypes with "
			"helper_installed=true: Purchase Invoice, Sales Invoice, Purchase "
			"Receipt, Delivery Note (others can be added via install.py)."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string", "description": "Target DocType (must exist)"},
			},
			"required": ["doctype"],
		},
	},
	{
		"name": "prepare_form_prefill",
		"description": (
			"Stage a form-prefill payload for a new-doc URL. Returns a short opaque "
			"token and a tiny URL (`/app/<dt>/new?_lz_token=<22-char>`) that the "
			"persistent Client Script will fetch and apply via `frappe.route_options` "
			"on form load. ALWAYS prefer this over the legacy `_lz_items=<base64>` URL "
			"convention when items count >= 5 OR total payload could exceed ~1 KB — "
			"the URL-embedded base64 approach hits HTTP 414 Request-URI Too Long for "
			"large reports (50+ rows). Token is single-use, user-bound, 5-min TTL "
			"(override via `ttl` arg, max 3600s). Re-checks create permission at "
			"staging time. Use the returned `url` directly in Query Report HTML "
			"link buttons (e.g. `<a href=\"<url>\">Debit Note</a>`)."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {
					"type": "string",
					"description": "Target DocType (e.g. 'Purchase Invoice', 'Sales Invoice')."
				},
				"parent_fields": {
					"type": "object",
					"description": "Parent-level field values to apply (e.g. {'supplier': 'X', 'is_return': 1, 'return_against': 'PI-001'}). May be empty."
				},
				"items": {
					"type": "array",
					"description": "List of item-row dicts to populate the items child table. Each dict can include item_code, qty, rate, uom, warehouse, pr_detail, etc. (see `get_form_prefill_capabilities(doctype)` for the whitelisted keys per doctype). May be empty.",
					"items": {"type": "object"},
				},
				"ttl": {
					"type": "integer",
					"description": "Optional TTL seconds (clamped to [60, 3600]; default 300)."
				},
			},
			"required": ["doctype"],
		},
	},
	{
		"name": "get_doctype_relationships",
		"description": (
			"Return canonical row-level + parent-level join hints for a doctype. "
			"Use this BEFORE writing variance/comparison SQL — the response tells "
			"you the EXACT join pattern (e.g. for Purchase Invoice Item, the row "
			"link to Purchase Receipt Item is via `pr_detail`, NOT `item_code`). "
			"Includes curated overrides for ERPNext's most-mismatched pairs: "
			"PR↔PI, SO↔SI, SI↔DN, Stock Ledger Entry↔PR, PR↔PO. Falls back to "
			"the generic describe_doctype links for uncurated doctypes."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string", "description": "Target DocType (must exist)"},
			},
			"required": ["doctype"],
		},
	},
	{
		"name": "find_join_path",
		"description": (
			"Discover the canonical SQL join chain between two doctypes by walking "
			"Frappe's DocField metadata graph (Link / Table fields) with BFS. "
			"Returns the shortest hop list, or curated canonical when one exists "
			"(e.g. Purchase Invoice → Payment Entry returns the route via "
			"`Payment Entry Reference` child table including the required "
			"`reference_doctype = 'Purchase Invoice'` predicate). USE THIS BEFORE "
			"writing any cross-doctype JOIN — eliminates the need to memorize join "
			"shapes and prevents the most common SQL bug class (wrong join key, "
			"missing reference_doctype filter, item_code-only joins). Each hop "
			"includes `via_field`, `via_kind` (link / parent_to_child / "
			"child_to_parent / curated), and `on_template` with `<a>`/`<b>` alias "
			"placeholders for the FROM and TARGET tables. Curated routes carry a "
			"`warning` field with the gotcha — always read it. Output: "
			"{found, from, to, hops[], hop_count, canonical}."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"from_doctype": {"type": "string", "description": "Source DocType (e.g. 'Purchase Invoice')"},
				"to_doctype":   {"type": "string", "description": "Target DocType (e.g. 'Payment Entry')"},
				"max_hops":     {"type": "integer", "description": "Max BFS depth (1-5, default 3)", "default": 3},
			},
			"required": ["from_doctype", "to_doctype"],
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
		"name": "run_sql_select",
		"description": (
			"AUTO-EXECUTE a raw SELECT (or WITH ... SELECT) SQL query against the Frappe DB and return rows IMMEDIATELY in this same turn. "
			"USE THIS for analytical queries — it's the right tool for compound questions where you need data back to compare/branch/synthesize. "
			"NO /commit step, NO Apply button — the query runs as soon as you call it and you get rows in the tool result. "
			"REQUIRES: site_config 'lazychat_allow_dangerous_tools'=true AND System Manager role (same gates as prepare_run_sql). "
			"VALIDATED SELECT-only: regex blocks DML/DDL keywords (INSERT/UPDATE/DELETE/DROP/ALTER/...) and multi-statement queries — non-SELECT input is rejected before execution. "
			"WARNING: bypasses Frappe per-user permission filters — only call when get_list/aggregate/count_doc cannot express the query. "
			"SCHEMA-FIRST: ALWAYS call describe_doctype on every doctype you reference BEFORE this — schema-hallucinated column names (the #1 failure mode) come back as 'Unknown column' OperationalErrors. "
			"CHILD-TABLE LINKS: in ERPNext, cross-document references usually live on the child Item table, not the parent (e.g. `Purchase Receipt Item.purchase_order`, NOT a column on `tabPurchase Receipt`). JOIN through the child on `child.parent = parent.name`. "
			"ERROR RECOVERY: if the query fails, the response includes a structured 'hint' field — read it, re-verify schema, retry with corrections. Do NOT retry the same query unchanged."
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
		"name": "prepare_run_sql",
		"description": (
			"STAGE a raw SELECT SQL query for user-approval gating (returns {preview_token, summary, preview} — does NOT execute). "
			"For analytical queries you should use `run_sql_select` instead — it returns rows immediately so you can compare/branch/synthesize in the same turn. "
			"Use `prepare_run_sql` ONLY when the user has explicitly asked to review the SQL before it runs (rare). "
			"REQUIRES: site_config 'lazychat_allow_dangerous_tools'=true AND System Manager role. "
			"The chat-ui auto-renders an inline Apply button for the user; do NOT instruct them to type /commit TOKEN. "
			"Same SCHEMA-FIRST and CHILD-TABLE LINKS rules as run_sql_select."
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
		"name": "run_python_readonly",
		"description": (
			"AUTO-EXECUTE read-only Python with frappe access (and pandas/numpy if installed) and return the result IMMEDIATELY in this same turn. "
			"USE THIS for analytical Python that needs data manipulation beyond what run_sql_select can express (pandas pivots, multi-pass computations, complex group-by-then-filter, etc.) — same in-turn semantics as run_sql_select, no /commit, no Apply button. "
			"REQUIRES: site_config 'lazychat_allow_dangerous_tools'=true AND System Manager role. "
			"READ-ONLY ENFORCED in two layers: "
			"(1) Static AST scan REJECTS the code BEFORE execution if it contains imports of subprocess/os/sys/shutil/socket/urllib/requests/http/smtplib/ftplib/telnetlib/ssl/ctypes/multiprocessing, or calls to file/dynamic-code built-ins (open, dynamic compile/eval/exec, __import__, input, breakpoint), or explicit frappe.db.set_value/set_many/delete/sql_ddl/multisql/commit/rollback/savepoint calls, or frappe.sendmail/publish_realtime/publish_progress/enqueue/enqueue_doc/delete_doc/rename_doc/copy_doc calls. "
			"(2) Runtime savepoint ALWAYS rolls back any DB mutations after the code runs — even if a write somehow gets past the AST scan (.save() / .insert() / .submit()), it's undone before this tool returns. "
			"Set the result by assigning to `_result` (or write a single expression). Print statements captured to stdout (cap 8 KB). "
			"For mutation work that genuinely needs to land in the DB (creating docs, sending emails, etc.), use the prepare_* tools instead — they go through the two-phase Apply gate."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"code": {"type": "string"},
			},
			"required": ["code"],
		},
	},
	{
		"name": "prepare_run_python",
		"description": (
			"STAGE Python code for user-approval gating (returns {preview_token, summary, preview} — does NOT execute). "
			"For analytical Python you should use `run_python_readonly` instead — it returns the result immediately so you can compare/branch/synthesize in the same turn, and DB mutations are auto-rolled-back. "
			"Use `prepare_run_python` ONLY when the code GENUINELY mutates the DB or has side-effects you want the user to approve before running (rare). "
			"REQUIRES: site_config 'lazychat_allow_dangerous_tools'=true AND System Manager role. "
			"Set the result by assigning to `_result`. Print statements captured to stdout. "
			"Same SCHEMA-FIRST and CHILD-TABLE LINKS rules as the other SQL/Python tools. "
			"ERROR RECOVERY: DB errors at /commit time return a structured hint on the next turn — read the hint, re-verify schema, re-stage."
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
		"name": "prepare_upload_file",
		"description": (
			"STAGE attaching a NEW file to a document. The chat-ui detects the response and "
			"renders an Upload button — the user clicks, picks a file, and the chat-ui "
			"automatically uploads + commits the attachment. Returns {preview_token, "
			"file_picker: true, accept, target_doctype, target_name, summary, confirm_with}. "
			"Permission: Write on the target doc. Use when the user asks 'attach this file to X' "
			"and they need to pick a file from their machine. To attach an EXISTING File doctype "
			"row, use prepare_add_file_to_kb (for KBs) or prepare_update_doc."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"target_doctype": {"type": "string"},
				"target_name": {"type": "string"},
				"accept": {"type": "string", "description": "Optional MIME or extension filter, e.g. 'application/pdf' or '.csv,.xlsx'."},
			},
			"required": ["target_doctype", "target_name"],
		},
	},
	{
		"name": "prepare_import_csv",
		"description": (
			"STAGE bulk-importing rows into a doctype from a CSV file via Frappe's "
			"Data Import. Gated identically to prepare_run_sql / prepare_run_python "
			"(requires allow_dangerous_tools site flag + System Manager role + /commit). "
			"On commit, creates a Data Import doctype row pointing at the CSV and calls "
			"start_import() — actual row inserts happen async in the background queue, "
			"watch via list_my_jobs. The CSV must already be uploaded as a File "
			"(use prepare_upload_file or list_attachments to find one)."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string", "description": "Target doctype to insert/update rows into."},
				"csv_file_url": {"type": "string", "description": "/files/... or /private/files/... — must already exist as a File doctype row."},
				"import_type": {"type": "string", "enum": ["Insert New Records", "Update Existing Records"], "default": "Insert New Records"},
			},
			"required": ["doctype", "csv_file_url"],
		},
	},
	{
		"name": "list_attachments",
		"description": (
			"List the File doctype rows attached to a parent document. Returns rows with "
			"{name, file_name, file_url, absolute_url, is_private, file_size, file_type, "
			"owner, creation}. Use when the user asks 'what files are attached to X?' or "
			"as a step before citing files in a reply (the absolute_url is clickable via "
			"Tier-A's link interceptor). Permission: Read on the parent doc."
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
		"name": "get_file_url",
		"description": (
			"Resolve a File doctype row (by name or file_url) to its absolute URL plus "
			"metadata. Returns {ok, name, file_name, file_url, absolute_url, is_private, "
			"file_size, attached_to_doctype, attached_to_name}. Use when you have a relative "
			"file_url (e.g. from get_doc's `image` or `attachment` field) and want to cite "
			"it as a clickable link in your reply, OR to confirm a file exists + the user "
			"can access it before referencing it."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"file": {"type": "string", "description": "File doctype name OR file_url (e.g. /files/foo.pdf)"},
			},
			"required": ["file"],
		},
	},
	{
		"name": "subscribe_doc_changes",
		"description": (
			"Watch a document for changes. When ANYONE saves it (you in another tab, a colleague "
			"in Desk, a scheduled job, an API call), a realtime toast appears in your chat showing "
			"who modified it + the new workflow_state / status. Subscriptions persist for 7 days "
			"or until you call unsubscribe_doc_changes. Permission: Read on the doc. Use when the "
			"user says 'watch X', 'notify me when X changes', 'tell me when this PO is approved', etc."
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
		"name": "unsubscribe_doc_changes",
		"description": "Stop watching a document. No-op if not currently subscribed.",
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
		"name": "list_my_subscriptions",
		"description": (
			"List the documents you're currently watching for realtime changes. Returns "
			"{ok, count, subscriptions: [{doctype, name, link}]}. Read-only."
		),
		"input_schema": {"type": "object", "properties": {}},
	},
	{
		"name": "make_chart",
		"description": (
			"Validate a Vega-Lite v5 chart spec and echo it back. Use this BEFORE emitting "
			"`[[lazychat:artifact kind=\"chart\"]]<spec>[[/lazychat:artifact]]` in your reply "
			"so the chart shows up as a tool-call card in the history. Spec must include `$schema` "
			"and at least one of `mark`/`layer`/`hconcat`/`vconcat`/`facet`/`repeat`. Inline the "
			"data via `data.values: [...]` (NOT a URL) — the chat-ui renders entirely client-side. "
			"Keep specs under 150 rows; for larger datasets, call `aggregate` first."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"spec": {
					"type": "object",
					"description": "Vega-Lite v5 spec object. Required keys: $schema (https://vega.github.io/schema/vega-lite/v5.json), data.values, mark, encoding.",
				},
				"title": {"type": "string", "description": "Optional chart title shown in the tool-call card."},
			},
			"required": ["spec"],
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
		"name": "reindex_kb",
		"description": (
			"Re-run the embedding pipeline for every file currently attached to a Lazychat "
			"Knowledge Base. Use after first install (existing files attached before the "
			"on_update hook was wired) or to refresh after switching embedding providers. "
			"Each file's chunks are skipped if their content_hash hasn't changed, so "
			"re-running is idempotent and cheap when nothing changed. Returns "
			"{ok, kb_name, files_enqueued} — actual indexing happens in background jobs "
			"visible via list_my_jobs."
		),
		"input_schema": {
			"type": "object",
			"properties": {"kb_name": {"type": "string"}},
			"required": ["kb_name"],
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
	{
		"name": "prepare_create_report",
		"description": (
			"Stage a new Frappe Report (Report Builder / Query Report / Script Report). Use this "
			"INSTEAD of prepare_create_doc({doctype:'Report'}) — it validates ref_doctype, report_type, "
			"and Query-Report SQL up front so the model gets actionable errors at preview time. "
			"Two-phase: returns preview_token + open_url; the user runs `/commit TOKEN` to apply. "
			"Cycle 11 M3 SQL gate: Query Report SQL is validated (regex), then EXPLAINed, then "
			"sample-executed (LIMIT 5, 8s timeout). All three MUST pass before a preview_token is "
			"issued. On failure, response is `{ok: false, error, sql_error, sql_phase: "
			"'validate'|'explain'|'execute', suggestion}` — route on sql_phase to apply targeted "
			"fixes (call describe_doctype if sql_phase === 'explain', etc.)."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"report_name": {"type": "string", "description": "Title for the new report"},
				"ref_doctype": {"type": "string", "description": "DocType the report runs against (must exist + user must have report permission)"},
				"report_type": {"type": "string", "enum": ["Report Builder", "Query Report", "Script Report"], "default": "Report Builder"},
				"query": {"type": "string", "description": "SELECT-only SQL for Query Report. Validated by the same regex as prepare_run_sql. EXPLAIN-probed against the live DB so table/column errors surface at preview time. Required iff report_type=Query Report."},
				"script": {"type": "string", "description": (
					"Python source for Script Report. Required iff report_type=Script Report. "
					"PREFER report_type='Query Report' with HTML link columns when buttons are needed — "
					"Query Reports support <a> tags in cell values and avoid the safe_exec sandbox. "
					"If you DO use Script Report, follow safe_exec rules:\n"
					"  * NO `import` statements (rejected at preview). `frappe`, `_`, `json` are "
					"pre-injected as globals. Calling `import frappe` fails at runtime with "
					"`ImportError: __import__ not found`.\n"
					"  * MUST define `def execute(filters=None):` returning (columns, data) — "
					"a tuple of (list-of-dict, list-of-dict).\n"
					"  * Allowed DB access: `frappe.db.get_list`, `frappe.db.get_all`, "
					"`frappe.db.get_value`, `frappe.db.count`, `frappe.qb`. NO `frappe.db.set_value`, "
					"NO mutations.\n"
					"  * NO side-effects: `frappe.sendmail`, `enqueue`, `delete_doc`, `rename_doc` "
					"are forbidden.\n"
					"Canonical pattern:\n"
					"  def execute(filters=None):\n"
					"      columns = [{'label': 'Item', 'fieldname': 'item_code', 'fieldtype': 'Link', "
					"'options': 'Item', 'width': 120}]\n"
					"      data = frappe.db.get_list('Doctype', filters=filters or {}, fields=['name'])\n"
					"      return columns, data\n"
					"The wrapper AST-validates + safe_exec dry-runs the body at preview, so any "
					"violation surfaces with an actionable hint BEFORE the report ships."
				)},
				"columns": {"type": "array", "items": {"type": "object"}, "description": "Optional column definitions (Report Builder)"},
				"filters": {"type": "object", "description": "Optional default filter values"},
				"javascript": {"type": "string", "description": (
					"Optional client-side JavaScript loaded by Frappe's Query Report page (Report.javascript). "
					"Only honored for Query Report / Script Report; ignored for Report Builder. Use this to "
					"add top-right inner page buttons via `report.page.add_inner_button()`. Pattern:\n"
					"  frappe.query_reports['<ReportName>'] = {\n"
					"    onload: function(report) {\n"
					"      report.page.add_inner_button('Debit Note', function() {\n"
					"        const data = report.data || []; // current rendered rows\n"
					"        // build _lz_items array from rows where both qty and rate diff,\n"
					"        // base64-encode JSON, navigate to /app/purchase-invoice/new?...\n"
					"      });\n"
					"    }\n"
					"  };\n"
					"Reference the lazychat _lz_items URL convention so the persistent helper "
					"Client Script populates the items child table on the new doc."
				)},
			},
			"required": ["report_name", "ref_doctype", "report_type"],
		},
	},
	{
		"name": "prepare_create_scheduled_job",
		"description": (
			"Stage a new Scheduled Job Type (Frappe's cron). Requires System Manager role + create permission. "
			"frequency=Cron requires cron_format (e.g. '0 */6 * * *'). Two-phase: returns preview_token; "
			"user runs `/commit TOKEN` to apply."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"method": {"type": "string", "description": "Importable Python path of the job function, e.g. 'erpnext.tasks.send_overdue_reminder'"},
				"frequency": {
					"type": "string",
					"enum": ["All", "Hourly", "Daily", "Daily Long", "Weekly", "Weekly Long", "Monthly", "Monthly Long", "Cron", "Annual"],
					"default": "Daily",
				},
				"cron_format": {"type": "string", "description": "Required when frequency=Cron. Standard 5-field cron expression."},
			},
			"required": ["method"],
		},
	},
	{
		"name": "prepare_create_number_card",
		"description": (
			"Stage a new Number Card (single-stat tile for the dashboard). function=Count needs no aggregate_field; "
			"Sum/Avg/Min/Max require aggregate_field. filters_json is the same JSON-string shape Number Card stores. "
			"Two-phase: returns preview_token; user runs `/commit TOKEN` to apply."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"label": {"type": "string", "description": "Display label (also doc name)"},
				"doctype": {"type": "string", "description": "Source doctype to count/aggregate over"},
				"function": {"type": "string", "enum": ["Count", "Sum", "Average", "Minimum", "Maximum"], "default": "Count"},
				"aggregate_function_based_on": {"type": "string", "description": "Field to aggregate (required iff function != Count)"},
				"filters_json": {"type": "string", "description": "JSON-encoded filter list, e.g. '[[\"Sales Invoice\",\"status\",\"=\",\"Paid\"]]'. Default '[]'."},
				"color": {"type": "string", "description": "Optional hex/CSS color"},
			},
			"required": ["label", "doctype"],
		},
	},
	{
		"name": "prepare_create_dashboard",
		"description": (
			"Stage a new Dashboard composed of existing Dashboard Charts and Number Cards. Each entry can be a "
			"plain string (chart/card name) or {chart|card, width: 'Half'|'Full'}. Two-phase: returns preview_token; "
			"user runs `/commit TOKEN` to apply. Use after make_chart / prepare_create_number_card."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"dashboard_name": {"type": "string"},
				"charts": {"type": "array", "items": {}, "description": "List of Dashboard Chart names or {chart, width} objects"},
				"cards": {"type": "array", "items": {}, "description": "List of Number Card names or {card, width} objects"},
				"module": {"type": "string", "description": "Optional Frappe Module to associate"},
			},
			"required": ["dashboard_name"],
		},
	},
	# ------------------------------------------------------------------
	# 2026-05-06 (Commit 1) — typed wrappers for ERPNext "Tools" workspace:
	# Calendar, Note, Bulk Update, Backup, Print Format, Print Settings,
	# Email Template, plus a direct (no /commit) Deleted Document restorer.
	# ------------------------------------------------------------------
	{
		"name": "prepare_create_calendar_event",
		"description": (
			"Stage a new Frappe Event (calendar entry). Validates ISO datetime / repeat enum / event_type at "
			"preview time so the Desk calendar never receives semantically-broken values. Two-phase: returns "
			"preview_token; user runs `/commit TOKEN` to apply."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"subject": {"type": "string", "description": "Event title"},
				"starts_on": {"type": "string", "description": "ISO datetime, e.g. '2026-05-10 09:00:00'"},
				"ends_on": {"type": "string", "description": "ISO datetime; must be >= starts_on. Optional if all_day=True."},
				"all_day": {"type": "boolean", "default": False},
				"description": {"type": "string", "description": "Optional long-form description"},
				"event_type": {"type": "string", "enum": ["Public", "Private"], "default": "Private"},
				"repeat_this_event": {"type": "boolean", "default": False},
				"repeat_on": {
					"type": "string",
					"enum": ["", "Daily", "Weekly", "Monthly", "Yearly"],
					"description": "Required when repeat_this_event=True.",
				},
				"participants": {
					"type": "array",
					"items": {"type": "object"},
					"description": "Optional list of {reference_doctype, reference_docname} participants.",
				},
			},
			"required": ["subject", "starts_on"],
		},
	},
	{
		"name": "prepare_create_note",
		"description": (
			"Stage a new Frappe Note. Note autonames as hash, so the actual document name is generated at /commit "
			"time and returned in the response — DO NOT pass the title to follow-up tools that take `name` (e.g. "
			"prepare_add_comment); use the `name` from the commit response. Two-phase: returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"title": {"type": "string", "description": "Display title (NOT the Frappe primary key — see description)"},
				"content": {"type": "string", "description": "HTML / markdown body"},
				"public": {"type": "boolean", "default": False, "description": "True = visible to all users"},
			},
			"required": ["title", "content"],
		},
	},
	{
		"name": "prepare_bulk_update",
		"description": (
			"Stage a bulk field update across N docs filtered by criteria. Runs count_doc inside the prepare to "
			"populate `affected_count` and refuses if N exceeds bulk_update_max_rows (default 500). Use INSTEAD of "
			"looping prepare_update_doc when the user says 'all overdue invoices'. Gated by lazychat_allow_dangerous_tools "
			"because of scale. Two-phase: returns preview_token + affected_count; user runs `/commit TOKEN`."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string"},
				"filters": {"type": "object", "description": "Frappe filter dict, e.g. {'status': 'Overdue'}"},
				"patch": {"type": "object", "description": "Field → new value mapping applied to every matched doc"},
				"max_rows": {"type": "integer", "description": "Optional cap < bulk_update_max_rows; refuses if affected_count > this."},
			},
			"required": ["doctype", "filters", "patch"],
		},
	},
	{
		"name": "prepare_download_backup",
		"description": (
			"Stage an asynchronous site-backup job. At commit time enqueues `bench backup` via frappe.enqueue and "
			"returns a job_id; poll progress with list_my_jobs and cancel with cancel_job. Requires System Manager. "
			"Two-phase: returns preview_token; commit returns job_id + estimated path under /sites/.../private/backups/."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"with_files": {"type": "boolean", "default": False, "description": "Include public/private file backups (slower, larger)."},
			},
		},
	},
	{
		"name": "prepare_create_print_format",
		"description": (
			"Stage a new Print Format. Validates doc_type exists and (when print_format_type=Jinja) dry-renders the "
			"HTML against an empty sample doc to catch Jinja syntax errors at preview time. Two-phase: returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"name": {"type": "string", "description": "Name of the Print Format"},
				"doc_type": {"type": "string", "description": "Target DocType (must exist + user must have print perm)"},
				"print_format_type": {"type": "string", "enum": ["Jinja", "Custom Format"], "default": "Jinja"},
				"html": {"type": "string", "description": "Jinja HTML template body (required for Jinja)"},
				"format_data": {"type": "string", "description": "JSON for Custom Format builder (required for Custom Format)"},
				"standard": {"type": "boolean", "default": False, "description": "Mark as standard (System Manager only)"},
			},
			"required": ["name", "doc_type"],
		},
	},
	{
		"name": "prepare_update_print_settings",
		"description": (
			"Stage updates to the site-wide Print Settings (Single doctype) — print font, paper size, with-letterhead "
			"defaults. Requires System Manager. Two-phase so a stray model edit doesn't silently change the look of "
			"every printed PDF; the diff renders in the preview. Returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"with_letterhead": {"type": "boolean"},
				"compact_item_print": {"type": "boolean"},
				"print_taxes_with_zero_amount": {"type": "boolean"},
				"font": {"type": "string", "description": "e.g. 'Default', 'Inter', 'Roboto'"},
				"font_size": {"type": "integer"},
				"pdf_page_size": {"type": "string", "enum": ["A4", "Letter", "A0", "A1", "A2", "A3", "A5", "A6", "A7", "A8", "A9", "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "C5E", "Comm10E", "DLE", "Executive", "Folio", "Ledger", "Legal", "Tabloid", "Custom"]},
				"pdf_page_height": {"type": "number"},
				"pdf_page_width": {"type": "number"},
			},
		},
	},
	{
		"name": "prepare_create_email_template",
		"description": (
			"Stage a new Email Template. Validates Jinja syntax in `subject` and `response` (body) at preview time "
			"by dry-rendering against an empty context. Templates are inert until used by send tools. Two-phase: "
			"returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"name": {"type": "string"},
				"subject": {"type": "string", "description": "Jinja-templated email subject line"},
				"response": {"type": "string", "description": "Jinja-templated email body (HTML)"},
				"use_html": {"type": "boolean", "default": True},
			},
			"required": ["name", "subject", "response"],
		},
	},
	{
		"name": "restore_deleted_doc",
		"description": (
			"Restore a previously-deleted document from Frappe's recycle bin (Deleted Document doctype). "
			"DIRECT — no /commit phase: restoring is a single, reversible action with full perm re-checks. "
			"Caller must have delete permission on the original doctype (Frappe enforces). "
			"Returns {ok, doctype, name, link}."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"deleted_document_name": {"type": "string", "description": "Name (primary key) of the Deleted Document row, e.g. 'XYZ12'."},
			},
			"required": ["deleted_document_name"],
		},
	},
	# ------------------------------------------------------------------
	# 2026-05-06 (Commit 2) — Alerts / Newsletter / Automation surface.
	# ------------------------------------------------------------------
	{
		"name": "prepare_create_notification",
		"description": (
			"Stage a new Frappe Notification (alert template). Validates event/channel enums, conditional "
			"required fields (Days Before/After → date_changed; Value Change → value_changed; Method → method), "
			"that document_type exists, that referenced fieldnames live on the doctype, and that the optional "
			"`condition` expression parses + is free of imports/lambdas. Two-phase: returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"subject": {"type": "string", "description": "Email subject (Jinja-templated)"},
				"document_type": {"type": "string", "description": "DocType the notification fires on"},
				"event": {
					"type": "string",
					"enum": ["New", "Save", "Submit", "Cancel", "Days After", "Days Before", "Value Change", "Method", "Custom"],
				},
				"channel": {
					"type": "string",
					"enum": ["Email", "Slack", "System Notification", "SMS"],
					"default": "Email",
				},
				"recipients": {
					"type": "array",
					"items": {"type": "object"},
					"description": "List of {receiver_by_role | receiver_by_document_field | receiver, cc?, bcc?}. At least one row required for channel=Email.",
				},
				"message": {"type": "string", "description": "Body (Jinja-templated)"},
				"condition": {"type": "string", "description": "Optional Python-style condition, e.g. 'doc.status == \"Overdue\"'. Validated for syntax + safety."},
				"date_changed": {"type": "string", "description": "Required when event ∈ {Days Before, Days After}. Fieldname on document_type."},
				"value_changed": {"type": "string", "description": "Required when event=Value Change. Fieldname on document_type."},
				"method": {"type": "string", "description": "Required when event=Method. Server-side method import path."},
				"days_in_advance": {"type": "integer", "description": "Used with event=Days Before/After."},
				"slack_webhook_url": {"type": "string", "description": "Required when channel=Slack — name of a Slack Webhook URL doctype row."},
				"property_value": {"type": "string", "description": "Compared-to value when event=Value Change."},
			},
			"required": ["subject", "document_type", "event"],
		},
	},
	{
		"name": "prepare_create_auto_email_report",
		"description": (
			"Stage a new Auto Email Report — schedule a Report to email itself on a frequency. Validates the "
			"Report exists and is readable, enum frequencies, and at least one recipient. Two-phase: returns "
			"preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"report": {"type": "string", "description": "Report name (must exist + user must have report perm)"},
				"email_to": {"type": "string", "description": "Newline-separated email addresses to receive the report"},
				"frequency": {"type": "string", "enum": ["Daily", "Weekdays", "Weekly", "Monthly"], "default": "Weekly"},
				"format": {"type": "string", "enum": ["HTML", "XLSX", "CSV"], "default": "HTML"},
				"day_of_week": {"type": "string", "enum": ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]},
				"description": {"type": "string"},
				"enabled": {"type": "boolean", "default": True},
			},
			"required": ["report", "email_to"],
		},
	},
	{
		"name": "update_notification_settings",
		"description": (
			"DIRECT — no /commit. Update the calling user's per-user Notification Settings (channels, seen/unseen, "
			"email subject filtering). Always limited to frappe.session.user (a System Manager calling for someone "
			"else is rejected — use the Desk for that). Returns {ok, updated_fields}."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"enabled": {"type": "boolean"},
				"email_message_subject_filter": {"type": "string"},
				"send_email_alerts": {"type": "boolean"},
				"seen": {"type": "boolean"},
			},
		},
	},
	{
		"name": "prepare_create_milestone_tracker",
		"description": (
			"Stage a new Milestone Tracker — auto-creates Milestones whenever a particular field on a doctype "
			"changes. Validates ref_doctype + track_field exist and that the field is a Link/Select. Two-phase: "
			"returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"document_type": {"type": "string", "description": "DocType to track"},
				"track_field": {"type": "string", "description": "Fieldname (Link or Select) to watch"},
				"disabled": {"type": "boolean", "default": False},
			},
			"required": ["document_type", "track_field"],
		},
	},
	{
		"name": "prepare_create_auto_repeat",
		"description": (
			"Stage a new Auto Repeat — recurring document creation against a reference doc. Validates the "
			"reference document exists and that no non-Cancelled Auto Repeat already targets the same "
			"(reference_doctype, reference_document) pair (idempotency). Commit re-checks the duplicate guard. "
			"Two-phase: returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"reference_doctype": {"type": "string"},
				"reference_document": {"type": "string"},
				"frequency": {
					"type": "string",
					"enum": ["Daily", "Weekly", "Monthly", "Quarterly", "Half-yearly", "Yearly"],
					"default": "Monthly",
				},
				"start_date": {"type": "string", "description": "ISO date, e.g. '2026-05-10'"},
				"end_date": {"type": "string", "description": "ISO date — must be > start_date if given."},
				"submit_on_creation": {"type": "boolean", "default": False},
				"notify_by_email": {"type": "boolean", "default": False},
				"recipients": {"type": "string", "description": "Comma-separated emails (used iff notify_by_email=True)"},
			},
			"required": ["reference_doctype", "reference_document", "start_date"],
		},
	},
	{
		"name": "prepare_create_email_group",
		"description": (
			"Stage a new Email Group (mailing list bucket). Refuses if an Email Group with the same title "
			"already exists. Two-phase: returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"title": {"type": "string"},
				"description": {"type": "string"},
				"public": {"type": "boolean", "default": False},
			},
			"required": ["title"],
		},
	},
	{
		"name": "prepare_add_to_email_group",
		"description": (
			"Stage adding an email address as a member of an existing Email Group. Validates the group exists "
			"and the email is well-formed. Idempotent at commit (existing membership is a graceful no-op). "
			"Two-phase: returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"email_group": {"type": "string", "description": "Title of the Email Group (must exist)"},
				"email": {"type": "string", "description": "Subscriber email address"},
			},
			"required": ["email_group", "email"],
		},
	},
	{
		"name": "prepare_create_newsletter",
		"description": (
			"Stage a new Newsletter (mass-mail draft). Validates the referenced Email Group exists. Newsletter "
			"itself is inert until manually sent from the Desk — staging here does NOT send. Two-phase: returns "
			"preview_token. (Sending is admin-driven, not LLM-driven, by design.)"
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"subject": {"type": "string"},
				"message": {"type": "string", "description": "Newsletter HTML body"},
				"email_group": {"type": "string", "description": "Title of an existing Email Group"},
				"send_from": {"type": "string", "description": "From-name + email, e.g. 'Acme <noreply@acme.com>'"},
				"send_unsubscribe_link": {"type": "boolean", "default": True},
			},
			"required": ["subject", "message", "email_group"],
		},
	},
	# ------------------------------------------------------------------
	# 2026-05-06 (Commit 3) — Email Account setup + Assignment Rule.
	# Both wrappers carry meaningful blast radius (SMTP creds; doc auto-
	# assignment rules) and ship together with the new
	# `lazychat_allow_email_setup` site flag.
	# ------------------------------------------------------------------
	{
		"name": "prepare_create_email_account",
		"description": (
			"Stage a new Email Account (SMTP/IMAP config). DOUBLE-GATED: requires System Manager role AND "
			"the new `lazychat_allow_email_setup` flag (separate from `lazychat_allow_email` because "
			"configuring SMTP/IMAP creds is meaningfully more dangerous than sending mail through an existing "
			"account). Validates service enum, conditional required fields per enable_outgoing/enable_incoming, "
			"and runs a live SMTP/IMAP connection probe at preview time — the result lands in the preview's "
			"`test_result.{smtp,imap}` so the user sees connectivity before /commit. Test failure does NOT "
			"refuse staging (server might be down). Optional `domain_name` triggers idempotent Email Domain "
			"create at commit time. Two-phase: returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"email_account_name": {"type": "string", "description": "Display name (also doc name)"},
				"email_id": {"type": "string", "description": "The mailbox address, e.g. 'noreply@acme.com'"},
				"password": {"type": "string", "description": "Mailbox password / app password. Stored encrypted by Frappe."},
				"service": {
					"type": "string",
					"enum": ["", "GMail", "Outlook.com", "Sendgrid", "SparkPost", "Yahoo Mail", "Yandex.Mail", "Frappe Mail"],
					"description": "Empty for custom server",
				},
				"enable_outgoing": {"type": "boolean", "default": True},
				"smtp_server": {"type": "string"},
				"smtp_port": {"type": "integer"},
				"use_tls": {"type": "boolean", "default": True},
				"use_ssl": {"type": "boolean", "default": False},
				"enable_incoming": {"type": "boolean", "default": False},
				"email_server": {"type": "string", "description": "IMAP/POP3 server"},
				"incoming_port": {"type": "integer"},
				"use_imap": {"type": "boolean", "default": True},
				"default_outgoing": {"type": "boolean", "default": False},
				"default_incoming": {"type": "boolean", "default": False},
				"domain_name": {"type": "string", "description": "Optional. Idempotently create Email Domain at commit time if missing."},
				"auth_method": {"type": "string", "enum": ["Basic", "OAuth"], "default": "Basic"},
			},
			"required": ["email_account_name", "email_id"],
		},
	},
	{
		"name": "prepare_create_assignment_rule",
		"description": (
			"Stage a new Assignment Rule (auto-assign docs to users). Validates rule enum (Round Robin / "
			"Load Balancing / Based on Field), users[] all exist, due_date_based_on is a Date/Datetime field "
			"on document_type, and assign_condition / unassign_condition are AST-validated against imports/"
			"lambdas/dunder. Requires Notification Manager OR System Manager role. Two-phase: returns preview_token."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"name": {"type": "string", "description": "Display name (also doc name)"},
				"document_type": {"type": "string", "description": "DocType the rule applies to"},
				"rule": {
					"type": "string",
					"enum": ["Round Robin", "Load Balancing", "Based on Field"],
					"default": "Round Robin",
				},
				"users": {
					"type": "array",
					"items": {"type": "string"},
					"description": "List of User names to cycle/load-balance across. At least one required.",
				},
				"field": {"type": "string", "description": "Required when rule=Based on Field. Must be a Link field on document_type pointing to User."},
				"assign_condition": {"type": "string", "description": "Optional Frappe expression — when truthy, the rule fires. Empty = always."},
				"unassign_condition": {"type": "string", "description": "Optional Frappe expression — when truthy, an existing assignment is cleared."},
				"due_date_based_on": {"type": "string", "description": "Optional fieldname (Date or Datetime) used to compute the assignee's due_date on the auto-created ToDo."},
				"priority": {"type": "integer", "default": 0},
				"description": {"type": "string"},
				"disabled": {"type": "boolean", "default": False},
			},
			"required": ["name", "document_type", "rule", "users"],
		},
	},
	{
		"name": "prepare_create_custom_field",
		"description": (
			"Stage a new Custom Field on an existing DocType. Use this INSTEAD of "
			"prepare_create_doc({doctype:'Custom Field'}) — it validates dt, fieldtype enum, "
			"and insert_after up front so the model gets actionable errors at preview time. "
			"Requires System Manager. Two-phase: returns preview_token; user clicks Apply to confirm."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"dt": {"type": "string", "description": "Target DocType (must exist)"},
				"label": {"type": "string", "description": "Display label. fieldname is auto-derived from this if not supplied."},
				"fieldtype": {
					"type": "string",
					"enum": [
						"Data", "Int", "Float", "Currency", "Percent", "Check", "Select", "Link",
						"Dynamic Link", "Date", "Datetime", "Time", "Duration", "Small Text",
						"Long Text", "Text", "Text Editor", "Markdown Editor", "HTML", "HTML Editor",
						"Code", "JSON", "Password", "Phone", "Color", "Rating", "Geolocation",
						"Barcode", "Signature", "Image", "Attach", "Attach Image", "Autocomplete",
						"Read Only", "Section Break", "Column Break", "Tab Break", "Heading",
						"Fold", "Icon", "Table", "Table MultiSelect", "Button",
					],
					"default": "Data",
				},
				"insert_after": {"type": "string", "description": "Existing fieldname on `dt` to place after, or 'append' for end"},
				"fieldname": {"type": "string", "description": "Optional snake_case identifier. Auto-derived from label if omitted."},
				"options": {"type": "string", "description": "For Select: newline-separated values. For Link/Table: target DocType. For Dynamic Link: source field."},
				"default": {"type": "string", "description": "Default value"},
				"reqd": {"type": "integer", "description": "1 = required field, 0 = optional", "enum": [0, 1]},
				"unique": {"type": "integer", "enum": [0, 1]},
				"read_only": {"type": "integer", "enum": [0, 1]},
				"hidden": {"type": "integer", "enum": [0, 1]},
				"description": {"type": "string"},
			},
			"required": ["dt", "label", "fieldtype", "insert_after"],
		},
	},
	{
		"name": "prepare_create_client_script",
		"description": (
			"Stage a new Client Script (browser-side JS that runs on Form or List view of a DocType). "
			"Use this INSTEAD of prepare_create_doc({doctype:'Client Script'}) — it validates dt + view "
			"and rejects empty scripts up front. Requires System Manager. Two-phase: returns "
			"preview_token; user clicks Apply to confirm."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"dt": {"type": "string", "description": "Target DocType (must exist)"},
				"view": {"type": "string", "enum": ["Form", "List"], "default": "Form"},
				"script": {"type": "string", "description": "JS source. Use frappe.ui.form.on(dt, {...}) for Form view; frappe.listview_settings[dt] = {...} for List."},
				"enabled": {"type": "integer", "enum": [0, 1], "default": 1},
				"name": {"type": "string", "description": "Optional Client Script doc name. Lazychat auto-derives '<DocType> <View> (lazychat <hash>)' when omitted (Frappe's autoname is Prompt — it requires an explicit name)."},
			},
			"required": ["dt", "script"],
		},
	},
	{
		"name": "prepare_create_page",
		"description": (
			"Stage a Desk Page (custom HTML/CSS/JS dashboard at /app/<page_name>). "
			"Internal-only (requires login, role-gated). Use this for any custom "
			"dashboard, full-page report, or executive overview. The page lives "
			"inside the Desk shell — frappe.call / frappe.db / frappe.boot are "
			"available out of the box.\n\n"
			"Render-preview HARD-blocks: HTML parse errors, CSS syntax errors, "
			"JS syntax errors, references to non-existent doctypes (frappe.db.get_list/etc.) "
			"or non-existent methods (frappe.call({method: ...})).\n\n"
			"Render-preview QUALITY_WARNINGS (non-blocking, render in Apply card): "
			"hardcoded colors without theme tokens (breaks dark mode), missing "
			"structural HTML (<header>, <main>, <section>), missing "
			"`document.body.dataset.lazychatReady = '1'` marker at end of JS "
			"(disables precise screenshot timing).\n\n"
			"Two-phase: returns preview_token; user clicks Apply to commit."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"page_name": {"type": "string", "description": "URL slug (auto-derived from title if omitted). Page will live at /app/<page_name>."},
				"title": {"type": "string", "description": "Display title."},
				"module": {"type": "string", "description": "Frappe module (default: Desk Assistant — the lazychat_erpnext app's own module). Must exist in tabModule Def on the bench; otherwise the commit will fail."},
				"roles": {"type": "array", "items": {"type": "string"}, "description": "Roles permitted to view (default: System Manager)."},
				"content": {"type": "string", "description": "Page body HTML. Use <header>/<main>/<section> for semantic structure."},
				"style": {"type": "string", "description": "Inline CSS. PREFER var(--bg-color)/var(--text-color)/var(--primary-color) etc. over hardcoded colors — hardcoded colors break dark mode."},
				"script": {"type": "string", "description": "Inline JS (the page controller). Use frappe.call / frappe.db.get_list for data. END with `document.body.dataset.lazychatReady = '1';` after final data fetches resolve — required for the screenshot preview tool to know when the page is fully rendered."},
				"icon": {"type": "string", "description": "Frappe icon class (e.g. 'octicon octicon-graph')."},
			},
			"required": ["title", "content"],
		},
	},
	{
		"name": "prepare_create_server_script",
		"description": (
			"Stage a Server Script of type API — a whitelisted Python endpoint reachable "
			"at /api/method/<api_method>. Use this to back complex Page dashboards: when a "
			"Page section needs an aggregation (sum/group-by/multi-doctype JOIN) that's "
			"too messy for one frappe.db.get_list call from JS, stage a Server Script and "
			"have the Page call it via frappe.call.\n\n"
			"READ-ONLY by construction: render-preview HARD-rejects subprocess/os/sys/etc. "
			"imports, the open/eval/exec/compile/__import__/input/breakpoint builtins, and "
			"frappe.db writes (set_value/delete/sql_ddl/commit/etc.). For writes use "
			"prepare_create_doc / prepare_update_doc.\n\n"
			"Output: end with `frappe.response.message = <dict>` — the API returns null otherwise.\n\n"
			"Gated: requires site_config lazychat_allow_dangerous_tools=true + System Manager role. "
			"Always explicit Apply (never auto-Apply)."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"name": {"type": "string", "description": "Unique Server Script name."},
				"api_method": {"type": "string", "description": "Optional. Becomes /api/method/<api_method>. Auto-derived from name if omitted (lazychat_erpnext.dashboards.<scrubbed_name>)."},
				"script": {"type": "string", "description": "Python body. Reads only (frappe.db.get_list, frappe.db.get_value, frappe.qb, etc.). End with `frappe.response.message = <result_dict>`."},
				"allow_guest": {"type": "boolean", "description": "Default false. Setting to true exposes the endpoint without auth — only set true for genuinely public data."},
				"disabled": {"type": "boolean", "description": "Default false."},
			},
			"required": ["name", "script"],
		},
	},
	{
		"name": "prepare_attach_assets",
		"description": (
			"Stage file uploads attached to a target doctype record. Use case: a "
			"prepare_create_page references a custom font or hero image; stage those "
			"files via this wrapper so they're served at /files/<filename> and "
			"@import-able from the Page's <style>.\n\n"
			"Each file capped at 5 MB; mime must start with image/ font/ text/ or "
			"application/octet-stream / application/font-woff(2). Caller must have "
			"'write' permission on target."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"target_doctype": {"type": "string", "description": "e.g. 'Page'"},
				"target_name": {"type": "string"},
				"files": {"type": "array", "items": {"type": "object", "properties": {
					"filename": {"type": "string"},
					"content_base64": {"type": "string", "description": "Base64-encoded file bytes."},
					"mime": {"type": "string", "description": "Defaults to application/octet-stream."}
				}, "required": ["filename", "content_base64"]}},
			},
			"required": ["target_doctype", "target_name", "files"],
		},
	},
	{
		"name": "list_whitelisted_methods",
		"description": (
			"List @frappe.whitelist() methods reachable via /api/method/<path>. "
			"Use this BEFORE staging a new Server Script — ERPNext ships dozens of "
			"data/aggregation methods (e.g. `erpnext.accounts.utils.*`, "
			"`erpnext.controllers.*`) and lazychat shouldn't reinvent the wheel.\n\n"
			"Use the `prefix` arg to scope: `frappe.client` for built-in CRUD, "
			"`erpnext.` for ERPNext domain methods, `lazychat_erpnext.` for our own."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"prefix": {"type": "string", "description": "e.g. 'frappe.client', 'erpnext.accounts'. Omit for all."},
				"limit": {"type": "integer", "description": "Default 100."},
			},
		},
	},
	{
		"name": "list_number_cards",
		"description": (
			"List existing Number Cards in the bench. Always call this before "
			"staging a new Number Card or a Workspace that needs cards — the "
			"agent should reuse existing aggregations rather than duplicate "
			"them ('Revenue MTD' shouldn't exist 4 times)."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"filter": {"type": "object", "description": "Frappe filter dict, e.g. {\"document_type\": \"Sales Invoice\"}."},
				"limit": {"type": "integer", "description": "Default 50, max 500."},
			},
		},
	},
	{
		"name": "prepare_create_workspace",
		"description": (
			"Stage a Workspace — Frappe's standard card-grid dashboard surface at /app/<workspace>. "
			"Composes Number Cards + Dashboard Charts + Shortcuts.\n\n"
			"Use this for SIMPLE dashboard needs (KPI cards in a grid). For sophisticated "
			"custom layouts (topbar + sidebar + custom sections), use `prepare_create_page` "
			"instead — Workspace's layout is fixed-grid.\n\n"
			"Render-preview rejects: unknown Number Card / Dashboard Chart / DocType references."
		),
		"input_schema": {
			"type": "object",
			"properties": {
				"title": {"type": "string"},
				"icon": {"type": "string", "description": "Frappe icon class (e.g. 'octicon octicon-graph')."},
				"parent_page": {"type": "string", "description": "Optional parent Workspace name."},
				"cards": {"type": "array", "items": {"type": "object", "properties": {"number_card_name": {"type": "string"}}}, "description": "Number Card references. Use `list_number_cards` to find existing cards before creating duplicates."},
				"charts": {"type": "array", "items": {"type": "object", "properties": {"chart_name": {"type": "string"}}}, "description": "Dashboard Chart references."},
				"shortcuts": {"type": "array", "items": {"type": "object", "properties": {"type": {"type": "string"}, "link_to": {"type": "string"}, "label": {"type": "string"}}}, "description": "Quick links — type=DocType / Report / Page / URL."},
				"roles": {"type": "array", "items": {"type": "string"}},
			},
			"required": ["title"],
		},
	},
]
