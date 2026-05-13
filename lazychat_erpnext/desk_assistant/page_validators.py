"""Render-preview validators for prepare_create_page.

Each `validate_*` function returns `None` on pass, or a dict
`{"phase": <name>, "error": <msg>, "hint": <actionable hint>}` on hard fail.

`collect_quality_warnings` returns a list of `{"category", "severity",
"description"}` dicts — these are NON-blocking (the agent and user see them
in the Apply card's critic strip but Apply still proceeds).

Lazy imports: lxml/tinycss2/pyjsparser are heavy (combined ~5 MB on disk).
We import them inside the functions so a bench that never stages a Page
doesn't pay the cost at module-import time.
"""
from __future__ import annotations
from typing import Optional


def validate_html(content: str) -> Optional[dict]:
    """Phase: html_parse — return None if content is well-formed HTML5."""
    raise NotImplementedError  # filled in Task M1.2


def validate_css(style: str) -> Optional[dict]:
    """Phase: css_syntax — return None if style is valid CSS."""
    raise NotImplementedError  # Task M1.2


def validate_js(script: str) -> Optional[dict]:
    """Phase: js_syntax — return None if script parses to a valid AST."""
    raise NotImplementedError  # Task M1.2


def validate_js_doctype_refs(script: str) -> Optional[dict]:
    """Phase: js_doctypes_exist — walk AST for frappe.db.get_list/get_value/exists
    referencing doctype X; reject if any X doesn't exist in the bench."""
    raise NotImplementedError  # Task M1.2


def validate_js_method_refs(script: str, staged_methods: Optional[list] = None) -> Optional[dict]:
    """Phase: js_methods_exist — walk AST for frappe.call references; reject if
    a referenced method is not (a) built-in whitelisted, (b) in staged_methods,
    (c) already registered."""
    raise NotImplementedError  # Task M1.2


def collect_quality_warnings(content: str, style: str, script: str) -> list:
    """Non-blocking — soft warnings: hardcoded colors w/o theme tokens, missing
    structural HTML, placeholder-looking data, missing lazychatReady marker."""
    return []  # Task M1.2
