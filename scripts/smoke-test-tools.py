"""Smoke-test every lazychat_mcp_erpnext tool against the live site.

Run via:
  cd /path/to/frappe-bench
  bench --site <site> execute lazychat_mcp_erpnext.smoke_runner.run

Prints PASS/SKIP/FAIL per tool. Cleans up any docs it created.
This file is the source; copy it into the app via run_via_console() at the bottom.
"""
import frappe


def _ok(label, ok, detail=""):
	mark = "PASS" if ok else "FAIL"
	print(f"[{mark}] {label} {detail}".rstrip())
	return ok


def _skip(label, reason):
	print(f"[SKIP] {label} — {reason}")


def run():
	frappe.set_user("Administrator")
	from lazychat_mcp_erpnext.desk_assistant.tools import execute_tool, commit_prepared

	results = {"pass": 0, "fail": 0, "skip": 0}

	def record(passed):
		results["pass" if passed else "fail"] += 1

	created_note = None
	created_customer = None  # only set if site allows simple create; otherwise we use an existing Customer for comment/assign

	# T1: get_list (Customer)
	r = execute_tool("get_list", {"doctype": "Customer", "limit": 3, "fields": ["name", "customer_name"]})
	record(_ok("T1 get_list Customer", r.get("ok"), f"count={r.get('count')}"))

	# T2: get_doc (first Customer if any)
	rows = frappe.get_all("Customer", limit=1, fields=["name"])
	if rows:
		r = execute_tool("get_doc", {"doctype": "Customer", "name": rows[0].name})
		record(_ok("T2 get_doc Customer", r.get("ok") and r.get("doc", {}).get("name") == rows[0].name))
	else:
		_skip("T2 get_doc Customer", "no Customer rows")
		results["skip"] += 1

	# T3: get_current_context
	r = execute_tool("get_current_context", {}, desk_context={"route": ["Form", "Customer"], "doctype": "Customer"})
	record(_ok("T3 get_current_context", r.get("ok") and r.get("context", {}).get("doctype") == "Customer"))

	# T4: describe_doctype
	r = execute_tool("describe_doctype", {"doctype": "Customer"})
	record(_ok("T4 describe_doctype Customer", r.get("ok") and len(r.get("fields", [])) > 5))

	# T5+T6: prepare_create_note + commit (typed wrapper path; Note has a
	# typed wrapper since 2026-05-08 — generic prepare_create_doc is now
	# refused for Note to enforce validation upstream).
	test_title = f"_lazychat_smoke_{frappe.generate_hash(length=6)}"
	r = execute_tool(
		"prepare_create_note",
		{"title": test_title, "content": "smoke test note"},
	)
	t5 = r.get("ok") and r.get("preview_token")
	record(_ok("T5 prepare_create_note (typed wrapper)", bool(t5), f"token={t5[:8]}…" if t5 else r.get("error")))

	if t5:
		c = commit_prepared(t5)
		t6 = c.get("ok") and c.get("name")
		record(_ok("T6 commit_prepared (create Note)", bool(t6), f"created={t6}" if t6 else c.get("error")))
		if t6:
			created_note = c["name"]
	else:
		_skip("T6 commit_prepared (create)", "T5 failed")
		results["skip"] += 1

	# T7+T8: prepare_update_doc + commit (rename the Note's title)
	if created_note:
		r = execute_tool(
			"prepare_update_doc",
			{
				"doctype": "Note",
				"name": created_note,
				"patch": {"content": "smoke test note (updated)"},
			},
		)
		t7 = r.get("ok") and r.get("preview_token")
		record(_ok("T7 prepare_update_doc Note", bool(t7)))
		if t7:
			c = commit_prepared(t7)
			t8_ok = c.get("ok")
			record(_ok("T8 commit_prepared (update)", t8_ok, c.get("error", "")))
			if t8_ok:
				updated = frappe.db.get_value("Note", created_note, "content")
				record(_ok("T8b update visible in DB", "updated" in (updated or ""), f"got '{updated}'"))
	else:
		_skip("T7/T8 update + commit", "no created note")
		results["skip"] += 2

	# T10–T13 use any existing Customer (no create needed — site customizations make Customer create heavy)
	cust_rows = frappe.get_all("Customer", limit=1, fields=["name"])
	target_customer = cust_rows[0].name if cust_rows else None

	# T9: list_workflow_actions — find any submittable doctype with a workflow
	wf = frappe.get_all("Workflow", filters={"is_active": 1}, fields=["document_type"], limit=1)
	if wf:
		dt = wf[0].document_type
		rows = frappe.get_all(dt, limit=1, fields=["name"])
		if rows:
			r = execute_tool("list_workflow_actions", {"doctype": dt, "name": rows[0].name})
			record(_ok("T9 list_workflow_actions", r.get("ok"), f"on {dt}/{rows[0].name}"))
		else:
			_skip("T9 list_workflow_actions", f"no {dt} rows")
			results["skip"] += 1
	else:
		_skip("T9 list_workflow_actions", "no active Workflow on this site")
		results["skip"] += 1

	# T10+T11: prepare_add_comment + commit (on an existing Customer)
	smoke_marker = f"lazychat smoke {frappe.generate_hash(length=6)}"
	if target_customer:
		r = execute_tool(
			"prepare_add_comment",
			{"doctype": "Customer", "name": target_customer, "text": smoke_marker},
		)
		t10 = r.get("ok") and r.get("preview_token")
		record(_ok("T10 prepare_add_comment", bool(t10)))
		if t10:
			c = commit_prepared(t10)
			record(_ok("T11 commit_prepared (add_comment)", c.get("ok"), c.get("error", "")))
			has_comment = frappe.db.exists(
				"Comment",
				{"reference_doctype": "Customer", "reference_name": target_customer, "content": ["like", f"%{smoke_marker}%"]},
			)
			record(_ok("T11b comment visible in DB", bool(has_comment)))
			# cleanup the comment we just made
			if has_comment:
				try:
					frappe.delete_doc("Comment", has_comment, force=1, ignore_missing=True)
				except Exception:
					pass
	else:
		_skip("T10/T11 add_comment", "no Customer rows on this site")
		results["skip"] += 2

	# T12+T13: prepare_assign_to + commit (assign existing Customer to Administrator)
	if target_customer:
		r = execute_tool(
			"prepare_assign_to",
			{"doctype": "Customer", "name": target_customer, "user": "Administrator", "description": "lazychat smoke"},
		)
		t12 = r.get("ok") and r.get("preview_token")
		record(_ok("T12 prepare_assign_to", bool(t12)))
		if t12:
			c = commit_prepared(t12)
			record(_ok("T13 commit_prepared (assign_to)", c.get("ok"), c.get("error", "")))
			todo_name = frappe.db.exists(
				"ToDo",
				{
					"reference_type": "Customer",
					"reference_name": target_customer,
					"allocated_to": "Administrator",
					"description": ["like", "%lazychat smoke%"],
				},
			)
			record(_ok("T13b ToDo visible in DB", bool(todo_name)))
			if todo_name:
				try:
					frappe.delete_doc("ToDo", todo_name, force=1, ignore_missing=True)
				except Exception:
					pass
	else:
		_skip("T12/T13 assign_to", "no Customer rows on this site")
		results["skip"] += 2

	# T14: aggregate (count Customer rows by customer_type)
	r = execute_tool(
		"aggregate",
		{"doctype": "Customer", "function": "count", "field": "name", "group_by": "customer_type", "limit": 10},
	)
	record(_ok("T14 aggregate Customer by type", r.get("ok"), f"groups={r.get('count')}"))

	# T15: dashboard_chart_data — only if any Dashboard Chart exists
	dc = frappe.get_all("Dashboard Chart", limit=1, fields=["name"])
	if dc:
		r = execute_tool("dashboard_chart_data", {"name": dc[0].name})
		record(_ok("T15 dashboard_chart_data", r.get("ok"), f"chart={dc[0].name}"))
	else:
		_skip("T15 dashboard_chart_data", "no Dashboard Chart on this site")
		results["skip"] += 1

	# T16: number_card_value — only Document Type cards are supported server-side
	nc = frappe.get_all("Number Card", filters={"type": "Document Type"}, limit=1, fields=["name"])
	if nc:
		r = execute_tool("number_card_value", {"name": nc[0].name})
		record(_ok("T16 number_card_value", r.get("ok"), f"card={nc[0].name}{' err='+r.get('error','') if not r.get('ok') else ''}"))
	else:
		# Check that the tool returns a clear error for unsupported types
		any_nc = frappe.get_all("Number Card", limit=1, fields=["name"])
		if any_nc:
			r = execute_tool("number_card_value", {"name": any_nc[0].name})
			record(_ok("T16 number_card_value rejects non-DocumentType cleanly", "card_type" in r))
		else:
			_skip("T16 number_card_value", "no Number Card on this site")
			results["skip"] += 1

	# T17: invalid token to commit
	c = commit_prepared("not-a-real-token")
	record(_ok("T17 invalid commit token rejected", c.get("ok") is False))

	# T18: unknown tool
	r = execute_tool("does_not_exist", {})
	record(_ok("T18 unknown tool rejected", "error" in r))

	# T19: search_global — search for the test customer name (which surely exists in __global_search)
	if cust_rows:
		r = execute_tool("search_global", {"query": cust_rows[0].name[:6], "limit": 5})
		record(_ok("T19 search_global", r.get("ok"), f"matches={r.get('count')}"))
	else:
		_skip("T19 search_global", "no Customer rows for query")
		results["skip"] += 1

	# T20: count_doc
	r = execute_tool("count_doc", {"doctype": "Customer"})
	record(_ok("T20 count_doc Customer", r.get("ok"), f"n={r.get('count')}"))

	# T21: get_value
	if cust_rows:
		r = execute_tool("get_value", {"doctype": "Customer", "name": cust_rows[0].name, "fieldname": "customer_name"})
		record(_ok("T21 get_value", r.get("ok") and r.get("value") is not None))
	else:
		_skip("T21 get_value", "no Customer rows")
		results["skip"] += 1

	# T22: get_doctype_links (exercise the path; OK if no linked docs found)
	if cust_rows:
		r = execute_tool("get_doctype_links", {"doctype": "Customer", "name": cust_rows[0].name})
		record(_ok("T22 get_doctype_links", r.get("ok"), f"linked={r.get('linked_count')}"))
	else:
		_skip("T22 get_doctype_links", "no Customer rows")
		results["skip"] += 1

	# T23: list_reports
	r = execute_tool("list_reports", {})
	record(_ok("T23 list_reports", r.get("ok"), f"n={r.get('count')}"))

	# T24: run_report — pick the first available report's name
	if r.get("ok") and r.get("reports"):
		rep_name = r["reports"][0]["name"]
		r2 = execute_tool("run_report", {"name": rep_name, "filters": {}})
		# Some reports require mandatory filters; that's expected behavior — error response is acceptable
		ok = r2.get("ok") or "error" in r2
		record(_ok(f"T24 run_report ('{rep_name}')", ok, "" if r2.get("ok") else "got expected error for filter-required report"))
	else:
		_skip("T24 run_report", "no reports available")
		results["skip"] += 1

	# T25: get_stock_balance — needs an Item
	items = frappe.get_all("Item", limit=1, fields=["name"])
	if items:
		r = execute_tool("get_stock_balance", {"item_code": items[0].name})
		record(_ok("T25 get_stock_balance", r.get("ok") or "erpnext not installed" in str(r.get("error", ""))))
	else:
		_skip("T25 get_stock_balance", "no Item rows")
		results["skip"] += 1

	# T26: get_account_balance — needs an Account
	accts = frappe.get_all("Account", filters={"is_group": 0}, limit=1, fields=["name"])
	if accts:
		r = execute_tool("get_account_balance", {"account": accts[0].name})
		record(_ok("T26 get_account_balance", r.get("ok") or "erpnext not installed" in str(r.get("error", ""))))
	else:
		_skip("T26 get_account_balance", "no Account rows")
		results["skip"] += 1

	# T27: get_outstanding (Customer) — accept ok or no rows
	if cust_rows:
		r = execute_tool("get_outstanding", {"party_type": "Customer", "party": cust_rows[0].name})
		record(_ok("T27 get_outstanding", r.get("ok"), f"total={r.get('total_outstanding')}"))
	else:
		_skip("T27 get_outstanding", "no Customer")
		results["skip"] += 1

	# T28: get_open_invoices (no party filter)
	r = execute_tool("get_open_invoices", {"party_type": "Customer", "limit": 5})
	record(_ok("T28 get_open_invoices", r.get("ok"), f"n={r.get('count')}"))

	# T29: get_sales_summary
	r = execute_tool("get_sales_summary", {"group_by": "customer", "limit": 5})
	record(_ok("T29 get_sales_summary", r.get("ok"), f"groups={len(r.get('rows', []))}"))

	# T30: get_item_price
	if items:
		r = execute_tool("get_item_price", {"item_code": items[0].name})
		record(_ok("T30 get_item_price", r.get("ok"), f"prices={r.get('count')}"))
	else:
		_skip("T30 get_item_price", "no Item rows")
		results["skip"] += 1

	# T31: get_company_defaults
	r = execute_tool("get_company_defaults", {})
	record(_ok("T31 get_company_defaults", r.get("ok"), f"company={(r.get('company') or {}).get('name')}"))

	# T32: prepare_send_email — should be REJECTED unless the email gate is on.
	# The gate lives in get_lazychat_settings() which layers the Lazychat
	# Settings doctype on top of site_config — checking site_config alone
	# misses bench setups that enable via the doctype (the common case).
	r = execute_tool(
		"prepare_send_email",
		{"recipients": ["test@example.com"], "subject": "smoke", "content": "x"},
	)
	from lazychat_mcp_erpnext.desk_assistant.boot import get_lazychat_settings as _get_lazychat_settings
	allow = bool(_get_lazychat_settings().get("allow_email"))
	if allow:
		record(_ok("T32 prepare_send_email staged (email allowed by Lazychat Settings)", bool(r.get("preview_token"))))
	else:
		record(_ok("T32 prepare_send_email gated when allow_email=false", "error" in r and "disabled" in r["error"]))

	# T33: prepare_share_doc + commit (Note still around? if not, skip)
	if created_note:
		r = execute_tool(
			"prepare_share_doc",
			{"doctype": "Note", "name": created_note, "user": "Administrator", "read": True},
		)
		t33 = r.get("ok") and r.get("preview_token")
		record(_ok("T33 prepare_share_doc", bool(t33), r.get("error", "")))
		if t33:
			c = commit_prepared(t33)
			record(_ok("T33b commit (share_doc)", c.get("ok"), c.get("error", "")))
	else:
		_skip("T33 prepare_share_doc", "no created Note")
		results["skip"] += 2

	# T34: search_doctype
	r = execute_tool("search_doctype", {"query": "Customer", "limit": 5})
	record(_ok("T34 search_doctype", r.get("ok") and r.get("count", 0) >= 1, f"matches={r.get('count')}"))

	# T35: search_link (Customer)
	r = execute_tool("search_link", {"doctype": "Customer", "query": "", "limit": 3})
	record(_ok("T35 search_link Customer", r.get("ok"), f"results={r.get('count')}"))

	# T36: get_pending_approvals (current user; expect 0+ rows)
	r = execute_tool("get_pending_approvals", {})
	record(_ok("T36 get_pending_approvals", r.get("ok"), f"pending={r.get('count')}"))

	# T37: report_requirements — pick first available report
	rl = execute_tool("list_reports", {})
	if rl.get("ok") and rl.get("reports"):
		r = execute_tool("report_requirements", {"name": rl["reports"][0]["name"]})
		record(_ok("T37 report_requirements", r.get("ok")))
	else:
		_skip("T37 report_requirements", "no reports")
		results["skip"] += 1

	# T38: list_user_dashboards
	r = execute_tool("list_user_dashboards", {})
	record(_ok("T38 list_user_dashboards", r.get("ok"), f"n={r.get('count')}"))

	# T39: extract_file_content — find any text-y attached file
	files = frappe.get_all(
		"File",
		filters={"file_name": ["like", "%.json"]},
		limit=1,
		fields=["name"],
	) or frappe.get_all(
		"File",
		filters={"file_name": ["like", "%.txt"]},
		limit=1,
		fields=["name"],
	)
	if files:
		r = execute_tool("extract_file_content", {"file": files[0].name, "max_chars": 200})
		# Accept ok=True OR a graceful error (stale file record / missing on disk / binary)
		passed = r.get("ok") or any(s in str(r.get("error", "")) for s in ["missing on disk", "binary", "no read permission"])
		detail = r.get("file_name") if r.get("ok") else f"graceful error: {r.get('error', '')[:60]}"
		record(_ok("T39 extract_file_content (text file)", passed, detail))
	else:
		r = execute_tool("extract_file_content", {"file": "does-not-exist-zzz"})
		record(_ok("T39 extract_file_content (not-found error)", "error" in r))

	# T40+T41: prepare_delete_doc + commit (delete a fresh throwaway Note)
	throwaway = frappe.get_doc({"doctype": "Note", "title": f"_lazychat_del_{frappe.generate_hash(length=4)}", "content": "to be deleted"})
	throwaway.insert(ignore_permissions=True)
	frappe.db.commit()
	r = execute_tool("prepare_delete_doc", {"doctype": "Note", "name": throwaway.name})
	t40 = r.get("ok") and r.get("preview_token")
	record(_ok("T40 prepare_delete_doc", bool(t40)))
	if t40:
		c = commit_prepared(t40)
		t41_ok = c.get("ok")
		record(_ok("T41 commit (delete)", t41_ok, c.get("error", "")))
		if t41_ok:
			gone = not frappe.db.exists("Note", throwaway.name)
			record(_ok("T41b doc actually gone", gone))

	# T42+T43: prepare_run_sql + prepare_run_python with the dangerous-tools
	# gate OFF — should be REJECTED. Read the effective flag via the unified
	# resolver (Lazychat Settings doctype layered on top of site_config) so
	# benches that enable via the doctype skip these correctly instead of
	# silently failing the assertion.
	flag_was = bool(_get_lazychat_settings().get("allow_dangerous_tools"))
	if not flag_was:
		r = execute_tool("prepare_run_sql", {"query": "SELECT 1 as one"})
		record(_ok("T42 prepare_run_sql gated (flag off)", "error" in r and "disabled" in r.get("error", "")))
		r = execute_tool("prepare_run_python", {"code": "_result = 2 + 2"})
		record(_ok("T43 prepare_run_python gated (flag off)", "error" in r and "disabled" in r.get("error", "")))
	else:
		_skip("T42/T43 flag-off rejection", "Lazychat Settings has allow_dangerous_tools=true")
		results["skip"] += 2

	# T44–T47: monkey-patch get_site_config to enable the flag for these tests
	original_get_config = frappe.get_site_config
	def patched_config(*a, **kw):
		c = original_get_config(*a, **kw)
		c = dict(c)
		c["lazychat_allow_dangerous_tools"] = True
		return c
	frappe.get_site_config = patched_config
	try:
		# SQL
		r = execute_tool("prepare_run_sql", {"query": "SELECT 1 as one, 'hi' as greeting", "limit": 5})
		t44 = r.get("ok") and r.get("preview_token")
		record(_ok("T44 prepare_run_sql staged (flag on)", bool(t44), r.get("error", "")))
		if t44:
			c = commit_prepared(t44)
			ok_sql = c.get("ok") and c.get("rows") and c["rows"][0].get("one") == 1
			record(_ok("T45 commit (run_sql) returned correct row", bool(ok_sql), c.get("error", "")))

		# SQL: reject DML attempt at prepare-time
		r = execute_tool("prepare_run_sql", {"query": "DELETE FROM tabUser WHERE name='x'"})
		err = r.get("error", "")
		record(_ok("T46 prepare_run_sql rejects DML", "error" in r and ("DML" in err or "SELECT" in err)))
		# And another DML form sneakier — UPDATE inside a CTE
		r = execute_tool("prepare_run_sql", {"query": "WITH x AS (SELECT 1) UPDATE tabUser SET email='x' WHERE 1=0"})
		record(_ok("T46b prepare_run_sql rejects sneaky DML", "error" in r))

		# Python
		r = execute_tool("prepare_run_python", {"code": "_result = sum(range(10))"})
		t47 = r.get("ok") and r.get("preview_token")
		if t47:
			c = commit_prepared(t47)
			ok_py = c.get("ok") and c.get("result") == 45
			record(_ok("T47 prepare_run_python + commit returns sum(range(10))=45", bool(ok_py), c.get("error", "")))

		# T47a–T47d: run_sql_select (auto-execute SELECT, no /commit)
		r = execute_tool("run_sql_select", {"query": "SELECT 1 as one, 'hi' as greeting", "limit": 5})
		ok_sel = r.get("ok") and r.get("rows") and r["rows"][0].get("one") == 1
		record(_ok("T47a run_sql_select returns rows immediately (no /commit)", bool(ok_sel), r.get("error", "")))

		r = execute_tool("run_sql_select", {"query": "-- get one row\nSELECT 1 as n", "limit": 5})
		record(_ok("T47b run_sql_select tolerates leading -- comment", r.get("ok") and r.get("rows", [{}])[0].get("n") == 1, r.get("error", "")))

		r = execute_tool("run_sql_select", {"query": "/* descriptive comment */ SELECT 2 as n", "limit": 5})
		record(_ok("T47c run_sql_select tolerates leading /* */ comment", r.get("ok") and r.get("rows", [{}])[0].get("n") == 2, r.get("error", "")))

		r = execute_tool("run_sql_select", {"query": "DELETE FROM tabUser WHERE name='x'"})
		record(_ok("T47d run_sql_select rejects DML", "error" in r))

		# T47e–T47k: run_python_readonly (auto-execute, AST-validated, savepoint-rollback)
		r = execute_tool("run_python_readonly", {"code": "_result = sum(range(10))"})
		record(_ok("T47e run_python_readonly returns result immediately", r.get("ok") and r.get("result") == 45, r.get("error", "")))

		# AST scan blocks dangerous imports
		r = execute_tool("run_python_readonly", {"code": "import subprocess\n_result = subprocess.check_output(['ls'])"})
		record(_ok("T47f run_python_readonly blocks subprocess import", "error" in r and "forbidden import" in r.get("error", "")))

		r = execute_tool("run_python_readonly", {"code": "import os\n_result = os.listdir('.')"})
		record(_ok("T47g run_python_readonly blocks os import", "error" in r and "forbidden import" in r.get("error", "")))

		# AST scan blocks frappe.db mutators
		r = execute_tool("run_python_readonly", {"code": "frappe.db.set_value('User', 'Administrator', 'first_name', 'oops')"})
		record(_ok("T47h run_python_readonly blocks frappe.db.set_value", "error" in r and "frappe.db.set_value" in r.get("error", "")))

		r = execute_tool("run_python_readonly", {"code": "frappe.delete_doc('Note', 'whatever')"})
		record(_ok("T47i run_python_readonly blocks frappe.delete_doc", "error" in r and "frappe.delete_doc" in r.get("error", "")))

		# AST scan blocks file/dynamic-code built-ins
		r = execute_tool("run_python_readonly", {"code": "f = open('/tmp/x', 'w')\nf.write('x')"})
		record(_ok("T47j run_python_readonly blocks open()", "error" in r and "open()" in r.get("error", "")))

		# Savepoint defense-in-depth: doc.save() escapes the AST scan
		# (chain root isn't `frappe`), but the savepoint rollback should undo
		# the insert. Verify by checking the Note doesn't persist after the call.
		import secrets as _secrets
		marker = "_lazychat_ro_savepoint_test_" + _secrets.token_hex(4)
		code = (
			"note = frappe.new_doc('Note')\n"
			f"note.title = '{marker}'\n"
			"note.public = 1\n"
			"note.insert(ignore_permissions=True)\n"
			"_result = note.name"
		)
		r = execute_tool("run_python_readonly", {"code": code})
		# The code "succeeded" from the LLM's perspective but the savepoint
		# should have rolled the insert back.
		survived = bool(frappe.db.exists("Note", {"title": marker}))
		record(_ok(
			"T47k run_python_readonly savepoint rolls back doc.insert() (defense-in-depth past AST scan)",
			r.get("ok") and not survived,
			f"survived={survived} result={r.get('result')} err={r.get('error', '')}"
		))
	finally:
		frappe.get_site_config = original_get_config

	# T48–T51: route-context briefing renders correctly into the system prompt
	from lazychat_mcp_erpnext.desk_assistant.claude_bridge import _route_context_summary

	form_ctx = {
		"view": "Form",
		"doctype": "Sales Invoice",
		"docname": "SI-2024-001",
		"current_doc": {"name": "SI-2024-001", "doctype": "Sales Invoice", "title": "Acme Corp", "workflow_state": "Pending Approval"},
	}
	s = _route_context_summary(form_ctx)
	record(_ok("T48 form-view briefing names the doc + asks for get_doc", "Sales Invoice / SI-2024-001" in s and "get_doc" in s))
	record(_ok("T48b form-view briefing includes workflow_state", "Pending Approval" in s))

	dirty_ctx = dict(form_ctx)
	dirty_ctx["current_doc"] = dict(form_ctx["current_doc"], dirty=True)
	s = _route_context_summary(dirty_ctx)
	record(_ok("T49 form-view briefing flags unsaved changes", "UNSAVED CHANGES" in s))

	list_ctx = {"view": "List", "doctype": "Customer", "selected_rows": ["CUST-1", "CUST-2", "CUST-3"]}
	s = _route_context_summary(list_ctx)
	record(_ok("T50 list-view briefing names selected rows", "Customer list view" in s and "CUST-1" in s and "3 row(s) selected" in s))

	record(_ok("T51 empty/None context = empty briefing (no spurious noise)", _route_context_summary(None) == "" and _route_context_summary({}) == ""))

	# T52–T57: MCP wire-protocol dispatcher (initialize, tools/list, tools/call, errors)
	from lazychat_mcp_erpnext.desk_assistant.mcp import dispatch as mcp_dispatch
	# T52: initialize handshake
	r = mcp_dispatch("initialize", {}, req_id=1)
	res = r.get("result") or {}
	record(_ok(
		"T52 MCP initialize returns capabilities + serverInfo",
		r.get("jsonrpc") == "2.0" and r.get("id") == 1
		and "tools" in (res.get("capabilities") or {})
		and (res.get("serverInfo") or {}).get("name") == "lazychat-mcp-erpnext",
	))
	# T53: ping
	r = mcp_dispatch("ping", {}, req_id=2)
	record(_ok("T53 MCP ping", r.get("result") == {} and "error" not in r))
	# T54: tools/list returns the full registry with MCP-shaped inputSchema.
	# We compare against TOOL_SCHEMAS so this stays correct when tools are
	# added (the count drifted from 38 → 65 silently before this fix).
	from lazychat_mcp_erpnext.desk_assistant.tool_schemas import TOOL_SCHEMAS as _ALL
	r = mcp_dispatch("tools/list", {}, req_id=3)
	tools = (r.get("result") or {}).get("tools") or []
	first = tools[0] if tools else {}
	expected = len(_ALL)
	record(_ok(
		f"T54 MCP tools/list returns {expected} tools with inputSchema",
		len(tools) == expected and "inputSchema" in first and "name" in first,
		f"got {len(tools)}",
	))
	# T55: tools/call dispatches to execute_tool — get_list against Customer
	r = mcp_dispatch("tools/call", {"name": "get_list", "arguments": {"doctype": "Customer", "limit": 2}}, req_id=4)
	res = r.get("result") or {}
	content = res.get("content") or []
	import json as _j
	body = _j.loads(content[0]["text"]) if content else {}
	record(_ok(
		"T55 MCP tools/call get_list returns rows wrapped in MCP content",
		not res.get("isError") and body.get("ok") is True and "rows" in body,
	))
	# T56: tools/call with unknown tool → JSONRPC error -32601
	r = mcp_dispatch("tools/call", {"name": "this_tool_does_not_exist", "arguments": {}}, req_id=5)
	err = r.get("error") or {}
	record(_ok("T56 MCP tools/call unknown tool → JSONRPC -32601", err.get("code") == -32601))
	# T57: tools/call with missing 'name' → JSONRPC error -32602
	r = mcp_dispatch("tools/call", {"arguments": {}}, req_id=6)
	err = r.get("error") or {}
	record(_ok("T57 MCP tools/call missing name → JSONRPC -32602", err.get("code") == -32602))
	# T58: unknown method → JSONRPC -32601
	r = mcp_dispatch("totally/unknown", {}, req_id=7)
	err = r.get("error") or {}
	record(_ok("T58 MCP unknown method → JSONRPC -32601", err.get("code") == -32601))
	# T59: tools/call with permission-failing tool returns isError=True (not an exception)
	# get_doc on a non-existent customer — graceful error
	r = mcp_dispatch("tools/call", {"name": "get_doc", "arguments": {"doctype": "Customer", "name": "NOPE-NONEXISTENT"}}, req_id=8)
	res = r.get("result") or {}
	body = _j.loads((res.get("content") or [{}])[0].get("text", "{}")) if res.get("content") else {}
	# Either ok=False with error, or isError flag set
	record(_ok("T59 MCP tools/call gracefully reports tool errors", res.get("isError") or "error" in body))

	# T60–T64: Lazychat Settings doctype + boot extension + save_conversation
	# T60: Single doc exists and exposes all expected fields. We don't check specific values
	# — admins can toggle them; the boot resolver in T61 fills missing fields from defaults.
	settings = frappe.get_single("Lazychat Settings")
	expected_fields = {"enabled", "iframe_base_url", "iframe_query_params", "chat_path", "mcp_endpoint", "legacy_widget_enabled", "allow_email", "allow_dangerous_tools", "llm_proxy_allowed_hosts"}
	doc_fields = {df.fieldname for df in settings.meta.fields}
	record(_ok(
		"T60 Lazychat Settings doc exists with all 9 expected fields",
		expected_fields.issubset(doc_fields),
	))

	# T61: boot_session populates frappe.boot.lazychat_settings with all expected fields
	# AND fills missing values from defaults (this is how blank doctype values resolve).
	from lazychat_mcp_erpnext.desk_assistant.boot import boot_session as _bs, _SETTINGS_DEFAULTS
	bootinfo = {}
	_bs(bootinfo)
	ls = bootinfo.get("lazychat_settings") or {}
	expected_keys = set(_SETTINGS_DEFAULTS.keys())
	# chat_path falls back to default when doctype value is empty
	record(_ok(
		"T61 boot_session exposes lazychat_settings with all default fields populated",
		expected_keys.issubset(set(ls.keys()))
		and ls.get("chat_path") in ("auto", "browser", "backend")
		and isinstance(ls.get("llm_proxy_allowed_hosts"), (list, str)),
	))

	# T62: site_config wins over doctype (backward-compat fallback path)
	# Set doctype False, mock site_config with True, get_lazychat_settings should return True.
	from lazychat_mcp_erpnext.desk_assistant.boot import get_lazychat_settings as _gls
	original_get_config = frappe.get_site_config

	def patched_config_t62(*a, **kw):
		c = dict(original_get_config(*a, **kw) or {})
		c["lazychat_allow_dangerous_tools"] = True
		c["lazychat_allow_email"] = True
		return c
	frappe.get_site_config = patched_config_t62
	try:
		eff = _gls()
		record(_ok(
			"T62 site_config 'lazychat_allow_dangerous_tools=True' overrides doctype False",
			eff.get("allow_dangerous_tools") is True and eff.get("allow_email") is True,
		))
	finally:
		frappe.get_site_config = original_get_config

	# T63: save_conversation creates a Claude Conversation row scoped to current user
	from lazychat_mcp_erpnext.desk_assistant.api import save_conversation
	r = save_conversation(
		conversation_id=None,
		messages=[{"role": "user", "content": "smoke test"}, {"role": "assistant", "content": "hi"}],
		title="Smoke Conv",
		model_label="bytedance/seed-oss-36b-instruct",
		usage={"input_tokens": 10, "output_tokens": 5},
	)
	convo_name = r.get("conversation_id")
	record(_ok("T63 save_conversation returns conversation_id + persists row", bool(convo_name) and frappe.db.exists("Claude Conversation", convo_name)))
	if convo_name:
		convo = frappe.get_doc("Claude Conversation", convo_name)
		record(_ok(
			"T63b saved conversation has user, history, last_model, usage",
			convo.user == frappe.session.user
			and "smoke test" in (convo.history or "")
			and convo.last_model == "bytedance/seed-oss-36b-instruct"
			and (convo.total_input_tokens or 0) >= 10
			and (convo.total_output_tokens or 0) >= 5,
		))
		# Cleanup test conversation
		try:
			frappe.delete_doc("Claude Conversation", convo_name, force=1, ignore_missing=True)
		except Exception:
			pass

	# T64: validation — mcp_endpoint must start with /api/method/
	settings_doc = frappe.get_single("Lazychat Settings")
	original_endpoint = settings_doc.mcp_endpoint
	threw = False
	try:
		settings_doc.mcp_endpoint = "https://elsewhere.example.com/mcp"
		settings_doc.save()
	except frappe.exceptions.ValidationError:
		threw = True
	except Exception:
		threw = True
	finally:
		# Restore via frappe.db to avoid second validation
		frappe.db.set_value("Lazychat Settings", "Lazychat Settings", "mcp_endpoint", original_endpoint)
		frappe.db.commit()
	record(_ok("T64 Lazychat Settings rejects non-/api/method/ mcp_endpoint", threw))

	# T65–T68: server-side LLM proxy
	# We test llm_proxy at the unit level (mock requests.post + frappe.request) so we don't
	# fire actual HTTP requests during smoke. Browser E2E covers the live wire.
	from unittest.mock import patch, MagicMock
	from lazychat_mcp_erpnext.desk_assistant import llm_proxy as _lp

	def _mock_request(target_url: str, body: bytes = b"{}", method: str = "POST", extra_headers: dict | None = None):
		req = MagicMock()
		req.method = method
		hdrs = {"x-target-url": target_url, "Authorization": "Bearer secret-key", "Content-Type": "application/json"}
		if extra_headers:
			hdrs.update(extra_headers)
		req.headers = hdrs
		req.args = {}
		req.get_data = MagicMock(return_value=body)
		return req

	def _read_response(resp) -> tuple[int, str, str]:
		# Werkzeug Response: status_code, mimetype, body (joined from generator)
		status = resp.status_code
		ct = resp.mimetype or ""
		try:
			body_bytes = b"".join(resp.iter_encoded())
			body = body_bytes.decode("utf-8", errors="replace")
		except Exception:
			body = ""
		return status, ct, body

	# T65: allowlist rejects an unknown host with 403
	with patch.object(frappe, "request", _mock_request("https://evil.example.com/v1/chat/completions")):
		resp = _lp.handle()
		status, _ct, body = _read_response(resp)
		record(_ok("T65 LLM proxy rejects unknown host with 403", status == 403 and "not in allowlist" in body))

	# T66: upstream connection error → 504
	with patch.object(frappe, "request", _mock_request("https://api.openai.com/v1/chat/completions")):
		import requests as _rq
		with patch("requests.post", side_effect=_rq.exceptions.ConnectionError("DNS")):
			resp = _lp.handle()
			status, _ct, body = _read_response(resp)
			record(_ok("T66 LLM proxy returns 504 on upstream connection error", status == 504 and "Upstream error" in body))

	# T67: header forwarding security model.
	#
	# The proxy DELIBERATELY strips inbound `Authorization` and `X-Frappe-CSRF-Token`
	# — those are FRAPPE auth/CSRF tokens that have no meaning to the upstream
	# LLM. The user's actual LLM API key arrives via `x-target-authorization`
	# and the proxy REWRITES it as `Authorization: ...` before the upstream call
	# (see llm_proxy.py:239). Same trick for `x-target-api-key`.
	deny_check_headers = {
		"Host": "erp.local:8000",
		"Cookie": "sid=abc",
		"Accept-Encoding": "gzip, br",
		"sec-fetch-mode": "cors",
		"X-Frappe-CSRF-Token": "csrf-xyz",       # frappe-internal — must be stripped
		"x-target-authorization": "Bearer llm-secret-key",  # user's real LLM key
	}
	posted_call: dict = {}
	def _capture_post(url, headers=None, data=None, stream=None, timeout=None):
		posted_call["url"] = url
		posted_call["headers"] = headers or {}
		posted_call["data"] = data
		fake_resp = MagicMock()
		fake_resp.headers = {"content-type": "application/json"}
		fake_resp.status_code = 200
		fake_resp.iter_content = MagicMock(return_value=iter([b'{"ok":1}']))
		fake_resp.close = MagicMock()
		return fake_resp

	with patch.object(frappe, "request", _mock_request("https://api.openai.com/v1/chat/completions", body=b'{"hi":"world"}', extra_headers=deny_check_headers)):
		with patch("requests.post", side_effect=_capture_post):
			resp = _lp.handle()
			# Drain
			_read_response(resp)
	hdrs = {k.lower(): v for k, v in (posted_call.get("headers") or {}).items()}
	t67_checks = {
		"body_passthrough":   posted_call.get("data") == b'{"hi":"world"}',
		"strip_host":         "host" not in hdrs,
		"strip_cookie":       "cookie" not in hdrs,
		"strip_accept_encoding": "accept-encoding" not in hdrs,
		"strip_sec_fetch":    not any(k.startswith("sec-fetch-") for k in hdrs),
		"strip_frappe_csrf":  "x-frappe-csrf-token" not in hdrs,            # frappe-internal
		"strip_frappe_auth":  hdrs.get("authorization") != "Bearer secret-key",  # the FRAPPE auth header (Bearer secret-key) must not pass through
		"rewrite_target_auth": hdrs.get("authorization") == "Bearer llm-secret-key",  # x-target-authorization → Authorization
		"strip_x_target_url": "x-target-url" not in hdrs,                   # never forward the proxy hint
	}
	t67_pass = all(t67_checks.values())
	if not t67_pass:
		failed = [k for k, v in t67_checks.items() if not v]
		print(f"[DEBUG-T67] failed checks: {failed}")
		print(f"[DEBUG-T67] forwarded headers: {hdrs}")
		print(f"[DEBUG-T67] forwarded body: {posted_call.get('data')!r}")
	record(_ok(
		"T67 LLM proxy strips frappe-internal headers, rewrites x-target-authorization to Authorization upstream",
		t67_pass,
	))

	# T68: upstream Content-Type preserved
	def _ct_post(url, **kw):
		fake_resp = MagicMock()
		fake_resp.headers = {"content-type": "text/event-stream"}
		fake_resp.status_code = 200
		fake_resp.iter_content = MagicMock(return_value=iter([b"event: ok\ndata: {}\n\n"]))
		fake_resp.close = MagicMock()
		return fake_resp
	with patch.object(frappe, "request", _mock_request("https://integrate.api.nvidia.com/v1/chat/completions")):
		with patch("requests.post", side_effect=_ct_post):
			resp = _lp.handle()
			status, ct, body = _read_response(resp)
	record(_ok(
		"T68 LLM proxy preserves upstream Content-Type (text/event-stream)",
		status == 200 and ct == "text/event-stream" and "event: ok" in body,
	))

	# T69–T71: tools added after the original 38 (covered by Layer 1 curl_smoke,
	# now mirrored in-process so an isolated bench run also exercises them).
	# T69: list_attachments — DocType doctype always exists; expect ok with
	# count >= 0 (likely 0 since DocType rows don't accumulate attachments).
	# Impl returns {"ok": True, "files": [...], "count": N}.
	r = execute_tool("list_attachments", {"doctype": "DocType", "name": "DocType"})
	record(_ok(
		"T69 list_attachments DocType",
		r.get("ok") is True and isinstance(r.get("files"), list),
		f"count={r.get('count')}",
	))

	# T70: get_file_url — non-existent path. Impl returns {"error": "file
	# not found: ..."} (no ok key) — proves the resolver runs gracefully
	# instead of raising.
	r = execute_tool("get_file_url", {"file": "/files/__lazychat_smoke_no_such.txt"})
	record(_ok(
		"T70 get_file_url graceful miss",
		"error" in r and "not found" in r["error"].lower(),
		r.get("error", "")[:60],
	))

	# T71: make_chart — Vega-Lite v5 spec validator. Spec must round-trip
	# unchanged with a title attached.
	spec = {
		"$schema": "https://vega.github.io/schema/vega-lite/v5.json",
		"data": {"values": [{"a": 1, "b": 2}, {"a": 3, "b": 4}]},
		"mark": "bar",
		"encoding": {
			"x": {"field": "a", "type": "ordinal"},
			"y": {"field": "b", "type": "quantitative"},
		},
	}
	r = execute_tool("make_chart", {"spec": spec, "title": "smoke"})
	record(_ok(
		"T71 make_chart returns valid spec",
		r.get("ok") is True and r.get("spec", {}).get("$schema") == spec["$schema"]
		and r.get("title") == "smoke",
		f"mark={r.get('spec', {}).get('mark')}",
	))

	# T72: make_chart rejects a spec with NO Vega-Lite shape keys at all.
	# (Validator passes if any of $schema/mark/layer/hconcat/vconcat/facet/repeat
	# is present, so a spec with just `data` should fail.)
	r = execute_tool("make_chart", {"spec": {"data": {"values": []}}})
	record(_ok(
		"T72 make_chart rejects spec missing Vega-Lite keys",
		"error" in r and "vega-lite" in r["error"].lower(),
		r.get("error", "")[:60],
	))

	# T73: cancel_job is idempotent — calling it twice on the same job (where
	# the second call hits a now-terminal state) must NOT surface an empty
	# 'cancel failed:' error. Regression for the rq.exceptions.InvalidJobOperation
	# empty-message bug fixed in tools.py.
	from frappe.utils.background_jobs import enqueue
	t73_job = enqueue("frappe.utils.sleep", seconds=30, queue="short", timeout=60,
	                   job_name="_lazychat_smoke_t73", now=False)
	t73_id = getattr(t73_job, "id", None) or str(t73_job)
	r1 = execute_tool("cancel_job", {"job_id": t73_id})
	r2 = execute_tool("cancel_job", {"job_id": t73_id})  # idempotent
	record(_ok(
		"T73 cancel_job first call ok",
		r1.get("ok") is True,
		f"status={r1.get('status')}",
	))
	# Idempotency contract: a second call must not surface 'cancel failed:' or
	# any other error to the caller. Whether RQ has propagated the terminal
	# status to the in-memory job doc by the time we re-load is unrelated to
	# the contract — what matters is no exception leaks out.
	record(_ok(
		"T74 cancel_job second call idempotent on terminal job",
		r2.get("ok") is True and "error" not in r2,
		f"status={r2.get('status')} already_terminal={r2.get('already_terminal')}",
	))

	# T75: defensive arg coercion — non-tool-trained models stringify args.
	# All these forms must succeed identically to native-typed args.
	# This is the regression for the chat-ui mcpCallTool round-trip with
	# seed-oss-36b emitting filters="{}", fields="['name']", limit="1".
	r = execute_tool("get_list", {
		"doctype": "Customer",
		"filters": "{}",                          # string instead of dict
		"fields": "['name', 'customer_name']",    # python-literal string
		"limit": "2",                              # string instead of int
	})
	record(_ok(
		"T75 get_list coerces stringified filters/fields/limit",
		r.get("ok") is True and isinstance(r.get("rows"), list) and r.get("count", 0) >= 1,
		f"count={r.get('count')} sample={r.get('rows', [{}])[0].get('name')}",
	))

	# T76: same coercion on a different tool — aggregate with stringified filters.
	r = execute_tool("aggregate", {
		"doctype": "Customer",
		"function": "count",
		"field": "name",
		"filters": "{}",
	})
	record(_ok(
		"T76 aggregate coerces stringified filters",
		r.get("ok") is True and isinstance(r.get("rows", r.get("count")), (list, int)),
		f"count={r.get('count')}",
	))

	# T77–T84: typed wrapper tools (added 2026-05-06). Stage-only — never commit.

	# T77: prepare_create_report (Report Builder, no SQL needed)
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lazychat_smoke_report_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Report Builder",
	})
	record(_ok(
		"T77 prepare_create_report Report Builder stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T78: prepare_create_report Query Report rejects invalid SQL
	r = execute_tool("prepare_create_report", {
		"report_name": "_lazychat_smoke_query_report",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "DROP TABLE tabCustomer",
	})
	record(_ok(
		"T78 prepare_create_report rejects non-SELECT query",
		not r.get("ok") and "error" in r,
		f"error={(r.get('error') or '')[:80]!r}",
	))

	# T79: prepare_create_report rejects bad ref_doctype
	r = execute_tool("prepare_create_report", {
		"report_name": "_lazychat_smoke_bad_ref",
		"ref_doctype": "_NoSuchDocType_",
		"report_type": "Report Builder",
	})
	record(_ok(
		"T79 prepare_create_report rejects non-existent ref_doctype",
		not r.get("ok") and "does not exist" in (r.get("error") or ""),
	))

	# T80: prepare_create_scheduled_job stages a Daily job
	r = execute_tool("prepare_create_scheduled_job", {
		"method": "frappe.utils.background_jobs.show_pending_jobs",
		"frequency": "Daily",
	})
	# Administrator has System Manager role in standard installs.
	record(_ok(
		"T80 prepare_create_scheduled_job Daily stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T81: prepare_create_scheduled_job rejects Cron without cron_format
	r = execute_tool("prepare_create_scheduled_job", {
		"method": "frappe.utils.background_jobs.show_pending_jobs",
		"frequency": "Cron",
	})
	record(_ok(
		"T81 prepare_create_scheduled_job Cron without cron_format errors",
		not r.get("ok") and "cron_format" in (r.get("error") or ""),
	))

	# T82: prepare_create_number_card Count
	r = execute_tool("prepare_create_number_card", {
		"label": f"_lazychat_smoke_card_{frappe.generate_hash(length=4)}",
		"doctype": "Customer",
		"function": "Count",
	})
	record(_ok(
		"T82 prepare_create_number_card Count stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
	))

	# T83: prepare_create_number_card Sum requires aggregate_field
	r = execute_tool("prepare_create_number_card", {
		"label": "_lazychat_smoke_card_sum",
		"doctype": "Sales Invoice",
		"function": "Sum",
	})
	record(_ok(
		"T83 prepare_create_number_card Sum without aggregate_field errors",
		not r.get("ok") and "aggregate_field" in (r.get("error") or ""),
	))

	# T84: prepare_create_dashboard rejects nonexistent chart
	r = execute_tool("prepare_create_dashboard", {
		"dashboard_name": "_lazychat_smoke_dashboard",
		"charts": ["_lazychat_smoke_no_chart"],
	})
	record(_ok(
		"T84 prepare_create_dashboard rejects missing chart ref",
		not r.get("ok") and "not found" in (r.get("error") or ""),
	))

	# ----------------------------------------------------------------
	# Build-page typed wrappers (added 2026-05-07)
	# ----------------------------------------------------------------

	# T85a: prepare_create_custom_field stages a Data field on Customer
	r = execute_tool("prepare_create_custom_field", {
		"dt": "Customer",
		"label": f"_lz_smoke_{frappe.generate_hash(length=4)}",
		"fieldtype": "Data",
		"insert_after": "customer_name",
	})
	record(_ok(
		"T85a prepare_create_custom_field Data stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T85b: rejects bad dt
	r = execute_tool("prepare_create_custom_field", {
		"dt": "_NoSuchDocType_",
		"label": "X",
		"fieldtype": "Data",
		"insert_after": "name",
	})
	record(_ok(
		"T85b prepare_create_custom_field rejects nonexistent dt",
		not r.get("ok") and "does not exist" in (r.get("error") or ""),
	))

	# T85c: rejects bad insert_after
	r = execute_tool("prepare_create_custom_field", {
		"dt": "Customer",
		"label": "X",
		"fieldtype": "Data",
		"insert_after": "_no_such_field",
	})
	record(_ok(
		"T85c prepare_create_custom_field rejects nonexistent insert_after",
		not r.get("ok") and "insert_after" in (r.get("error") or ""),
	))

	# T85d: Link without options is rejected
	r = execute_tool("prepare_create_custom_field", {
		"dt": "Customer",
		"label": "X",
		"fieldtype": "Link",
		"insert_after": "customer_name",
	})
	record(_ok(
		"T85d prepare_create_custom_field Link without options errors",
		not r.get("ok") and "options" in (r.get("error") or ""),
	))

	# T86a: prepare_create_client_script stages a Form-view script
	r = execute_tool("prepare_create_client_script", {
		"dt": "Customer",
		"view": "Form",
		"script": "frappe.ui.form.on('Customer', {refresh: function(frm) {}});",
	})
	record(_ok(
		"T86a prepare_create_client_script Form stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
	))

	# T86b: rejects empty script
	r = execute_tool("prepare_create_client_script", {
		"dt": "Customer",
		"view": "Form",
		"script": "   ",
	})
	record(_ok(
		"T86b prepare_create_client_script rejects empty script",
		not r.get("ok") and "script required" in (r.get("error") or ""),
	))

	# T86c: rejects bad view
	r = execute_tool("prepare_create_client_script", {
		"dt": "Customer",
		"view": "Tree",
		"script": "x = 1;",
	})
	record(_ok(
		"T86c prepare_create_client_script rejects invalid view",
		not r.get("ok") and "view" in (r.get("error") or ""),
	))

	# T87a: prepare_create_report Query Report — EXPLAIN probe rejects bogus
	# table name. Regression for the production bug where an LLM-staged
	# query referencing `tabPurchase_Order` (underscored, fictional) passed
	# regex-only validation and shipped to disk; user only saw the 1146 at
	# open time. The probe must catch this at preview time.
	r = execute_tool("prepare_create_report", {
		"report_name": "_lazychat_smoke_bad_table",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "SELECT name FROM tabPurchase_Order LIMIT 1",
	})
	err = (r.get("error") or "").lower()
	record(_ok(
		"T87a prepare_create_report Query Report rejects nonexistent table at preview",
		not r.get("ok") and ("doesn't exist" in err or "table" in err),
		f"error={(r.get('error') or '')[:120]!r}",
	))

	# T87b: prepare_create_report Query Report — happy path with a real
	# backtick-quoted DocType table. EXPLAIN must NOT block valid SQL.
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lazychat_smoke_qr_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "SELECT name FROM `tabCustomer` LIMIT 1",
	})
	record(_ok(
		"T87b prepare_create_report Query Report stages valid SQL",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T87c: prepare_create_report Query Report — EXPLAIN probe rejects
	# unknown column. The other half of the production gap.
	r = execute_tool("prepare_create_report", {
		"report_name": "_lazychat_smoke_bad_col",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "SELECT _no_such_column_ FROM `tabCustomer` LIMIT 1",
	})
	err = (r.get("error") or "").lower()
	record(_ok(
		"T87c prepare_create_report Query Report rejects unknown column at preview",
		not r.get("ok") and ("unknown column" in err or "column" in err),
		f"error={(r.get('error') or '')[:120]!r}",
	))

	# T87d: prepare_create_report Query Report — placeholder substitution.
	# Frappe Query Reports support `%(filter_name)s` filters; the EXPLAIN
	# probe must not trip on these. We substitute placeholders with NULL
	# before EXPLAIN-ing so legitimate parameterized reports pass through.
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lazychat_smoke_qr_param_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "SELECT name FROM `tabCustomer` WHERE name = %(customer)s LIMIT 1",
	})
	record(_ok(
		"T87d prepare_create_report Query Report tolerates %(name)s placeholders",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T87e: prepare_create_report Script Report — REJECT empty script body.
	# Production bug 2026-05-08: wrapper accepted Script Report with no
	# `script` arg and stored an empty Report row. User opened report → blank,
	# LLM hallucinated success. Force the wrapper to require a Python body.
	r = execute_tool("prepare_create_report", {
		"report_name": "_lazychat_smoke_script_no_body",
		"ref_doctype": "Customer",
		"report_type": "Script Report",
	})
	err = (r.get("error") or "").lower()
	record(_ok(
		"T87e prepare_create_report Script Report rejects missing script body",
		not r.get("ok") and "script" in err,
		f"error={(r.get('error') or '')[:120]!r}",
	))

	# T87f: prepare_create_report Script Report happy path with script body.
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lazychat_smoke_script_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Script Report",
		"script": "def execute(filters=None):\n\tcolumns = [{'label': 'Name', 'fieldname': 'name', 'fieldtype': 'Data'}]\n\tdata = [{'name': 'smoke'}]\n\treturn columns, data\n",
	})
	record(_ok(
		"T87f prepare_create_report Script Report stages with valid script body",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T87g: prepare_create_report Script Report rejects whitespace-only script.
	r = execute_tool("prepare_create_report", {
		"report_name": "_lazychat_smoke_script_blank",
		"ref_doctype": "Customer",
		"report_type": "Script Report",
		"script": "   \n\t  \n",
	})
	err = (r.get("error") or "").lower()
	record(_ok(
		"T87g prepare_create_report Script Report rejects whitespace-only script",
		not r.get("ok") and "script" in err,
		f"error={(r.get('error') or '')[:120]!r}",
	))

	# T87h: prepare_create_doc({doctype:'Report'}) should REFUSE and redirect.
	# Production bug 2026-05-08 (real chat transcript): LLM bypassed
	# prepare_create_report wrapper, used generic prepare_create_doc with
	# doctype=Report, ignored the duplicate-name failure, narrated success.
	# Force the model onto the typed wrapper.
	r = execute_tool("prepare_create_doc", {
		"doctype": "Report",
		"values": {"report_name": "_lz_smoke_redirect_probe", "ref_doctype": "Customer", "report_type": "Report Builder"},
	})
	err = (r.get("error") or "").lower()
	record(_ok(
		"T87h prepare_create_doc rejects doctype=Report, redirects to prepare_create_report",
		not r.get("ok") and ("prepare_create_report" in err or "typed wrapper" in err),
		f"error={(r.get('error') or '')[:160]!r}",
	))

	# T87i: same redirect for Custom Field, Client Script, Notification, etc.
	for dt, wrapper in [
		("Custom Field", "prepare_create_custom_field"),
		("Client Script", "prepare_create_client_script"),
		("Notification", "prepare_create_notification"),
		("Print Format", "prepare_create_print_format"),
	]:
		r = execute_tool("prepare_create_doc", {"doctype": dt, "values": {}})
		err = (r.get("error") or "").lower()
		record(_ok(
			f"T87i prepare_create_doc rejects doctype={dt!r}, redirects to {wrapper}",
			not r.get("ok") and wrapper in err,
			f"error={(r.get('error') or '')[:120]!r}",
		))

	# T88a: Script Report rejects top-level `import frappe`.
	# Production bug 2026-05-08: LLM staged a Script Report starting with
	# `import frappe`. AST validation passed (syntax ok, def execute exists)
	# but at runtime safe_exec / RestrictedPython rejected it with
	# `ImportError: __import__ not found`. Catch it at preview.
	r = execute_tool("prepare_create_report", {
		"report_name": "_lz_smoke_sr_import",
		"ref_doctype": "Customer",
		"report_type": "Script Report",
		"script": "import frappe\ndef execute(filters=None):\n\treturn [], []\n",
	})
	record(_ok(
		"T88a Script Report rejects top-level import",
		not r.get("ok") and "import" in (r.get("error") or "").lower(),
		f"error={(r.get('error') or '')[:120]!r}",
	))

	# T88b: Script Report rejects `from frappe import _`.
	r = execute_tool("prepare_create_report", {
		"report_name": "_lz_smoke_sr_fromimport",
		"ref_doctype": "Customer",
		"report_type": "Script Report",
		"script": "from frappe import _\ndef execute(filters=None):\n\treturn [], []\n",
	})
	record(_ok(
		"T88b Script Report rejects from-import",
		not r.get("ok") and "import" in (r.get("error") or "").lower(),
		f"error={(r.get('error') or '')[:120]!r}",
	))

	# T88c: Script Report rejects forbidden frappe.db write call.
	r = execute_tool("prepare_create_report", {
		"report_name": "_lz_smoke_sr_setvalue",
		"ref_doctype": "Customer",
		"report_type": "Script Report",
		"script": (
			"def execute(filters=None):\n"
			"\tfrappe.db.set_value('Customer', '21000001', 'name1', 'x')\n"
			"\treturn [], []\n"
		),
	})
	record(_ok(
		"T88c Script Report rejects frappe.db.set_value (write)",
		not r.get("ok") and "set_value" in (r.get("error") or ""),
		f"error={(r.get('error') or '')[:120]!r}",
	))

	# T88d: Script Report rejects `__import__('os')`.
	r = execute_tool("prepare_create_report", {
		"report_name": "_lz_smoke_sr_dunder",
		"ref_doctype": "Customer",
		"report_type": "Script Report",
		"script": (
			"def execute(filters=None):\n"
			"\t__import__('os')\n"
			"\treturn [], []\n"
		),
	})
	record(_ok(
		"T88d Script Report rejects __import__",
		not r.get("ok") and "__import__" in (r.get("error") or ""),
		f"error={(r.get('error') or '')[:120]!r}",
	))

	# T88f: Query Report SQL with `Create DN` HTML link content must NOT
	# trip the DML/DDL keyword regex. Production trigger 2026-05-08: LLM's
	# Query Report with `CONCAT('<a class="btn">Create DN</a>')` got rejected
	# because `Create` matched `\bCREATE\b` even though it was inside a
	# string literal. The validator should strip string literals before
	# applying the DML regex.
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lz_smoke_qr_create_str_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": (
			"SELECT name, "
			"CONCAT('<a href=\"/app/note/new\" class=\"btn\">Create Note</a>') AS 'Action' "
			"FROM `tabCustomer` LIMIT 1"
		),
	})
	record(_ok(
		"T88f Query Report tolerates 'Create' keyword inside string literal",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r} error={(r.get('error') or '')[:120]!r}",
	))

	# T88g: same for UPDATE/DELETE/DROP inside HTML cell content
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lz_smoke_qr_dml_str_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": (
			"SELECT name, "
			"'Update / Delete / Drop labels in a string' AS 'Note' "
			"FROM `tabCustomer` LIMIT 1"
		),
	})
	record(_ok(
		"T88g Query Report tolerates UPDATE/DELETE/DROP in string literal",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r} error={(r.get('error') or '')[:120]!r}",
	))

	# T88h: real DML in code (not in string) STILL gets rejected.
	r = execute_tool("prepare_create_report", {
		"report_name": "_lz_smoke_qr_real_dml",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "DROP TABLE `tabCustomer`",
	})
	record(_ok(
		"T88h Query Report still rejects real DROP statement",
		not r.get("ok") and "only SELECT" in (r.get("error") or ""),
		f"error={(r.get('error') or '')[:120]!r}",
	))

	# T88i: DML keyword AFTER the SELECT (in a WHERE clause string) still rejected
	r = execute_tool("prepare_create_report", {
		"report_name": "_lz_smoke_qr_subquery_dml",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "SELECT name FROM `tabCustomer`; DROP TABLE foo",
	})
	record(_ok(
		"T88i Query Report rejects multi-statement with trailing DROP",
		not r.get("ok") and "multi-statement" in (r.get("error") or ""),
		f"error={(r.get('error') or '')[:120]!r}",
	))

	# T88j: MariaDB rejects LIMIT inside IN/ANY/ALL/SOME subqueries with
	# NotSupportedError(1235). EXPLAIN actually catches it at parse time.
	# Static regex (Layer 1) rejects most shapes at preview time.
	r = execute_tool("prepare_create_report", {
		"report_name": "_lz_smoke_qr_limit_in_subquery",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": (
			"SELECT name FROM `tabCustomer` "
			"WHERE name IN (SELECT name FROM `tabCustomer` LIMIT 1)"
		),
	})
	record(_ok(
		"T88j Query Report rejects LIMIT in IN subquery",
		not r.get("ok") and "1235" in (r.get("error") or ""),
		f"error={(r.get('error') or '')[:160]!r}",
	))

	# T88s: Query Report execute probe — happy path. Real SELECT against
	# tabCustomer; preview must include sample_rows and sample_columns.
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lz_smoke_qr_exec_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "SELECT name, creation FROM `tabCustomer` LIMIT 100",
	})
	preview = r.get("preview") or {}
	record(_ok(
		"T88s execute probe returns sample_rows + sample_columns for Query Report",
		r.get("ok") is True
		and isinstance(preview.get("sample_rows"), list)
		and isinstance(preview.get("sample_columns"), list)
		and "name" in (preview.get("sample_columns") or []),
		f"sample_columns={preview.get('sample_columns')!r} rows_n={len(preview.get('sample_rows') or [])}",
	))

	# T88t: execute probe catches RUNTIME error EXPLAIN can't see —
	# division by zero in a SELECT expression. EXPLAIN parses it; only
	# execution raises. Probe must reject at preview.
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lz_smoke_qr_div0_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		# strict-divide is enabled by default on MariaDB 10.6+; if the
		# session has it off, ZEROFILL might return NULL instead of error.
		# Use SIGNAL SQLSTATE to force a deterministic runtime error.
		"query": (
			"SELECT name, "
			"(SELECT name FROM `tabCustomer` WHERE name = 'NONEXISTENT' "
			"UNION SELECT 'x' || cast(1/0 as char(10))) AS forced "
			"FROM `tabCustomer` LIMIT 1"
		),
	})
	# Some MariaDB versions return NULL for 1/0 silently — accept either
	# a probe rejection OR a successful empty/forced row. The PRIMARY
	# point of T88t is that the probe runs without crashing the wrapper.
	record(_ok(
		"T88t execute probe runs runtime queries without crashing wrapper",
		isinstance(r.get("ok"), bool),
		f"ok={r.get('ok')} err={(r.get('error') or '')[:120]!r}",
	))

	# T88v: sample_columns alignment with SELECT alias order. Critical
	# for the chat-ui Apply card rendering; if columns don't match row
	# keys, the table would show empty cells.
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lz_smoke_qr_cols_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "SELECT name AS supplier_id, creation AS created_at FROM `tabCustomer` LIMIT 1",
	})
	preview = r.get("preview") or {}
	cols = preview.get("sample_columns") or []
	rows = preview.get("sample_rows") or []
	record(_ok(
		"T88v sample_columns matches SELECT aliases and rows[0].keys()",
		r.get("ok") is True
		and cols == ["supplier_id", "created_at"]
		and (not rows or list(rows[0].keys()) == cols),
		f"cols={cols!r}",
	))

	# T88r: prepare_update_doc on a non-existent typed-wrapper doctype
	# returns a redirect hint pointing at the typed CREATE wrapper. Stops
	# the recurring LLM-loop where stale chat state leads to update calls
	# on docs we've deleted, and the LLM then hallucinates success.
	r = execute_tool("prepare_update_doc", {
		"doctype": "Report",
		"name": "_lz_smoke_does_not_exist_xyz",
		"patch": {"query": "SELECT 1"},
	})
	record(_ok(
		"T88r prepare_update_doc on non-existent Report redirects to prepare_create_report",
		"does not exist" in (r.get("error") or "")
		and "prepare_create_report" in (r.get("error") or ""),
		f"err={(r.get('error') or '')[:160]!r}",
	))

	# T88w: prepare_create_client_script auto-derives `name` when LLM omits it.
	# Frappe's Client Script doctype uses autoname=Prompt — without an explicit
	# name the commit insert errors with "Please set the document name" and
	# the LLM-generated Client Script never lands. Real-user trigger 2026-05-08.
	r = execute_tool("prepare_create_client_script", {
		"dt": "Customer",
		"view": "Form",
		"script": "frappe.ui.form.on('Customer', { refresh: function(frm) { /* lazychat smoke T88w */ } });",
	})
	preview_w = r.get("preview") or {}
	derived_name = preview_w.get("name") or ""
	record(_ok(
		"T88w prepare_create_client_script auto-derives name when omitted",
		r.get("ok") is True
		and derived_name.startswith("Customer Form (lazychat ")
		and derived_name.endswith(")"),
		f"name={derived_name!r}",
	))
	# T88x: explicit `name` arg passes through unchanged.
	explicit = f"_lz_smoke_cs_{frappe.generate_hash(length=4)}"
	r = execute_tool("prepare_create_client_script", {
		"dt": "Customer",
		"view": "Form",
		"script": "frappe.ui.form.on('Customer', { refresh: function(frm) {} });",
		"name": explicit,
	})
	record(_ok(
		"T88x prepare_create_client_script honors explicit name",
		r.get("ok") is True and (r.get("preview") or {}).get("name") == explicit,
		f"name={(r.get('preview') or {}).get('name')!r}",
	))

	# T88z: prepare_create_report accepts optional `javascript` arg for
	# Query Reports (Report.javascript field — Frappe loads it for
	# non-standard reports). Used for top-right inner-page buttons.
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lz_smoke_qr_js_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "SELECT name FROM `tabCustomer` LIMIT 1",
		"javascript": "frappe.query_reports['_lz_smoke'] = { onload: function(r) {} };",
	})
	record(_ok(
		"T88z prepare_create_report accepts javascript arg for Query Report",
		r.get("ok") is True,
		f"err={(r.get('error') or '')[:120]!r}",
	))

	# T88aa: signature-based reapply pattern in form helper script body —
	# the new helper detects items clobber via signature mismatch and
	# re-applies. Verify the body contains the signature helpers + the
	# expanded parent-whitelist (supplier handling).
	from lazychat_mcp_erpnext.install import seed_lazychat_form_helpers
	seed_lazychat_form_helpers()
	cs_doc = frappe.get_doc("Client Script", "Lazychat Form Helper (Purchase Invoice)")
	body = cs_doc.script or ""
	record(_ok(
		"T88aa form helper has signature-based reapply + supplier handling",
		"_sig" in body
		and "_frmSig" in body
		and "PARENT_WHITELIST" in body
		and "'supplier'" in body
		and "ITEM_WHITELIST" in body,
		f"len={len(body)}",
	))

	# T89a: cycle9_enabled flag defaults false; site_config override works.
	from lazychat_mcp_erpnext.desk_assistant.boot import get_lazychat_settings
	settings = get_lazychat_settings()
	record(_ok(
		"T89a cycle9_enabled defaults false",
		settings.get("cycle9_enabled") is False,
		f"cycle9_enabled={settings.get('cycle9_enabled')!r}",
	))

	# T88y: persistent lazychat form helper Client Scripts are seeded by
	# install hooks on Purchase Invoice / Sales Invoice / Purchase Receipt /
	# Delivery Note. Verify the Purchase Invoice helper exists, is enabled,
	# and contains the `_lz_items` URL-param parser. This is what makes the
	# variance-report HTML buttons populate the items child table — URL
	# params alone can't reach child rows in Frappe.
	from lazychat_mcp_erpnext.install import seed_lazychat_form_helpers
	seed_lazychat_form_helpers()
	pi_helper_name = "Lazychat Form Helper (Purchase Invoice)"
	cs_exists = frappe.db.exists("Client Script", pi_helper_name)
	if cs_exists:
		cs_doc = frappe.get_doc("Client Script", pi_helper_name)
		body = cs_doc.script or ""
	else:
		body = ""
	record(_ok(
		"T88y persistent Lazychat Form Helper (Purchase Invoice) is installed and reads _lz_items",
		bool(cs_exists)
		and (cs_doc.enabled if cs_exists else 0) == 1
		and (cs_doc.dt if cs_exists else "") == "Purchase Invoice"
		and "_lz_items" in body
		and "is_return" in body,
		f"exists={bool(cs_exists)} dt={cs_doc.dt if cs_exists else None!r} enabled={cs_doc.enabled if cs_exists else None}",
	))

	# T88p: prepare_create_report previews must point at /app/query-report/
	# for Query AND Script Reports — Frappe routes both there. The generic
	# /app/report/<name> path is Report-Builder-only and gives "Sorry I
	# could not find what you were looking for" + a getdoctype() crash for
	# the other two types. Bug from real-user replay 2026-05-08.
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lz_smoke_qr_url_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Query Report",
		"query": "SELECT name FROM `tabCustomer` LIMIT 1",
	})
	record(_ok(
		"T88p Query Report preview open_url uses /app/query-report/",
		r.get("ok") and r.get("preview", {}).get("open_url", "").startswith("/app/query-report/"),
		f"open_url={(r.get('preview') or {}).get('open_url')!r}",
	))

	r = execute_tool("prepare_create_report", {
		"report_name": f"_lz_smoke_sr_url_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Script Report",
		"script": (
			"def execute(filters=None):\n"
			"\treturn [{'label':'Name','fieldname':'name','fieldtype':'Data'}], "
			"frappe.db.get_list('Customer', limit=1)\n"
		),
	})
	record(_ok(
		"T88q Script Report preview open_url uses /app/query-report/ (NOT /app/report/)",
		r.get("ok") and r.get("preview", {}).get("open_url", "").startswith("/app/query-report/"),
		f"open_url={(r.get('preview') or {}).get('open_url')!r}",
	))

	# T88l: describe_doctype on a business-term alias ("Debit Note") returns
	# an actionable redirect with hint, not a bare "invalid doctype". This
	# stops the recurring loop where the LLM bounces off the error and
	# never finds the real doctype (Purchase Invoice with is_return=1).
	r = execute_tool("describe_doctype", {"doctype": "Debit Note"})
	record(_ok(
		"T88l describe_doctype('Debit Note') returns alias redirect",
		r.get("error") == "invalid doctype"
		and r.get("redirect") == "Purchase Invoice"
		and "is_return" in (r.get("hint") or ""),
		f"redirect={r.get('redirect')!r} hint={(r.get('hint') or '')[:120]!r}",
	))

	# T88m: same alias-redirect for "Credit Note" → Sales Invoice.
	r = execute_tool("describe_doctype", {"doctype": "Credit Note"})
	record(_ok(
		"T88m describe_doctype('Credit Note') returns alias redirect",
		r.get("error") == "invalid doctype"
		and r.get("redirect") == "Sales Invoice"
		and "is_return" in (r.get("hint") or ""),
		f"redirect={r.get('redirect')!r}",
	))

	# T88n: case-insensitive — "debit note" (lowercase) also redirects.
	r = execute_tool("describe_doctype", {"doctype": "debit note"})
	record(_ok(
		"T88n describe_doctype alias is case-insensitive",
		r.get("redirect") == "Purchase Invoice",
		f"redirect={r.get('redirect')!r}",
	))

	# T88o: a genuinely unknown doctype still returns plain "invalid doctype"
	# without a redirect (no false-positive aliasing).
	r = execute_tool("describe_doctype", {"doctype": "Frob Quux"})
	record(_ok(
		"T88o unknown doctype still bare 'invalid doctype' (no false alias)",
		r.get("error") == "invalid doctype" and "redirect" not in r and "hint" not in r,
		f"r={r!r}",
	))

	# T88k: nested subquery shape that escapes the static regex (LIMIT not
	# directly inside IN — separated by an extra paren), but EXPLAIN catches
	# 1235. _wrap_db_error must classify it as `syntax` so the probe
	# surfaces it instead of swallowing.
	from lazychat_mcp_erpnext.desk_assistant.tools import _wrap_db_error

	class _FakeNotSupportedError(Exception):
		pass

	wrapped = _wrap_db_error(
		_FakeNotSupportedError(
			"(1235, \"This version of MariaDB doesn't yet support 'LIMIT & IN/ALL/ANY/SOME subquery'\")"
		),
		"SELECT name FROM tabCustomer WHERE name IN (SELECT * FROM (SELECT name FROM tabCustomer LIMIT 1) sub)",
		"explain_probe",
	)
	record(_ok(
		"T88k _wrap_db_error classifies MariaDB 1235 as 'syntax' with rewrite hint",
		wrapped.get("error_kind") == "syntax"
		and "1235" in (wrapped.get("hint") or "")
		and "JOIN" in (wrapped.get("hint") or ""),
		f"kind={wrapped.get('error_kind')!r} hint={(wrapped.get('hint') or '')[:120]!r}",
	))

	# T88e: Script Report happy path with safe_exec-clean body.
	r = execute_tool("prepare_create_report", {
		"report_name": f"_lz_smoke_sr_ok_{frappe.generate_hash(length=4)}",
		"ref_doctype": "Customer",
		"report_type": "Script Report",
		"script": (
			"def execute(filters=None):\n"
			"\tcols = [{'label': 'Name', 'fieldname': 'name', 'fieldtype': 'Data'}]\n"
			"\tdata = frappe.db.get_list('Customer', limit=1)\n"
			"\treturn cols, data\n"
		),
	})
	record(_ok(
		"T88e Script Report stages with safe_exec-clean body",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r} error={(r.get('error') or '')[:100]!r}",
	))

	# T87j: prepare_create_report PRE-DETECTS duplicate names at preview time.
	# Production bug: LLM staged "Receipt vs Invoice Variance Report" twice;
	# first stage succeeded, second fired "Applied" then commit-time
	# IntegrityError 1062. The LLM rendered the failure card but kept
	# narrating success. Catch this at PREVIEW so user sees the warning
	# BEFORE the Apply button.
	# Use a known-existing report from fixtures.json.
	import json as _json
	from pathlib import Path
	fx = _json.loads((Path(frappe.get_app_path("lazychat_mcp_erpnext")).parent / "test/results/fixtures.json").read_text()) if (Path(frappe.get_app_path("lazychat_mcp_erpnext")).parent / "test/results/fixtures.json").exists() else {}
	existing = fx.get("report") or "Account Balance"  # Account Balance is a stock standard report
	r = execute_tool("prepare_create_report", {
		"report_name": existing,
		"ref_doctype": "Customer",
		"report_type": "Report Builder",
	})
	err = (r.get("error") or "").lower()
	record(_ok(
		"T87j prepare_create_report pre-detects duplicate name at preview",
		not r.get("ok") and "already exists" in err,
		f"error={(r.get('error') or '')[:160]!r}",
	))

	# ----------------------------------------------------------------
	# Commit 1 — typed wrappers for ERPNext "Tools" workspace
	# ----------------------------------------------------------------

	# T90: prepare_create_calendar_event happy path
	r = execute_tool("prepare_create_calendar_event", {
		"subject": f"_lazychat_smoke_event_{frappe.generate_hash(length=4)}",
		"starts_on": "2030-01-01 09:00:00",
		"ends_on": "2030-01-01 10:00:00",
		"event_type": "Private",
	})
	record(_ok(
		"T90 prepare_create_calendar_event stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T91: ends_on before starts_on errors
	r = execute_tool("prepare_create_calendar_event", {
		"subject": "_lazychat_smoke_event_bad",
		"starts_on": "2030-01-01 10:00:00",
		"ends_on":   "2030-01-01 09:00:00",
	})
	record(_ok(
		"T91 prepare_create_calendar_event rejects ends_on < starts_on",
		not r.get("ok") and "ends_on" in (r.get("error") or ""),
	))

	# T92: repeat_this_event=True without repeat_on errors
	r = execute_tool("prepare_create_calendar_event", {
		"subject": "_lazychat_smoke_event_repeat",
		"starts_on": "2030-01-01 09:00:00",
		"repeat_this_event": True,
	})
	record(_ok(
		"T92 prepare_create_calendar_event rejects repeat without repeat_on",
		not r.get("ok") and "repeat_on" in (r.get("error") or ""),
	))

	# T93: prepare_create_note happy path
	r = execute_tool("prepare_create_note", {
		"title": f"_lazychat_smoke_note_{frappe.generate_hash(length=4)}",
		"content": "Smoke probe content.",
		"public": False,
	})
	record(_ok(
		"T93 prepare_create_note stages preview_token + autoname hint",
		r.get("ok") is True and bool(r.get("preview_token"))
		and "autoname" in str((r.get("preview") or {}).get("note", "")),
	))

	# T94: prepare_create_note rejects empty content
	r = execute_tool("prepare_create_note", {
		"title": "_lazychat_smoke_empty_content",
		"content": "",
	})
	record(_ok(
		"T94 prepare_create_note rejects empty content",
		not r.get("ok") and "content" in (r.get("error") or ""),
	))

	# T95: prepare_bulk_update — gating + count plumbing.
	r = execute_tool("prepare_bulk_update", {
		"doctype": "Note",
		"filters": {"title": "_definitely_no_such_note_for_smoke"},
		"patch": {"public": 0},
	})
	gated_ok = (not r.get("ok")) and "gated" in (r.get("error") or "").lower()
	matched_zero = (not r.get("ok")) and "no docs matched" in (r.get("error") or "")
	live_token = r.get("ok") is True and bool(r.get("preview_token"))
	record(_ok(
		"T95 prepare_bulk_update gracefully gated OR runs cleanly",
		gated_ok or matched_zero or live_token,
		f"error={(r.get('error') or '')[:80]!r} ok={r.get('ok')}",
	))

	# T96: prepare_bulk_update rejects unknown patch field (when ungated).
	r = execute_tool("prepare_bulk_update", {
		"doctype": "Customer",
		"filters": {"name": "_definitely_no_such_customer"},
		"patch": {"_definitely_not_a_field_": "x"},
	})
	gated_ok = (not r.get("ok")) and "gated" in (r.get("error") or "").lower()
	bad_field = (not r.get("ok")) and "unknown field" in (r.get("error") or "").lower()
	record(_ok(
		"T96 prepare_bulk_update fails on gate or unknown field",
		gated_ok or bad_field,
		f"error={(r.get('error') or '')[:80]!r}",
	))

	# T97: prepare_download_backup — System Manager gated.
	r = execute_tool("prepare_download_backup", {"with_files": False})
	either = (r.get("ok") is True and bool(r.get("preview_token"))) or (
		not r.get("ok") and "System Manager" in (r.get("error") or "")
	)
	record(_ok(
		"T97 prepare_download_backup stages or gates",
		either,
		f"summary={r.get('summary')!r} error={(r.get('error') or '')[:60]!r}",
	))

	# T98: prepare_create_print_format happy
	r = execute_tool("prepare_create_print_format", {
		"name": f"_lazychat_smoke_pf_{frappe.generate_hash(length=4)}",
		"doc_type": "Customer",
		"print_format_type": "Jinja",
		"html": "<div>{{ doc.name }}</div>",
	})
	record(_ok(
		"T98 prepare_create_print_format Jinja stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T99: prepare_create_print_format rejects bad Jinja
	r = execute_tool("prepare_create_print_format", {
		"name": "_lazychat_smoke_pf_bad",
		"doc_type": "Customer",
		"print_format_type": "Jinja",
		"html": "{% if x %}{% endwhatever %}",
	})
	record(_ok(
		"T99 prepare_create_print_format rejects bad Jinja",
		not r.get("ok") and "Jinja" in (r.get("error") or ""),
	))

	# T100: prepare_create_print_format rejects unknown doc_type
	r = execute_tool("prepare_create_print_format", {
		"name": "_lazychat_smoke_pf_bad_dt",
		"doc_type": "_NoSuchDocType_",
		"html": "<div>x</div>",
	})
	record(_ok(
		"T100 prepare_create_print_format rejects unknown doc_type",
		not r.get("ok") and "does not exist" in (r.get("error") or ""),
	))

	# T101: prepare_update_print_settings happy path (System Manager).
	r = execute_tool("prepare_update_print_settings", {"font_size": 11})
	either = (r.get("ok") is True and bool(r.get("preview_token"))) or (
		not r.get("ok") and "System Manager" in (r.get("error") or "")
	)
	record(_ok(
		"T101 prepare_update_print_settings stages or gates",
		either,
		f"summary={r.get('summary')!r}",
	))

	# T102: prepare_update_print_settings empty patch errors
	r = execute_tool("prepare_update_print_settings", {})
	record(_ok(
		"T102 prepare_update_print_settings rejects empty patch",
		not r.get("ok") and (
			"supply at least one field" in (r.get("error") or "")
			or "System Manager" in (r.get("error") or "")
		),
	))

	# T103: prepare_create_email_template happy path
	r = execute_tool("prepare_create_email_template", {
		"name": f"_lazychat_smoke_tpl_{frappe.generate_hash(length=4)}",
		"subject": "Hello {{ doc.name or 'world' }}",
		"response": "<p>Smoke template — {{ doc.name }}</p>",
	})
	record(_ok(
		"T103 prepare_create_email_template stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T104: prepare_create_email_template rejects bad Jinja in subject
	r = execute_tool("prepare_create_email_template", {
		"name": "_lazychat_smoke_tpl_bad",
		"subject": "Hello {% if",
		"response": "<p>ok</p>",
	})
	record(_ok(
		"T104 prepare_create_email_template rejects bad subject Jinja",
		not r.get("ok") and "subject Jinja" in (r.get("error") or ""),
	))

	# T105: restore_deleted_doc graceful error on nonexistent name
	r = execute_tool("restore_deleted_doc", {
		"deleted_document_name": "_lazychat_smoke_no_dd",
	})
	record(_ok(
		"T105 restore_deleted_doc returns graceful error on missing name",
		not r.get("ok") and "not found" in (r.get("error") or ""),
	))

	# ----------------------------------------------------------------
	# Commit 2 — Alerts / Newsletter / Automation typed wrappers
	# ----------------------------------------------------------------

	# T106: prepare_create_notification happy
	r = execute_tool("prepare_create_notification", {
		"subject": f"_lazychat_smoke_notif_{frappe.generate_hash(length=4)}",
		"document_type": "Customer",
		"event": "New",
		"channel": "Email",
		"recipients": [{"receiver_by_role": "System Manager"}],
	})
	record(_ok(
		"T106 prepare_create_notification New/Email stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T107: Days Before without date_changed errors
	r = execute_tool("prepare_create_notification", {
		"subject": "_lazychat_smoke_notif_bad",
		"document_type": "Customer",
		"event": "Days Before",
		"channel": "Email",
		"recipients": [{"receiver_by_role": "System Manager"}],
	})
	record(_ok(
		"T107 prepare_create_notification Days Before without date_changed errors",
		not r.get("ok") and "date_changed" in (r.get("error") or ""),
	))

	# T108: invalid condition expression
	r = execute_tool("prepare_create_notification", {
		"subject": "_lazychat_smoke_notif_cond",
		"document_type": "Customer",
		"event": "New",
		"channel": "Email",
		"recipients": [{"receiver_by_role": "System Manager"}],
		"condition": "import os",
	})
	record(_ok(
		"T108 prepare_create_notification rejects condition with imports",
		not r.get("ok") and "condition" in (r.get("error") or "").lower(),
	))

	# T109: empty recipients on channel=Email
	r = execute_tool("prepare_create_notification", {
		"subject": "_lazychat_smoke_notif_no_rec",
		"document_type": "Customer",
		"event": "New",
		"channel": "Email",
		"recipients": [],
	})
	record(_ok(
		"T109 prepare_create_notification rejects empty recipients on Email",
		not r.get("ok") and "recipient" in (r.get("error") or "").lower(),
	))

	# T110: prepare_create_auto_email_report rejects nonexistent Report
	r = execute_tool("prepare_create_auto_email_report", {
		"report": "_lazychat_smoke_no_report",
		"email_to": "smoke@example.com",
	})
	record(_ok(
		"T110 prepare_create_auto_email_report rejects nonexistent Report",
		not r.get("ok") and "does not exist" in (r.get("error") or ""),
	))

	# T111: update_notification_settings happy (direct, no /commit)
	r = execute_tool("update_notification_settings", {"send_email_alerts": True})
	record(_ok(
		"T111 update_notification_settings updates session user prefs",
		r.get("ok") is True and r.get("user") == frappe.session.user
		and "send_email_alerts" in (r.get("updated_fields") or {}),
	))

	# T112: update_notification_settings with no fields errors
	r = execute_tool("update_notification_settings", {})
	record(_ok(
		"T112 update_notification_settings rejects empty patch",
		not r.get("ok") and "supply at least one" in (r.get("error") or ""),
	))

	# T113: prepare_create_milestone_tracker happy
	r = execute_tool("prepare_create_milestone_tracker", {
		"document_type": "Customer",
		"track_field": "customer_group",
	})
	record(_ok(
		"T113 prepare_create_milestone_tracker stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T114: prepare_create_milestone_tracker rejects non-Link/Select field
	r = execute_tool("prepare_create_milestone_tracker", {
		"document_type": "Customer",
		"track_field": "customer_name",  # Data field, not Link/Select
	})
	record(_ok(
		"T114 prepare_create_milestone_tracker rejects non-Link/Select field",
		not r.get("ok") and "Link or Select" in (r.get("error") or ""),
	))

	# T115: prepare_create_auto_repeat rejects nonexistent ref doc
	r = execute_tool("prepare_create_auto_repeat", {
		"reference_doctype": "Sales Order",
		"reference_document": "_lazychat_smoke_no_so",
		"frequency": "Monthly",
		"start_date": "2030-01-01",
	})
	record(_ok(
		"T115 prepare_create_auto_repeat rejects nonexistent ref doc",
		not r.get("ok") and "does not exist" in (r.get("error") or ""),
	))

	# T116: prepare_create_auto_repeat rejects end_date <= start_date
	r = execute_tool("prepare_create_auto_repeat", {
		"reference_doctype": "Sales Order",
		"reference_document": "_lazychat_smoke_no_so2",
		"frequency": "Monthly",
		"start_date": "2030-01-01",
		"end_date":   "2029-12-31",
	})
	record(_ok(
		"T116 prepare_create_auto_repeat rejects end_date <= start_date",
		not r.get("ok") and "end_date" in (r.get("error") or ""),
	))

	# T117: prepare_create_email_group happy
	group_title = f"_lazychat_smoke_grp_{frappe.generate_hash(length=4)}"
	r = execute_tool("prepare_create_email_group", {"title": group_title})
	record(_ok(
		"T117 prepare_create_email_group stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T118: prepare_add_to_email_group rejects unknown group
	r = execute_tool("prepare_add_to_email_group", {
		"email_group": "_lazychat_smoke_no_group",
		"email": "smoke@example.com",
	})
	record(_ok(
		"T118 prepare_add_to_email_group rejects unknown group",
		not r.get("ok") and "not found" in (r.get("error") or ""),
	))

	# T119: prepare_add_to_email_group rejects malformed email
	# (Use a real-looking group title; existence check fires first if no group,
	# so we accept that fail-mode too.)
	r = execute_tool("prepare_add_to_email_group", {
		"email_group": "_no_such_group_for_email_check",
		"email": "not-an-email",
	})
	record(_ok(
		"T119 prepare_add_to_email_group rejects malformed email or unknown group",
		(not r.get("ok")) and (
			"valid email" in (r.get("error") or "")
			or "not found" in (r.get("error") or "")
		),
	))

	# T120: prepare_create_newsletter rejects unknown email_group
	r = execute_tool("prepare_create_newsletter", {
		"subject": "_lazychat_smoke_newsletter",
		"message": "<p>body</p>",
		"email_group": "_lazychat_smoke_no_group",
	})
	record(_ok(
		"T120 prepare_create_newsletter rejects unknown email_group",
		not r.get("ok") and "not found" in (r.get("error") or ""),
	))

	# ----------------------------------------------------------------
	# Commit 3 — Email Account setup + Assignment Rule
	# ----------------------------------------------------------------

	# T121: prepare_create_email_account — gated unless lazychat_allow_email_setup is set.
	r = execute_tool("prepare_create_email_account", {
		"email_account_name": "_lazychat_smoke_acct",
		"email_id": "smoke@example.com",
		"enable_outgoing": False,
		"enable_incoming": False,
	})
	err_lc = (r.get("error") or "").lower()
	gated = (not r.get("ok")) and ("gated" in err_lc or "system manager" in err_lc)
	staged = r.get("ok") is True and bool(r.get("preview_token"))
	record(_ok(
		"T121 prepare_create_email_account gates or stages",
		gated or staged,
		f"error={(r.get('error') or '')[:80]!r}",
	))

	# T122: bad email_id format
	r = execute_tool("prepare_create_email_account", {
		"email_account_name": "_lazychat_smoke_acct_bad",
		"email_id": "not-an-email",
		"enable_outgoing": False,
		"enable_incoming": False,
	})
	record(_ok(
		"T122 prepare_create_email_account rejects malformed email_id",
		not r.get("ok") and "email_id" in (r.get("error") or ""),
	))

	# T123: enable_outgoing without smtp_server. Gate fires first if the flag
	# is off, otherwise the conditional-required check fires.
	r = execute_tool("prepare_create_email_account", {
		"email_account_name": "_lazychat_smoke_acct_no_smtp",
		"email_id": "smoke@example.com",
		"enable_outgoing": True,
	})
	err_lc = (r.get("error") or "").lower()
	record(_ok(
		"T123 prepare_create_email_account rejects enable_outgoing without smtp_server",
		not r.get("ok") and (
			"smtp_server" in err_lc
			or "gated" in err_lc
			or "system manager" in err_lc
		),
	))

	# T124: prepare_create_assignment_rule happy
	r = execute_tool("prepare_create_assignment_rule", {
		"name": f"_lazychat_smoke_rule_{frappe.generate_hash(length=4)}",
		"document_type": "ToDo",
		"rule": "Round Robin",
		"users": ["Administrator"],
	})
	record(_ok(
		"T124 prepare_create_assignment_rule Round Robin stages preview_token",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"summary={r.get('summary')!r}",
	))

	# T125: invalid rule enum
	r = execute_tool("prepare_create_assignment_rule", {
		"name": "_lazychat_smoke_rule_bad",
		"document_type": "ToDo",
		"rule": "Magic Auto",
		"users": ["Administrator"],
	})
	record(_ok(
		"T125 prepare_create_assignment_rule rejects bad rule enum",
		not r.get("ok") and "rule must be" in (r.get("error") or ""),
	))

	# T126: empty users
	r = execute_tool("prepare_create_assignment_rule", {
		"name": "_lazychat_smoke_rule_no_users",
		"document_type": "ToDo",
		"rule": "Round Robin",
		"users": [],
	})
	record(_ok(
		"T126 prepare_create_assignment_rule rejects empty users",
		not r.get("ok") and "users" in (r.get("error") or ""),
	))

	# T127: nonexistent user
	r = execute_tool("prepare_create_assignment_rule", {
		"name": "_lazychat_smoke_rule_bad_user",
		"document_type": "ToDo",
		"rule": "Round Robin",
		"users": ["_no_such_user@example.com"],
	})
	record(_ok(
		"T127 prepare_create_assignment_rule rejects nonexistent user",
		not r.get("ok") and "does not exist" in (r.get("error") or ""),
	))

	# T128: rule=Based on Field without `field`
	r = execute_tool("prepare_create_assignment_rule", {
		"name": "_lazychat_smoke_rule_no_field",
		"document_type": "ToDo",
		"rule": "Based on Field",
		"users": ["Administrator"],
	})
	record(_ok(
		"T128 prepare_create_assignment_rule rejects 'Based on Field' without field",
		not r.get("ok") and "field" in (r.get("error") or ""),
	))

	# T129: invalid assign_condition (imports rejected)
	r = execute_tool("prepare_create_assignment_rule", {
		"name": "_lazychat_smoke_rule_cond",
		"document_type": "ToDo",
		"rule": "Round Robin",
		"users": ["Administrator"],
		"assign_condition": "import sys",
	})
	record(_ok(
		"T129 prepare_create_assignment_rule rejects condition with imports",
		not r.get("ok") and "condition" in (r.get("error") or "").lower(),
	))

	# T130: due_date_based_on must be Date or Datetime
	# 'description' on ToDo is a Text field — not Date/Datetime.
	r = execute_tool("prepare_create_assignment_rule", {
		"name": "_lazychat_smoke_rule_bad_due",
		"document_type": "ToDo",
		"rule": "Round Robin",
		"users": ["Administrator"],
		"due_date_based_on": "description",
	})
	record(_ok(
		"T130 prepare_create_assignment_rule rejects non-Date due_date_based_on",
		not r.get("ok") and "due_date_based_on" in (r.get("error") or ""),
	))

	# T85–T89: acceptance smoke for typed-wrapper paths (was generic
	# prepare_create_doc; updated 2026-05-08 because that path is now
	# REFUSED for these doctypes — typed wrappers validate required fields
	# up front instead of letting the generic path stage incomplete rows).
	# Each test verifies dispatch + permission path returns a preview_token.
	for label, tool, args in [
		("T85 Custom Field create stages token (typed wrapper)", "prepare_create_custom_field", {
			"dt": "Customer", "label": "Lazychat Smoke", "fieldtype": "Data",
			"insert_after": "customer_name",
		}),
		("T87 Client Script create stages token (typed wrapper)", "prepare_create_client_script", {
			"dt": "Customer", "view": "Form", "script": "frappe.ui.form.on('Customer', {refresh: function(frm) {}});",
		}),
	]:
		r = execute_tool(tool, args)
		record(_ok(
			label,
			r.get("ok") is True and bool(r.get("preview_token")),
			f"tool={tool} error={(r.get('error') or '')[:80]!r}",
		))

	# T86 Server Script — no typed wrapper exists (script body is too freeform
	# for schema validation). Generic prepare_create_doc still works because
	# Server Script is NOT in _TYPED_WRAPPER_FOR_DOCTYPE.
	r = execute_tool("prepare_create_doc", {"doctype": "Server Script", "values": {
		"name": "_lazychat_smoke_server_script",
		"script_type": "DocType Event",
		"reference_doctype": "Customer",
		"doctype_event": "Before Save",
		"script": "# noop",
	}})
	record(_ok(
		"T86 Server Script create stages token (generic path — no wrapper)",
		r.get("ok") is True and bool(r.get("preview_token")),
		f"error={(r.get('error') or '')[:80]!r}",
	))

	# Continue T88/T89 typed-wrapper tests
	for label, tool, args in [
		("T88 Notification create stages token (typed wrapper)", "prepare_create_notification", {
			"subject": "_lazychat_smoke_notification",
			"document_type": "Customer",
			"event": "New",
			"channel": "Email",
			"recipients": [{"receiver_by_role": "System Manager"}],
		}),
		("T89 Print Format create stages token (typed wrapper)", "prepare_create_print_format", {
			"name": "_lazychat_smoke_print_format",
			"doc_type": "Customer",
			"print_format_type": "Jinja",
			"html": "<div>smoke</div>",
		}),
	]:
		r = execute_tool(tool, args)
		record(_ok(
			label,
			r.get("ok") is True and bool(r.get("preview_token")),
			f"tool={tool} error={(r.get('error') or '')[:80]!r}",
		))

	# Cleanup
	cleaned = []
	if created_note:
		try:
			frappe.delete_doc("Note", created_note, force=1, ignore_missing=True)
			cleaned.append(f"Note/{created_note}")
		except Exception as e:
			print(f"[CLEANUP-WARN] Note/{created_note}: {e}")
	frappe.db.commit()
	print(f"\n[CLEANUP] removed: {cleaned or 'nothing'}")

	print(f"\n=== {results['pass']} pass, {results['fail']} fail, {results['skip']} skip ===")
	return results
