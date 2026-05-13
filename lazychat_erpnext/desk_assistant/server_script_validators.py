"""Render-preview AST validators for prepare_create_server_script (script_type=API).

Mirrors tools.py:_validate_script_report_body but adapted for API endpoints:
- API scripts must produce output via `frappe.response.message = <dict>` OR
  a top-level `return` (not enforced by Frappe but useful for clarity).
- Reads/computations only — writes are explicitly rejected (they belong in
  prepare_create_doc / prepare_update_doc, not in API endpoints).
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
    raise NotImplementedError  # Task M1.2


def validate_no_forbidden_imports(tree: ast.AST) -> Optional[dict]:
    """Phase: forbidden_imports — reject imports of network/shell modules."""
    raise NotImplementedError  # Task M1.2


def validate_no_forbidden_builtins(tree: ast.AST) -> Optional[dict]:
    """Phase: forbidden_builtins — reject calls to dangerous builtins by name."""
    raise NotImplementedError  # Task M1.2


def validate_no_frappe_writes(tree: ast.AST) -> Optional[dict]:
    """Phase: forbidden_frappe_writes — reject frappe.db.<write> calls."""
    raise NotImplementedError  # Task M1.2


def validate_output_present(tree: ast.AST) -> Optional[dict]:
    """Phase: output_present — script must set frappe.response.message OR return."""
    raise NotImplementedError  # Task M1.2


def run_all(script: str) -> Optional[dict]:
    """Run every phase in order. Return first failure, or None if all pass."""
    raise NotImplementedError  # Task M1.2
