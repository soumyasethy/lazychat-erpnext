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

	# T5+T6: prepare_create_doc + commit — use Note (Frappe core, minimal required fields)
	test_title = f"_lazychat_smoke_{frappe.generate_hash(length=6)}"
	r = execute_tool(
		"prepare_create_doc",
		{
			"doctype": "Note",
			"values": {"title": test_title, "content": "smoke test note", "public": 0},
		},
	)
	t5 = r.get("ok") and r.get("preview_token")
	record(_ok("T5 prepare_create_doc Note", bool(t5), f"token={t5[:8]}…" if t5 else r.get("error")))

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

	# T32: prepare_send_email — should be REJECTED unless site flag set
	r = execute_tool(
		"prepare_send_email",
		{"recipients": ["test@example.com"], "subject": "smoke", "content": "x"},
	)
	allow = bool(frappe.get_site_config().get("lazychat_allow_email"))
	if allow:
		record(_ok("T32 prepare_send_email staged", bool(r.get("preview_token"))))
	else:
		record(_ok("T32 prepare_send_email gated when flag off", "error" in r and "disabled" in r["error"]))

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

	# T42+T43: prepare_run_sql + run_python with flag OFF — should be REJECTED
	# (Note: even though we will mutate site_config below, frappe.get_site_config caches per request;
	# we test rejection at default site state, then exercise the staged-with-flag-on path via direct token call)
	import os
	import json as _json
	site_path = os.path.join(frappe.local.sites_path, frappe.local.site, "site_config.json")
	with open(site_path) as f:
		conf = _json.load(f)
	flag_was = conf.get("lazychat_allow_dangerous_tools")
	if not flag_was:
		r = execute_tool("prepare_run_sql", {"query": "SELECT 1 as one"})
		record(_ok("T42 prepare_run_sql gated (flag off)", "error" in r and "disabled" in r.get("error", "")))
		r = execute_tool("prepare_run_python", {"code": "_result = 2 + 2"})
		record(_ok("T43 prepare_run_python gated (flag off)", "error" in r and "disabled" in r.get("error", "")))
	else:
		_skip("T42/T43 flag-off rejection", "site already has dangerous tools enabled")
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
