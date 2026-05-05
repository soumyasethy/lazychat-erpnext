import io
import json
import re
import secrets

import frappe
from frappe.utils import get_url as _frappe_get_url

PREP_TTL_SEC = 300
PREP_KEY = "lazychat:prep:"

# DANGEROUS-TOOL GUARD
# These tools (prepare_run_sql, prepare_run_python) require:
#   1. site_config.json: "lazychat_allow_dangerous_tools": true
#   2. Caller has "System Manager" role
#   3. User /commit confirmation per call (two-phase)
SQL_DML_PATTERN = re.compile(
	r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|GRANT|REVOKE|RENAME|LOCK|UNLOCK|CALL|HANDLER)\b",
	re.IGNORECASE,
)
SQL_ALLOWED_PATTERN = re.compile(r"^\s*(WITH|SELECT|\()", re.IGNORECASE)


def _dangerous_tools_enabled():
	# Defer import to avoid circular imports during install (boot.py imports nothing here,
	# but execute_tool can be called very early from MCP wire / smoke tests).
	from lazychat_mcp_erpnext.desk_assistant.boot import get_lazychat_settings

	if not get_lazychat_settings().get("allow_dangerous_tools"):
		return False, (
			"dangerous tools disabled (enable in Desk → Lazychat Settings → "
			"'Allow prepare_run_sql + prepare_run_python Tools', or set "
			"'lazychat_allow_dangerous_tools': true in site_config.json)"
		)
	if "System Manager" not in frappe.get_roles():
		return False, "requires System Manager role"
	return True, None


def _validate_select_sql(sql):
	stripped = (sql or "").strip().rstrip(";")
	if not stripped:
		return "empty query"
	if ";" in stripped:
		return "multi-statement queries not allowed"
	if not SQL_ALLOWED_PATTERN.match(stripped):
		return "only SELECT (or WITH ... SELECT) queries allowed"
	if SQL_DML_PATTERN.search(stripped):
		return "DML/DDL keywords not allowed (INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/...)"
	return None  # OK


def _stage_action(action, payload):
	"""Cache an action payload bound to the current user; return a one-time token."""
	token = secrets.token_urlsafe(16)
	user = frappe.session.user
	frappe.cache().set_value(
		PREP_KEY + token,
		json.dumps({"action": action, "user": user, "payload": payload}, default=str),
		expires_in_sec=PREP_TTL_SEC,
	)
	return token


def _retrieve_action(token):
	user = frappe.session.user
	raw = frappe.cache().get_value(PREP_KEY + token)
	if not raw:
		return None
	try:
		obj = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
	except Exception:
		return None
	if obj.get("user") != user:
		return None
	return obj


def _consume_action(token):
	frappe.cache().delete_value(PREP_KEY + token)


_FILE_PATH_RE = re.compile(r"^/(?:private/)?files/")


def _resolve_file_urls(d):
	"""For every value that looks like a relative Frappe file path, inject an
	absolute sibling under '<key>_url'. Stops the LLM from having to invent
	URLs from raw paths (it does so badly — typical hallucination is
	'/files/<itemcode>_01.png'). Empty/null values produce no sibling.

	Mutates and returns the same dict.
	"""
	if not isinstance(d, dict):
		return d
	additions = {}
	for k, v in d.items():
		if isinstance(v, str) and _FILE_PATH_RE.match(v):
			try:
				additions[f"{k}_url"] = _frappe_get_url(v)
			except Exception:
				pass
	d.update(additions)
	return d


def _trim_doc(doc_dict, max_child_rows=25):
	"""Truncate child-table lists so huge docs don't overflow the LLM context window."""
	note_parts = []
	trimmed = {}
	for k, v in doc_dict.items():
		if isinstance(v, list) and len(v) > max_child_rows:
			trimmed[k] = v[:max_child_rows]
			note_parts.append(f"{k}: showing {max_child_rows} of {len(v)} rows")
		else:
			trimmed[k] = v
	if note_parts:
		trimmed["_note"] = (
			"Child tables truncated — " + "; ".join(note_parts)
			+ ". Use get_list with filters for the full data."
		)
	# Resolve relative file paths on the parent doc (e.g. `image: "/files/foo.png"`
	# gains `image_url: "https://erp.local/files/foo.png"`). Also walk one level
	# of child rows since item images are common.
	_resolve_file_urls(trimmed)
	for k, v in trimmed.items():
		if isinstance(v, list):
			for row in v:
				_resolve_file_urls(row)
	return trimmed


def execute_tool(name, args, *, allow_writes=False, desk_context=None):
	if name == "get_list":
		dt = args.get("doctype")
		if not dt or not frappe.db.exists("DocType", dt):
			return {"error": "invalid doctype"}
		if not frappe.has_permission(dt, "read"):
			return {"error": "no read permission"}
		filters = args.get("filters") or {}
		if isinstance(filters, str):
			filters = json.loads(filters)
		fields = args.get("fields") or ["name"]
		limit = min(int(args.get("limit") or 20), 50)
		try:
			rows = frappe.get_list(dt, filters=filters, fields=fields, limit_page_length=limit)
			return {"ok": True, "count": len(rows), "rows": rows}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_doc":
		dt = args.get("doctype")
		dn = args.get("name")
		if not dt or not dn:
			return {"error": "doctype and name required"}
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission"}
		try:
			doc = frappe.get_doc(dt, dn)
			return {"ok": True, "doc": _trim_doc(doc.as_dict())}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_current_context":
		return {"ok": True, "context": desk_context or {}}

	if name == "describe_doctype":
		dt = args.get("doctype")
		if not dt or not frappe.db.exists("DocType", dt):
			return {"error": "invalid doctype"}
		if not frappe.has_permission(dt, "read"):
			return {"error": "no read permission"}
		try:
			meta = frappe.get_meta(dt)
			fields = []
			for df in meta.fields:
				fields.append(
					{
						"fieldname": df.fieldname,
						"label": df.label,
						"fieldtype": df.fieldtype,
						"options": df.options,
						"reqd": bool(df.reqd),
						"read_only": bool(df.read_only),
						"hidden": bool(df.hidden),
					}
				)
			return {
				"ok": True,
				"doctype": dt,
				"is_submittable": bool(meta.is_submittable),
				"is_table": bool(meta.istable),
				"fields": fields,
			}
		except Exception as e:
			return {"error": str(e)}

	if name == "prepare_create_doc":
		dt = args.get("doctype")
		values = args.get("values") or {}
		if not dt or not frappe.db.exists("DocType", dt):
			return {"error": "invalid doctype"}
		if not frappe.has_permission(dt, "create"):
			return {"error": "no create permission"}
		token = _stage_action("create", {"doctype": dt, "values": values})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create {dt} with {len(values)} field(s)",
			"preview": {"doctype": dt, "fields": values},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "prepare_update_doc":
		dt = args.get("doctype")
		dn = args.get("name")
		patch = args.get("patch") or {}
		if not dt or not dn:
			return {"error": "doctype and name required"}
		if not frappe.has_permission(dt, "write", doc=dn):
			return {"error": "no write permission"}
		try:
			doc = frappe.get_doc(dt, dn)
		except Exception as e:
			return {"error": str(e)}
		diff = {}
		for f, v in patch.items():
			diff[f] = {"from": doc.get(f) if hasattr(doc, "get") else None, "to": v}
		token = _stage_action("update", {"doctype": dt, "name": dn, "patch": patch})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will update {dt}/{dn} — {len(patch)} field(s)",
			"diff": diff,
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "prepare_submit_doc":
		dt = args.get("doctype")
		dn = args.get("name")
		if not dt or not dn:
			return {"error": "doctype and name required"}
		if not frappe.has_permission(dt, "submit", doc=dn):
			return {"error": "no submit permission"}
		try:
			meta = frappe.get_meta(dt)
		except Exception as e:
			return {"error": str(e)}
		if not meta.is_submittable:
			return {"error": f"{dt} is not submittable"}
		token = _stage_action("submit", {"doctype": dt, "name": dn})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will submit {dt}/{dn}",
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "list_workflow_actions":
		dt = args.get("doctype")
		dn = args.get("name")
		if not dt or not dn:
			return {"error": "doctype and name required"}
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission"}
		try:
			from frappe.model.workflow import get_transitions

			doc = frappe.get_doc(dt, dn)
			transitions = get_transitions(doc) or []
			return {
				"ok": True,
				"doctype": dt,
				"name": dn,
				"current_state": getattr(doc, "workflow_state", None),
				"transitions": [
					{
						"action": t.get("action"),
						"next_state": t.get("next_state"),
						"allowed_role": t.get("allowed"),
					}
					for t in transitions
				],
			}
		except Exception as e:
			return {"error": str(e)}

	if name == "prepare_workflow_action":
		dt = args.get("doctype")
		dn = args.get("name")
		action = args.get("action")
		if not dt or not dn or not action:
			return {"error": "doctype, name, and action required"}
		if not frappe.has_permission(dt, "write", doc=dn):
			return {"error": "no write permission"}
		try:
			from frappe.model.workflow import get_transitions

			doc = frappe.get_doc(dt, dn)
			allowed = [t.get("action") for t in (get_transitions(doc) or [])]
			if action not in allowed:
				return {
					"error": f"action '{action}' not allowed from current state",
					"allowed": allowed,
				}
		except Exception as e:
			return {"error": str(e)}
		token = _stage_action("workflow_action", {"doctype": dt, "name": dn, "action": action})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will apply workflow action '{action}' on {dt}/{dn}",
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "prepare_add_comment":
		dt = args.get("doctype")
		dn = args.get("name")
		text = args.get("text")
		if not dt or not dn or not text:
			return {"error": "doctype, name, and text required"}
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission"}
		token = _stage_action("add_comment", {"doctype": dt, "name": dn, "text": text})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will add comment on {dt}/{dn}",
			"preview": {"text": text[:500]},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "prepare_assign_to":
		dt = args.get("doctype")
		dn = args.get("name")
		assign_user = args.get("user")
		description = args.get("description") or ""
		if not dt or not dn or not assign_user:
			return {"error": "doctype, name, and user required"}
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission"}
		if not frappe.db.exists("User", assign_user):
			return {"error": f"user not found: {assign_user}"}
		token = _stage_action(
			"assign_to",
			{"doctype": dt, "name": dn, "user": assign_user, "description": description},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will assign {dt}/{dn} to {assign_user}",
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "aggregate":
		dt = args.get("doctype")
		func = (args.get("function") or "").lower()
		field = args.get("field") or "name"
		group_by = args.get("group_by")
		filters = args.get("filters") or {}
		limit = min(int(args.get("limit") or 50), 200)
		if not dt or not frappe.db.exists("DocType", dt):
			return {"error": "invalid doctype"}
		if not frappe.has_permission(dt, "read"):
			return {"error": "no read permission"}
		if func not in ("sum", "avg", "count", "min", "max"):
			return {"error": "function must be one of sum/avg/count/min/max"}
		if isinstance(filters, str):
			try:
				filters = json.loads(filters)
			except Exception:
				return {"error": "filters must be a JSON object or list"}
		# Validate field/group_by are real fieldnames on the doctype
		try:
			meta = frappe.get_meta(dt)
			valid_fields = {df.fieldname for df in meta.fields} | {"name", "creation", "modified", "owner", "modified_by", "docstatus"}
			if field != "name" and field not in valid_fields:
				return {"error": f"unknown field on {dt}: {field}"}
			if group_by and group_by not in valid_fields:
				return {"error": f"unknown field on {dt}: {group_by}"}
		except Exception as e:
			return {"error": str(e)}
		select_fields = []
		if group_by:
			select_fields.append(group_by)
		select_fields.append(f"{func}(`{field}`) as value")
		try:
			rows = frappe.get_all(
				dt,
				filters=filters,
				fields=select_fields,
				group_by=group_by,
				order_by="value desc",
				limit_page_length=limit,
			)
			return {
				"ok": True,
				"doctype": dt,
				"function": func,
				"field": field,
				"group_by": group_by,
				"count": len(rows),
				"rows": rows,
			}
		except Exception as e:
			return {"error": str(e)}

	if name == "dashboard_chart_data":
		chart_name = args.get("name")
		if not chart_name or not frappe.db.exists("Dashboard Chart", chart_name):
			return {"error": "invalid Dashboard Chart name"}
		if not frappe.has_permission("Dashboard Chart", "read", doc=chart_name):
			return {"error": "no read permission on Dashboard Chart"}
		try:
			from frappe.desk.doctype.dashboard_chart.dashboard_chart import get

			data = get(chart_name=chart_name, refresh=1)
			return {"ok": True, "name": chart_name, "data": data}
		except Exception as e:
			return {"error": str(e)}

	if name == "search_global":
		query = (args.get("query") or "").strip()
		if not query:
			return {"error": "query required"}
		doctypes = args.get("doctypes") or []
		if isinstance(doctypes, str):
			doctypes = [doctypes]
		limit = min(int(args.get("limit") or 20), 50)
		try:
			where = ["content LIKE %(q)s"]
			params = {"q": f"%{query}%", "limit": limit}
			if doctypes:
				ph = ", ".join(f"%(dt{i})s" for i in range(len(doctypes)))
				where.append(f"doctype IN ({ph})")
				for i, dt in enumerate(doctypes):
					params[f"dt{i}"] = dt
			rows = frappe.db.sql(
				f"SELECT doctype, name, content FROM `__global_search` WHERE {' AND '.join(where)} LIMIT %(limit)s",
				params,
				as_dict=True,
			)
			# permission filter
			out = []
			for r in rows:
				if frappe.has_permission(r["doctype"], "read", doc=r["name"]):
					snippet = (r.get("content") or "").strip()[:240]
					out.append({"doctype": r["doctype"], "name": r["name"], "snippet": snippet})
			return {"ok": True, "count": len(out), "results": out}
		except Exception as e:
			return {"error": str(e)}

	if name == "count_doc":
		dt = args.get("doctype")
		if not dt or not frappe.db.exists("DocType", dt):
			return {"error": "invalid doctype"}
		if not frappe.has_permission(dt, "read"):
			return {"error": "no read permission"}
		filters = args.get("filters") or {}
		if isinstance(filters, str):
			try:
				filters = json.loads(filters)
			except Exception:
				return {"error": "invalid filters JSON"}
		try:
			n = frappe.db.count(dt, filters=filters)
			return {"ok": True, "doctype": dt, "count": int(n)}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_value":
		dt = args.get("doctype")
		dn = args.get("name")
		field = args.get("fieldname")
		if not dt or not dn or not field:
			return {"error": "doctype, name, fieldname required"}
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission"}
		try:
			v = frappe.db.get_value(dt, dn, field)
			return {"ok": True, "doctype": dt, "name": dn, "fieldname": field, "value": v}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_doctype_links":
		dt = args.get("doctype")
		dn = args.get("name")
		if not dt or not dn:
			return {"error": "doctype and name required"}
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission"}
		try:
			from frappe.desk.form.linked_with import get_linked_doctypes

			linkinfo = get_linked_doctypes(dt) or {}
			out = {}
			for linked_dt, info in linkinfo.items():
				if not frappe.has_permission(linked_dt, "read"):
					continue
				link_field = info.get("fieldname") if isinstance(info, dict) else None
				if not link_field:
					continue
				try:
					rows = frappe.get_all(
						linked_dt, filters={link_field: dn}, fields=["name"], limit_page_length=20
					)
					if rows:
						out[linked_dt] = [r["name"] for r in rows]
				except Exception:
					continue
			return {"ok": True, "doctype": dt, "name": dn, "linked": out, "linked_count": sum(len(v) for v in out.values())}
		except Exception as e:
			return {"error": str(e)}

	if name == "list_reports":
		module = args.get("module")
		filters = {"disabled": 0}
		if module:
			filters["module"] = module
		try:
			rows = frappe.get_all(
				"Report",
				filters=filters,
				fields=["name", "report_type", "ref_doctype", "module"],
				limit_page_length=100,
				order_by="name",
			)
			# Filter by user perm on ref_doctype
			out = [r for r in rows if not r.get("ref_doctype") or frappe.has_permission(r["ref_doctype"], "read")]
			return {"ok": True, "count": len(out), "reports": out}
		except Exception as e:
			return {"error": str(e)}

	if name == "run_report":
		report_name = args.get("name")
		report_filters = args.get("filters") or {}
		if isinstance(report_filters, str):
			try:
				report_filters = json.loads(report_filters)
			except Exception:
				return {"error": "invalid filters JSON"}
		if not report_name or not frappe.db.exists("Report", report_name):
			return {"error": "invalid report name"}
		try:
			ref_dt = frappe.db.get_value("Report", report_name, "ref_doctype")
			if ref_dt and not frappe.has_permission(ref_dt, "read"):
				return {"error": "no read permission on report's ref_doctype"}
			from frappe.desk.query_report import run

			data = run(report_name=report_name, filters=report_filters)
			# Trim huge results
			result = data.get("result") if isinstance(data, dict) else data
			if isinstance(result, list) and len(result) > 200:
				result = result[:200]
				truncated = True
			else:
				truncated = False
			return {
				"ok": True,
				"report": report_name,
				"columns": data.get("columns") if isinstance(data, dict) else None,
				"result": result,
				"truncated": truncated,
			}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_stock_balance":
		item_code = args.get("item_code")
		warehouse = args.get("warehouse")
		posting_date = args.get("posting_date")
		if not item_code:
			return {"error": "item_code required"}
		try:
			from erpnext.stock.utils import get_stock_balance

			bal = get_stock_balance(item_code, warehouse, posting_date) if warehouse else get_stock_balance(item_code, None, posting_date)
			return {
				"ok": True,
				"item_code": item_code,
				"warehouse": warehouse,
				"posting_date": posting_date,
				"balance": bal,
			}
		except ImportError:
			return {"error": "erpnext not installed"}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_account_balance":
		account = args.get("account")
		date = args.get("date")
		if not account or not frappe.db.exists("Account", account):
			return {"error": "invalid account"}
		if not frappe.has_permission("Account", "read", doc=account):
			return {"error": "no read permission on Account"}
		try:
			from erpnext.accounts.utils import get_balance_on

			bal = get_balance_on(account=account, date=date)
			return {"ok": True, "account": account, "date": date, "balance": bal}
		except ImportError:
			return {"error": "erpnext not installed"}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_outstanding":
		party_type = args.get("party_type")
		party = args.get("party")
		if party_type not in ("Customer", "Supplier"):
			return {"error": "party_type must be Customer or Supplier"}
		if not party or not frappe.db.exists(party_type, party):
			return {"error": f"invalid {party_type}"}
		if not frappe.has_permission(party_type, "read", doc=party):
			return {"error": f"no read permission on {party_type}"}
		invoice_dt = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"
		party_field = "customer" if party_type == "Customer" else "supplier"
		try:
			rows = frappe.get_all(
				invoice_dt,
				filters={party_field: party, "docstatus": 1, "outstanding_amount": [">", 0]},
				fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "status"],
				order_by="due_date asc",
				limit_page_length=100,
			)
			total = sum((r.get("outstanding_amount") or 0) for r in rows)
			return {
				"ok": True,
				"party_type": party_type,
				"party": party,
				"total_outstanding": total,
				"invoice_count": len(rows),
				"invoices": rows,
			}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_open_invoices":
		party_type = args.get("party_type")
		party = args.get("party")
		invoice_dt = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice" if party_type == "Supplier" else None
		if not invoice_dt:
			return {"error": "party_type must be Customer or Supplier"}
		if not frappe.has_permission(invoice_dt, "read"):
			return {"error": f"no read permission on {invoice_dt}"}
		filters = {"docstatus": 1, "outstanding_amount": [">", 0]}
		if party:
			party_field = "customer" if party_type == "Customer" else "supplier"
			filters[party_field] = party
		try:
			rows = frappe.get_all(
				invoice_dt,
				filters=filters,
				fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "status"],
				order_by="due_date asc",
				limit_page_length=int(args.get("limit") or 50),
			)
			return {"ok": True, "doctype": invoice_dt, "count": len(rows), "invoices": rows}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_sales_summary":
		group_by = args.get("group_by") or "customer"
		from_date = args.get("from_date")
		to_date = args.get("to_date")
		customer = args.get("customer")
		if not frappe.has_permission("Sales Invoice", "read"):
			return {"error": "no read permission on Sales Invoice"}
		filters = {"docstatus": 1}
		if from_date:
			filters["posting_date"] = [">=", from_date]
		if to_date:
			filters.setdefault("posting_date", [">=", "1900-01-01"])
			filters["posting_date"] = ["between", [filters["posting_date"][1] if isinstance(filters["posting_date"], list) and filters["posting_date"][0] == ">=" else from_date or "1900-01-01", to_date]]
		if customer:
			filters["customer"] = customer
		# Whitelist group_by to known fields on Sales Invoice
		allowed_group_by = {"customer", "owner", "company", "currency", "status", "posting_date"}
		if group_by not in allowed_group_by:
			return {"error": f"group_by must be one of {sorted(allowed_group_by)}"}
		try:
			rows = frappe.get_all(
				"Sales Invoice",
				filters=filters,
				fields=[group_by, "sum(grand_total) as total", "count(name) as invoices"],
				group_by=group_by,
				order_by="total desc",
				limit_page_length=int(args.get("limit") or 50),
			)
			return {"ok": True, "group_by": group_by, "rows": rows}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_item_price":
		item_code = args.get("item_code")
		price_list = args.get("price_list")
		if not item_code:
			return {"error": "item_code required"}
		filters = {"item_code": item_code}
		if price_list:
			filters["price_list"] = price_list
		try:
			rows = frappe.get_all(
				"Item Price",
				filters=filters,
				fields=["price_list", "price_list_rate", "currency", "valid_from", "valid_upto", "uom"],
				order_by="valid_from desc",
				limit_page_length=20,
			)
			return {"ok": True, "item_code": item_code, "count": len(rows), "prices": rows}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_company_defaults":
		try:
			defaults = dict(frappe.defaults.get_defaults() or {})
			# Strip private fields
			for k in list(defaults.keys()):
				if k.startswith("_") or "password" in k.lower():
					defaults.pop(k)
			company = defaults.get("company") or defaults.get("Company")
			company_info = None
			if company and frappe.db.exists("Company", company):
				company_info = frappe.db.get_value(
					"Company",
					company,
					["name", "default_currency", "country", "default_letter_head"],
					as_dict=True,
				)
			return {
				"ok": True,
				"defaults": defaults,
				"company": company_info,
				"current_user": frappe.session.user,
				"user_roles": frappe.get_roles(),
			}
		except Exception as e:
			return {"error": str(e)}

	if name == "prepare_send_email":
		# Gated to prevent accidental mass-mail. Reads Lazychat Settings doctype first,
		# then site_config (advanced override).
		from lazychat_mcp_erpnext.desk_assistant.boot import get_lazychat_settings as _gls

		if not _gls().get("allow_email"):
			return {
				"error": (
					"Email sending disabled. Enable in Desk → Lazychat Settings → "
					"'Allow prepare_send_email Tool', or set "
					"'lazychat_allow_email': true in site_config.json."
				),
			}
		recipients = args.get("recipients") or []
		if isinstance(recipients, str):
			recipients = [r.strip() for r in recipients.split(",") if r.strip()]
		subject = args.get("subject") or ""
		content = args.get("content") or ""
		ref_dt = args.get("doctype")
		ref_name = args.get("name")
		if not recipients or not subject:
			return {"error": "recipients and subject required"}
		if ref_dt and ref_name and not frappe.has_permission(ref_dt, "read", doc=ref_name):
			return {"error": "no read permission on referenced doc"}
		token = _stage_action(
			"send_email",
			{
				"recipients": recipients,
				"subject": subject,
				"content": content,
				"doctype": ref_dt,
				"name": ref_name,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will email {len(recipients)} recipient(s): '{subject}'",
			"preview": {
				"recipients": recipients,
				"subject": subject,
				"content": content[:500],
				"linked": f"{ref_dt}/{ref_name}" if ref_dt and ref_name else None,
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "prepare_delete_doc":
		dt = args.get("doctype")
		dn = args.get("name")
		if not dt or not dn:
			return {"error": "doctype and name required"}
		if not frappe.has_permission(dt, "delete", doc=dn):
			return {"error": "no delete permission"}
		if not frappe.db.exists(dt, dn):
			return {"error": f"{dt}/{dn} does not exist"}
		token = _stage_action("delete", {"doctype": dt, "name": dn})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will delete {dt}/{dn} (irreversible)",
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "search_doctype":
		query = (args.get("query") or "").strip()
		limit = min(int(args.get("limit") or 20), 50)
		if not query:
			return {"error": "query required"}
		try:
			rows = frappe.get_all(
				"DocType",
				filters={"name": ["like", f"%{query}%"], "istable": 0},
				fields=["name", "module", "is_submittable", "issingle"],
				order_by="name",
				limit_page_length=limit,
			)
			out = [r for r in rows if frappe.has_permission(r["name"], "read")]
			return {"ok": True, "query": query, "count": len(out), "doctypes": out}
		except Exception as e:
			return {"error": str(e)}

	if name == "search_link":
		dt = args.get("doctype")
		txt = args.get("query") or ""
		limit = min(int(args.get("limit") or 10), 50)
		if not dt or not frappe.db.exists("DocType", dt):
			return {"error": "invalid doctype"}
		if not frappe.has_permission(dt, "read"):
			return {"error": "no read permission"}
		try:
			from frappe.desk.search import search_link as _search_link

			# search_link writes its result to frappe.response["results"]
			frappe.response.pop("results", None)
			_search_link(doctype=dt, txt=txt, page_length=limit)
			results = frappe.response.get("results") or []
			return {"ok": True, "doctype": dt, "query": txt, "count": len(results), "results": results}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_pending_approvals":
		target_user = args.get("user") or frappe.session.user
		if target_user != frappe.session.user and "System Manager" not in frappe.get_roles():
			return {"error": "can only view your own pending approvals (or be System Manager)"}
		try:
			rows = frappe.get_all(
				"Workflow Action",
				filters={"user": target_user, "status": "Open"},
				fields=["name", "reference_doctype", "reference_name", "workflow_state", "creation"],
				order_by="creation desc",
				limit_page_length=int(args.get("limit") or 50),
			)
			# Enrich each with doc title (if accessible)
			out = []
			for r in rows:
				if not frappe.has_permission(r["reference_doctype"], "read", doc=r["reference_name"]):
					continue
				title = frappe.db.get_value(r["reference_doctype"], r["reference_name"], "title") or r["reference_name"]
				out.append({
					"workflow_action": r["name"],
					"doctype": r["reference_doctype"],
					"name": r["reference_name"],
					"title": title,
					"workflow_state": r["workflow_state"],
					"created": r["creation"],
				})
			return {"ok": True, "user": target_user, "count": len(out), "pending": out}
		except Exception as e:
			return {"error": str(e)}

	if name == "report_requirements":
		report_name = args.get("name")
		if not report_name or not frappe.db.exists("Report", report_name):
			return {"error": "invalid report name"}
		try:
			rep = frappe.get_doc("Report", report_name)
			if rep.ref_doctype and not frappe.has_permission(rep.ref_doctype, "read"):
				return {"error": "no read permission on report's ref_doctype"}
			info = {
				"name": rep.name,
				"report_type": rep.report_type,
				"ref_doctype": rep.ref_doctype,
				"is_standard": rep.is_standard,
			}
			# Filters live in `json` for Report Builder; in `script_filters` or JS for Script Reports.
			if rep.report_type == "Report Builder":
				try:
					rb = json.loads(rep.json or "{}")
					info["filters"] = rb.get("filters") or []
					info["columns"] = rb.get("columns") or []
				except Exception:
					info["filters"] = []
			elif rep.report_type == "Script Report":
				info["filters_hint"] = "Script Report — filter definitions live in the .js file alongside the report; pass filters as a JSON object when calling run_report"
			elif rep.report_type == "Query Report":
				info["query_excerpt"] = (rep.query or "")[:500]
				info["filters_hint"] = "Query Report — supply filters as %(name)s parameters used in the SQL"
			return {"ok": True, "info": info}
		except Exception as e:
			return {"error": str(e)}

	if name == "list_user_dashboards":
		try:
			user = frappe.session.user
			# owned + shared dashboards
			owned = frappe.get_all(
				"Dashboard",
				filters={"owner": user},
				fields=["name", "dashboard_name", "is_default", "owner", "modified"],
				limit_page_length=50,
			)
			shared = frappe.get_all(
				"DocShare",
				filters={"share_doctype": "Dashboard", "user": user},
				fields=["share_name as name"],
				limit_page_length=50,
			)
			shared_names = [s["name"] for s in shared if s.get("name")]
			extra = []
			if shared_names:
				extra = frappe.get_all(
					"Dashboard",
					filters={"name": ["in", shared_names]},
					fields=["name", "dashboard_name", "is_default", "owner", "modified"],
					limit_page_length=50,
				)
			# dedupe by name
			by_name = {d["name"]: d for d in owned}
			for d in extra:
				by_name.setdefault(d["name"], d)
			# also list public dashboards (no DocShare needed) — best-effort
			try:
				public = frappe.get_all(
					"Dashboard",
					filters={"is_default": 1},
					fields=["name", "dashboard_name", "is_default", "owner", "modified"],
					limit_page_length=20,
				)
				for d in public:
					by_name.setdefault(d["name"], d)
			except Exception:
				pass
			return {"ok": True, "count": len(by_name), "dashboards": list(by_name.values())}
		except Exception as e:
			return {"error": str(e)}

	if name == "extract_file_content":
		ref = (args.get("file") or args.get("name") or "").strip()
		max_chars = min(int(args.get("max_chars") or 20000), 100000)
		if not ref:
			return {"error": "file (File doctype name or file_url) required"}
		try:
			# Resolve File doc by name OR by file_url
			file_doc = None
			if frappe.db.exists("File", ref):
				file_doc = frappe.get_doc("File", ref)
			else:
				# try by file_url
				match = frappe.get_all("File", filters={"file_url": ref}, limit=1, fields=["name"])
				if match:
					file_doc = frappe.get_doc("File", match[0].name)
			if not file_doc:
				return {"error": f"File not found: {ref}"}
			# Permission: if attached to a doc, check perm on that doc
			if file_doc.attached_to_doctype and file_doc.attached_to_name:
				if not frappe.has_permission(file_doc.attached_to_doctype, "read", doc=file_doc.attached_to_name):
					return {"error": "no read permission on attached doc"}
			try:
				content_bytes = file_doc.get_content()
			except FileNotFoundError:
				return {
					"error": "file record exists but underlying file is missing on disk",
					"name": file_doc.name,
					"file_url": file_doc.file_url,
				}
			if isinstance(content_bytes, bytes):
				try:
					text = content_bytes.decode("utf-8")
				except UnicodeDecodeError:
					return {
						"ok": False,
						"error": "binary file — text extraction not supported (only UTF-8 text files)",
						"file_name": file_doc.file_name,
						"file_size": file_doc.file_size,
						"file_type": file_doc.file_type,
					}
			else:
				text = str(content_bytes)
			truncated = len(text) > max_chars
			return {
				"ok": True,
				"name": file_doc.name,
				"file_name": file_doc.file_name,
				"file_url": file_doc.file_url,
				"file_size": file_doc.file_size,
				"truncated": truncated,
				"content": text[:max_chars],
			}
		except Exception as e:
			return {"error": str(e)}

	if name == "prepare_run_sql":
		ok, err = _dangerous_tools_enabled()
		if not ok:
			return {"error": err}
		query = (args.get("query") or "").strip()
		validation_error = _validate_select_sql(query)
		if validation_error:
			return {"error": validation_error}
		limit = min(int(args.get("limit") or 200), 1000)
		token = _stage_action("run_sql", {"query": query, "limit": limit})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will execute SELECT query (returns up to {limit} rows)",
			"preview": {"query": query[:2000], "limit": limit, "warning": "Raw SQL bypasses Frappe per-user permissions — review the query carefully before /commit."},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "prepare_run_python":
		ok, err = _dangerous_tools_enabled()
		if not ok:
			return {"error": err}
		code = args.get("code") or ""
		if not code.strip():
			return {"error": "code required"}
		timeout = min(int(args.get("timeout") or 30), 120)
		token = _stage_action("run_python", {"code": code, "timeout": timeout})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will execute Python code (timeout {timeout}s) with full Frappe access",
			"preview": {"code": code[:4000], "timeout": timeout, "warning": "This code runs with FULL access to your Frappe data and the server filesystem (as the calling user). Review carefully before /commit."},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "prepare_share_doc":
		dt = args.get("doctype")
		dn = args.get("name")
		share_user = args.get("user")
		read = bool(args.get("read", True))
		write = bool(args.get("write", False))
		if not dt or not dn or not share_user:
			return {"error": "doctype, name, user required"}
		if not frappe.has_permission(dt, "share", doc=dn):
			return {"error": "no share permission on this doc (need 'Share' perm)"}
		if not frappe.db.exists("User", share_user):
			return {"error": f"user not found: {share_user}"}
		token = _stage_action(
			"share_doc",
			{"doctype": dt, "name": dn, "user": share_user, "read": read, "write": write},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will share {dt}/{dn} with {share_user} (read={read}, write={write})",
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "number_card_value":
		card_name = args.get("name")
		if not card_name or not frappe.db.exists("Number Card", card_name):
			return {"error": "invalid Number Card name"}
		if not frappe.has_permission("Number Card", "read", doc=card_name):
			return {"error": "no read permission on Number Card"}
		try:
			card = frappe.get_doc("Number Card", card_name)
			ctype = (card.get("type") or "Document Type") if hasattr(card, "get") else "Document Type"
			if ctype != "Document Type" or not card.get("document_type"):
				return {
					"error": f"Number Card type '{ctype}' is not supported (only 'Document Type' cards have a server-side value endpoint)",
					"card_type": ctype,
				}
			from frappe.desk.doctype.number_card.number_card import get_result

			card_filters = []
			fj = card.get("filters_json")
			if fj:
				try:
					card_filters = json.loads(fj)
				except Exception:
					card_filters = []
			value = get_result(card.as_dict(), card_filters)
			return {"ok": True, "name": card_name, "value": value, "label": card.label}
		except Exception as e:
			return {"error": str(e)}

	# Admin tools — rename, version history, version revert. Cover Frappe admin
	# capabilities (rename tool, document versioning) that the generic
	# prepare_create_doc / prepare_update_doc don't reach. Permission re-checked
	# at commit time so a stale preview_token can't bypass a perm change.
	if name == "prepare_rename_doc":
		dt = args.get("doctype")
		old_name = (args.get("name") or args.get("old_name") or "").strip()
		new_name = (args.get("new_name") or "").strip()
		merge = bool(args.get("merge", False))
		if not dt or not old_name or not new_name:
			return {"error": "doctype, name (or old_name), and new_name required"}
		if old_name == new_name:
			return {"error": "new_name must differ from current name"}
		if not frappe.has_permission(dt, "write", doc=old_name):
			return {"error": "no write permission on this doc (need 'Write')"}
		if not frappe.db.exists(dt, old_name):
			return {"error": f"doc not found: {dt}/{old_name}"}
		if frappe.db.exists(dt, new_name) and not merge:
			return {"error": f"new_name already exists: {dt}/{new_name}. Set merge=true to merge instead."}
		token = _stage_action(
			"rename_doc",
			{"doctype": dt, "old_name": old_name, "new_name": new_name, "merge": merge},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will rename {dt}/{old_name} -> {new_name}" + (" (merge)" if merge else ""),
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	if name == "list_doc_versions":
		dt = args.get("doctype")
		dn = args.get("name")
		limit = min(int(args.get("limit") or 20), 50)
		if not dt or not dn:
			return {"error": "doctype and name required"}
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission"}
		rows = frappe.get_all(
			"Version",
			filters={"ref_doctype": dt, "docname": dn},
			fields=["name", "owner", "creation", "data"],
			order_by="creation desc",
			limit_page_length=limit,
		)
		versions = []
		for r in rows:
			try:
				data = json.loads(r["data"]) if isinstance(r["data"], str) else (r["data"] or {})
			except Exception:
				data = {}
			scalar_changes = data.get("changed") or []
			# scalar_changes is [[field, old, new], ...]; child-table changes
			# live under data["row_changed"] / "added" / "removed" — surface
			# their counts so the user knows the version isn't pure-revertible.
			versions.append(
				{
					"version_id": r["name"],
					"owner": r["owner"],
					"creation": str(r["creation"]),
					"field_changes": [
						{"field": ch[0], "old": ch[1], "new": ch[2]}
						for ch in scalar_changes
						if isinstance(ch, (list, tuple)) and len(ch) >= 3
					],
					"row_added_count": len(data.get("added", [])) if isinstance(data.get("added"), list) else 0,
					"row_removed_count": len(data.get("removed", [])) if isinstance(data.get("removed"), list) else 0,
					"row_changed_count": len(data.get("row_changed", [])) if isinstance(data.get("row_changed"), list) else 0,
				}
			)
		return {"ok": True, "doctype": dt, "name": dn, "count": len(versions), "versions": versions}

	if name == "prepare_revert_doc":
		dt = args.get("doctype")
		dn = args.get("name")
		version_id = (args.get("version_id") or "").strip()
		if not dt or not dn or not version_id:
			return {"error": "doctype, name, version_id required"}
		if not frappe.has_permission(dt, "write", doc=dn):
			return {"error": "no write permission"}
		if not frappe.db.exists("Version", version_id):
			return {"error": f"version not found: {version_id}"}
		version = frappe.get_doc("Version", version_id)
		if version.ref_doctype != dt or version.docname != dn:
			return {"error": "version does not belong to this doc"}
		try:
			data = json.loads(version.data) if isinstance(version.data, str) else (version.data or {})
		except Exception:
			data = {}
		scalar_changes = data.get("changed") or []
		valid_changes = [ch for ch in scalar_changes if isinstance(ch, (list, tuple)) and len(ch) >= 3]
		if not valid_changes:
			return {
				"error": "this version has no scalar field changes to revert. Child-table or non-revertible changes are not handled by this tool — use prepare_update_doc to fix specific fields manually.",
			}
		# Stage the inverse: for each (field, old, new), set field back to old
		inverse_pairs = [[ch[0], ch[1]] for ch in valid_changes]
		token = _stage_action(
			"revert_doc",
			{"doctype": dt, "name": dn, "version_id": version_id, "inverse": inverse_pairs},
		)
		# Surface a human-readable diff so the user can confirm before /commit
		diff_preview = [
			{"field": ch[0], "current": ch[2], "will_revert_to": ch[1]}
			for ch in valid_changes
		]
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will revert {dt}/{dn} via Version {version_id}: {len(valid_changes)} scalar field change(s)",
			"diff": diff_preview,
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/commit {token}",
		}

	# Audit Trail — one-shot aggregator across the Frappe surfaces that record
	# "who changed/said what when" for a single doc. Read-only.
	# Sources: Version (field diffs), Comment (user remarks + workflow events
	# Frappe stamps as 'Workflow' comment_type), Activity Log (login/edit
	# events with reference_doctype/name set), and the doc's own creation/
	# modified metadata as a synthesised first event.
	if name == "get_audit_trail":
		dt = args.get("doctype")
		dn = args.get("name")
		limit = min(int(args.get("limit") or 100), 200)
		if not dt or not dn:
			return {"error": "doctype and name required"}
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission"}
		events = []
		# Doc creation / last-modified metadata
		try:
			meta = frappe.db.get_value(
				dt, dn, ["owner", "creation", "modified", "modified_by"], as_dict=True
			) or {}
			if meta.get("creation"):
				events.append({
					"kind": "created",
					"ts": str(meta["creation"]),
					"user": meta.get("owner"),
					"summary": f"Document created by {meta.get('owner')}",
				})
		except Exception:
			meta = {}
		# Version doctype rows (scalar field changes)
		try:
			vrows = frappe.get_all(
				"Version",
				filters={"ref_doctype": dt, "docname": dn},
				fields=["name", "owner", "creation", "data"],
				order_by="creation desc",
				limit_page_length=limit,
			)
			for v in vrows:
				try:
					d = json.loads(v["data"]) if isinstance(v["data"], str) else (v["data"] or {})
				except Exception:
					d = {}
				changed = d.get("changed") or []
				row_changed = d.get("row_changed") or []
				added = d.get("added") or []
				removed = d.get("removed") or []
				parts = []
				if changed:
					parts.append(f"{len(changed)} field change(s)")
				if row_changed or added or removed:
					parts.append(f"{len(row_changed)+len(added)+len(removed)} child-row change(s)")
				summary = ", ".join(parts) or "(empty version)"
				events.append({
					"kind": "modified",
					"ts": str(v["creation"]),
					"user": v["owner"],
					"summary": summary,
					"version_id": v["name"],
					"changed_fields": [ch[0] for ch in changed if isinstance(ch, (list, tuple)) and len(ch) >= 1],
				})
		except Exception:
			pass
		# Comment doctype rows (user remarks, workflow notes, attachments)
		try:
			crows = frappe.get_all(
				"Comment",
				filters={"reference_doctype": dt, "reference_name": dn},
				fields=["name", "owner", "creation", "comment_type", "content", "subject"],
				order_by="creation desc",
				limit_page_length=limit,
			)
			for c in crows:
				txt = (c.get("content") or c.get("subject") or "").strip()
				# Strip simple HTML so the snippet is readable
				txt = re.sub(r"<[^>]+>", " ", txt)
				txt = re.sub(r"\s+", " ", txt)[:200]
				kind_map = {
					"Comment": "comment",
					"Workflow": "workflow_event",
					"Like": "like",
					"Attachment": "attachment",
					"Attachment Removed": "attachment_removed",
					"Assigned": "assigned",
					"Assignment Completed": "assignment_completed",
					"Edit": "edit",
				}
				events.append({
					"kind": kind_map.get(c.get("comment_type"), "comment"),
					"ts": str(c["creation"]),
					"user": c["owner"],
					"summary": txt,
					"comment_id": c["name"],
				})
		except Exception:
			pass
		# Activity Log rows (login + Desk activity tied to this doc)
		try:
			arows = frappe.get_all(
				"Activity Log",
				filters={"reference_doctype": dt, "reference_name": dn},
				fields=["name", "owner", "creation", "subject", "operation"],
				order_by="creation desc",
				limit_page_length=limit,
			)
			for a in arows:
				events.append({
					"kind": "activity",
					"ts": str(a["creation"]),
					"user": a["owner"],
					"summary": (a.get("subject") or a.get("operation") or "")[:200],
					"activity_id": a["name"],
				})
		except Exception:
			pass
		# Sort newest-first then cap
		events.sort(key=lambda e: e["ts"], reverse=True)
		return {
			"ok": True,
			"doctype": dt,
			"name": dn,
			"created_by": meta.get("owner"),
			"created_at": str(meta.get("creation")) if meta.get("creation") else None,
			"last_modified_at": str(meta.get("modified")) if meta.get("modified") else None,
			"last_modified_by": meta.get("modified_by"),
			"event_count": len(events),
			"events": events[:limit],
		}

	# Export — generates an actual downloadable file, returns a clickable URL.
	# Generic get_list/get_doc tools can't produce files — only this can.
	if name == "export_list_to_csv":
		dt = args.get("doctype")
		if not dt or not frappe.db.exists("DocType", dt):
			return {"error": "invalid doctype"}
		if not frappe.has_permission(dt, "read"):
			return {"error": "no read permission"}
		filters = args.get("filters") or {}
		if isinstance(filters, str):
			try: filters = json.loads(filters)
			except Exception: return {"error": "filters must be a JSON object"}
		fields = args.get("fields") or ["name"]
		if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
			return {"error": "fields must be a list of strings"}
		limit = min(int(args.get("limit") or 1000), 5000)
		try:
			import csv as _csv
			rows = frappe.get_list(dt, filters=filters, fields=fields, limit_page_length=limit)
			buf = io.StringIO()
			writer = _csv.DictWriter(buf, fieldnames=fields)
			writer.writeheader()
			for r in rows:
				# Coerce non-stringable values
				writer.writerow({f: ("" if r.get(f) is None else str(r.get(f))) for f in fields})
			csv_bytes = buf.getvalue().encode("utf-8")
			ts = frappe.utils.now_datetime().strftime("%Y-%m-%d-%H%M%S")
			fname = f"{frappe.scrub(dt)}-{ts}.csv"
			file_doc = frappe.get_doc({
				"doctype": "File",
				"file_name": fname,
				"is_private": 1,
				"content": csv_bytes,
			}).insert(ignore_permissions=False)
			return {
				"ok": True,
				"file_url": file_doc.file_url,
				"absolute_url": _frappe_get_url(file_doc.file_url),
				"file_name": fname,
				"row_count": len(rows),
				"truncated": len(rows) >= limit,
			}
		except Exception as e:
			return {"error": str(e)}

	if name == "export_doc_pdf":
		dt = args.get("doctype")
		dn = args.get("name")
		print_format = args.get("print_format") or None
		if not dt or not dn:
			return {"error": "doctype and name required"}
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission"}
		try:
			from frappe.utils.pdf import get_pdf
			html = frappe.get_print(dt, dn, print_format=print_format)
			pdf_bytes = get_pdf(html)
			ts = frappe.utils.now_datetime().strftime("%Y-%m-%d-%H%M%S")
			fname = f"{frappe.scrub(dt)}-{frappe.scrub(dn)}-{ts}.pdf"
			file_doc = frappe.get_doc({
				"doctype": "File",
				"file_name": fname,
				"is_private": 1,
				"content": pdf_bytes,
				"attached_to_doctype": dt,
				"attached_to_name": dn,
			}).insert(ignore_permissions=False)
			return {
				"ok": True,
				"file_url": file_doc.file_url,
				"absolute_url": _frappe_get_url(file_doc.file_url),
				"file_name": fname,
				"print_format_used": print_format or "(default)",
				"size_bytes": len(pdf_bytes),
			}
		except Exception as e:
			return {"error": f"PDF render failed: {e}"}

	# RQ Job tools — early Tier D pieces. Read + cancel; full enqueue/schedule
	# arrives with the rest of Tier D.
	if name == "list_my_jobs":
		limit = min(int(args.get("limit") or 20), 100)
		try:
			# RQ Job is a Frappe-shipped doctype; it stores who queued and when.
			rows = frappe.get_all(
				"RQ Job",
				filters={"user": frappe.session.user},
				fields=["name", "status", "queue", "job_name", "creation", "started_at", "ended_at", "exc_info"],
				order_by="creation desc",
				limit_page_length=limit,
			)
			for r in rows:
				if r.get("exc_info"):
					r["exc_info"] = str(r["exc_info"])[:400]
			return {"ok": True, "count": len(rows), "jobs": rows}
		except Exception as e:
			return {"error": f"RQ Job query failed: {e}"}

	if name == "cancel_job":
		job_id = (args.get("job_id") or "").strip()
		if not job_id:
			return {"error": "job_id required"}
		if not frappe.has_permission("RQ Job", "write", doc=job_id):
			return {"error": "no permission to cancel this job"}
		try:
			job = frappe.get_doc("RQ Job", job_id)
			# RQ Job exposes a stop method on Frappe v15+; fall back to status flip
			# for older versions.
			if hasattr(job, "stop_job"):
				job.stop_job()
			elif hasattr(job, "cancel"):
				job.cancel()
			else:
				return {"error": "this Frappe build doesn't expose RQ Job cancel — use the bench worker controls"}
			return {"ok": True, "job_id": job_id, "status": getattr(job, "status", "cancelled")}
		except Exception as e:
			return {"error": f"cancel failed: {e}"}

	# Diagnostics — what's running here? Read-only, no gates.
	if name == "get_system_info":
		info = {
			"site": getattr(frappe.local, "site", None),
			"frappe_version": getattr(frappe, "__version__", None),
			"installed_apps": [],
		}
		try:
			for app in frappe.get_installed_apps():
				ver = None
				try:
					ver = frappe.get_attr(f"{app}.__version__")
				except Exception:
					ver = None
				info["installed_apps"].append({"app": app, "version": ver})
		except Exception as e:
			info["installed_apps_error"] = str(e)
		try:
			ss = frappe.get_single("System Settings")
			info["country"] = ss.country
			info["time_zone"] = ss.time_zone
			info["language"] = ss.language
			info["date_format"] = ss.date_format
			info["currency"] = ss.currency
		except Exception:
			pass
		try:
			info["python_version"] = __import__("sys").version.split()[0]
		except Exception:
			pass
		return {"ok": True, "info": info}

	if name == "get_user_info":
		user = frappe.session.user
		try:
			full_name, language, time_zone, enabled = frappe.db.get_value(
				"User", user, ["full_name", "language", "time_zone", "enabled"]
			) or (None, None, None, None)
		except Exception:
			full_name, language, time_zone, enabled = None, None, None, None
		return {
			"ok": True,
			"user": user,
			"full_name": full_name,
			"language": language,
			"time_zone": time_zone,
			"enabled": bool(enabled) if enabled is not None else None,
			"roles": frappe.get_roles(user),
		}

	# Knowledge Base (Tier H) — query attached files in a Lazychat Knowledge Base
	# doctype row. MVP: keyword paragraph search across all visible KBs (or one
	# named KB). Multi-format extraction via _extract_file_text covers
	# txt/md/csv/json/yaml (UTF-8) + xlsx (openpyxl) + pdf (pdfplumber/pypdf) +
	# docx (python-docx). Embeddings/vector search deferred to slice 2.
	if name == "list_knowledge_bases":
		from lazychat_mcp_erpnext.desk_assistant import knowledge as _kb

		return {"ok": True, "knowledge_bases": _kb.list_kbs_for_user()}

	if name == "get_kb_files":
		from lazychat_mcp_erpnext.desk_assistant import knowledge as _kb

		kb_name = (args.get("kb_name") or "").strip()
		if not kb_name:
			return {"error": "kb_name required"}
		return _kb.get_kb_files(kb_name)

	if name == "search_kb":
		from lazychat_mcp_erpnext.desk_assistant import knowledge as _kb

		query = (args.get("query") or "").strip()
		if not query:
			return {"error": "query required"}
		kb_name = (args.get("kb_name") or "").strip() or None
		max_chunks = min(int(args.get("max_chunks") or 8), 20)
		return _kb.search(query, kb_name=kb_name, max_chunks=max_chunks)

	# Skills (Tier E) — runtime activation/deactivation of agent personas.
	# Implementation in desk_assistant/skills.py. The active set is stored in
	# Redis per user; mcp.handle reads it on every tools/list to filter the
	# tool universe, and claude_bridge._system_prompt reads it to compose the
	# active skill snippets onto the base prompt.
	if name in ("list_skills", "activate_skill", "deactivate_skill"):
		from lazychat_mcp_erpnext.desk_assistant import skills

		if name == "list_skills":
			return {"ok": True, "skills": skills.list_skills_for_user()}
		if name == "activate_skill":
			skill_name = args.get("skill_name")
			if not skill_name:
				return {"error": "skill_name required"}
			return skills.activate_skill(skill_name)
		if name == "deactivate_skill":
			skill_name = args.get("skill_name")
			if not skill_name:
				return {"error": "skill_name required"}
			return skills.deactivate_skill(skill_name)

	return {"error": f"unknown tool {name}"}


def commit_prepared(token):
	"""Execute a previously staged action. Called by /commit slash command, NOT by the LLM."""
	obj = _retrieve_action(token)
	if not obj:
		return {"ok": False, "error": "Token not found, expired, or not yours"}
	action = obj["action"]
	payload = obj["payload"]
	sp_name = "lazychat_commit"
	try:
		frappe.db.savepoint(sp_name)
		if action == "create":
			doc = frappe.get_doc({"doctype": payload["doctype"], **(payload["values"] or {})})
			if not frappe.has_permission(payload["doctype"], "create"):
				return {"ok": False, "error": "no create permission at commit time"}
			doc.insert()
		elif action == "update":
			if not frappe.has_permission(payload["doctype"], "write", doc=payload["name"]):
				return {"ok": False, "error": "no write permission at commit time"}
			doc = frappe.get_doc(payload["doctype"], payload["name"])
			for f, v in (payload["patch"] or {}).items():
				doc.set(f, v)
			doc.save()
		elif action == "submit":
			if not frappe.has_permission(payload["doctype"], "submit", doc=payload["name"]):
				return {"ok": False, "error": "no submit permission at commit time"}
			doc = frappe.get_doc(payload["doctype"], payload["name"])
			doc.submit()
		elif action == "workflow_action":
			if not frappe.has_permission(payload["doctype"], "write", doc=payload["name"]):
				return {"ok": False, "error": "no write permission at commit time"}
			from frappe.model.workflow import apply_workflow

			doc = frappe.get_doc(payload["doctype"], payload["name"])
			apply_workflow(doc, payload["action"])
		elif action == "add_comment":
			if not frappe.has_permission(payload["doctype"], "read", doc=payload["name"]):
				return {"ok": False, "error": "no read permission at commit time"}
			doc = frappe.get_doc(payload["doctype"], payload["name"])
			doc.add_comment("Comment", payload["text"])
		elif action == "assign_to":
			if not frappe.has_permission(payload["doctype"], "read", doc=payload["name"]):
				return {"ok": False, "error": "no read permission at commit time"}
			from frappe.desk.form.assign_to import add as assign_add

			assign_add(
				{
					"assign_to": [payload["user"]],
					"doctype": payload["doctype"],
					"name": payload["name"],
					"description": payload.get("description") or "",
				}
			)
			doc = frappe.get_doc(payload["doctype"], payload["name"])
		elif action == "send_email":
			from lazychat_mcp_erpnext.desk_assistant.boot import get_lazychat_settings as _gls

			if not _gls().get("allow_email"):
				return {"ok": False, "error": "Email disabled at commit time (Lazychat Settings → Allow Email is unchecked)"}
			frappe.sendmail(
				recipients=payload["recipients"],
				subject=payload["subject"],
				message=payload["content"],
				reference_doctype=payload.get("doctype"),
				reference_name=payload.get("name"),
				delayed=False,
			)
			# fabricate a "doc" so the return shape matches
			class _R:
				doctype = "Email"
				name = ", ".join(payload["recipients"][:3])
			doc = _R()
		elif action == "run_sql":
			# Re-check guard at commit time (site flag may have changed; user role may have changed)
			ok2, err2 = _dangerous_tools_enabled()
			if not ok2:
				return {"ok": False, "error": err2}
			query = payload["query"]
			validation_error = _validate_select_sql(query)
			if validation_error:
				return {"ok": False, "error": validation_error}
			limit = int(payload.get("limit") or 200)
			# Run; cap rows by re-querying with explicit limit
			rows = frappe.db.sql(query, as_dict=True)
			if isinstance(rows, list) and len(rows) > limit:
				rows = rows[:limit]
				truncated = True
			else:
				truncated = False
			_consume_action(token)
			return {
				"ok": True,
				"action": "run_sql",
				"row_count": len(rows) if isinstance(rows, list) else 0,
				"truncated": truncated,
				"rows": rows,
				"name": "(sql)",
				"doctype": "SQL",
				"link": None,
			}
		elif action == "run_python":
			ok2, err2 = _dangerous_tools_enabled()
			if not ok2:
				return {"ok": False, "error": err2}
			code = payload["code"]
			# timeout = payload.get("timeout") or 30  # SIGALRM-based timeout would need signal handling; keep simple
			# Try optional pandas/numpy imports — best effort
			ns = {"frappe": frappe, "json": json, "_result": None}
			try:
				import datetime as _dt
				ns["datetime"] = _dt
			except Exception:
				pass
			for libname in ("pandas", "numpy"):
				try:
					ns[libname] = __import__(libname)
				except Exception:
					pass
			# Capture stdout
			buf = io.StringIO()
			import contextlib
			try:
				with contextlib.redirect_stdout(buf):
					try:
						# Try as expression first (so "1+1" returns 2)
						value = eval(compile(code, "<lazychat>", "eval"), ns, ns)
						ns["_result"] = value
					except SyntaxError:
						# Fallback: execute as statements; user code can set _result
						exec(compile(code, "<lazychat>", "exec"), ns, ns)
			except Exception as e:
				return {
					"ok": False,
					"action": "run_python",
					"error": f"{type(e).__name__}: {e}",
					"stdout": buf.getvalue()[:8000],
				}
			result = ns.get("_result")
			# Coerce non-JSON-serializable to string
			try:
				json.dumps(result, default=str)
			except Exception:
				result = str(result)
			_consume_action(token)
			return {
				"ok": True,
				"action": "run_python",
				"result": result,
				"stdout": buf.getvalue()[:8000],
				"name": "(python)",
				"doctype": "Python",
				"link": None,
			}
		elif action == "delete":
			if not frappe.has_permission(payload["doctype"], "delete", doc=payload["name"]):
				return {"ok": False, "error": "no delete permission at commit time"}
			doctype = payload["doctype"]
			docname = payload["name"]
			try:
				frappe.delete_doc(doctype, docname)
			except frappe.LinkExistsError as e:
				return {"ok": False, "error": f"cannot delete — other docs link to it: {e}"}
			class _R:
				pass
			doc = _R()
			doc.doctype = doctype
			doc.name = docname
		elif action == "rename_doc":
			if not frappe.has_permission(payload["doctype"], "write", doc=payload["old_name"]):
				return {"ok": False, "error": "no write permission at commit time"}
			# frappe.rename_doc returns the resolved final name (Frappe may
			# normalise it). It also handles autoname constraints and merge mode.
			new_name = frappe.rename_doc(
				payload["doctype"],
				payload["old_name"],
				payload["new_name"],
				merge=bool(payload.get("merge", False)),
				ignore_permissions=False,
			)
			class _R:
				pass
			doc = _R()
			doc.doctype = payload["doctype"]
			doc.name = new_name
		elif action == "revert_doc":
			if not frappe.has_permission(payload["doctype"], "write", doc=payload["name"]):
				return {"ok": False, "error": "no write permission at commit time"}
			doc = frappe.get_doc(payload["doctype"], payload["name"])
			# Re-fetch the version and apply the inverse so a stale token can't
			# revert against a doc that's moved further. inverse is [[field, old], ...].
			for fieldname, old_value in payload.get("inverse", []):
				doc.set(fieldname, old_value)
			doc.save(ignore_permissions=False)
		elif action == "share_doc":
			if not frappe.has_permission(payload["doctype"], "share", doc=payload["name"]):
				return {"ok": False, "error": "no share permission at commit time"}
			from frappe.share import add as share_add

			share_add(
				doctype=payload["doctype"],
				name=payload["name"],
				user=payload["user"],
				read=1 if payload.get("read") else 0,
				write=1 if payload.get("write") else 0,
				notify=1,
			)
			doc = frappe.get_doc(payload["doctype"], payload["name"])
		else:
			return {"ok": False, "error": f"Unknown action: {action}"}
		frappe.db.commit()
		_consume_action(token)
		return {
			"ok": True,
			"action": action,
			"name": doc.name,
			"doctype": doc.doctype,
			"link": f"/app/{frappe.scrub(doc.doctype)}/{doc.name}",
		}
	except Exception as e:
		try:
			frappe.db.rollback(save_point=sp_name)
		except Exception:
			pass
		frappe.log_error(frappe.get_traceback(), f"lazychat commit_prepared {action}")
		return {"ok": False, "error": str(e), "action": action}
