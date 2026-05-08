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


def _strip_leading_sql_comments(sql):
	"""Strip leading -- line comments and /* */ block comments so an LLM can
	prefix a query with descriptive comments without tripping the
	SELECT/WITH-must-be-first regex. Only strips at the START of the trimmed
	string; comments AFTER the SELECT keyword are left alone (they're handled
	by MariaDB itself). Returns the de-commented string.
	"""
	s = (sql or "").strip()
	while s:
		if s.startswith("--"):
			nl = s.find("\n")
			if nl < 0:
				return ""  # comment-only
			s = s[nl + 1:].lstrip()
		elif s.startswith("/*"):
			end = s.find("*/")
			if end < 0:
				return s  # unterminated; let downstream validator surface a clear error
			s = s[end + 2:].lstrip()
		else:
			break
	return s


def _strip_sql_string_literals(sql):
	"""Replace SQL single-quoted string contents with empty literals so the
	DML/DDL keyword regex doesn't false-positive on words appearing inside
	string values.

	Example: `CONCAT('<a class="btn">Create DN</a>')` → `CONCAT('')` —
	the `Create` text inside the literal becomes invisible to the keyword
	scan, but the surrounding SQL structure is preserved (and the multi-
	statement / SELECT-prefix checks still see the right thing).

	Handles SQL's single-quote-doubling escape (`'It''s ok'` is one literal).
	Backtick-quoted identifiers (`tabCustomer`) and double-quoted identifiers
	in ANSI mode are NOT stripped — those legitimately can't contain DML
	keywords as values, and the LLM uses backticks for table names.
	"""
	out = []
	i = 0
	n = len(sql)
	while i < n:
		c = sql[i]
		if c == "'":
			# Skip until the matching unescaped closing quote
			out.append("''")  # preserve as empty literal so syntax stays valid
			i += 1
			while i < n:
				if sql[i] == "'":
					# Look for `''` escape
					if i + 1 < n and sql[i + 1] == "'":
						i += 2
						continue
					i += 1
					break
				i += 1
		else:
			out.append(c)
			i += 1
	return "".join(out)


def _validate_select_sql(sql):
	stripped = (sql or "").strip().rstrip(";")
	if not stripped:
		return "empty query"
	# Tolerate leading SQL comments — LLMs often prefix queries with
	# "-- get PRs linked to..." for self-narration. The previous strict
	# "must start with SELECT/WITH" check rejected these.
	uncommented = _strip_leading_sql_comments(stripped)
	if not uncommented:
		return "empty query"
	if ";" in uncommented:
		return "multi-statement queries not allowed"
	if not SQL_ALLOWED_PATTERN.match(uncommented):
		return "only SELECT (or WITH ... SELECT) queries allowed"
	# Apply DML/DDL regex to a version with string literals neutralized so
	# legitimate `CONCAT('<a>Create DN</a>')` rendering doesn't match the
	# keyword regex. Real DML at SQL-statement level (DROP TABLE, INSERT INTO,
	# etc.) is unaffected because keywords there are NOT inside literals.
	defanged = _strip_sql_string_literals(uncommented)
	if SQL_DML_PATTERN.search(defanged):
		return "DML/DDL keywords not allowed (INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/...)"
	# MariaDB rejects LIMIT inside IN/ANY/ALL/SOME subqueries with
	# NotSupportedError(1235). EXPLAIN does NOT catch it — the optimizer
	# parses fine, the restriction fires only at execution. Static regex
	# is the only reliable preview-time guard. Scan against `defanged` so
	# HTML link content like CONCAT('<a href="?limit=10">') doesn't false-
	# positive. `[^()]*` bounds the match to a single subquery (no nested
	# parens cross-match).
	if re.search(
		r"\b(IN|ANY|ALL|SOME)\s*\(\s*SELECT\b[^()]*\bLIMIT\b",
		defanged,
		re.IGNORECASE | re.DOTALL,
	):
		return (
			"MariaDB does not support LIMIT inside IN/ANY/ALL/SOME subqueries "
			"(NotSupportedError 1235). Rewrite using a JOIN on a derived table: "
			"`SELECT a.* FROM tabA a JOIN (SELECT name FROM tabB LIMIT N) b "
			"ON a.name = b.name`. Or remove the LIMIT and add WHERE filters that "
			"constrain the subquery instead."
		)
	return None  # OK


# Match MySQL/MariaDB error texts surfaced through pymysql.OperationalError /
# frappe wrappers. Both shapes appear in the wild — we look for the textual
# pattern and the numeric code (e.g. (1054, "...")).
_DB_ERR_UNKNOWN_COLUMN = re.compile(
	r"""(?:\(?1054[,)]?\s*)?["']?Unknown column ['"`]([^'"`]+)['"`] in ['"`]([^'"`]+)['"`]""",
	re.IGNORECASE,
)
_DB_ERR_TABLE_NOT_FOUND = re.compile(
	r"""(?:\(?1146[,)]?\s*)?["']?Table ['"`]?([^'"`)]+?)['"`]?\s+doesn't exist""",
	re.IGNORECASE,
)
_DB_ERR_SYNTAX = re.compile(
	r"""(?:\(?1064[,)]?\s*)?["']?You have an error in your SQL syntax""",
	re.IGNORECASE,
)
# ERPNext relationships that frequently live on the child table, not the
# parent — these are the column names the LLM most often hallucinates onto a
# parent doctype. When a 1054 error names one of these on a parent table, we
# emit a targeted hint pointing at the right child-table location.
_CHILD_TABLE_LINKS = {
	"purchase_order": "Purchase Receipt Item / Purchase Invoice Item",
	"purchase_receipt": "Purchase Invoice Item / Stock Ledger Entry",
	"sales_order": "Sales Invoice Item / Delivery Note Item",
	"sales_invoice": "Payment Entry Reference",
	"delivery_note": "Sales Invoice Item",
	"against_sales_order": "Delivery Note Item / Sales Invoice Item",
	"against_purchase_order": "Purchase Receipt Item",
}

# Common business-term aliases that AREN'T separate doctypes in ERPNext.
# When the LLM calls describe_doctype with one of these, return an
# actionable redirect so it routes to the real doctype with the correct
# `is_return=1` flag instead of bouncing off an "invalid doctype" error.
# Keys are Title-Cased; lookup normalizes incoming `doctype` arg.
_DOCTYPE_ALIASES = {
	"Debit Note": (
		"Purchase Invoice",
		"Debit Note is NOT a separate doctype in ERPNext. It's a Purchase "
		"Invoice with `is_return=1` (and typically `return_against=<original PI name>`). "
		"Use describe_doctype('Purchase Invoice') for the schema, and "
		"prepare_create_doc({doctype:'Purchase Invoice', values:{is_return:1, "
		"return_against:'<PI-name>', supplier:'...', items:[...]}}) to create one. "
		"For HTML link buttons in Query Reports, use "
		"`/app/purchase-invoice/new?is_return=1&return_against=<PI>`.",
	),
	"Credit Note": (
		"Sales Invoice",
		"Credit Note is NOT a separate doctype in ERPNext. It's a Sales "
		"Invoice with `is_return=1` (and `return_against=<original SI name>`). "
		"Use describe_doctype('Sales Invoice') and "
		"prepare_create_doc({doctype:'Sales Invoice', values:{is_return:1, "
		"return_against:'<SI-name>', customer:'...', items:[...]}}).",
	),
	"Purchase Return": (
		"Purchase Invoice",
		"Purchase Return is NOT a separate doctype. It's a Purchase Invoice "
		"with `is_return=1` (or a Purchase Receipt with `is_return=1` for "
		"stock-only returns). See Debit Note for the invoice path.",
	),
	"Sales Return": (
		"Sales Invoice",
		"Sales Return is NOT a separate doctype. It's a Sales Invoice with "
		"`is_return=1` (or a Delivery Note with `is_return=1` for stock-only). "
		"See Credit Note for the invoice path.",
	),
}


def _wrap_db_error(e, query, action):
	"""Build a structured, LLM-actionable error response for a DB exception
	thrown during run_sql / run_python execution.

	The opaque `OperationalError: (1054, "Unknown column 'pr.purchase_order'")`
	dead-ends the agent loop because the LLM has no idea WHICH column is
	missing or what it should have used instead. This wrapper extracts the
	column/table from the message and emits a hint pointing at the most
	likely correction (child-table link conventions, or generic
	describe_doctype guidance).

	Returns a dict matching the existing run_sql/run_python error shape so
	the caller can `return _wrap_db_error(...)` directly.
	"""
	msg = str(e)
	err_type = type(e).__name__
	resp = {
		"ok": False,
		"action": action,
		"error": f"{err_type}: {msg}",
		"error_kind": "other",
		"hint": None,
		"query": (query or "")[:1000],
	}

	m = _DB_ERR_UNKNOWN_COLUMN.search(msg)
	if m:
		col_ref, where_clause = m.group(1), m.group(2)
		# col_ref is typically "alias.column" or just "column"
		col_name = col_ref.rsplit(".", 1)[-1]
		resp["error_kind"] = "schema"
		child_hint = _CHILD_TABLE_LINKS.get(col_name)
		if child_hint:
			resp["hint"] = (
				f"Column `{col_ref}` does not exist (in `{where_clause}`). In ERPNext, "
				f"`{col_name}` typically lives on the CHILD table — try `{child_hint}` "
				f"instead. Example: SELECT ... FROM `tabPurchase Receipt` pr "
				f"JOIN `tabPurchase Receipt Item` pri ON pri.parent = pr.name "
				f"WHERE pri.{col_name} = ... — the child rows carry the cross-doc link, "
				f"not the parent. Run `describe_doctype` on the parent and inspect its "
				f"child-table fields ('table' fieldtype) before retrying."
			)
		else:
			resp["hint"] = (
				f"Column `{col_ref}` does not exist (in `{where_clause}`). Run "
				f"`describe_doctype` on the table to see the actual column names "
				f"before retrying."
			)
		return resp

	m = _DB_ERR_TABLE_NOT_FOUND.search(msg)
	if m:
		resp["error_kind"] = "schema"
		resp["hint"] = (
			f"Table `{m.group(1)}` does not exist. ERPNext doctype tables are "
			f"`tab<Doctype Name>` (with the space, no underscore). Run "
			f"`describe_doctype` to confirm the doctype exists, then retry "
			f"with the correct backtick-quoted table name."
		)
		return resp

	if _DB_ERR_SYNTAX.search(msg):
		resp["error_kind"] = "syntax"
		resp["hint"] = (
			"SQL syntax error. Re-read the query, fix the syntax, and retry. "
			"Common causes: missing backticks around table/column names that "
			"contain spaces, unbalanced parentheses, or DML/DDL keywords "
			"(only SELECT is allowed)."
		)
		return resp

	# MariaDB rejects LIMIT inside IN/ALL/ANY/SOME subqueries with
	# NotSupportedError(1235). EXPLAIN catches it (raises 1235 at parse
	# time), but only if the caller surfaces non-schema/non-syntax errors.
	# Flag as `syntax` so _probe_select_sql_explain re-raises it to the LLM.
	if "1235" in msg or (
		"LIMIT" in msg and ("IN/ALL/ANY/SOME" in msg or "subquery" in msg.lower())
	):
		resp["error_kind"] = "syntax"
		resp["hint"] = (
			"MariaDB does not support LIMIT inside IN/ANY/ALL/SOME subqueries "
			"(NotSupportedError 1235). Rewrite using a JOIN on a derived table: "
			"`SELECT a.* FROM tabA a JOIN (SELECT name FROM tabB LIMIT N) b "
			"ON a.name = b.name`. Or remove the LIMIT and add WHERE filters that "
			"constrain the subquery instead."
		)
		return resp

	# Permission errors etc. — pass through with no structured hint.
	if "1142" in msg or "denied" in msg.lower() or "no permission" in msg.lower():
		resp["error_kind"] = "permission"
		resp["hint"] = (
			"Permission denied at the database layer. This usually means the "
			"calling user lacks read access on the table. Try the higher-level "
			"`get_list` / `get_doc` tools which respect Frappe's per-user "
			"permission filters."
		)
	return resp


# Frappe Query Reports parameterize filters with `%(filter_name)s`. EXPLAIN
# can't bind these, so we substitute NULL before probing — EXPLAIN doesn't
# fetch rows, so the literal NULL is fine for plan validation.
_SQL_PLACEHOLDER_RE = re.compile(r"%\([^)]+\)s")


# DocTypes for which a typed wrapper exists. prepare_create_doc REFUSES
# for these and redirects the LLM to the wrapper, which validates the
# required fields up front. Without this redirect, the LLM ends up
# storing structurally-valid but semantically-broken rows (Report with
# no ref_doctype, Custom Field with no insert_after, Notification with
# no event, etc.) that explode at /commit or open time.
_TYPED_WRAPPER_FOR_DOCTYPE = {
	"Report": "prepare_create_report",
	"Custom Field": "prepare_create_custom_field",
	"Client Script": "prepare_create_client_script",
	# "Server Script" deliberately NOT in this map — it has no typed wrapper
	# (the script-body field is too freeform for schema-based validation),
	# and the generic prepare_create_doc path is gated by allow_dangerous_tools
	# + System Manager which is sufficient defense.
	"Scheduled Job Type": "prepare_create_scheduled_job",
	"Notification": "prepare_create_notification",
	"Print Format": "prepare_create_print_format",
	"Email Template": "prepare_create_email_template",
	"Email Group": "prepare_create_email_group",
	"Newsletter": "prepare_create_newsletter",
	"Email Account": "prepare_create_email_account",
	"Assignment Rule": "prepare_create_assignment_rule",
	"Auto Email Report": "prepare_create_auto_email_report",
	"Auto Repeat": "prepare_create_auto_repeat",
	"Milestone Tracker": "prepare_create_milestone_tracker",
	"Number Card": "prepare_create_number_card",
	"Dashboard": "prepare_create_dashboard",
	"Knowledge Base": "prepare_create_kb",
	"Note": "prepare_create_note",
	"Event": "prepare_create_calendar_event",
}


# Frappe Script Reports execute inside `safe_exec` (RestrictedPython +
# FrappeTransformer). All `import` statements are rejected at compile
# time; `frappe`, `_`, `json`, and a curated subset of frappe.* are
# pre-injected as globals. The LLM's instinct is `import frappe` —
# which fails with `ImportError: __import__ not found` BEFORE execute()
# runs. We catch this at preview so the LLM sees an actionable hint
# instead of shipping a broken Report row.
_SAFE_EXEC_FORBIDDEN_FRAPPE_DB = {
	"set_value", "set_many", "delete", "sql_ddl", "multisql",
	"commit", "rollback", "savepoint", "release_savepoint",
}
_SAFE_EXEC_FORBIDDEN_FRAPPE = {
	"sendmail", "publish_realtime", "publish_progress",
	"enqueue", "enqueue_doc", "delete_doc", "rename_doc", "copy_doc",
}
_SAFE_EXEC_FORBIDDEN_BUILTINS = {
	"__import__", "compile", "exec", "eval", "open", "input", "breakpoint",
}


def _validate_script_report_body(script):
	"""AST-validate a Script Report body against safe_exec rules.

	Returns None on success, an error string with hint on failure.
	Catches the most common LLM mistakes at preview time so the wrapper
	can surface actionable errors INSTEAD of shipping a Report whose
	body explodes the moment the user opens it.
	"""
	import ast as _ast
	try:
		tree = _ast.parse(script)
	except SyntaxError as e:
		return f"script has Python syntax error: {e.msg} (line {e.lineno})"
	for node in _ast.walk(tree):
		if isinstance(node, (_ast.Import, _ast.ImportFrom)):
			return (
				"Script Reports run in safe_exec — `import` statements are "
				"FORBIDDEN. `frappe`, `_`, `json` are pre-injected as globals. "
				"Remove `import frappe` / `from frappe import _` from the top "
				"of your script. Use `frappe.db.get_list(...)` or `frappe.qb` "
				"directly. PREFER report_type='Query Report' with HTML link "
				"columns when buttons are needed — Query Reports avoid this "
				"sandbox entirely."
			)
		if isinstance(node, _ast.Call):
			f = node.func
			if isinstance(f, _ast.Name) and f.id in _SAFE_EXEC_FORBIDDEN_BUILTINS:
				return (
					f"`{f.id}(...)` is not allowed in safe_exec. Remove it. "
					f"safe_exec strips dangerous builtins; only the curated "
					f"subset (abs, all, any, bool, dict, list, range, set, "
					f"sorted, sum, ...) is available."
				)
			chain = _attr_chain(f)
			if (
				len(chain) >= 3
				and chain[0] == "frappe"
				and chain[1] == "db"
				and chain[2] in _SAFE_EXEC_FORBIDDEN_FRAPPE_DB
			):
				return (
					f"`frappe.db.{chain[2]}(...)` is a write call — Script "
					f"Reports are read-only. Use `frappe.db.get_list/"
					f"get_value/get_all/count` or `frappe.qb` for queries."
				)
			if (
				len(chain) >= 2
				and chain[0] == "frappe"
				and chain[1] in _SAFE_EXEC_FORBIDDEN_FRAPPE
			):
				return (
					f"`frappe.{chain[1]}(...)` is a side-effect call — Script "
					f"Reports are read-only and must not enqueue jobs, send "
					f"emails, or mutate documents."
				)
	# Structural sanity — must define `execute` returning two-tuple
	if not any(
		isinstance(n, _ast.FunctionDef) and n.name == "execute"
		for n in _ast.walk(tree)
	):
		return (
			"script must define a top-level `def execute(filters=None):` "
			"returning (columns, data)"
		)
	return None


def _probe_select_sql_explain(query):
	"""EXPLAIN-probe a SELECT against the live DB so table-not-found /
	column-not-found / syntax errors surface at preview time instead of
	at report-open time. Returns None on success, an error string with
	hint on schema/syntax failure. Other DB errors (permission, deadlock)
	pass through to avoid fail-closing on transient issues.

	Companion to _validate_select_sql, which is regex-only and can't see
	whether `tabPurchase_Order` is a real table or LLM hallucination.
	"""
	try:
		stripped = _strip_leading_sql_comments((query or "").strip().rstrip(";"))
		if not stripped:
			return None
		explain_query = _SQL_PLACEHOLDER_RE.sub("NULL", stripped)
		frappe.db.sql("EXPLAIN " + explain_query)
		return None
	except Exception as e:
		wrapped = _wrap_db_error(e, query, "explain_probe")
		if wrapped.get("error_kind") in ("schema", "syntax"):
			err = wrapped.get("error") or str(e)
			hint = wrapped.get("hint")
			return f"{err}\nHint: {hint}" if hint else str(err)
		return None


def _attr_chain(node):
	"""For an AST Attribute node like `frappe.db.sql`, return ['frappe', 'db', 'sql'].
	Returns [] for non-Name/Attribute roots so callers can ignore complex receivers.
	"""
	import ast
	parts = []
	while isinstance(node, ast.Attribute):
		parts.append(node.attr)
		node = node.value
	if isinstance(node, ast.Name):
		parts.append(node.id)
		return list(reversed(parts))
	return []


# Modules that can produce side-effects outside the DB (file I/O, shell out,
# network, redis publish, queue-job spawn). The savepoint-rollback we wrap
# around the code execution can undo DB mutations but cannot un-send an
# email, un-spawn a subprocess, or un-publish a realtime event — those have
# to be blocked statically before the code runs.
_PY_RO_BLOCKED_IMPORTS = {
	"subprocess", "os", "sys", "shutil", "socket", "urllib", "requests",
	"http", "smtplib", "ftplib", "telnetlib", "ssl", "ctypes", "multiprocessing",
}
_PY_RO_BLOCKED_BUILTINS = {
	# Built-ins that could escape the readonly contract (file I/O, dynamic code
	# loading, prompt the operator). Listed by name; the validator looks for
	# Call(Name(id=name)) at the AST root.
	"open", "__import__", "compile", "input", "breakpoint",
	"exec", "eval",
}
# Exact frappe.X / frappe.db.X attribute chains that have side-effects the
# savepoint can't undo, or that cause damage we don't want auto-execute Python
# to be capable of.
_PY_RO_BLOCKED_FRAPPE = {
	"sendmail", "publish_realtime", "publish_progress", "enqueue", "enqueue_doc",
	"delete_doc", "rename_doc", "copy_doc",
}
_PY_RO_BLOCKED_FRAPPE_DB = {
	"sql_ddl", "multisql", "commit", "rollback", "savepoint", "release_savepoint",
	# set_value / delete are caught by the savepoint rollback, but blocking them
	# at AST time is clearer signal to the LLM that this tool is read-only.
	"set_value", "set_many", "delete",
}


def _validate_python_readonly(code):
	"""Static AST scan to reject Python code that would have side-effects we
	cannot roll back. Returns None on success, a human-readable error string
	on rejection.

	Defense-in-depth: even if this scan misses something, run_python_readonly
	wraps the code execution in a savepoint + always-rollback (see the tool
	dispatch). The scan blocks the obvious mutators so the LLM gets a clear
	"no" rather than seeing its mutation succeed and then silently rolled back.
	"""
	import ast
	if not (code or "").strip():
		return "empty code"
	try:
		tree = ast.parse(code, mode="exec")
	except SyntaxError as e:
		return f"syntax error: {e.msg}"

	for node in ast.walk(tree):
		# Block dangerous module imports
		if isinstance(node, ast.Import):
			for alias in node.names:
				root = alias.name.split(".")[0]
				if root in _PY_RO_BLOCKED_IMPORTS:
					return f"forbidden import: {alias.name} — run_python_readonly cannot use modules that produce non-DB side-effects"
		if isinstance(node, ast.ImportFrom):
			root = (node.module or "").split(".")[0]
			if root in _PY_RO_BLOCKED_IMPORTS:
				return f"forbidden import: from {node.module} — run_python_readonly cannot use modules that produce non-DB side-effects"

		# Block calls to dangerous built-ins (open / dynamic-code / prompt)
		if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
			if node.func.id in _PY_RO_BLOCKED_BUILTINS:
				return f"forbidden call: {node.func.id}() — run_python_readonly cannot perform file/shell I/O or dynamic code execution"

		# Block specific frappe.* / frappe.db.* attribute chains
		if isinstance(node, ast.Attribute):
			chain = _attr_chain(node)
			if chain and chain[0] == "frappe":
				if len(chain) >= 3 and chain[1] == "db" and chain[2] in _PY_RO_BLOCKED_FRAPPE_DB:
					return f"forbidden DB mutation: frappe.db.{chain[2]}() — run_python_readonly cannot mutate the database"
				if len(chain) >= 2 and chain[1] in _PY_RO_BLOCKED_FRAPPE:
					return f"forbidden side-effect: frappe.{chain[1]}() — run_python_readonly cannot send mail, publish events, enqueue jobs, or delete/rename docs"

	return None


def _validate_frappe_expression(expr):
	"""Validate a Frappe condition expression via Python AST (used by
	Notification + Assignment Rule). AST-only — catches ~95% of typo errors
	without invoking the Frappe runtime; the runtime itself will surface the
	rest at the first trigger. Returns None on success, an error string on
	failure.
	"""
	import ast
	expr = (expr or "").strip()
	if not expr:
		return None  # empty is fine — Frappe treats as 'always true'
	try:
		tree = ast.parse(expr, mode="eval")
	except SyntaxError as e:
		return f"condition syntax error: {e.msg}"
	forbidden = (ast.Import, ast.ImportFrom, ast.Lambda, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)
	for node in ast.walk(tree):
		if isinstance(node, forbidden):
			return "condition cannot contain imports / lambdas / function definitions"
		if isinstance(node, ast.Attribute) and isinstance(node.attr, str) and node.attr.startswith("_"):
			return f"condition cannot access dunder/private attributes ({node.attr!r})"
	return None


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


def _coerce_args(args):
	"""Normalize stringified JSON values to their native types.

	Models that aren't fully tool-trained (seed-oss-36b, smaller open-weight
	models, some OpenAI-compatible gateways) routinely emit `tool_calls.
	function.arguments` with EVERYTHING stringified — `filters: "{}"`,
	`fields: "['name', 'foo']"`, `limit: "1"`, etc. — even when the schema
	declares them as objects/arrays/integers. The system prompt explicitly
	asks them not to (see lazychat.ai/.../routerSystemPrompt.ts) but
	enforcement on the model side is unreliable.

	Rather than make every tool's impl handle every stringified-vs-native
	combination, normalize at the dispatch boundary. Common-shape keys are
	probed: if the value is a string that looks like JSON, json.loads it;
	if int-coercible, int it. Unknown keys pass through untouched.

	Idempotent — already-typed values pass through.
	"""
	if not isinstance(args, dict):
		return args
	out = dict(args)
	# Object / array fields the schemas expect as JSON.
	for k in ("filters", "fields", "values", "patch", "spec", "extra_payload",
	          "extraHeaders", "headers", "tools", "params", "data"):
		v = out.get(k)
		if isinstance(v, str) and v:
			s = v.strip()
			# Only attempt parse if it LOOKS like JSON — otherwise the string is
			# a real string the schema expects (e.g. `query` text, `code` body).
			# Single-quote pseudo-JSON ("['name', 'customer_name']") is the most
			# common offender from non-tool-trained models; convert before parse.
			if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
				try:
					out[k] = json.loads(s)
				except Exception:
					try:
						# seed-oss-36b emits Python-literal-looking lists with
						# single quotes — JSON requires double quotes. Swap and retry.
						out[k] = json.loads(s.replace("'", '"'))
					except Exception:
						pass  # leave as-is; downstream will surface the issue
	# Integer fields the schemas expect as ints.
	for k in ("limit", "max_chunks", "max_tokens", "temperature_x100", "depth"):
		v = out.get(k)
		if isinstance(v, str) and v.strip():
			try:
				out[k] = int(v.strip())
			except ValueError:
				try:
					out[k] = float(v.strip())
				except ValueError:
					pass
		elif isinstance(v, float) and k == "limit":
			out[k] = int(v)
	return out


def execute_tool(name, args, *, allow_writes=False, desk_context=None):
	# Defensive: many models stringify their tool args. Normalize before
	# dispatch so each tool's impl can rely on native types.
	args = _coerce_args(args)
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
		# Intent-aware sizing (2026-05-06, revised):
		# - No `limit` ⇒ default 20 (cheap schema probes).
		# - Explicit `limit` ⇒ honored verbatim. NO HARDCODED CEILING — enterprise
		#   queries legitimately need tens of thousands of rows, and any number
		#   we pick here becomes another wall the model hits and apologizes for.
		# - `limit <= 0` ⇒ unbounded (Frappe accepts limit_page_length=0 = no limit).
		# Physical safety: the chat-ui's mcpResultToText byte budget (250k chars)
		# truncates oversized results before they overflow the LLM context, and
		# Frappe's own DB query timeout protects against runaway queries.
		raw_limit = args.get("limit")
		if raw_limit is None:
			limit = 20
		else:
			limit = int(raw_limit)
			if limit < 0:
				limit = 0  # Frappe: 0 = no limit
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
			# Common business-term aliases that aren't doctypes in ERPNext.
			# Each entry: (target_doctype, hint). Returned with error so the
			# LLM sees both that the lookup failed AND what to do instead.
			alias = _DOCTYPE_ALIASES.get((dt or "").strip().title())
			if alias:
				return {
					"error": "invalid doctype",
					"redirect": alias[0],
					"hint": alias[1],
				}
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
		# REFUSE for doctypes that have a typed wrapper. Generic prepare_create_doc
		# lets the LLM stage incomplete rows that fail at /commit time with
		# opaque IntegrityError / getdoctype() / etc. Force the typed wrapper
		# so the user gets actionable validation errors at preview time.
		# Production trigger: LLM bypassed prepare_create_report on real chat
		# transcript 2026-05-08, used prepare_create_doc({doctype:"Report"}),
		# narrated success after the staging failed.
		typed_wrapper = _TYPED_WRAPPER_FOR_DOCTYPE.get(dt)
		if typed_wrapper:
			return {"error": (
				f"Use the typed wrapper '{typed_wrapper}' INSTEAD of "
				f"prepare_create_doc({{doctype:{dt!r}}}). The typed wrapper "
				f"validates required fields up front so you get actionable "
				f"errors at preview time. The generic path was refused to "
				f"prevent shipping incomplete rows."
			)}
		if not frappe.has_permission(dt, "create"):
			return {"error": "no create permission"}
		token = _stage_action("create", {"doctype": dt, "values": values})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create {dt} with {len(values)} field(s)",
			"preview": {"doctype": dt, "fields": values},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
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
			"confirm_with": "click the inline Apply button to confirm",
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
			"confirm_with": "click the inline Apply button to confirm",
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
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_add_comment":
		dt = args.get("doctype")
		dn = args.get("name")
		text = args.get("text")
		if not dt or not dn or not text:
			return {"error": "doctype, name, and text required"}
		# Fail-fast existence check. Many doctypes (Note, ToDo, Comment, …) use
		# autoname=hash so the document name is NOT the title the model just
		# created — passing the title here used to stage successfully and only
		# fail on /commit. Catch it now with a hint the model can act on.
		if not frappe.db.exists(dt, dn):
			return {
				"error": (
					f"{dt} '{dn}' not found. The document name is the Frappe "
					f"primary key, which for autoname=hash doctypes (Note, "
					f"ToDo, Comment, …) is NOT the title. Use search_global "
					f"or get_list to find the actual name."
				)
			}
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission"}
		token = _stage_action("add_comment", {"doctype": dt, "name": dn, "text": text})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will add comment on {dt}/{dn}",
			"preview": {"text": text[:500]},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
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
			"confirm_with": "click the inline Apply button to confirm",
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
			"confirm_with": "click the inline Apply button to confirm",
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
			"confirm_with": "click the inline Apply button to confirm",
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
		# Intent-aware sizing: default 20k for quick scans, NO hardcoded cap.
		# A 5MB invoice PDF legitimately needs all of it. The chat-ui's
		# mcpResultToText byte budget (250k chars) governs what fits in the
		# LLM context — anything beyond is summarized client-side.
		raw = args.get("max_chars")
		if raw is None:
			max_chars = 20000
		else:
			max_chars = int(raw)
			if max_chars <= 0:
				# Sentinel for "give me everything you can read" — read the
				# entire file. Pure-Python io.read() handles this fine.
				max_chars = None  # interpreted below as "no cap"
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
			# max_chars is None => no cap (return whole file)
			if max_chars is None:
				truncated = False
				out_text = text
			else:
				truncated = len(text) > max_chars
				out_text = text[:max_chars]
			return {
				"ok": True,
				"name": file_doc.name,
				"file_name": file_doc.file_name,
				"file_url": file_doc.file_url,
				"file_size": file_doc.file_size,
				"truncated": truncated,
				"content": out_text,
			}
		except Exception as e:
			return {"error": str(e)}

	if name == "run_sql_select":
		# Auto-execute SELECT-only SQL — no /commit gate. Same security
		# envelope as prepare_run_sql (allow_dangerous_tools site flag +
		# System Manager role + _validate_select_sql regex). The /commit
		# step that prepare_run_sql adds is over-cautious for read-only
		# queries: SQL is already permission-bypassing (raw query against
		# the DB) but the 3 gates above prevent abuse, and the staging
		# step adds friction without safety. Use this for analytical
		# queries; use prepare_run_sql only when an explicit user-approval
		# gate is desirable (rare).
		ok, err = _dangerous_tools_enabled()
		if not ok:
			return {"error": err}
		query = (args.get("query") or "").strip()
		validation_error = _validate_select_sql(query)
		if validation_error:
			return {"error": validation_error}
		limit = min(int(args.get("limit") or 200), 1000)
		try:
			rows = frappe.db.sql(query, as_dict=True)
		except Exception as e:
			return _wrap_db_error(e, query, action="run_sql_select")
		truncated = False
		if isinstance(rows, list) and len(rows) > limit:
			rows = rows[:limit]
			truncated = True
		return {
			"ok": True,
			"row_count": len(rows) if isinstance(rows, list) else 0,
			"truncated": truncated,
			"rows": rows,
		}

	if name == "run_python_readonly":
		# Auto-execute Python with read-only enforcement. Two layers:
		#   1. Static AST scan (_validate_python_readonly) blocks imports of
		#      non-DB-rollbackable modules (subprocess, os, urllib, smtplib,
		#      ...), forbidden built-ins (open, exec, eval, __import__),
		#      and explicit frappe.* / frappe.db.* mutator/side-effect calls
		#      (sendmail, publish_realtime, enqueue, delete_doc,
		#      frappe.db.set_value, frappe.db.delete, ...).
		#   2. Runtime savepoint that ALWAYS rolls back. Even if the AST scan
		#      misses something, any DB mutation (.save(), .insert(),
		#      doc.set('field', ...).save(), etc.) is undone before the
		#      response is returned.
		# Same gating as prepare_run_python (allow_dangerous_tools site flag
		# + System Manager role). For analytical Python that goes beyond
		# what run_sql_select can express (pandas pivots, multi-pass
		# computations, etc).
		ok, err = _dangerous_tools_enabled()
		if not ok:
			return {"error": err}
		code = args.get("code") or ""
		validation_error = _validate_python_readonly(code)
		if validation_error:
			return {"error": validation_error}

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

		buf = io.StringIO()
		import contextlib
		sp = "lazychat_ro_" + secrets.token_hex(4)
		try:
			frappe.db.savepoint(sp)
		except Exception:
			pass
		try:
			with contextlib.redirect_stdout(buf):
				try:
					value = eval(compile(code, "<lazychat_readonly>", "eval"), ns, ns)
					ns["_result"] = value
				except SyntaxError:
					exec(compile(code, "<lazychat_readonly>", "exec"), ns, ns)
		except Exception as e:
			# Always rollback first so any partial mutation is undone
			try: frappe.db.rollback(save_point=sp)
			except Exception: pass
			_msg = str(e)
			if (
				"OperationalError" in type(e).__name__
				or "ProgrammingError" in type(e).__name__
				or "1054" in _msg or "1064" in _msg or "1146" in _msg
			):
				wrapped = _wrap_db_error(e, code, action="run_python_readonly")
				wrapped["stdout"] = buf.getvalue()[:8000]
				return wrapped
			return {
				"ok": False,
				"action": "run_python_readonly",
				"error": f"{type(e).__name__}: {e}",
				"stdout": buf.getvalue()[:8000],
			}
		# Read-only by design — rollback any DB writes the AST scan didn't catch.
		try: frappe.db.rollback(save_point=sp)
		except Exception: pass

		result = ns.get("_result")
		try:
			json.dumps(result, default=str)
		except Exception:
			result = str(result)
		return {
			"ok": True,
			"action": "run_python_readonly",
			"result": result,
			"stdout": buf.getvalue()[:8000],
		}

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
			"confirm_with": "click the inline Apply button to confirm",
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
			"confirm_with": "click the inline Apply button to confirm",
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
			"confirm_with": "click the inline Apply button to confirm",
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
			"confirm_with": "click the inline Apply button to confirm",
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
			"confirm_with": "click the inline Apply button to confirm",
		}

	# Tier B-upload — chat-side file picker. prepare_upload_file stages an
	# attach action; the chat-ui panel shim's /upload TOKEN slash command opens
	# a file picker, uploads to /api/method/upload_file, then calls
	# commit_prepared_action with the returned file_url. The commit handler
	# attaches the new File row to the target doc.
	if name == "prepare_upload_file":
		dt = (args.get("target_doctype") or args.get("doctype") or "").strip()
		dn = (args.get("target_name") or args.get("name") or "").strip()
		accept = (args.get("accept") or "").strip()  # optional MIME / ext filter for the picker
		if not dt or not dn:
			return {"error": "target_doctype and target_name required"}
		if not frappe.db.exists(dt, dn):
			return {"error": f"target doc not found: {dt}/{dn}"}
		if not frappe.has_permission(dt, "write", doc=dn):
			return {"error": "no write permission on target doc"}
		token = _stage_action(
			"attach_file",
			{"target_doctype": dt, "target_name": dn, "accept": accept},
		)
		return {
			"ok": True,
			"preview_token": token,
			"file_picker": True,  # chat-ui marker — render an Upload button
			"accept": accept or "*/*",
			"target_doctype": dt,
			"target_name": dn,
			"summary": f"Will attach a file to {dt}/{dn}" + (f" (filter: {accept})" if accept else ""),
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": f"/upload {token}",
			"_note": "Type /upload TOKEN in the chat input to open the file picker. The chat-ui will upload + attach automatically.",
		}

	# Tier C-import — bulk insert/update via Frappe's Data Import doctype.
	# Gated identically to prepare_run_sql / prepare_run_python: requires
	# allow_dangerous_tools site flag + System Manager role + /commit. Bulk
	# DB writes need the same safeguard as raw SQL.
	if name == "prepare_import_csv":
		ok, gate_err = _dangerous_tools_enabled()
		if not ok:
			return {"error": gate_err}
		dt = (args.get("doctype") or "").strip()
		csv_file_url = (args.get("csv_file_url") or args.get("file_url") or "").strip()
		import_type = (args.get("import_type") or "Insert New Records").strip()
		if not dt or not frappe.db.exists("DocType", dt):
			return {"error": "valid doctype required"}
		if not csv_file_url:
			return {"error": "csv_file_url required (upload the CSV via Desk attachments first OR call prepare_upload_file)"}
		# Find the File doctype row by URL and verify the user can read it
		matches = frappe.get_all("File", filters={"file_url": csv_file_url}, fields=["name", "file_name"], limit=1)
		if not matches:
			return {"error": f"file not found at URL: {csv_file_url}"}
		if not frappe.has_permission("Data Import", "create"):
			return {"error": "no permission to create Data Import"}
		if import_type not in ("Insert New Records", "Update Existing Records"):
			return {"error": "import_type must be 'Insert New Records' or 'Update Existing Records'"}
		token = _stage_action(
			"import_csv",
			{
				"reference_doctype": dt,
				"import_type": import_type,
				"file_url": csv_file_url,
				"file_name": matches[0]["file_name"],
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create a Data Import for {dt} ({import_type}) using {matches[0]['file_name']}",
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
			"_note": "On commit, a Data Import doctype row is created and start_import() is called. Watch progress via list_my_jobs.",
		}

	# Files (Tier B reads) — list attachments on any doc the user can read,
	# resolve a File doctype row (by name or file_url) to its absolute URL.
	# These complement extract_file_content (which reads a file's text) and
	# the KB tools (which search across attached files semantically).
	if name == "list_attachments":
		dt = args.get("doctype")
		dn = args.get("name")
		if not dt or not dn:
			return {"error": "doctype and name required"}
		# Permission gate on the parent doc — File rows inherit visibility from
		# their attached doc when attached_to_doctype/name are set.
		if not frappe.has_permission(dt, "read", doc=dn):
			return {"error": "no read permission on parent doc"}
		try:
			rows = frappe.get_all(
				"File",
				filters={"attached_to_doctype": dt, "attached_to_name": dn},
				fields=["name", "file_name", "file_url", "is_private", "file_size", "file_type", "owner", "creation"],
				order_by="creation desc",
			)
			# Inject absolute_url so the agent can cite a clickable link without
			# guessing the host. Tier-A's <a> interceptor already opens
			# /files/... and /private/files/... in a new tab.
			for r in rows:
				url = r.get("file_url")
				if url:
					try:
						r["absolute_url"] = _frappe_get_url(url)
					except Exception:
						r["absolute_url"] = None
			return {"ok": True, "doctype": dt, "name": dn, "count": len(rows), "files": rows}
		except Exception as e:
			return {"error": str(e)}

	if name == "get_file_url":
		# Accept either the File doctype name OR a raw file_url. Useful when
		# the agent has a URL from list_attachments / get_doc and wants the
		# absolute path it can cite to the user.
		ref = (args.get("file") or args.get("name") or args.get("file_url") or "").strip()
		if not ref:
			return {"error": "file (File doctype name or file_url) required"}
		try:
			file_doc = None
			if frappe.db.exists("File", ref):
				file_doc = frappe.get_doc("File", ref)
			else:
				match = frappe.get_all("File", filters={"file_url": ref}, fields=["name"], limit=1)
				if match:
					file_doc = frappe.get_doc("File", match[0].name)
			if not file_doc:
				return {"error": f"file not found: {ref}"}
			# Permission: if the file's attached to a doc, user must be able to read that doc.
			# Public files (no attached_to_doctype) are readable by anyone authenticated.
			if file_doc.attached_to_doctype and file_doc.attached_to_name:
				if not frappe.has_permission(file_doc.attached_to_doctype, "read", doc=file_doc.attached_to_name):
					return {"error": "no read permission on the doc this file is attached to"}
			absolute = None
			if file_doc.file_url:
				try:
					absolute = _frappe_get_url(file_doc.file_url)
				except Exception:
					pass
			return {
				"ok": True,
				"name": file_doc.name,
				"file_name": file_doc.file_name,
				"file_url": file_doc.file_url,
				"absolute_url": absolute,
				"is_private": bool(file_doc.is_private),
				"file_size": file_doc.file_size,
				"attached_to_doctype": file_doc.attached_to_doctype,
				"attached_to_name": file_doc.attached_to_name,
			}
		except Exception as e:
			return {"error": str(e)}

	# Tier D — Realtime doc-change subscriptions. User says "watch SO-001",
	# every save (anywhere) pings the chat-ui as a toast. Read-only / config
	# tools, no /commit needed.
	if name == "subscribe_doc_changes":
		from lazychat_mcp_erpnext.desk_assistant import realtime_subs as _rt

		dt = (args.get("doctype") or "").strip()
		dn = (args.get("name") or "").strip()
		if not dt or not dn:
			return {"error": "doctype and name required"}
		return _rt.subscribe(dt, dn)

	if name == "unsubscribe_doc_changes":
		from lazychat_mcp_erpnext.desk_assistant import realtime_subs as _rt

		dt = (args.get("doctype") or "").strip()
		dn = (args.get("name") or "").strip()
		if not dt or not dn:
			return {"error": "doctype and name required"}
		return _rt.unsubscribe(dt, dn)

	if name == "list_my_subscriptions":
		from lazychat_mcp_erpnext.desk_assistant import realtime_subs as _rt

		return _rt.list_my()

	# Charts (Tier F) — thin passthrough that validates a Vega-Lite spec and
	# echoes it back. Purpose: gives the LLM a tool-call so the live mcpTool
	# card shows "Calling make_chart…" while the chart itself is rendered
	# inline via the [[lazychat:artifact kind="chart"]]...[[/lazychat:artifact]]
	# marker the agent also emits in its reply.
	if name == "make_chart":
		spec = args.get("spec")
		title = (args.get("title") or "").strip() or None
		if isinstance(spec, str):
			try:
				spec = json.loads(spec)
			except Exception as e:
				return {"error": f"spec must be a JSON object or a JSON-parseable string: {e}"}
		if not isinstance(spec, dict):
			return {"error": "spec must be a JSON object"}
		# Vega-Lite shape check — spec needs at least ONE of: $schema, mark,
		# layer, hconcat, vconcat, facet, repeat. Cheap reject of obvious
		# nonsense without pulling in a vega-lite validator.
		shape_keys = {"$schema", "mark", "layer", "hconcat", "vconcat", "facet", "repeat"}
		if not any(k in spec for k in shape_keys):
			return {
				"error": "spec doesn't look like a Vega-Lite document — needs at least one of: "
				+ ", ".join(sorted(shape_keys))
			}
		return {"ok": True, "spec": spec, "title": title}

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
	# Tier G: when called with NO `fields` arg, returns a field-picker preview
	# (preview_token + available fields with default-selected flags + row-count
	# estimate). The chat-ui detects this shape and renders an inline checkbox
	# UI; on Generate, posts /commit TOKEN fields=... to run the actual export.
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
		fields = args.get("fields")
		# --- Tier G: field-picker preview when fields omitted ---
		if fields is None:
			try:
				meta = frappe.get_meta(dt)
				picker_fields = []
				# Always offer 'name' first — every doctype has it
				picker_fields.append({
					"fieldname": "name",
					"label": "ID",
					"fieldtype": "Data",
					"default_selected": True,
				})
				for df in meta.fields:
					if df.fieldtype in ("Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading"):
						continue
					if df.fieldtype == "Table" or df.fieldtype == "Table MultiSelect":
						continue  # child tables can't go in a flat CSV
					picker_fields.append({
						"fieldname": df.fieldname,
						"label": df.label or df.fieldname,
						"fieldtype": df.fieldtype,
						"default_selected": bool(getattr(df, "in_list_view", 0)),
					})
				# Estimate row count given filters
				try:
					row_count_estimate = frappe.db.count(dt, filters=filters)
				except Exception:
					row_count_estimate = None
				token = _stage_action(
					"export_csv",
					{"doctype": dt, "filters": filters, "limit": min(int(args.get("limit") or 1000), 5000)},
				)
				return {
					"ok": True,
					"preview_token": token,
					"field_picker": True,  # chat-ui marker — render checkbox UI
					"target_doctype": dt,
					"fields": picker_fields,
					"row_count_estimate": row_count_estimate,
					"prompt": f"Pick fields to include in the {dt} CSV. Default selection follows the doctype's 'in_list_view' flags.",
					"expires_in_sec": PREP_TTL_SEC,
					"confirm_with": "pick fields in the inline checkbox UI and confirm",
				}
			except Exception as e:
				return {"error": f"field-picker preview failed: {e}"}
		# --- Direct export when fields supplied ---
		if not isinstance(fields, list) or not all(isinstance(f, str) for f in fields):
			return {"error": "fields must be a list of strings"}
		# CSV export is the enterprise-bulk path — file output, no LLM-context
		# concern. Default 5000 (typical), honor explicit limit verbatim, NO
		# hardcoded ceiling. Pass <= 0 for unbounded (Frappe limit_page_length=0).
		raw_csv_limit = args.get("limit")
		if raw_csv_limit is None:
			limit = 5000
		else:
			limit = int(raw_csv_limit)
			if limit < 0:
				limit = 0  # Frappe: 0 = no limit
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
			# Attach the export to the user's User row so Frappe's File-permission
			# resolver grants /private/files access on click. Without an
			# attached_to_doctype/attached_to_name, the File defaults to
			# owner-only semantics and the request session can fail the check
			# (yields 403 on click).
			file_doc = frappe.get_doc({
				"doctype": "File",
				"file_name": fname,
				"is_private": 1,
				"content": csv_bytes,
				"attached_to_doctype": "User",
				"attached_to_name": frappe.session.user,
			}).insert(ignore_permissions=False)
			return {
				"ok": True,
				"file_url": file_doc.file_url,
				"absolute_url": _frappe_get_url(file_doc.file_url),
				"file_name": fname,
				"row_count": len(rows),
				"truncated": (limit > 0 and len(rows) >= limit),
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
			# Check terminal status BEFORE attempting cancel. Idempotent:
			# repeated calls on a finished job shouldn't surface errors.
			current_status = (getattr(job, "status", "") or "").lower()
			if current_status in ("finished", "failed", "stopped", "canceled", "cancelled"):
				return {
					"ok": True,
					"job_id": job_id,
					"status": current_status,
					"already_terminal": True,
				}
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
			# Three exception classes mean the same thing — "the job is gone /
			# already terminal":
			#   - rq.exceptions.InvalidJobOperation: stop_job() on a terminal job
			#   - rq.exceptions.NoSuchJobError:      RQ purged the Redis entry
			#   - frappe.exceptions.DoesNotExistError: Frappe's RQ Job doc was
			#     cleaned up (typical when finished_jobs_ttl elapses, ~60s after
			#     a job completes)
			# All three should be treated as idempotent success — the caller's
			# intent (cancel) is satisfied because the job is no longer running.
			err_name = type(e).__name__
			if err_name in ("InvalidJobOperation", "NoSuchJobError", "DoesNotExistError"):
				return {
					"ok": True,
					"job_id": job_id,
					"status": "gone",
					"already_terminal": True,
					"note": f"{err_name}: treated as idempotent success",
				}
			# repr(e) surfaces type+message — str(e) was returning empty for
			# zero-message rq exceptions.
			return {"error": f"cancel failed: {err_name}: {e!r}"}

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

	if name == "reindex_kb":
		from lazychat_mcp_erpnext.desk_assistant import embeddings as _emb

		kb_name = (args.get("kb_name") or "").strip()
		if not kb_name:
			return {"error": "kb_name required"}
		# reindex_kb is direct (no /commit) because it's idempotent — content_hash
		# dedupe means re-running is safe and cheap when nothing changed.
		return _emb.reindex_kb(kb_name)

	# KB write tools (Tier H3) — create a Lazychat Knowledge Base or attach an
	# existing File to one. Two-phase via /commit because they mutate state.
	if name == "prepare_create_kb":
		title = (args.get("title") or "").strip()
		slug = (args.get("slug") or args.get("kb_name") or "").strip()
		description = (args.get("description") or "").strip()
		is_public = bool(args.get("is_public", False))
		if not title:
			return {"error": "title required"}
		if not slug:
			# Auto-derive from title — kebab-case, alphanumeric only, capped 64.
			slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:64]
		if not slug:
			return {"error": "could not derive slug from title — pass `slug` explicitly"}
		if frappe.db.exists("Lazychat Knowledge Base", slug):
			return {"error": f"knowledge base already exists: {slug}"}
		if is_public and "System Manager" not in frappe.get_roles():
			return {"error": "only System Manager can publish a knowledge base (is_public=true)"}
		if not frappe.has_permission("Lazychat Knowledge Base", "create"):
			return {"error": "no permission to create knowledge bases"}
		token = _stage_action(
			"create_kb",
			{
				"kb_name": slug,
				"title": title,
				"description": description,
				"is_public": 1 if is_public else 0,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create knowledge base '{slug}' titled '{title}'" + (" (public)" if is_public else ""),
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_add_file_to_kb":
		kb_name = (args.get("kb_name") or "").strip()
		file_url = (args.get("file_url") or "").strip()
		if not kb_name or not file_url:
			return {"error": "kb_name and file_url required"}
		if not frappe.db.exists("Lazychat Knowledge Base", kb_name):
			return {"error": f"knowledge base not found: {kb_name}"}
		# Find File doctype row by file_url
		matches = frappe.get_all("File", filters={"file_url": file_url}, fields=["name", "file_name"], limit=1)
		if not matches:
			return {"error": f"file not found: {file_url}"}
		file_doc_name = matches[0]["name"]
		display_name = matches[0]["file_name"] or file_url
		# Permission: user must be able to write the KB AND read the file
		if not frappe.has_permission("Lazychat Knowledge Base", "write", doc=kb_name):
			return {"error": "no write permission on this knowledge base"}
		if not frappe.has_permission("File", "read", doc=file_doc_name):
			return {"error": "no read permission on this file"}
		token = _stage_action(
			"add_file_to_kb",
			{"kb_name": kb_name, "file_name": file_doc_name, "file_url": file_url},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will attach '{display_name}' to knowledge base '{kb_name}'",
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	# Typed wrappers for doctypes where prepare_create_doc is too generic
	# (the model can supply structurally-valid but semantically-broken values
	# that only fail when the user opens the resulting record).
	#
	# 2026-05-06: added Report, Scheduled Job Type, Number Card, Dashboard
	# wrappers. These coexist with prepare_create_doc — they validate
	# doctype-specific fields up front so the model gets actionable errors
	# at preview time, not at /commit + open time.
	if name == "prepare_create_report":
		report_name = args.get("report_name") or args.get("name")
		ref_dt = args.get("ref_doctype")
		report_type = args.get("report_type") or "Report Builder"
		query = (args.get("query") or "").strip()
		script = (args.get("script") or args.get("report_script") or "").strip()
		columns = args.get("columns") or []
		filters = args.get("filters") or {}
		if not report_name or not ref_dt:
			return {"error": "report_name and ref_doctype required"}
		if report_type not in ("Report Builder", "Query Report", "Script Report"):
			return {"error": "report_type must be one of: Report Builder, Query Report, Script Report"}
		if not frappe.db.exists("DocType", ref_dt):
			return {"error": f"ref_doctype '{ref_dt}' does not exist"}
		if not frappe.has_permission("Report", "create"):
			return {"error": "no create permission on Report"}
		if not frappe.has_permission(ref_dt, "report"):
			return {"error": f"no report permission on {ref_dt}"}
		# Pre-detect duplicate name so the user sees the conflict at preview
		# time — NOT after clicking Apply and getting a commit-time
		# IntegrityError 1062. Production bug 2026-05-08: LLM kept restaging
		# the same name and narrating success after each Failed card.
		if frappe.db.exists("Report", report_name):
			return {"error": (
				f"Report '{report_name}' already exists. To modify it, use "
				f"prepare_update_doc({{doctype:'Report', name:{report_name!r}, "
				f"patch:{{...}}}}). To replace, delete the existing Report "
				f"first via prepare_delete_doc."
			)}
		if report_type == "Query Report":
			if not query:
				return {"error": "query is required for Query Report"}
			validation_error = _validate_select_sql(query)
			if validation_error:
				return {"error": validation_error}
			explain_error = _probe_select_sql_explain(query)
			if explain_error:
				return {"error": explain_error}
		if report_type == "Script Report":
			# Production bug 2026-05-08: a Script Report stored without a Python
			# `report_script` body opens to a blank page in Desk and the LLM has
			# no way to know it shipped empty. Force the body up front; the
			# minimal valid shape is `def execute(filters=None): return [], []`.
			if not script:
				return {"error": (
					"Script Reports require a `script` body (Python with `def execute(filters=None)` "
					"returning (columns, data)). PREFER report_type='Query Report' with HTML <a> "
					"link columns for buttons — Query Reports support HTML in cell values "
					"(e.g. CONCAT('<a href=\"/app/...\">Click</a>')) and avoid the safe_exec "
					"sandbox entirely. Either pass the full Python source as `script`, or "
					"switch to Query Report."
				)}
			# Reject imports, dangerous builtins, write-side frappe.db.*, and
			# side-effect frappe.* calls. Catches the most common LLM mistakes
			# (`import frappe`, `from frappe import _`, `frappe.db.set_value`,
			# `__import__('os')`) BEFORE the report ships and breaks at open time.
			validation_err = _validate_script_report_body(script)
			if validation_err:
				return {"error": validation_err}
			# Defense-in-depth: dry-run the body through Frappe's actual
			# safe_exec to catch subtle runtime errors AST can't see (leading-
			# underscore attribute access, unsafe getattr, etc.). Wrapped so
			# an import-time failure of safe_exec doesn't break the wrapper.
			try:
				from frappe.utils.safe_exec import safe_exec as _safe_exec
				_loc = {"filters": frappe._dict({}), "data": None, "result": None}
				_safe_exec(script, None, _loc, script_filename="lazychat-preview-probe")
			except ImportError:
				# safe_exec not importable on this Frappe version — skip dry-run
				pass
			except Exception as _e:
				_msg = str(_e)
				return {"error": (
					f"Script failed safe_exec dry-run at preview: "
					f"{type(_e).__name__}: {_msg[:200]}. Remove the offending "
					f"construct or switch to report_type='Query Report' for a "
					f"simpler path that supports HTML link columns."
				)}
		token = _stage_action(
			"create_report",
			{
				"report_name": report_name,
				"ref_doctype": ref_dt,
				"report_type": report_type,
				"query": query,
				"script": script,
				"columns": columns,
				"filters": filters,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create {report_type} '{report_name}' on {ref_dt}",
			"preview": {
				"name": report_name,
				"ref_doctype": ref_dt,
				"report_type": report_type,
				"query": query[:500] if query else None,
				"columns": columns[:20] if isinstance(columns, list) else columns,
				"filters": filters,
				# Frappe routes Query Report AND Script Report at /app/query-report/<name>.
				# Only Report Builder reports use /app/report/<name>.
				"open_url": (
					f"/app/report/{report_name}"
					if report_type == "Report Builder"
					else f"/app/query-report/{report_name}"
				),
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_scheduled_job":
		method = args.get("method")
		frequency = args.get("frequency") or "Daily"
		cron_format = args.get("cron_format") or ""
		if not method:
			return {"error": "method required (e.g. 'app.module.fn' — must be a server-side import path)"}
		valid_freqs = ("All", "Hourly", "Daily", "Daily Long", "Weekly", "Weekly Long", "Monthly", "Monthly Long", "Cron", "Annual")
		if frequency not in valid_freqs:
			return {"error": f"frequency must be one of: {', '.join(valid_freqs)}"}
		if frequency == "Cron" and not cron_format:
			return {"error": "cron_format required when frequency=Cron (e.g. '0 */6 * * *')"}
		# Scheduled Job Type creation is restricted to System Manager — re-check.
		if "System Manager" not in frappe.get_roles(frappe.session.user):
			return {"error": "System Manager role required to schedule jobs"}
		if not frappe.has_permission("Scheduled Job Type", "create"):
			return {"error": "no create permission on Scheduled Job Type"}
		token = _stage_action(
			"create_scheduled_job",
			{"method": method, "frequency": frequency, "cron_format": cron_format},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will schedule '{method}' to run {frequency.lower()}{f' (cron: {cron_format})' if cron_format else ''}",
			"preview": {"method": method, "frequency": frequency, "cron_format": cron_format or None},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_number_card":
		label = args.get("label") or args.get("name")
		dt = args.get("doctype")
		function = args.get("function") or "Count"
		aggregate_field = args.get("aggregate_function_based_on") or args.get("aggregate_field") or ""
		filters_json = args.get("filters_json") or "[]"
		color = args.get("color") or ""
		if not label or not dt:
			return {"error": "label and doctype required"}
		if function not in ("Count", "Sum", "Average", "Minimum", "Maximum"):
			return {"error": "function must be one of: Count, Sum, Average, Minimum, Maximum"}
		if function != "Count" and not aggregate_field:
			return {"error": f"aggregate_field required when function={function}"}
		if not frappe.db.exists("DocType", dt):
			return {"error": f"doctype '{dt}' does not exist"}
		if not frappe.has_permission(dt, "read"):
			return {"error": f"no read permission on {dt}"}
		if not frappe.has_permission("Number Card", "create"):
			return {"error": "no create permission on Number Card"}
		if isinstance(filters_json, (list, dict)):
			filters_json = json.dumps(filters_json)
		token = _stage_action(
			"create_number_card",
			{
				"label": label,
				"doctype": dt,
				"function": function,
				"aggregate_function_based_on": aggregate_field,
				"filters_json": filters_json,
				"color": color,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create Number Card '{label}' ({function} of {dt})",
			"preview": {
				"label": label,
				"doctype": dt,
				"function": function,
				"aggregate_field": aggregate_field or None,
				"filters_json": filters_json,
				"open_url": f"/app/number-card/{label}",
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_dashboard":
		dashboard_name = args.get("dashboard_name") or args.get("name")
		charts = args.get("charts") or []
		cards = args.get("cards") or []
		module = args.get("module") or ""
		if not dashboard_name:
			return {"error": "dashboard_name required"}
		if not isinstance(charts, list) or not isinstance(cards, list):
			return {"error": "charts and cards must be lists"}
		if not charts and not cards:
			return {"error": "supply at least one chart or card to embed"}
		if not frappe.has_permission("Dashboard", "create"):
			return {"error": "no create permission on Dashboard"}
		# Verify each referenced chart / card exists and is readable.
		for c in charts:
			cname = c.get("chart") if isinstance(c, dict) else c
			if not cname or not frappe.db.exists("Dashboard Chart", cname):
				return {"error": f"Dashboard Chart '{cname}' not found"}
		for c in cards:
			cname = c.get("card") if isinstance(c, dict) else c
			if not cname or not frappe.db.exists("Number Card", cname):
				return {"error": f"Number Card '{cname}' not found"}
		token = _stage_action(
			"create_dashboard",
			{"dashboard_name": dashboard_name, "charts": charts, "cards": cards, "module": module},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create Dashboard '{dashboard_name}' with {len(charts)} chart(s) + {len(cards)} card(s)",
			"preview": {
				"name": dashboard_name,
				"charts": [c.get("chart") if isinstance(c, dict) else c for c in charts],
				"cards": [c.get("card") if isinstance(c, dict) else c for c in cards],
				"open_url": f"/app/dashboard-view/{dashboard_name}",
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	# ------------------------------------------------------------------
	# 2026-05-06 (Commit 1) — typed wrappers for ERPNext "Tools" workspace.
	# Each one validates doctype-specific shape at preview time so the
	# model gets actionable errors in the SAME turn instead of a confusing
	# /commit failure.
	# ------------------------------------------------------------------

	if name == "prepare_create_calendar_event":
		subject = (args.get("subject") or "").strip()
		starts_on = args.get("starts_on")
		ends_on = args.get("ends_on")
		all_day = bool(args.get("all_day"))
		event_type = args.get("event_type") or "Private"
		repeat_this_event = bool(args.get("repeat_this_event"))
		repeat_on = (args.get("repeat_on") or "").strip()
		participants = args.get("participants") or []
		description = args.get("description") or ""
		if not subject:
			return {"error": "subject required"}
		if not starts_on:
			return {"error": "starts_on required (ISO datetime, e.g. '2026-05-10 09:00:00')"}
		if event_type not in ("Public", "Private"):
			return {"error": "event_type must be 'Public' or 'Private'"}
		try:
			from frappe.utils import get_datetime
			start_dt = get_datetime(starts_on)
		except Exception as e:
			return {"error": f"starts_on is not a valid datetime: {e}"}
		end_dt = None
		if ends_on:
			try:
				from frappe.utils import get_datetime
				end_dt = get_datetime(ends_on)
			except Exception as e:
				return {"error": f"ends_on is not a valid datetime: {e}"}
			if end_dt < start_dt:
				return {"error": "ends_on must be >= starts_on"}
		if repeat_this_event:
			if repeat_on not in ("Daily", "Weekly", "Monthly", "Yearly"):
				return {"error": "repeat_on required when repeat_this_event=True (Daily/Weekly/Monthly/Yearly)"}
		if not isinstance(participants, list):
			return {"error": "participants must be a list of {reference_doctype, reference_docname}"}
		if not frappe.has_permission("Event", "create"):
			return {"error": "no create permission on Event"}
		token = _stage_action(
			"create_calendar_event",
			{
				"subject": subject,
				"starts_on": str(start_dt),
				"ends_on": str(end_dt) if end_dt else None,
				"all_day": 1 if all_day else 0,
				"description": description,
				"event_type": event_type,
				"repeat_this_event": 1 if repeat_this_event else 0,
				"repeat_on": repeat_on or None,
				"participants": participants,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create {event_type} Event '{subject}' @ {start_dt}",
			"preview": {
				"subject": subject,
				"starts_on": str(start_dt),
				"ends_on": str(end_dt) if end_dt else None,
				"event_type": event_type,
				"repeat": repeat_on if repeat_this_event else None,
				"participant_count": len(participants),
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_note":
		title = (args.get("title") or "").strip()
		content = args.get("content") or ""
		public = bool(args.get("public"))
		if not title:
			return {"error": "title required"}
		if not content or not content.strip():
			return {"error": "content required (HTML/markdown body)"}
		if not frappe.has_permission("Note", "create"):
			return {"error": "no create permission on Note"}
		token = _stage_action(
			"create_note",
			{"title": title, "content": content, "public": 1 if public else 0},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create {'public ' if public else ''}Note '{title}'",
			"preview": {
				"title": title,
				"public": public,
				"content_preview": content[:300] + ("…" if len(content) > 300 else ""),
				"note": "Note autonames as hash; the actual document `name` is returned in the /commit response — pass that to follow-up tools that take `name`, not the title.",
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_bulk_update":
		dt = args.get("doctype")
		filters = args.get("filters") or {}
		patch = args.get("patch") or {}
		caller_max = args.get("max_rows")
		if not dt:
			return {"error": "doctype required"}
		if not frappe.db.exists("DocType", dt):
			return {"error": f"doctype '{dt}' does not exist"}
		if not isinstance(filters, dict):
			return {"error": "filters must be an object/dict"}
		if not isinstance(patch, dict) or not patch:
			return {"error": "patch must be a non-empty object/dict of fieldname → new value"}
		# Gate: bulk update is high-blast-radius; reuse the dangerous-tools flag.
		ok, err = _dangerous_tools_enabled()
		if not ok:
			return {"error": f"prepare_bulk_update is gated: {err}"}
		if not frappe.has_permission(dt, "write"):
			return {"error": f"no write permission on {dt}"}
		# Resolve the configured ceiling. Lazychat Settings → bulk_update_max_rows
		# (default 500). Site_config can override via lazychat_bulk_update_max_rows.
		try:
			from lazychat_mcp_erpnext.desk_assistant.boot import get_lazychat_settings as _gls
			settings_max = int(_gls().get("bulk_update_max_rows") or 500)
		except Exception:
			settings_max = 500
		# Validate patch fieldnames FIRST — cheap, no DB hit. If the patch is
		# bogus we want the model to see that error before the row-count
		# check (which can otherwise hide it behind 'no docs matched').
		try:
			meta = frappe.get_meta(dt)
		except Exception as e:
			return {"error": f"could not load meta for {dt}: {e}"}
		valid_fields = {df.fieldname for df in meta.fields} | {"name", "owner", "modified_by"}
		bad = [f for f in patch.keys() if f not in valid_fields]
		if bad:
			return {"error": f"unknown field(s) on {dt}: {', '.join(bad)}"}
		# Live count via Frappe (mirrors count_doc tool semantics).
		try:
			affected_count = frappe.db.count(dt, filters=filters)
		except Exception as e:
			return {"error": f"count failed for filters {filters}: {e}"}
		caller_max = int(caller_max) if caller_max not in (None, "") else None
		effective_max = min(settings_max, caller_max) if caller_max else settings_max
		if affected_count > effective_max:
			return {
				"error": (
					f"affected_count={affected_count} exceeds the bulk update ceiling "
					f"({effective_max}). Tighten filters or raise bulk_update_max_rows in "
					f"Lazychat Settings."
				),
				"affected_count": affected_count,
				"ceiling": effective_max,
			}
		if affected_count == 0:
			return {"error": "no docs matched the filter — nothing to update"}
		token = _stage_action(
			"bulk_update",
			{
				"doctype": dt,
				"filters": filters,
				"patch": patch,
				"affected_count_at_prepare": affected_count,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will update {affected_count} {dt} doc(s) — {len(patch)} field(s)",
			"preview": {
				"doctype": dt,
				"filters": filters,
				"patch": patch,
				"affected_count": affected_count,
				"ceiling": effective_max,
				"note": "If new docs match the filter between preview and /commit, commit re-counts and refuses if the count grew >1.5×.",
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_download_backup":
		with_files = bool(args.get("with_files"))
		if "System Manager" not in frappe.get_roles(frappe.session.user):
			return {"error": "System Manager role required to trigger a backup"}
		token = _stage_action(
			"download_backup",
			{"with_files": 1 if with_files else 0},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will enqueue site backup{' (with files)' if with_files else ''}; poll progress with list_my_jobs.",
			"preview": {"with_files": with_files},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_print_format":
		pf_name = (args.get("name") or "").strip()
		doc_type = args.get("doc_type")
		print_format_type = args.get("print_format_type") or "Jinja"
		html = args.get("html") or ""
		format_data = args.get("format_data") or ""
		standard = bool(args.get("standard"))
		if not pf_name:
			return {"error": "name required"}
		if not doc_type:
			return {"error": "doc_type required"}
		if not frappe.db.exists("DocType", doc_type):
			return {"error": f"doc_type '{doc_type}' does not exist"}
		if print_format_type not in ("Jinja", "Custom Format"):
			return {"error": "print_format_type must be 'Jinja' or 'Custom Format'"}
		if print_format_type == "Jinja" and not html.strip():
			return {"error": "html is required when print_format_type=Jinja"}
		if print_format_type == "Custom Format" and not format_data.strip():
			return {"error": "format_data (JSON) is required when print_format_type='Custom Format'"}
		if standard and "System Manager" not in frappe.get_roles(frappe.session.user):
			return {"error": "System Manager role required to mark a Print Format as standard"}
		if not frappe.has_permission("Print Format", "create"):
			return {"error": "no create permission on Print Format"}
		if not frappe.has_permission(doc_type, "print"):
			return {"error": f"no print permission on {doc_type}"}
		# Jinja dry-render to catch template syntax errors at preview time.
		if print_format_type == "Jinja":
			try:
				frappe.render_template(html, {"doc": frappe._dict()})
			except Exception as e:
				return {"error": f"Jinja template did not render: {type(e).__name__}: {e}"}
		token = _stage_action(
			"create_print_format",
			{
				"name": pf_name,
				"doc_type": doc_type,
				"print_format_type": print_format_type,
				"html": html,
				"format_data": format_data,
				"standard": "Yes" if standard else "No",
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create {print_format_type} Print Format '{pf_name}' for {doc_type}",
			"preview": {
				"name": pf_name,
				"doc_type": doc_type,
				"print_format_type": print_format_type,
				"html_preview": (html[:300] + "…") if len(html) > 300 else html,
				"open_url": f"/app/print-format/{pf_name}",
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_update_print_settings":
		if "System Manager" not in frappe.get_roles(frappe.session.user):
			return {"error": "System Manager role required to update Print Settings"}
		# Build the patch from supported fields only.
		supported = {
			"with_letterhead", "compact_item_print", "print_taxes_with_zero_amount",
			"font", "font_size", "pdf_page_size", "pdf_page_height", "pdf_page_width",
		}
		patch = {k: v for k, v in args.items() if k in supported and v is not None}
		if not patch:
			return {"error": f"supply at least one field to update. Supported: {sorted(supported)}"}
		# Validate enum values.
		valid_page_sizes = {
			"A4", "Letter", "A0", "A1", "A2", "A3", "A5", "A6", "A7", "A8", "A9",
			"B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10",
			"C5E", "Comm10E", "DLE", "Executive", "Folio", "Ledger", "Legal",
			"Tabloid", "Custom",
		}
		if "pdf_page_size" in patch and patch["pdf_page_size"] not in valid_page_sizes:
			return {"error": f"pdf_page_size must be one of: {sorted(valid_page_sizes)}"}
		# Build a from→to diff so the preview is meaningful.
		try:
			cur = frappe.get_single("Print Settings")
		except Exception as e:
			return {"error": f"could not load Print Settings: {e}"}
		diff = {f: {"from": cur.get(f), "to": v} for f, v in patch.items()}
		token = _stage_action("update_print_settings", {"patch": patch})
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will update Print Settings ({len(patch)} field(s))",
			"diff": diff,
			"preview": {"patch": patch, "open_url": "/app/print-settings"},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_email_template":
		tpl_name = (args.get("name") or "").strip()
		subject = args.get("subject") or ""
		response = args.get("response") or ""
		use_html = bool(args.get("use_html") if args.get("use_html") is not None else True)
		if not tpl_name:
			return {"error": "name required"}
		if not subject.strip():
			return {"error": "subject required"}
		if not response.strip():
			return {"error": "response (body) required"}
		if not frappe.has_permission("Email Template", "create"):
			return {"error": "no create permission on Email Template"}
		# Jinja dry-render against an empty context — catches the bulk of
		# template typos at preview time so the LLM doesn't have to roundtrip.
		try:
			frappe.render_template(subject, {"doc": frappe._dict()})
		except Exception as e:
			return {"error": f"subject Jinja did not render: {type(e).__name__}: {e}"}
		try:
			frappe.render_template(response, {"doc": frappe._dict()})
		except Exception as e:
			return {"error": f"response (body) Jinja did not render: {type(e).__name__}: {e}"}
		token = _stage_action(
			"create_email_template",
			{
				"name": tpl_name,
				"subject": subject,
				"response": response,
				"use_html": 1 if use_html else 0,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create Email Template '{tpl_name}'",
			"preview": {
				"name": tpl_name,
				"subject": subject[:200],
				"body_preview": (response[:300] + "…") if len(response) > 300 else response,
				"open_url": f"/app/email-template/{tpl_name}",
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	# ------------------------------------------------------------------
	# 2026-05-06 (Commit 2) — Alerts / Newsletter / Automation surface.
	# ------------------------------------------------------------------

	if name == "prepare_create_notification":
		subject = (args.get("subject") or "").strip()
		document_type = args.get("document_type")
		event = args.get("event")
		channel = args.get("channel") or "Email"
		recipients = args.get("recipients") or []
		message = args.get("message") or ""
		condition = args.get("condition") or ""
		date_changed = args.get("date_changed")
		value_changed = args.get("value_changed")
		method = args.get("method")
		days_in_advance = args.get("days_in_advance")
		slack_webhook = args.get("slack_webhook_url")
		property_value = args.get("property_value")

		if not subject:
			return {"error": "subject required"}
		if not document_type:
			return {"error": "document_type required"}
		if not event:
			return {"error": "event required"}
		valid_events = ("New", "Save", "Submit", "Cancel", "Days After", "Days Before", "Value Change", "Method", "Custom")
		if event not in valid_events:
			return {"error": f"event must be one of: {', '.join(valid_events)}"}
		valid_channels = ("Email", "Slack", "System Notification", "SMS")
		if channel not in valid_channels:
			return {"error": f"channel must be one of: {', '.join(valid_channels)}"}
		if not frappe.db.exists("DocType", document_type):
			return {"error": f"document_type '{document_type}' does not exist"}
		if not frappe.has_permission("Notification", "create"):
			return {"error": "no create permission on Notification"}
		# Conditional required fields per event.
		if event in ("Days Before", "Days After"):
			if not date_changed:
				return {"error": f"date_changed (a Date/Datetime fieldname on {document_type}) is required when event='{event}'"}
		if event == "Value Change":
			if not value_changed:
				return {"error": f"value_changed (a fieldname on {document_type}) is required when event='Value Change'"}
		if event == "Method":
			if not method:
				return {"error": "method (server-side import path) is required when event='Method'"}
		if channel == "Slack" and not slack_webhook:
			return {"error": "slack_webhook_url is required when channel='Slack'"}
		# Existential checks on referenced fieldnames.
		try:
			meta = frappe.get_meta(document_type)
		except Exception as e:
			return {"error": f"could not load meta for {document_type}: {e}"}
		field_map = {df.fieldname: df for df in meta.fields}
		if date_changed and date_changed not in field_map:
			return {"error": f"date_changed='{date_changed}' is not a fieldname on {document_type}"}
		if date_changed and field_map[date_changed].fieldtype not in ("Date", "Datetime"):
			return {"error": f"date_changed='{date_changed}' must be a Date or Datetime field (got {field_map[date_changed].fieldtype})"}
		if value_changed and value_changed not in field_map:
			return {"error": f"value_changed='{value_changed}' is not a fieldname on {document_type}"}
		# Recipients shape — at least one row for Email/Slack/SMS channels.
		if channel != "System Notification":
			if not isinstance(recipients, list) or not recipients:
				return {"error": f"at least one recipient row is required for channel='{channel}'"}
			for i, row in enumerate(recipients):
				if not isinstance(row, dict):
					return {"error": f"recipients[{i}] must be an object/dict"}
				keys = ("receiver_by_role", "receiver_by_document_field", "receiver")
				if not any(row.get(k) for k in keys):
					return {"error": f"recipients[{i}] needs at least one of: {', '.join(keys)}"}
				if row.get("receiver_by_role") and not frappe.db.exists("Role", row["receiver_by_role"]):
					return {"error": f"recipients[{i}].receiver_by_role='{row['receiver_by_role']}' does not exist"}
		# Condition syntax + safety.
		cond_err = _validate_frappe_expression(condition)
		if cond_err:
			return {"error": cond_err}
		token = _stage_action(
			"create_notification",
			{
				"subject": subject,
				"document_type": document_type,
				"event": event,
				"channel": channel,
				"recipients": recipients,
				"message": message,
				"condition": condition,
				"date_changed": date_changed,
				"value_changed": value_changed,
				"method": method,
				"days_in_advance": days_in_advance,
				"slack_webhook_url": slack_webhook,
				"property_value": property_value,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create Notification '{subject}' on {document_type} (event={event}, channel={channel})",
			"preview": {
				"subject": subject,
				"document_type": document_type,
				"event": event,
				"channel": channel,
				"recipient_count": len(recipients),
				"condition": condition or None,
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_auto_email_report":
		report = args.get("report")
		email_to = (args.get("email_to") or "").strip()
		frequency = args.get("frequency") or "Weekly"
		fmt = args.get("format") or "HTML"
		day_of_week = args.get("day_of_week") or ""
		description = args.get("description") or ""
		enabled = args.get("enabled")
		enabled = True if enabled is None else bool(enabled)
		if not report:
			return {"error": "report required"}
		if not email_to:
			return {"error": "email_to required (newline-separated email addresses)"}
		if not frappe.db.exists("Report", report):
			return {"error": f"Report '{report}' does not exist"}
		valid_freq = ("Daily", "Weekdays", "Weekly", "Monthly")
		if frequency not in valid_freq:
			return {"error": f"frequency must be one of: {', '.join(valid_freq)}"}
		valid_fmt = ("HTML", "XLSX", "CSV")
		if fmt not in valid_fmt:
			return {"error": f"format must be one of: {', '.join(valid_fmt)}"}
		# Re-check the user can actually read the report.
		try:
			rep = frappe.get_doc("Report", report)
			if not frappe.has_permission(rep.ref_doctype, "report"):
				return {"error": f"no report permission on {rep.ref_doctype} (the Report's ref_doctype)"}
		except Exception as e:
			return {"error": f"could not load Report/{report}: {e}"}
		if not frappe.has_permission("Auto Email Report", "create"):
			return {"error": "no create permission on Auto Email Report"}
		token = _stage_action(
			"create_auto_email_report",
			{
				"report": report,
				"email_to": email_to,
				"frequency": frequency,
				"format": fmt,
				"day_of_week": day_of_week,
				"description": description,
				"enabled": 1 if enabled else 0,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will email Report '{report}' to {len(email_to.splitlines())} address(es) {frequency.lower()}",
			"preview": {
				"report": report,
				"email_to": email_to,
				"frequency": frequency,
				"format": fmt,
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "update_notification_settings":
		# Direct (no /commit) — per-user prefs, fully reversible.
		user = frappe.session.user
		if user == "Guest":
			return {"error": "must be logged in"}
		try:
			cur = frappe.get_doc("Notification Settings", user)
		except Exception:
			# First-time accessing user — Frappe creates on demand.
			cur = frappe.get_doc({"doctype": "Notification Settings", "user": user}).insert(ignore_permissions=True)
		updatable = {"enabled", "email_message_subject_filter", "send_email_alerts", "seen"}
		updated = {}
		for k in updatable:
			if k in args:
				v = args[k]
				if isinstance(v, bool):
					v = 1 if v else 0
				cur.set(k, v)
				updated[k] = v
		if not updated:
			return {"error": f"supply at least one of: {sorted(updatable)}"}
		try:
			cur.save(ignore_permissions=False)
			frappe.db.commit()
		except Exception as e:
			return {"error": f"save failed: {type(e).__name__}: {e}"}
		return {
			"ok": True,
			"action": "update_notification_settings",
			"user": user,
			"updated_fields": updated,
		}

	if name == "prepare_create_milestone_tracker":
		dt = args.get("document_type")
		track_field = args.get("track_field")
		disabled = bool(args.get("disabled"))
		if not dt or not track_field:
			return {"error": "document_type and track_field required"}
		if not frappe.db.exists("DocType", dt):
			return {"error": f"document_type '{dt}' does not exist"}
		if not frappe.has_permission("Milestone Tracker", "create"):
			return {"error": "no create permission on Milestone Tracker"}
		try:
			meta = frappe.get_meta(dt)
		except Exception as e:
			return {"error": f"could not load meta for {dt}: {e}"}
		fld = next((df for df in meta.fields if df.fieldname == track_field), None)
		if not fld:
			return {"error": f"track_field='{track_field}' is not a fieldname on {dt}"}
		if fld.fieldtype not in ("Link", "Select"):
			return {"error": f"track_field='{track_field}' must be a Link or Select field (got {fld.fieldtype})"}
		token = _stage_action(
			"create_milestone_tracker",
			{"document_type": dt, "track_field": track_field, "disabled": 1 if disabled else 0},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will track milestones on {dt}.{track_field}",
			"preview": {"document_type": dt, "track_field": track_field, "disabled": disabled},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_auto_repeat":
		ref_dt = args.get("reference_doctype")
		ref_name = args.get("reference_document")
		frequency = args.get("frequency") or "Monthly"
		start_date = args.get("start_date")
		end_date = args.get("end_date")
		submit_on_creation = bool(args.get("submit_on_creation"))
		notify_by_email = bool(args.get("notify_by_email"))
		recipients = args.get("recipients") or ""
		if not ref_dt or not ref_name:
			return {"error": "reference_doctype and reference_document required"}
		valid_freq = ("Daily", "Weekly", "Monthly", "Quarterly", "Half-yearly", "Yearly")
		if frequency not in valid_freq:
			return {"error": f"frequency must be one of: {', '.join(valid_freq)}"}
		if not start_date:
			return {"error": "start_date required (ISO date, e.g. '2026-05-10')"}
		try:
			from frappe.utils import getdate
			sd = getdate(start_date)
		except Exception as e:
			return {"error": f"start_date is not a valid date: {e}"}
		ed = None
		if end_date:
			try:
				from frappe.utils import getdate
				ed = getdate(end_date)
			except Exception as e:
				return {"error": f"end_date is not a valid date: {e}"}
			if ed <= sd:
				return {"error": "end_date must be > start_date"}
		if not frappe.db.exists(ref_dt, ref_name):
			return {"error": f"{ref_dt} '{ref_name}' does not exist"}
		# Idempotency at preview — refuse if a non-Cancelled Auto Repeat
		# already targets this exact pair.
		dup = frappe.get_all(
			"Auto Repeat",
			filters={
				"reference_doctype": ref_dt,
				"reference_document": ref_name,
				"status": ["!=", "Cancelled"],
			},
			fields=["name", "status", "frequency"],
			limit=1,
		)
		if dup:
			return {
				"error": (
					f"Auto Repeat already exists for {ref_dt}/{ref_name} "
					f"(name={dup[0].name}, status={dup[0].status}, frequency={dup[0].frequency})."
				)
			}
		if notify_by_email and not recipients:
			return {"error": "recipients required when notify_by_email=True"}
		if not frappe.has_permission("Auto Repeat", "create"):
			return {"error": "no create permission on Auto Repeat"}
		if submit_on_creation and not frappe.has_permission(ref_dt, "submit"):
			return {"error": f"submit_on_creation=True requires submit permission on {ref_dt}"}
		token = _stage_action(
			"create_auto_repeat",
			{
				"reference_doctype": ref_dt,
				"reference_document": ref_name,
				"frequency": frequency,
				"start_date": str(sd),
				"end_date": str(ed) if ed else None,
				"submit_on_creation": 1 if submit_on_creation else 0,
				"notify_by_email": 1 if notify_by_email else 0,
				"recipients": recipients,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will Auto-Repeat {ref_dt}/{ref_name} {frequency.lower()} starting {sd}",
			"preview": {
				"reference_doctype": ref_dt,
				"reference_document": ref_name,
				"frequency": frequency,
				"start_date": str(sd),
				"end_date": str(ed) if ed else None,
				"submit_on_creation": submit_on_creation,
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_email_group":
		title = (args.get("title") or "").strip()
		description = args.get("description") or ""
		public = bool(args.get("public"))
		if not title:
			return {"error": "title required"}
		# Email Group autonames from title — refuse if the same title
		# already has a row.
		if frappe.db.exists("Email Group", {"title": title}):
			return {"error": f"Email Group with title '{title}' already exists"}
		if not frappe.has_permission("Email Group", "create"):
			return {"error": "no create permission on Email Group"}
		token = _stage_action(
			"create_email_group",
			{"title": title, "description": description, "public": 1 if public else 0},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create {'public ' if public else ''}Email Group '{title}'",
			"preview": {"title": title, "public": public},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_add_to_email_group":
		group = args.get("email_group")
		email = (args.get("email") or "").strip()
		if not group or not email:
			return {"error": "email_group and email required"}
		# Email Group autonames hash so look up by title.
		row = frappe.db.get_value("Email Group", {"title": group}, "name") if not frappe.db.exists("Email Group", group) else group
		if not row:
			return {"error": f"Email Group '{group}' not found"}
		# Cheap email well-formedness probe — a `@` somewhere with at least
		# one char on each side. Frappe's own validate_email_address kicks
		# in at insert anyway.
		if "@" not in email or email.startswith("@") or email.endswith("@"):
			return {"error": f"'{email}' does not look like a valid email address"}
		if not frappe.has_permission("Email Group Member", "create"):
			return {"error": "no create permission on Email Group Member"}
		token = _stage_action(
			"add_to_email_group",
			{"email_group": row, "email": email},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will add '{email}' to Email Group '{row}'",
			"preview": {"email_group": row, "email": email},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_newsletter":
		subject = (args.get("subject") or "").strip()
		message = args.get("message") or ""
		email_group = args.get("email_group")
		send_from = args.get("send_from") or ""
		send_unsubscribe_link = args.get("send_unsubscribe_link")
		send_unsubscribe_link = True if send_unsubscribe_link is None else bool(send_unsubscribe_link)
		if not subject:
			return {"error": "subject required"}
		if not message.strip():
			return {"error": "message (body) required"}
		if not email_group:
			return {"error": "email_group required"}
		# Email Group autonames hash; resolve by title fallback.
		group_row = email_group if frappe.db.exists("Email Group", email_group) else (
			frappe.db.get_value("Email Group", {"title": email_group}, "name") or None
		)
		if not group_row:
			return {"error": f"Email Group '{email_group}' not found"}
		if not frappe.has_permission("Newsletter", "create"):
			return {"error": "no create permission on Newsletter"}
		token = _stage_action(
			"create_newsletter",
			{
				"subject": subject,
				"message": message,
				"email_group": group_row,
				"send_from": send_from,
				"send_unsubscribe_link": 1 if send_unsubscribe_link else 0,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will draft Newsletter '{subject}' for Email Group '{group_row}' (sending is admin-driven from the Desk)",
			"preview": {
				"subject": subject,
				"email_group": group_row,
				"body_preview": (message[:300] + "…") if len(message) > 300 else message,
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	# ------------------------------------------------------------------
	# 2026-05-06 (Commit 3) — Email Account setup + Assignment Rule.
	# ------------------------------------------------------------------

	if name == "prepare_create_email_account":
		account_name = (args.get("email_account_name") or "").strip()
		email_id = (args.get("email_id") or "").strip()
		password = args.get("password") or ""
		service = args.get("service") or ""
		enable_outgoing = bool(args.get("enable_outgoing") if args.get("enable_outgoing") is not None else True)
		enable_incoming = bool(args.get("enable_incoming"))
		smtp_server = args.get("smtp_server")
		smtp_port = args.get("smtp_port")
		use_tls = bool(args.get("use_tls") if args.get("use_tls") is not None else True)
		use_ssl = bool(args.get("use_ssl"))
		email_server = args.get("email_server")
		incoming_port = args.get("incoming_port")
		use_imap = bool(args.get("use_imap") if args.get("use_imap") is not None else True)
		default_outgoing = bool(args.get("default_outgoing"))
		default_incoming = bool(args.get("default_incoming"))
		domain_name = args.get("domain_name")
		auth_method = args.get("auth_method") or "Basic"

		if not account_name:
			return {"error": "email_account_name required"}
		if not email_id or "@" not in email_id:
			return {"error": "email_id required (full mailbox address, e.g. 'noreply@acme.com')"}
		valid_services = ("", "GMail", "Outlook.com", "Sendgrid", "SparkPost", "Yahoo Mail", "Yandex.Mail", "Frappe Mail")
		if service not in valid_services:
			return {"error": f"service must be one of: {', '.join(s or '<custom>' for s in valid_services)}"}
		if auth_method not in ("Basic", "OAuth"):
			return {"error": "auth_method must be 'Basic' or 'OAuth'"}
		# Double gate: System Manager + lazychat_allow_email_setup.
		if "System Manager" not in frappe.get_roles(frappe.session.user):
			return {"error": "System Manager role required to configure Email Accounts"}
		try:
			from lazychat_mcp_erpnext.desk_assistant.boot import get_lazychat_settings as _gls
			if not _gls().get("allow_email_setup"):
				return {"error": "prepare_create_email_account is gated: enable Lazychat Settings → Allow prepare_create_email_account Tool"}
		except Exception as e:
			return {"error": f"could not read settings: {e}"}
		if not frappe.has_permission("Email Account", "create"):
			return {"error": "no create permission on Email Account"}
		# Conditional required fields.
		if enable_outgoing:
			if not smtp_server:
				return {"error": "smtp_server required when enable_outgoing=True"}
			if not smtp_port:
				return {"error": "smtp_port required when enable_outgoing=True"}
			if auth_method == "Basic" and not password:
				return {"error": "password required when enable_outgoing=True with auth_method=Basic"}
		if enable_incoming:
			if not email_server:
				return {"error": "email_server required when enable_incoming=True"}
			if not incoming_port:
				return {"error": "incoming_port required when enable_incoming=True"}
			if auth_method == "Basic" and not password:
				return {"error": "password required when enable_incoming=True with auth_method=Basic"}
		# Warn (don't refuse) if default_outgoing collides — Frappe enforces uniqueness.
		default_collision = None
		if default_outgoing:
			cur_default = frappe.db.get_value("Email Account", {"default_outgoing": 1}, "name")
			if cur_default and cur_default != account_name:
				default_collision = cur_default
		# Live SMTP/IMAP probe — never refuse staging on test failure (server may
		# be down right now, but the user might still want to stage the config).
		test_result = {"smtp": "skipped", "imap": "skipped"}
		if enable_outgoing and smtp_server and smtp_port and password and auth_method == "Basic":
			try:
				import smtplib, ssl
				if use_ssl:
					srv = smtplib.SMTP_SSL(smtp_server, int(smtp_port), timeout=8)
				else:
					srv = smtplib.SMTP(smtp_server, int(smtp_port), timeout=8)
					if use_tls:
						srv.starttls(context=ssl.create_default_context())
				srv.login(email_id, password)
				srv.quit()
				test_result["smtp"] = "ok"
			except Exception as e:
				test_result["smtp"] = f"failed: {type(e).__name__}: {str(e)[:120]}"
		if enable_incoming and email_server and incoming_port and password and auth_method == "Basic":
			try:
				if use_imap:
					import imaplib, ssl
					if use_ssl:
						srv2 = imaplib.IMAP4_SSL(email_server, int(incoming_port))
					else:
						srv2 = imaplib.IMAP4(email_server, int(incoming_port))
					srv2.login(email_id, password)
					srv2.logout()
				else:
					import poplib, ssl
					if use_ssl:
						srv2 = poplib.POP3_SSL(email_server, int(incoming_port), timeout=8)
					else:
						srv2 = poplib.POP3(email_server, int(incoming_port), timeout=8)
					srv2.user(email_id)
					srv2.pass_(password)
					srv2.quit()
				test_result["imap"] = "ok"
			except Exception as e:
				test_result["imap"] = f"failed: {type(e).__name__}: {str(e)[:120]}"
		token = _stage_action(
			"create_email_account",
			{
				"email_account_name": account_name,
				"email_id": email_id,
				"password": password,
				"service": service,
				"enable_outgoing": 1 if enable_outgoing else 0,
				"smtp_server": smtp_server,
				"smtp_port": smtp_port,
				"use_tls": 1 if use_tls else 0,
				"use_ssl": 1 if use_ssl else 0,
				"enable_incoming": 1 if enable_incoming else 0,
				"email_server": email_server,
				"incoming_port": incoming_port,
				"use_imap": 1 if use_imap else 0,
				"default_outgoing": 1 if default_outgoing else 0,
				"default_incoming": 1 if default_incoming else 0,
				"domain_name": domain_name,
				"auth_method": auth_method,
			},
		)
		summary_bits = []
		if enable_outgoing:
			summary_bits.append(f"SMTP {smtp_server}:{smtp_port} ({test_result['smtp']})")
		if enable_incoming:
			summary_bits.append(f"{'IMAP' if use_imap else 'POP3'} {email_server}:{incoming_port} ({test_result['imap']})")
		preview = {
			"email_account_name": account_name,
			"email_id": email_id,
			"service": service or "<custom>",
			"enable_outgoing": enable_outgoing,
			"enable_incoming": enable_incoming,
			"test_result": test_result,
		}
		if default_collision:
			preview["default_outgoing_collision"] = (
				f"Email Account '{default_collision}' is currently default_outgoing — committing this will REPLACE it."
			)
		if domain_name:
			preview["domain_name"] = domain_name
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create Email Account '{account_name}' for {email_id}" + (f" — {'; '.join(summary_bits)}" if summary_bits else ""),
			"preview": preview,
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_assignment_rule":
		rule_name = (args.get("name") or "").strip()
		document_type = args.get("document_type")
		rule = args.get("rule") or "Round Robin"
		users = args.get("users") or []
		field = args.get("field")
		assign_condition = args.get("assign_condition") or ""
		unassign_condition = args.get("unassign_condition") or ""
		due_date_based_on = args.get("due_date_based_on")
		priority = args.get("priority")
		description = args.get("description") or ""
		disabled = bool(args.get("disabled"))

		if not rule_name:
			return {"error": "name required"}
		if not document_type:
			return {"error": "document_type required"}
		valid_rules = ("Round Robin", "Load Balancing", "Based on Field")
		if rule not in valid_rules:
			return {"error": f"rule must be one of: {', '.join(valid_rules)}"}
		if not isinstance(users, list) or not users:
			return {"error": "users required (non-empty list of User names)"}
		if not frappe.db.exists("DocType", document_type):
			return {"error": f"document_type '{document_type}' does not exist"}
		if not frappe.has_permission("Assignment Rule", "create"):
			return {"error": "no create permission on Assignment Rule"}
		# Role gate — Notification Manager OR System Manager.
		caller_roles = frappe.get_roles(frappe.session.user)
		if not ({"Notification Manager", "System Manager"} & set(caller_roles)):
			return {"error": "Assignment Rule create requires 'Notification Manager' or 'System Manager' role"}
		# Existential check on each user.
		for u in users:
			if not frappe.db.exists("User", u):
				return {"error": f"user '{u}' does not exist"}
		# rule=Based on Field requires `field` to be a Link to User on document_type.
		try:
			meta = frappe.get_meta(document_type)
		except Exception as e:
			return {"error": f"could not load meta for {document_type}: {e}"}
		field_map = {df.fieldname: df for df in meta.fields}
		if rule == "Based on Field":
			if not field:
				return {"error": "field required when rule='Based on Field'"}
			if field not in field_map:
				return {"error": f"field='{field}' is not a fieldname on {document_type}"}
			if field_map[field].fieldtype != "Link" or field_map[field].options != "User":
				return {"error": f"field='{field}' must be a Link field pointing to User (got fieldtype={field_map[field].fieldtype}, options={field_map[field].options})"}
		# due_date_based_on must be a Date/Datetime fieldname on document_type.
		if due_date_based_on:
			if due_date_based_on not in field_map:
				return {"error": f"due_date_based_on='{due_date_based_on}' is not a fieldname on {document_type}"}
			if field_map[due_date_based_on].fieldtype not in ("Date", "Datetime"):
				return {"error": f"due_date_based_on='{due_date_based_on}' must be Date or Datetime (got {field_map[due_date_based_on].fieldtype})"}
		# Conditions go through the shared Frappe-expression validator.
		err = _validate_frappe_expression(assign_condition)
		if err:
			return {"error": f"assign_condition: {err}"}
		err = _validate_frappe_expression(unassign_condition)
		if err:
			return {"error": f"unassign_condition: {err}"}
		token = _stage_action(
			"create_assignment_rule",
			{
				"name": rule_name,
				"document_type": document_type,
				"rule": rule,
				"users": users,
				"field": field,
				"assign_condition": assign_condition,
				"unassign_condition": unassign_condition,
				"due_date_based_on": due_date_based_on,
				"priority": int(priority) if priority not in (None, "") else 0,
				"description": description,
				"disabled": 1 if disabled else 0,
			},
		)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will create {rule} Assignment Rule '{rule_name}' on {document_type} ({len(users)} user(s))",
			"preview": {
				"name": rule_name,
				"document_type": document_type,
				"rule": rule,
				"users": users,
				"field": field,
				"assign_condition": assign_condition or None,
				"open_url": f"/app/assignment-rule/{rule_name}",
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	# Build-page typed wrappers (added 2026-05-07): Custom Field + Client Script.
	# Same shape as the Cycle 6 Report wrapper — validate doctype-specific fields
	# at preview time so the model gets actionable errors in the same turn instead
	# of a confusing /commit failure.
	if name == "prepare_create_custom_field":
		dt = args.get("dt")
		label = (args.get("label") or "").strip()
		fieldtype = args.get("fieldtype") or "Data"
		insert_after = args.get("insert_after") or ""
		fieldname = (args.get("fieldname") or "").strip()
		if not dt:
			return {"error": "dt required (target DocType to attach the field to)"}
		if not label:
			return {"error": "label required"}
		if not insert_after:
			return {"error": "insert_after required (existing fieldname on dt, or 'append')"}
		valid_types = {
			"Data", "Int", "Float", "Currency", "Percent", "Check", "Select", "Link",
			"Dynamic Link", "Date", "Datetime", "Time", "Duration", "Small Text",
			"Long Text", "Text", "Text Editor", "Markdown Editor", "HTML", "HTML Editor",
			"Code", "JSON", "Password", "Phone", "Color", "Rating", "Geolocation",
			"Barcode", "Signature", "Image", "Attach", "Attach Image", "Autocomplete",
			"Read Only", "Section Break", "Column Break", "Tab Break", "Heading",
			"Fold", "Icon", "Table", "Table MultiSelect", "Button",
		}
		if fieldtype not in valid_types:
			return {"error": f"fieldtype must be one of the 43 Frappe fieldtypes (got {fieldtype!r})"}
		if not frappe.db.exists("DocType", dt):
			return {"error": f"DocType '{dt}' does not exist"}
		# System Manager gate — Custom Field is a powerful customization that
		# changes the schema. Mirrors prepare_create_scheduled_job pattern.
		if "System Manager" not in frappe.get_roles(frappe.session.user):
			return {"error": "System Manager role required to create custom fields"}
		if not frappe.has_permission("Custom Field", "create"):
			return {"error": "no create permission on Custom Field"}
		try:
			meta = frappe.get_meta(dt)
		except Exception as e:
			return {"error": f"could not load meta for {dt}: {e}"}
		fieldnames = [df.fieldname for df in meta.get("fields") or []]
		if insert_after != "append" and insert_after not in fieldnames:
			return {"error": f"insert_after '{insert_after}' is not a fieldname on {dt}. Valid: {fieldnames[:20]}…"}
		if fieldname and fieldname in fieldnames:
			return {"error": f"fieldname '{fieldname}' already exists on {dt}"}
		# Link/Table-flavored fields need `options` (target doctype / source field).
		if fieldtype in ("Link", "Table", "Table MultiSelect", "Dynamic Link") and not args.get("options"):
			return {"error": f"fieldtype={fieldtype} requires `options` (target DocType for Link/Table; source field for Dynamic Link)"}
		payload = {
			"dt": dt,
			"label": label,
			"fieldtype": fieldtype,
			"insert_after": insert_after,
			"fieldname": fieldname,
			"options": args.get("options") or "",
			"default": args.get("default") or "",
			"reqd": int(bool(args.get("reqd"))),
			"unique": int(bool(args.get("unique"))),
			"read_only": int(bool(args.get("read_only"))),
			"hidden": int(bool(args.get("hidden"))),
			"description": args.get("description") or "",
		}
		token = _stage_action("create_custom_field", payload)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will add Custom Field '{label}' ({fieldtype}) on {dt} after `{insert_after}`",
			"preview": {**payload, "open_url": f"/app/customize-form?doc_type={dt}"},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "prepare_create_client_script":
		dt = args.get("dt")
		view = args.get("view") or "Form"
		script = args.get("script") or ""
		enabled_raw = args.get("enabled")
		# Default enabled=1 when omitted; honor explicit 0/false/"0".
		if enabled_raw in (None, ""):
			enabled = 1
		else:
			enabled = 1 if enabled_raw in (1, "1", True, "true", "True") else 0
		cs_name = (args.get("name") or "").strip()
		if not dt:
			return {"error": "dt required (target DocType)"}
		if not script.strip():
			return {"error": "script required (non-empty JS source)"}
		if view not in ("Form", "List"):
			return {"error": "view must be 'Form' or 'List'"}
		if not frappe.db.exists("DocType", dt):
			return {"error": f"DocType '{dt}' does not exist"}
		if "System Manager" not in frappe.get_roles(frappe.session.user):
			return {"error": "System Manager role required to create client scripts"}
		if not frappe.has_permission("Client Script", "create"):
			return {"error": "no create permission on Client Script"}
		payload = {"dt": dt, "view": view, "script": script, "enabled": enabled, "name": cs_name}
		token = _stage_action("create_client_script", payload)
		return {
			"ok": True,
			"preview_token": token,
			"summary": f"Will add Client Script ({view}) on {dt} ({len(script)} chars{' — disabled' if not enabled else ''})",
			"preview": {
				"dt": dt,
				"view": view,
				"enabled": enabled,
				"script_preview": script[:300] + ("…" if len(script) > 300 else ""),
				"open_url": "/app/client-script",
			},
			"expires_in_sec": PREP_TTL_SEC,
			"confirm_with": "click the inline Apply button to confirm",
		}

	if name == "restore_deleted_doc":
		# Direct (no /commit) — restoring is single-doc, fully reversible.
		dd_name = args.get("deleted_document_name")
		if not dd_name:
			return {"error": "deleted_document_name required"}
		if not frappe.db.exists("Deleted Document", dd_name):
			return {"error": f"Deleted Document '{dd_name}' not found"}
		try:
			dd = frappe.get_doc("Deleted Document", dd_name)
		except Exception as e:
			return {"error": f"could not load Deleted Document/{dd_name}: {e}"}
		original_dt = dd.deleted_doctype
		original_name = dd.deleted_name
		# Re-check the user has create permission on the original doctype —
		# restore is effectively a re-insert, and the permission model treats
		# it that way.
		if not frappe.has_permission(original_dt, "create"):
			return {"error": f"no create permission on {original_dt} — cannot restore"}
		try:
			from frappe.desk.doctype.deleted_document.deleted_document import restore as _restore
			_restore(dd_name)
			frappe.db.commit()
		except Exception as e:
			return {"error": f"restore failed: {type(e).__name__}: {e}"}
		return {
			"ok": True,
			"action": "restore",
			"doctype": original_dt,
			"name": original_name,
			"link": f"/app/{frappe.scrub(original_dt)}/{original_name}",
		}

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


def commit_prepared(token, **extras):
	"""Execute a previously staged action. Called by /commit slash command, NOT by the LLM.

	`extras` carries action-specific runtime parameters that arrive at commit
	time but weren't known at prepare time:
	  - attach_file: extras['file_url'] from the panel shim's /upload flow
	  - export_csv: extras['fields'] from the field-picker UI
	"""
	obj = _retrieve_action(token)
	if not obj:
		return {"ok": False, "error": "Token not found, expired, or not yours"}
	action = obj["action"]
	payload = obj["payload"]
	sp_name = "lazychat_commit"
	# Stash a place for handlers to drop extra response fields (e.g.
	# export_csv returns the file_url + row_count + selected fields).
	frappe.local.flags.lazychat_commit_extras = None
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
			# Run; cap rows by re-querying with explicit limit. Inner try/except
			# converts DB errors (e.g. "Unknown column 'pr.purchase_order'") into
			# a structured response with a self-correction hint, so the agent
			# loop can recover on the next turn instead of dead-ending.
			try:
				rows = frappe.db.sql(query, as_dict=True)
			except Exception as e:
				return _wrap_db_error(e, query, action="run_sql")
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
				# Detect DB errors (pymysql.OperationalError + frappe wrappers
				# typically include the numeric MySQL code in the message). For
				# those, route through _wrap_db_error so the LLM gets the same
				# self-correction hint as run_sql. Other Python errors fall
				# through to the original opaque shape.
				_msg = str(e)
				if (
					"OperationalError" in type(e).__name__
					or "ProgrammingError" in type(e).__name__
					or "1054" in _msg
					or "1064" in _msg
					or "1146" in _msg
				):
					wrapped = _wrap_db_error(e, code, action="run_python")
					wrapped["stdout"] = buf.getvalue()[:8000]
					return wrapped
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
		elif action == "create_kb":
			if not frappe.has_permission("Lazychat Knowledge Base", "create"):
				return {"ok": False, "error": "no permission at commit time"}
			kb_doc = frappe.get_doc({
				"doctype": "Lazychat Knowledge Base",
				"kb_name": payload["kb_name"],
				"title": payload["title"],
				"description": payload.get("description") or "",
				"enabled": 1,
				"is_public": payload.get("is_public", 0),
			}).insert(ignore_permissions=False)
			doc = kb_doc
		elif action == "attach_file":
			# Tier B-upload commit. Caller passes file_url alongside the token
			# (panel shim's /upload command does this after the upload_file POST).
			file_url = (extras.get("file_url") or "").strip()
			if not file_url:
				return {"ok": False, "error": "file_url required (panel shim's /upload should pass this)"}
			if not frappe.has_permission(payload["target_doctype"], "write", doc=payload["target_name"]):
				return {"ok": False, "error": "no write permission at commit time"}
			matches = frappe.get_all("File", filters={"file_url": file_url}, fields=["name"], limit=1)
			if not matches:
				return {"ok": False, "error": f"uploaded file not found by url: {file_url}"}
			file_doc = frappe.get_doc("File", matches[0]["name"])
			file_doc.attached_to_doctype = payload["target_doctype"]
			file_doc.attached_to_name = payload["target_name"]
			file_doc.save(ignore_permissions=False)
			class _R:
				pass
			doc = _R()
			doc.doctype = payload["target_doctype"]
			doc.name = payload["target_name"]
		elif action == "import_csv":
			# Tier C-import commit. Creates a Frappe Data Import doctype row
			# and kicks off start_import() — same path as the Desk's Data
			# Import wizard. The job runs async via Frappe's background queue;
			# the user can watch progress via list_my_jobs.
			ok2, gate_err2 = _dangerous_tools_enabled()
			if not ok2:
				return {"ok": False, "error": gate_err2}
			if not frappe.has_permission("Data Import", "create"):
				return {"ok": False, "error": "no permission to create Data Import"}
			data_import = frappe.get_doc({
				"doctype": "Data Import",
				"reference_doctype": payload["reference_doctype"],
				"import_type": payload["import_type"],
				"import_file": payload["file_url"],
				"submit_after_import": 0,
				"mute_emails": 1,
			}).insert(ignore_permissions=False)
			# start_import enqueues the actual row inserts as a background job
			try:
				data_import.start_import()
			except Exception as e:
				# Preserve the row so the user can inspect via Desk
				return {"ok": False, "error": f"start_import failed: {e}", "data_import": data_import.name}
			doc = data_import
		elif action == "export_csv":
			# Tier G commit — caller passes selected fields[] alongside the
			# token after picking columns in the field-picker UI. We re-use
			# the same CSV-write logic as the direct export_list_to_csv path.
			selected = extras.get("fields") or []
			if isinstance(selected, str):
				selected = [s.strip() for s in selected.split(",") if s.strip()]
			if not isinstance(selected, list) or not selected:
				return {"ok": False, "error": "fields[] required from the picker"}
			if not all(isinstance(f, str) for f in selected):
				return {"ok": False, "error": "fields must be a list of strings"}
			dt = payload["doctype"]
			if not frappe.has_permission(dt, "read"):
				return {"ok": False, "error": "no read permission at commit time"}
			try:
				import csv as _csv
				rows = frappe.get_list(dt, filters=payload.get("filters") or {}, fields=selected, limit_page_length=payload.get("limit") or 1000)
				buf = io.StringIO()
				writer = _csv.DictWriter(buf, fieldnames=selected)
				writer.writeheader()
				for r in rows:
					writer.writerow({f: ("" if r.get(f) is None else str(r.get(f))) for f in selected})
				ts = frappe.utils.now_datetime().strftime("%Y-%m-%d-%H%M%S")
				fname = f"{frappe.scrub(dt)}-{ts}.csv"
				file_doc = frappe.get_doc({
					"doctype": "File",
					"file_name": fname,
					"is_private": 1,
					"content": buf.getvalue().encode("utf-8"),
				}).insert(ignore_permissions=False)
				class _R:
					pass
				doc = _R()
				doc.doctype = "File"
				doc.name = file_doc.name
				# Stash the URL so commit_prepared returns it in the result
				_export_csv_result = {
					"ok": True,
					"file_url": file_doc.file_url,
					"absolute_url": _frappe_get_url(file_doc.file_url),
					"file_name": fname,
					"row_count": len(rows),
					"fields": selected,
				}
				# We'll merge this into the response below
				frappe.local.flags.lazychat_commit_extras = _export_csv_result
			except Exception as e:
				return {"ok": False, "error": f"export failed: {e}"}
		elif action == "add_file_to_kb":
			if not frappe.has_permission("Lazychat Knowledge Base", "write", doc=payload["kb_name"]):
				return {"ok": False, "error": "no permission on KB at commit time"}
			file_doc = frappe.get_doc("File", payload["file_name"])
			file_doc.attached_to_doctype = "Lazychat Knowledge Base"
			file_doc.attached_to_name = payload["kb_name"]
			file_doc.save(ignore_permissions=False)
			class _R:
				pass
			doc = _R()
			doc.doctype = "Lazychat Knowledge Base"
			doc.name = payload["kb_name"]
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
		elif action == "create_report":
			if not frappe.has_permission("Report", "create"):
				return {"ok": False, "error": "no create permission on Report at commit time"}
			ref_dt = payload["ref_doctype"]
			if not frappe.has_permission(ref_dt, "report"):
				return {"ok": False, "error": f"no report permission on {ref_dt} at commit time"}
			rep_values = {
				"doctype": "Report",
				"report_name": payload["report_name"],
				"ref_doctype": ref_dt,
				"report_type": payload["report_type"],
				"is_standard": "No",
			}
			if payload["report_type"] == "Query Report":
				rep_values["query"] = payload["query"]
			if payload["report_type"] == "Script Report":
				# Refuse at commit too — defense-in-depth against payload tampering.
				body = (payload.get("script") or "").strip()
				if not body:
					return {"ok": False, "error": "Script Report payload missing `script` body at commit"}
				rep_values["report_script"] = body
				rep_values["script_type"] = "Python"
			# Re-validate Query Report SQL at commit time — the staging machinery
			# already validated it, but defense-in-depth is cheap.
			if rep_values.get("query"):
				err = _validate_select_sql(rep_values["query"])
				if err:
					return {"ok": False, "error": f"query failed validation at commit: {err}"}
				probe_err = _probe_select_sql_explain(rep_values["query"])
				if probe_err:
					return {"ok": False, "error": f"query failed EXPLAIN at commit: {probe_err}"}
			doc = frappe.get_doc(rep_values).insert(ignore_permissions=False)
			# Persist columns / filters as JSON on the report's `json` field
			# (Report Builder convention) when supplied. Query Report renders
			# columns from the SELECT itself.
			if payload.get("columns") or payload.get("filters"):
				doc.json = json.dumps({
					"columns": payload.get("columns") or [],
					"filters": payload.get("filters") or {},
				})
				doc.save(ignore_permissions=False)
		elif action == "create_scheduled_job":
			if "System Manager" not in frappe.get_roles(frappe.session.user):
				return {"ok": False, "error": "System Manager role required to schedule jobs"}
			if not frappe.has_permission("Scheduled Job Type", "create"):
				return {"ok": False, "error": "no create permission on Scheduled Job Type at commit time"}
			values = {
				"doctype": "Scheduled Job Type",
				"method": payload["method"],
				"frequency": payload["frequency"],
			}
			if payload.get("cron_format"):
				values["cron_format"] = payload["cron_format"]
			doc = frappe.get_doc(values).insert(ignore_permissions=False)
		elif action == "create_number_card":
			if not frappe.has_permission("Number Card", "create"):
				return {"ok": False, "error": "no create permission on Number Card at commit time"}
			if not frappe.has_permission(payload["doctype"], "read"):
				return {"ok": False, "error": f"no read permission on {payload['doctype']} at commit time"}
			values = {
				"doctype": "Number Card",
				"label": payload["label"],
				"document_type": payload["doctype"],
				"function": payload["function"],
				"filters_json": payload.get("filters_json") or "[]",
				"is_public": 0,
			}
			if payload.get("aggregate_function_based_on"):
				values["aggregate_function_based_on"] = payload["aggregate_function_based_on"]
			if payload.get("color"):
				values["color"] = payload["color"]
			doc = frappe.get_doc(values).insert(ignore_permissions=False)
		elif action == "create_dashboard":
			if not frappe.has_permission("Dashboard", "create"):
				return {"ok": False, "error": "no create permission on Dashboard at commit time"}
			values = {
				"doctype": "Dashboard",
				"dashboard_name": payload["dashboard_name"],
				"is_standard": 0,
			}
			if payload.get("module"):
				values["module"] = payload["module"]
			doc = frappe.get_doc(values)
			for c in payload.get("charts") or []:
				cname = c.get("chart") if isinstance(c, dict) else c
				width = (c.get("width") if isinstance(c, dict) else None) or "Half"
				doc.append("charts", {"chart": cname, "width": width})
			for c in payload.get("cards") or []:
				cname = c.get("card") if isinstance(c, dict) else c
				width = (c.get("width") if isinstance(c, dict) else None) or "Half"
				doc.append("cards", {"card": cname, "width": width})
			doc.insert(ignore_permissions=False)
		elif action == "create_calendar_event":
			if not frappe.has_permission("Event", "create"):
				return {"ok": False, "error": "no create permission on Event at commit time"}
			values = {
				"doctype": "Event",
				"subject": payload["subject"],
				"starts_on": payload["starts_on"],
				"all_day": payload.get("all_day") or 0,
				"event_type": payload["event_type"],
				"description": payload.get("description") or "",
			}
			if payload.get("ends_on"):
				values["ends_on"] = payload["ends_on"]
			if payload.get("repeat_this_event"):
				values["repeat_this_event"] = 1
				values["repeat_on"] = payload.get("repeat_on")
			doc = frappe.get_doc(values)
			for p in payload.get("participants") or []:
				if not isinstance(p, dict):
					continue
				ref_dt = p.get("reference_doctype")
				ref_name = p.get("reference_docname") or p.get("reference_name")
				if ref_dt and ref_name:
					doc.append("event_participants", {"reference_doctype": ref_dt, "reference_docname": ref_name})
			doc.insert(ignore_permissions=False)
		elif action == "create_note":
			if not frappe.has_permission("Note", "create"):
				return {"ok": False, "error": "no create permission on Note at commit time"}
			doc = frappe.get_doc({
				"doctype": "Note",
				"title": payload["title"],
				"content": payload["content"],
				"public": payload.get("public") or 0,
			}).insert(ignore_permissions=False)
		elif action == "bulk_update":
			dt = payload["doctype"]
			filters = payload.get("filters") or {}
			patch = payload.get("patch") or {}
			if not frappe.has_permission(dt, "write"):
				return {"ok": False, "error": f"no write permission on {dt} at commit time"}
			# Re-check the dangerous-tools gate at commit (admin may have flipped it off).
			ok2, err2 = _dangerous_tools_enabled()
			if not ok2:
				return {"ok": False, "error": err2}
			# Time-sensitive recheck: refuse if the matched-row count grew >1.5×
			# since prepare-time (data flooded in during the 5-min preview window).
			at_prepare = int(payload.get("affected_count_at_prepare") or 0)
			try:
				now_count = frappe.db.count(dt, filters=filters)
			except Exception as e:
				return {"ok": False, "error": f"recount failed: {e}"}
			if at_prepare and now_count > int(at_prepare * 1.5):
				return {
					"ok": False,
					"error": (
						f"matched docs grew from {at_prepare} to {now_count} since preview — "
						f"re-stage prepare_bulk_update for safety."
					),
				}
			rows = frappe.get_all(dt, filters=filters, pluck="name")
			updated = []
			for n in rows:
				try:
					d = frappe.get_doc(dt, n)
					for f, v in patch.items():
						d.set(f, v)
					d.save(ignore_permissions=False)
					updated.append(n)
				except Exception as e:
					frappe.local.flags.lazychat_commit_extras = {
						"updated_count": len(updated),
						"failed_at": n,
						"failed_error": str(e),
						"updated_names": updated[:20],
					}
					# Stop on first failure so the savepoint rollback covers it cleanly.
					raise
			frappe.local.flags.lazychat_commit_extras = {
				"updated_count": len(updated),
				"updated_names": updated[:20],
			}
			# Synthesize a "doc" so the response shape matches.
			class _R:
				doctype = dt
				name = f"{len(updated)} {dt}(s)"
			doc = _R()
		elif action == "download_backup":
			if "System Manager" not in frappe.get_roles(frappe.session.user):
				return {"ok": False, "error": "System Manager role required to trigger a backup"}
			from frappe.utils.background_jobs import enqueue
			job = enqueue(
				"frappe.utils.backups.scheduled_backup",
				queue="long",
				timeout=3600,
				ignore_files=not bool(payload.get("with_files")),
				now=False,
				user=frappe.session.user,
			)
			job_id = getattr(job, "id", None) or getattr(job, "get_id", lambda: None)()
			frappe.local.flags.lazychat_commit_extras = {
				"job_id": job_id,
				"hint": "Poll progress with list_my_jobs; backups land under /sites/<site>/private/backups/.",
			}
			class _R:
				doctype = "Backup"
				name = job_id or "queued"
			doc = _R()
		elif action == "create_print_format":
			if not frappe.has_permission("Print Format", "create"):
				return {"ok": False, "error": "no create permission on Print Format at commit time"}
			if not frappe.has_permission(payload["doc_type"], "print"):
				return {"ok": False, "error": f"no print permission on {payload['doc_type']} at commit time"}
			values = {
				"doctype": "Print Format",
				"name": payload["name"],
				"doc_type": payload["doc_type"],
				"print_format_type": payload["print_format_type"],
				"standard": payload.get("standard") or "No",
			}
			if payload["print_format_type"] == "Jinja":
				values["html"] = payload.get("html") or ""
			else:
				values["format_data"] = payload.get("format_data") or ""
			doc = frappe.get_doc(values).insert(ignore_permissions=False)
		elif action == "update_print_settings":
			if "System Manager" not in frappe.get_roles(frappe.session.user):
				return {"ok": False, "error": "System Manager role required to update Print Settings"}
			cur = frappe.get_single("Print Settings")
			for f, v in (payload.get("patch") or {}).items():
				cur.set(f, v)
			cur.save(ignore_permissions=False)
			doc = cur
		elif action == "create_email_template":
			if not frappe.has_permission("Email Template", "create"):
				return {"ok": False, "error": "no create permission on Email Template at commit time"}
			doc = frappe.get_doc({
				"doctype": "Email Template",
				"name": payload["name"],
				"subject": payload["subject"],
				"response": payload["response"],
				"use_html": payload.get("use_html") or 0,
			}).insert(ignore_permissions=False)
		elif action == "create_notification":
			if not frappe.has_permission("Notification", "create"):
				return {"ok": False, "error": "no create permission on Notification at commit time"}
			values = {
				"doctype": "Notification",
				"subject": payload["subject"],
				"document_type": payload["document_type"],
				"event": payload["event"],
				"channel": payload["channel"],
				"message": payload.get("message") or "",
				"condition": payload.get("condition") or "",
			}
			for k in ("date_changed", "value_changed", "method", "days_in_advance", "slack_webhook_url", "property_value"):
				if payload.get(k) is not None:
					values[k] = payload[k]
			doc = frappe.get_doc(values)
			for r in payload.get("recipients") or []:
				if isinstance(r, dict):
					doc.append("recipients", {
						k: r.get(k) for k in (
							"receiver_by_role", "receiver_by_document_field",
							"receiver", "cc", "bcc",
						) if r.get(k)
					})
			doc.insert(ignore_permissions=False)
		elif action == "create_auto_email_report":
			if not frappe.has_permission("Auto Email Report", "create"):
				return {"ok": False, "error": "no create permission on Auto Email Report at commit time"}
			rep = frappe.get_doc("Report", payload["report"])
			if not frappe.has_permission(rep.ref_doctype, "report"):
				return {"ok": False, "error": f"no report permission on {rep.ref_doctype} at commit time"}
			values = {
				"doctype": "Auto Email Report",
				"report": payload["report"],
				"email_to": payload["email_to"],
				"frequency": payload["frequency"],
				"format": payload["format"],
				"description": payload.get("description") or "",
				"enabled": payload.get("enabled") or 0,
			}
			if payload.get("day_of_week"):
				values["day_of_week"] = payload["day_of_week"]
			doc = frappe.get_doc(values).insert(ignore_permissions=False)
		elif action == "create_milestone_tracker":
			if not frappe.has_permission("Milestone Tracker", "create"):
				return {"ok": False, "error": "no create permission on Milestone Tracker at commit time"}
			doc = frappe.get_doc({
				"doctype": "Milestone Tracker",
				"document_type": payload["document_type"],
				"track_field": payload["track_field"],
				"disabled": payload.get("disabled") or 0,
			}).insert(ignore_permissions=False)
		elif action == "create_auto_repeat":
			if not frappe.has_permission("Auto Repeat", "create"):
				return {"ok": False, "error": "no create permission on Auto Repeat at commit time"}
			# Re-check the duplicate guard at commit — a token created
			# in one preview might land after a sibling has filled the slot.
			dup = frappe.get_all(
				"Auto Repeat",
				filters={
					"reference_doctype": payload["reference_doctype"],
					"reference_document": payload["reference_document"],
					"status": ["!=", "Cancelled"],
				},
				limit=1,
			)
			if dup:
				return {
					"ok": False,
					"error": f"Auto Repeat already exists for {payload['reference_doctype']}/{payload['reference_document']} (race with another preview).",
				}
			values = {
				"doctype": "Auto Repeat",
				"reference_doctype": payload["reference_doctype"],
				"reference_document": payload["reference_document"],
				"frequency": payload["frequency"],
				"start_date": payload["start_date"],
				"submit_on_creation": payload.get("submit_on_creation") or 0,
				"notify_by_email": payload.get("notify_by_email") or 0,
			}
			if payload.get("end_date"):
				values["end_date"] = payload["end_date"]
			if payload.get("recipients"):
				values["recipients"] = payload["recipients"]
			doc = frappe.get_doc(values).insert(ignore_permissions=False)
		elif action == "create_email_group":
			if not frappe.has_permission("Email Group", "create"):
				return {"ok": False, "error": "no create permission on Email Group at commit time"}
			# Idempotency at commit — title may have been claimed in the
			# 5-min preview window.
			if frappe.db.exists("Email Group", {"title": payload["title"]}):
				return {"ok": False, "error": f"Email Group with title '{payload['title']}' already exists"}
			doc = frappe.get_doc({
				"doctype": "Email Group",
				"title": payload["title"],
				"description": payload.get("description") or "",
				"public": payload.get("public") or 0,
			}).insert(ignore_permissions=False)
		elif action == "add_to_email_group":
			if not frappe.has_permission("Email Group Member", "create"):
				return {"ok": False, "error": "no create permission on Email Group Member at commit time"}
			# Idempotent — existing membership is a graceful no-op.
			existing = frappe.db.exists(
				"Email Group Member",
				{"email_group": payload["email_group"], "email": payload["email"]},
			)
			if existing:
				class _R:
					doctype = "Email Group Member"
					name = existing
				doc = _R()
			else:
				doc = frappe.get_doc({
					"doctype": "Email Group Member",
					"email_group": payload["email_group"],
					"email": payload["email"],
				}).insert(ignore_permissions=False)
		elif action == "create_newsletter":
			if not frappe.has_permission("Newsletter", "create"):
				return {"ok": False, "error": "no create permission on Newsletter at commit time"}
			values = {
				"doctype": "Newsletter",
				"subject": payload["subject"],
				"message": payload["message"],
				"send_unsubscribe_link": payload.get("send_unsubscribe_link") or 0,
			}
			if payload.get("send_from"):
				values["send_from"] = payload["send_from"]
			doc = frappe.get_doc(values)
			# Newsletter's email_group is a child table.
			doc.append("email_group", {"email_group": payload["email_group"]})
			doc.insert(ignore_permissions=False)
		elif action == "create_email_account":
			# Re-check both gates at commit (admin may have flipped flag off).
			if "System Manager" not in frappe.get_roles(frappe.session.user):
				return {"ok": False, "error": "System Manager role required to configure Email Accounts"}
			from lazychat_mcp_erpnext.desk_assistant.boot import get_lazychat_settings as _gls
			if not _gls().get("allow_email_setup"):
				return {"ok": False, "error": "allow_email_setup flag is now off"}
			if not frappe.has_permission("Email Account", "create"):
				return {"ok": False, "error": "no create permission on Email Account at commit time"}
			# Idempotent Email Domain create when domain_name supplied.
			if payload.get("domain_name"):
				dn = payload["domain_name"]
				if not frappe.db.exists("Email Domain", dn):
					try:
						frappe.get_doc({
							"doctype": "Email Domain",
							"domain_name": dn,
							"email_server": payload.get("email_server") or "",
							"smtp_server": payload.get("smtp_server") or "",
							"smtp_port": payload.get("smtp_port") or "",
							"use_tls": payload.get("use_tls") or 0,
							"use_ssl": payload.get("use_ssl") or 0,
							"use_imap": payload.get("use_imap") or 0,
							"incoming_port": payload.get("incoming_port") or "",
						}).insert(ignore_permissions=False)
					except Exception as e:
						# Domain creation is best-effort — don't fail the whole flow if it conflicts.
						frappe.local.flags.lazychat_commit_extras = {"email_domain_warning": f"Email Domain '{dn}' insert failed: {type(e).__name__}: {e}"}
			values = {
				"doctype": "Email Account",
				"email_account_name": payload["email_account_name"],
				"email_id": payload["email_id"],
				"password": payload.get("password") or "",
				"enable_outgoing": payload.get("enable_outgoing") or 0,
				"enable_incoming": payload.get("enable_incoming") or 0,
				"use_tls": payload.get("use_tls") or 0,
				"use_ssl": payload.get("use_ssl") or 0,
				"use_imap": payload.get("use_imap") or 0,
				"default_outgoing": payload.get("default_outgoing") or 0,
				"default_incoming": payload.get("default_incoming") or 0,
				"auth_method": payload.get("auth_method") or "Basic",
			}
			for k in ("service", "smtp_server", "smtp_port", "email_server", "incoming_port", "domain_name"):
				if payload.get(k):
					values[k] = payload[k]
			doc = frappe.get_doc(values).insert(ignore_permissions=False)
		elif action == "create_assignment_rule":
			if not frappe.has_permission("Assignment Rule", "create"):
				return {"ok": False, "error": "no create permission on Assignment Rule at commit time"}
			caller_roles = frappe.get_roles(frappe.session.user)
			if not ({"Notification Manager", "System Manager"} & set(caller_roles)):
				return {"ok": False, "error": "Assignment Rule create requires 'Notification Manager' or 'System Manager' role"}
			values = {
				"doctype": "Assignment Rule",
				"name": payload["name"],
				"document_type": payload["document_type"],
				"rule": payload["rule"],
				"priority": payload.get("priority") or 0,
				"disabled": payload.get("disabled") or 0,
				"description": payload.get("description") or "",
			}
			for k in ("field", "assign_condition", "unassign_condition", "due_date_based_on"):
				if payload.get(k):
					values[k] = payload[k]
			doc = frappe.get_doc(values)
			for u in payload.get("users") or []:
				doc.append("users", {"user": u})
			doc.insert(ignore_permissions=False)
		elif action == "create_custom_field":
			if "System Manager" not in frappe.get_roles(frappe.session.user):
				return {"ok": False, "error": "System Manager role required at commit time"}
			if not frappe.has_permission("Custom Field", "create"):
				return {"ok": False, "error": "no create permission on Custom Field at commit time"}
			if not frappe.db.exists("DocType", payload["dt"]):
				return {"ok": False, "error": f"DocType '{payload['dt']}' no longer exists"}
			values = {
				"doctype": "Custom Field",
				"dt": payload["dt"],
				"label": payload["label"],
				"fieldtype": payload["fieldtype"],
				"insert_after": payload["insert_after"],
			}
			for k in ("fieldname", "options", "default", "description"):
				if payload.get(k):
					values[k] = payload[k]
			for k in ("reqd", "unique", "read_only", "hidden"):
				if payload.get(k):
					values[k] = payload[k]
			doc = frappe.get_doc(values).insert(ignore_permissions=False)
		elif action == "create_client_script":
			if "System Manager" not in frappe.get_roles(frappe.session.user):
				return {"ok": False, "error": "System Manager role required at commit time"}
			if not frappe.has_permission("Client Script", "create"):
				return {"ok": False, "error": "no create permission on Client Script at commit time"}
			if not frappe.db.exists("DocType", payload["dt"]):
				return {"ok": False, "error": f"DocType '{payload['dt']}' no longer exists"}
			values = {
				"doctype": "Client Script",
				"dt": payload["dt"],
				"view": payload["view"],
				"script": payload["script"],
				"enabled": payload.get("enabled", 1),
			}
			if payload.get("name"):
				values["name"] = payload["name"]
			doc = frappe.get_doc(values).insert(ignore_permissions=False)
		else:
			return {"ok": False, "error": f"Unknown action: {action}"}
		frappe.db.commit()
		_consume_action(token)
		# URL routing exception: Report doctype with report_type in
		# {Query Report, Script Report} opens at /app/query-report/<name>,
		# NOT /app/report/<name> (which is Report-Builder-only). The generic
		# scrub-doctype pattern produces the wrong URL for these.
		if doc.doctype == "Report" and getattr(doc, "report_type", "") in ("Query Report", "Script Report"):
			link = f"/app/query-report/{doc.name}"
		else:
			link = f"/app/{frappe.scrub(doc.doctype)}/{doc.name}"
		response = {
			"ok": True,
			"action": action,
			"name": doc.name,
			"doctype": doc.doctype,
			"link": link,
		}
		# Merge handler-supplied extras (export_csv returns file_url + row_count etc).
		extras_out = getattr(frappe.local.flags, "lazychat_commit_extras", None)
		if isinstance(extras_out, dict):
			response.update({k: v for k, v in extras_out.items() if k != "ok"})
		return response
	except Exception as e:
		try:
			frappe.db.rollback(save_point=sp_name)
		except Exception:
			pass
		frappe.log_error(frappe.get_traceback(), f"lazychat commit_prepared {action}")
		return {"ok": False, "error": str(e), "action": action}
