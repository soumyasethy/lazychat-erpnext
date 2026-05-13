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
    """Phase: html_parse — return None if content is well-formed HTML5.

    Uses lxml's XML parser (strict) wrapped in an `<html>` root because HTML
    parsers (including lxml's) auto-recover from unclosed tags, mismatched
    quotes, etc., so they silently accept malformed input. The XML strict
    pass surfaces those errors.
    """
    if not content or not content.strip():
        return None  # empty is fine; Page may be all-JS
    try:
        from lxml import etree as lxml_etree
    except ImportError:
        return None  # graceful — let install hook surface the missing dep
    try:
        # Wrap content in a root and parse strictly. The void-element tolerance
        # we lose vs an HTML parser (e.g. <br> without /) is a deliberate
        # trade-off — Pages should produce XHTML-clean markup.
        wrapped = f"<root>{content}</root>"
        parser = lxml_etree.XMLParser(recover=False, resolve_entities=False, no_network=True)
        lxml_etree.fromstring(wrapped.encode("utf-8"), parser=parser)
    except Exception as e:
        return {
            "phase": "html_parse",
            "error": f"HTML parse error: {e}",
            "hint": "Common causes: unclosed tag, mismatched quotes, stray < or >. Use XHTML-style self-closing for void elements (<br/>, <img/>, <input/>).",
        }
    return None


def validate_css(style: str) -> Optional[dict]:
    """Phase: css_syntax — return None if style is valid CSS.

    tinycss2 is lenient: `parse_stylesheet_bytes` returns `(rules, encoding)`,
    and parse errors are emitted as `ParseError` nodes interleaved with the
    rules list. We scan the rules for any `ParseError` and surface the first
    one. We also do a complementary brace-balance check because tinycss2
    treats unterminated blocks at EOF as "the rest of the file" rather than
    a hard error.
    """
    if not style or not style.strip():
        return None
    try:
        import tinycss2
        from tinycss2.ast import ParseError
    except ImportError:
        return None

    # Brace-balance check first — tinycss2 happily accepts unterminated
    # blocks (treats EOF as implicit close).
    open_braces = style.count("{")
    close_braces = style.count("}")
    if open_braces != close_braces:
        return {
            "phase": "css_syntax",
            "error": f"CSS brace imbalance: {open_braces} opening `{{` vs {close_braces} closing `}}`.",
            "hint": "Every `{` must have a matching `}`. Check for missing closes at end-of-file.",
        }

    rules, _encoding = tinycss2.parse_stylesheet_bytes(
        style.encode("utf-8"), skip_comments=True, skip_whitespace=True
    )
    for rule in rules:
        if isinstance(rule, ParseError):
            return {
                "phase": "css_syntax",
                "error": f"CSS syntax error at line {getattr(rule, 'source_line', '?')}: {getattr(rule, 'message', str(rule))}",
                "hint": "Check brace balance and ; terminators. tinycss2 surfaces the first failure only.",
            }
    return None


def validate_js(script: str) -> Optional[dict]:
    """Phase: js_syntax — return None if script parses to a valid AST."""
    if not script or not script.strip():
        return None
    try:
        import pyjsparser
    except ImportError:
        return None
    try:
        pyjsparser.parse(script)
    except Exception as e:
        return {
            "phase": "js_syntax",
            "error": f"JS syntax error: {e}",
            "hint": "pyjsparser is ES5-flavored; some ES2015+ syntax (arrow functions in some shapes, async/await, classes) may flag — re-write in plain function form if you hit this.",
        }
    return None


_BUILTIN_WHITELISTED_PREFIXES = (
    "frappe.client.get", "frappe.client.set_value", "frappe.client.insert",
    "frappe.client.delete", "frappe.client.cancel", "frappe.client.submit",
    "frappe.client.rename_doc", "frappe.desk.", "frappe.utils.",
    "frappe.email.queue.", "frappe.handler.",
)


def _walk_string_literals(node):
    if isinstance(node, dict):
        if node.get("type") == "Literal" and isinstance(node.get("value"), str):
            yield node["value"]
        for v in node.values():
            yield from _walk_string_literals(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_string_literals(item)


def _walk_call_expressions(node, target_func_path):
    if isinstance(node, dict):
        if node.get("type") == "CallExpression":
            callee = node.get("callee", {})
            path = _extract_member_path(callee)
            if path == target_func_path:
                yield node.get("arguments", [])
        for v in node.values():
            yield from _walk_call_expressions(v, target_func_path)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_call_expressions(item, target_func_path)


def _extract_member_path(callee):
    parts = []
    cur = callee
    while cur and isinstance(cur, dict):
        t = cur.get("type")
        if t == "MemberExpression":
            prop = cur.get("property", {})
            if prop.get("type") == "Identifier":
                parts.insert(0, prop.get("name"))
            cur = cur.get("object", {})
        elif t == "Identifier":
            parts.insert(0, cur.get("name"))
            cur = None
        else:
            return []
    return parts


def validate_js_doctype_refs(script: str) -> Optional[dict]:
    """Phase: js_doctypes_exist — walk AST for frappe.db.get_list/get_value/exists
    referencing doctype X; reject if any X doesn't exist in the bench."""
    if not script or not script.strip():
        return None
    try:
        import pyjsparser
        import frappe
    except ImportError:
        return None
    try:
        tree = pyjsparser.parse(script)
    except Exception:
        return None  # caught by validate_js
    referenced = set()
    for target in (["frappe", "db", "get_list"], ["frappe", "db", "get_value"], ["frappe", "db", "exists"], ["frappe", "db", "get_doc"]):
        for args in _walk_call_expressions(tree, target):
            if args and args[0].get("type") == "Literal" and isinstance(args[0].get("value"), str):
                referenced.add(args[0]["value"])
    for dt in referenced:
        if not frappe.db.exists("DocType", dt):
            return {
                "phase": "js_doctypes_exist",
                "error": f"JS references doctype '{dt}' which doesn't exist.",
                "hint": f"Run `describe_doctype` to find the right name. Common typos: 'User' (not 'Users'), 'Sales Invoice' (not 'sales_invoice').",
            }
    return None


def validate_js_method_refs(script: str, staged_methods: Optional[list] = None) -> Optional[dict]:
    """Phase: js_methods_exist — walk AST for frappe.call references; reject if
    a referenced method is not (a) built-in whitelisted, (b) in staged_methods,
    (c) already registered."""
    if not script or not script.strip():
        return None
    try:
        import pyjsparser
        import frappe
    except ImportError:
        return None
    try:
        tree = pyjsparser.parse(script)
    except Exception:
        return None
    referenced = set()
    for args in _walk_call_expressions(tree, ["frappe", "call"]):
        if not args:
            continue
        first = args[0]
        if first.get("type") == "ObjectExpression":
            for prop in first.get("properties", []):
                key = prop.get("key", {})
                key_name = key.get("name") if key.get("type") == "Identifier" else key.get("value")
                if key_name == "method":
                    val = prop.get("value", {})
                    if val.get("type") == "Literal" and isinstance(val.get("value"), str):
                        referenced.add(val["value"])
    staged = set(staged_methods or [])
    for method in referenced:
        if method in staged:
            continue
        if any(method.startswith(p) for p in _BUILTIN_WHITELISTED_PREFIXES):
            continue
        try:
            from frappe.handler import get_method
            get_method(method)
            continue
        except Exception:
            pass
        return {
            "phase": "js_methods_exist",
            "error": f"JS references method '{method}' that doesn't exist.",
            "hint": "Either: (a) stage `prepare_create_server_script` with this api_method in the same turn (the validator considers same-turn-staged methods as valid), (b) use a built-in like `frappe.client.get_list`, or (c) if the method DOES exist on this bench, double-check the dotted path.",
        }
    return None


def collect_quality_warnings(content: str, style: str, script: str) -> list[dict]:
    """Non-blocking — soft warnings: hardcoded colors w/o theme tokens, missing
    structural HTML, placeholder-looking data, missing lazychatReady marker."""
    import re
    warnings = []

    color_pattern = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([0-9.\s,]+\)")
    var_pattern = re.compile(r"var\(\s*--")
    color_count = len(color_pattern.findall(style or ""))
    var_count = len(var_pattern.findall(style or ""))
    if color_count > 5 and var_count == 0:
        warnings.append({
            "category": "theme_tokens",
            "severity": "major",
            "description": f"Page CSS has {color_count} hardcoded colors and 0 `var(--*)` references — page will not respect Frappe dark mode. Use `var(--bg-color)`, `var(--text-color)`, `var(--primary-color)`, `var(--text-muted)`, `var(--border-color)` from Frappe's theme.",
        })

    if content:
        has_header = "<header" in content
        has_main = "<main" in content
        has_section = "<section" in content
        missing = [t for t, has in (("header", has_header), ("main", has_main), ("section", has_section)) if not has]
        if len(missing) >= 2:
            warnings.append({
                "category": "semantic_html",
                "severity": "minor",
                "description": f"Page is missing structural HTML elements: {', '.join('<'+m+'>' for m in missing)}. Use <header>, <main>, <section> for semantic structure.",
            })

    if script and "lazychatReady" not in script:
        warnings.append({
            "category": "ready_signal",
            "severity": "major",
            "description": "Page JS does not set `document.body.dataset.lazychatReady = '1'`. The screenshot preview will use a 5s fallback timeout instead of precise ready-detection. Add the marker at the end of your final `frappe.call(...).then(...)` chain.",
        })

    return warnings
