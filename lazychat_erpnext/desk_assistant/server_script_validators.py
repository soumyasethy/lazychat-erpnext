"""Render-preview AST validators for prepare_create_server_script (script_type=API).

Mirrors tools.py:_validate_script_report_body but adapted for API endpoints:
- API scripts must produce output via `frappe.response.message = <dict>` OR
  a top-level `return` (not enforced by Frappe but useful for clarity).
- Reads/computations only — writes are explicitly rejected (they belong in
  prepare_create_doc / prepare_update_doc, not in API endpoints).

Scope: this validator catches `frappe.db.<write>` calls (FORBIDDEN_FRAPPE_DB_WRITES)
plus dangerous imports / builtins. It does NOT cover non-DB side-effect calls like
`frappe.sendmail` / `frappe.enqueue` / `frappe.publish_realtime` / `frappe.delete_doc`
/ `frappe.rename_doc` — those are handled at a different tier (role-based permissions
+ explicit Apply gating + the `allow_dangerous_tools` site flag). If a future cycle
needs to block them at AST-scan time, add a FORBIDDEN_FRAPPE_SIDE_EFFECTS constant
mirroring tools.py:_PY_RO_BLOCKED_FRAPPE and a corresponding validate_no_frappe_side_effects
function. Out of scope for Cycle 13.
"""
from __future__ import annotations
from typing import Optional
import ast


FORBIDDEN_IMPORTS = {
    "subprocess", "os", "sys", "shutil", "socket", "urllib", "requests",
    "http", "smtplib", "ftplib", "telnetlib", "ssl", "ctypes", "multiprocessing",
}

# Named without the open-paren so this file passes static scanners that flag
# arbitrary code execution patterns.
FORBIDDEN_BUILTINS = {"open", "eval", "exec", "compile", "__import__", "input", "breakpoint"}

FORBIDDEN_FRAPPE_DB_WRITES = {
    "set_value", "set_many", "delete", "sql_ddl", "multisql",
    "commit", "rollback", "savepoint", "release_savepoint",
}


def validate_python_ast(script: str) -> Optional[dict]:
    """Phase: python_ast — return None on successful parse, else error dict."""
    if not script or not script.strip():
        return {"phase": "python_ast", "error": "script is empty", "hint": "Provide a Python body that sets frappe.response.message = <dict>."}
    try:
        ast.parse(script)
    except SyntaxError as e:
        return {
            "phase": "python_ast",
            "error": f"Python syntax error at line {e.lineno}: {e.msg}",
            "hint": "Server Scripts run as standard Python under Frappe's safe_exec. Tabs/spaces, missing colons, and unclosed brackets are the usual culprits.",
        }
    return None


def validate_no_forbidden_imports(tree: ast.AST) -> Optional[dict]:
    """Phase: forbidden_imports — reject imports of network/shell modules."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in FORBIDDEN_IMPORTS:
                    return {
                        "phase": "forbidden_imports",
                        "error": f"`import {alias.name}` is not allowed in Server Scripts (Frappe safe_exec sandbox).",
                        "hint": "Use frappe.* alternatives: frappe.db for data, frappe.utils.* for helpers, frappe.session.user for current user.",
                    }
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top in FORBIDDEN_IMPORTS:
                return {
                    "phase": "forbidden_imports",
                    "error": f"`from {node.module} import ...` is not allowed in Server Scripts.",
                    "hint": "Use frappe.* alternatives.",
                }
    return None


def validate_no_forbidden_builtins(tree: ast.AST) -> Optional[dict]:
    """Phase: forbidden_builtins — reject calls to dangerous builtins by name."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_BUILTINS:
                return {
                    "phase": "forbidden_builtins",
                    "error": f"`{node.func.id}(...)` is forbidden under Frappe safe_exec.",
                    "hint": "These builtins are stripped from the safe_exec namespace. For file I/O use frappe.get_doc('File', ...).get_content(); for serialization use json.* (which IS available).",
                }
    return None


def validate_no_frappe_writes(tree: ast.AST) -> Optional[dict]:
    """Phase: forbidden_frappe_writes — reject frappe.db.<write> calls."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            if (isinstance(node.value, ast.Attribute) and
                isinstance(node.value.value, ast.Name) and
                node.value.value.id == "frappe" and
                node.value.attr == "db" and
                node.attr in FORBIDDEN_FRAPPE_DB_WRITES):
                return {
                    "phase": "forbidden_frappe_writes",
                    "error": f"`frappe.db.{node.attr}` is forbidden in Server Script API endpoints.",
                    "hint": "API endpoints are READ-ONLY by design. For writes, use prepare_create_doc / prepare_update_doc which go through the two-phase Apply pattern.",
                }
    return None


def validate_output_present(tree: ast.AST) -> Optional[dict]:
    """Phase: output_present — script must set frappe.response.message OR return."""
    has_response = False
    has_return = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Attribute) and
                    isinstance(target.value, ast.Attribute) and
                    isinstance(target.value.value, ast.Name) and
                    target.value.value.id == "frappe" and
                    target.value.attr == "response" and
                    target.attr == "message"):
                    has_response = True
        if isinstance(node, ast.Return):
            has_return = True
    if not has_response and not has_return:
        return {
            "phase": "output_present",
            "error": "Server Script API endpoint produces no output.",
            "hint": "End with `frappe.response.message = <result_dict>` (preferred) or a top-level `return <value>`. Without this the API endpoint returns null.",
        }
    return None


def run_all(script: str) -> Optional[dict]:
    """Run every phase in order. Return first failure, or None if all pass."""
    err = validate_python_ast(script)
    if err:
        return err
    try:
        tree = ast.parse(script)
    except SyntaxError:
        return validate_python_ast(script)
    for check in (validate_no_forbidden_imports, validate_no_forbidden_builtins,
                  validate_no_frappe_writes, validate_output_present):
        err = check(tree)
        if err:
            return err
    return None
