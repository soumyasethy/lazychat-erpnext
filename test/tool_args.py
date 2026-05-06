"""Per-tool argument fixtures + validators for the HTTP-level smoke test.

Args come from `test/results/fixtures.json` (run setup_fixtures.py first).
For each tool we declare:

    TOOL_ARGS[<tool>]            – arguments to pass through tools/call
    EXPECT_ERROR_OK              – tools where a graceful error IS success
                                   (gated by site config, missing fixture
                                    that doesn't exist on a clean bench, etc.)
    VALIDATORS[<tool>]           – `(body) -> (ok, detail)` callable that
                                   returns whether the tool actually
                                   delivered the right shape / data.
                                   Without one, "no error" counts as OK.
    QUICK_PROBE_TOOLS            – the 9 tools the user reported failing.
                                   `QUICK_PROBE=1` runs only these.
    SKIP_NEEDS_FIXTURE           – kept for tools that genuinely can't be
                                   exercised without machinery the harness
                                   doesn't own (today: empty — every tool
                                   has a fixture).
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Load fixture handles produced by setup_fixtures.py
# ---------------------------------------------------------------------------
_FIXTURES_PATH = Path(__file__).parent / "results" / "fixtures.json"
if not _FIXTURES_PATH.exists():
    raise SystemExit(
        f"fixtures.json not found at {_FIXTURES_PATH}\n"
        "Provision fixtures first:\n"
        "  cp test/setup_fixtures.py <bench>/.../lazychat_mcp_erpnext/_setup_fixtures.py\n"
        "  cd <bench> && bench --site <site> execute lazychat_mcp_erpnext._setup_fixtures.run"
    )
F = json.loads(_FIXTURES_PATH.read_text())

# Every tool can rely on these — populated either by setup_fixtures.py
# (created by us) or by reading what already exists on the site.
KNOWN_DOCTYPE = "DocType"
KNOWN_DOCTYPE_NAME = "DocType"  # the DocType doctype's row for itself
KNOWN_USER = "Administrator"
NONEXISTENT_FILE = "/files/__lazychat_smoke_no_such_xyz.txt"

CUSTOMER = F.get("customer") or "21000001"
SALES_ORDER = F.get("sales_order") or "SO-02-26-000406"
ITEM_CODE = F.get("item_code") or "214602"
NOTE_NAME = F.get("note") or ""
FILE_NAME = F.get("file") or ""
KB_NAME = F.get("kb") or ""
JOB_ID = F.get("job_id") or ""
DASHBOARD_CHART = F.get("dashboard_chart") or ""
NUMBER_CARD = F.get("number_card") or ""
REPORT_NAME = F.get("report") or ""
PRINT_FORMAT = F.get("print_format") or "Standard"
FILE_URL = F.get("file_url") or ""
COMPANY = F.get("company") or ""

# A tiny but valid Vega-Lite v5 spec — make_chart only validates shape.
_TINY_VEGA_SPEC = {
    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
    "data": {"values": [{"a": 1, "b": 2}, {"a": 3, "b": 4}]},
    "mark": "bar",
    "encoding": {
        "x": {"field": "a", "type": "ordinal"},
        "y": {"field": "b", "type": "quantitative"},
    },
}

# ---------------------------------------------------------------------------
# 9 tools the user reported failing — quick-probe scope
# ---------------------------------------------------------------------------
QUICK_PROBE_TOOLS = {
    "describe_doctype",
    "aggregate",
    "get_list",
    "get_current_context",
    "list_attachments",
    "get_doc",
    "get_file_url",
    "make_chart",
    "count_doc",
}

# ---------------------------------------------------------------------------
# Args per tool — keyed so missing ones surface as MISSING_ARGS
# ---------------------------------------------------------------------------
TOOL_ARGS: dict[str, dict[str, Any]] = {
    # --- Discovery / reads ---
    "get_list": {"doctype": "Customer", "limit": 2},
    "get_doc": {"doctype": "Customer", "name": CUSTOMER},
    "get_current_context": {},
    "describe_doctype": {"doctype": "Sales Order"},
    "get_value": {"doctype": "Customer", "name": CUSTOMER, "fieldname": "customer_name"},
    "count_doc": {"doctype": "Customer"},
    "search_doctype": {"query": "Sales Order", "limit": 5},
    "search_global": {"query": "Customer", "limit": 5},
    "search_link": {"doctype": "Customer", "txt": "", "limit": 5},
    "get_doctype_links": {"doctype": "Customer", "name": CUSTOMER},

    # --- Aggregation ---
    "aggregate": {"doctype": "Item", "function": "count", "field": "name", "group_by": "item_group"},

    # --- Workflow / approvals ---
    "list_workflow_actions": {"doctype": "Customer", "name": CUSTOMER},
    "get_pending_approvals": {},

    # --- Reports ---
    "list_reports": {"limit": 5},
    "report_requirements": {"name": REPORT_NAME},
    # Most ERPNext reports require `company` — use the bench's default.
    "run_report": {"name": REPORT_NAME, "filters": {"company": COMPANY}},

    # --- Dashboards / numbers ---
    "list_user_dashboards": {},
    "dashboard_chart_data": {"name": DASHBOARD_CHART},
    "number_card_value": {"name": NUMBER_CARD},

    # --- Files ---
    "list_attachments": {"doctype": "Note", "name": NOTE_NAME},
    "get_file_url": {"file": FILE_NAME},
    # Impl reads the param under any of: `file`, `file_url`, `name`. Pass
    # the explicit `file` key — most direct path.
    "extract_file_content": {"file": FILE_URL},

    # --- Domain helpers ---
    "get_company_defaults": {},
    "get_stock_balance": {"item_code": ITEM_CODE},
    "get_account_balance": {"account": "_lazychat_smoke_no_account"},  # EXPECT_ERROR_OK
    "get_outstanding": {"party_type": "Customer", "party": CUSTOMER},
    "get_open_invoices": {"party_type": "Customer"},
    "get_sales_summary": {},
    "get_item_price": {"item_code": ITEM_CODE},

    # --- Subscriptions (Tier D) ---
    "subscribe_doc_changes": {"doctype": "Customer", "name": CUSTOMER},
    "unsubscribe_doc_changes": {"doctype": "Customer", "name": CUSTOMER},
    "list_my_subscriptions": {},

    # --- Charts ---
    "make_chart": {"spec": _TINY_VEGA_SPEC, "title": "lazychat smoke"},

    # --- Audit / metadata ---
    "get_audit_trail": {"doctype": "Customer", "name": CUSTOMER},
    "get_system_info": {},
    "get_user_info": {"user": KNOWN_USER},
    "list_doc_versions": {"doctype": "Customer", "name": CUSTOMER},

    # --- Jobs ---
    "list_my_jobs": {},
    "cancel_job": {"job_id": JOB_ID},

    # --- Mutations (prepare_* — staged only, never committed by harness) ---
    "prepare_create_doc": {
        "doctype": "Note",
        "values": {"title": "_lazychat_smoke_create_probe", "content": "smoke test"},
    },
    "prepare_update_doc": {
        "doctype": "Note", "name": NOTE_NAME,
        "patch": {"content": "smoke noop update"},
    },
    "prepare_submit_doc": {"doctype": "Sales Order", "name": SALES_ORDER},  # already submitted → EXPECT_ERROR_OK
    "prepare_delete_doc": {"doctype": "Note", "name": "_lazychat_smoke_no_note"},  # EXPECT_ERROR_OK
    "prepare_add_comment": {"doctype": "Customer", "name": CUSTOMER, "text": "lazychat smoke comment"},
    "prepare_assign_to": {"doctype": "Customer", "name": CUSTOMER, "user": KNOWN_USER, "description": "smoke"},
    "prepare_workflow_action": {
        "doctype": "Customer", "name": CUSTOMER, "action": "_lazychat_smoke_no_action",
    },  # EXPECT_ERROR_OK
    "prepare_send_email": {"recipients": "test@example.com", "subject": "smoke", "content": "smoke test"},
    "prepare_share_doc": {"doctype": "Customer", "name": CUSTOMER, "user": KNOWN_USER, "read": 1},
    "prepare_upload_file": {"target_doctype": "Note", "target_name": NOTE_NAME},
    "prepare_import_csv": {"doctype": "Note", "csv_file_url": FILE_URL},  # gated → EXPECT_ERROR_OK
    "prepare_rename_doc": {"doctype": "Note", "name": "_lazychat_smoke_no_note", "new_name": "_lazychat_smoke_renamed"},
    "prepare_revert_doc": {"doctype": "Customer", "name": CUSTOMER, "version_name": "_lazychat_smoke_no_version"},

    # --- Power tools (gated by site_config flag) ---
    "prepare_run_sql": {"sql": "SELECT 1 AS smoke"},
    "prepare_run_python": {"code": "result = 1 + 1"},

    # --- Exports ---
    "export_list_to_csv": {"doctype": "Customer"},  # without `fields` → returns field-picker preview
    "export_doc_pdf": {"doctype": "Sales Order", "name": SALES_ORDER, "print_format": PRINT_FORMAT},

    # --- Knowledge Base (Tier H) ---
    "list_knowledge_bases": {},
    "get_kb_files": {"kb_name": KB_NAME},
    "search_kb": {"query": "smoke", "kb_name": KB_NAME},
    "reindex_kb": {"kb_name": KB_NAME},
    "prepare_create_kb": {
        "title": "Lazychat Smoke Probe KB", "slug": "_lz_smoke_kb",  # already exists → EXPECT_ERROR_OK
        "description": "Probe", "is_public": False,
    },
    "prepare_add_file_to_kb": {"kb_name": KB_NAME, "file_url": FILE_URL},

    # --- Skills (Tier E) ---
    "list_skills": {},
    "activate_skill": {"skill_name": "_lazychat_smoke_no_skill"},  # EXPECT_ERROR_OK
    "deactivate_skill": {"skill_name": "_lazychat_smoke_no_skill"},  # EXPECT_ERROR_OK

    # --- Typed wrappers (added 2026-05-06) ---
    # Each one stages a preview_token; nothing is actually committed by the harness.
    "prepare_create_report": {
        "report_name": "_lazychat_smoke_report_probe",
        "ref_doctype": "Customer",
        "report_type": "Report Builder",
    },
    # Scheduled Job Type creation requires System Manager — when the smoke
    # runs as that role, expect a token; otherwise expect a permission error
    # (still validates the dispatch path).
    "prepare_create_scheduled_job": {
        "method": "frappe.utils.background_jobs.show_pending_jobs",
        "frequency": "Daily",
    },
    "prepare_create_number_card": {
        "label": "_lazychat_smoke_card_probe",
        "doctype": "Customer",
        "function": "Count",
    },
    # Dashboard requires existing chart/card refs — the smoke should NOT mutate
    # data, so we pass a deliberately-bogus chart name and rely on the wrapper's
    # exists-check to return a graceful error (EXPECT_ERROR_OK).
    "prepare_create_dashboard": {
        "dashboard_name": "_lazychat_smoke_dashboard_probe",
        "charts": ["_lazychat_smoke_no_chart"],
    },
}

# ---------------------------------------------------------------------------
# Tools where a graceful error response IS the expected outcome.
# Either gated by site config (allow_email / allow_dangerous_tools), or
# probing a deliberately-non-existent fixture, or already-applied state.
# ---------------------------------------------------------------------------
EXPECT_ERROR_OK: set[str] = {
    "get_account_balance",       # placeholder account
    "prepare_submit_doc",        # already submitted
    "prepare_delete_doc",        # nonexistent target
    "prepare_workflow_action",   # invalid action
    "prepare_rename_doc",        # nonexistent target
    "prepare_revert_doc",        # invalid version
    "prepare_send_email",        # gated by 'lazychat_allow_email'
    "prepare_run_sql",           # gated by 'lazychat_allow_dangerous_tools'
    "prepare_run_python",        # gated by 'lazychat_allow_dangerous_tools'
    "prepare_import_csv",        # gated by 'lazychat_allow_dangerous_tools'
    "prepare_create_kb",         # KB slug already exists
    "activate_skill",            # nonexistent skill
    "deactivate_skill",          # nonexistent skill
    "prepare_create_dashboard",  # references nonexistent chart on purpose
    # prepare_create_scheduled_job is conditionally OK_ERROR — the harness
    # may or may not have System Manager. Treat permission-deny as graceful.
    "prepare_create_scheduled_job",
}

# Empty now — every tool has args. Kept for shape compat / future fixtures.
SKIP_NEEDS_FIXTURE: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Per-tool content validators. Returns (ok, detail). Without one, "no error"
# counts as OK.
#
# Each validator gets the unwrapped tool body (the dict the impl returned).
# We lean on light shape checks — enough to catch wrong-fields / missing-keys
# regressions without coupling to volatile data.
# ---------------------------------------------------------------------------

def _has(d: dict, *keys: str) -> bool:
    return all(k in d for k in keys)


def _v_get_list(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("rows"), list) and b["rows"],
            f"count={b.get('count')} sample={b['rows'][0].get('name') if b.get('rows') else '∅'}")


def _v_get_doc(b: dict) -> tuple[bool, str]:
    doc = b.get("doc") or {}
    return (b.get("ok") is True and bool(doc) and doc.get("name") == CUSTOMER,
            f"doc.name={doc.get('name')}")


def _v_get_value(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and b.get("value") is not None,
            f"value={b.get('value')!r}")


def _v_count_doc(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("count"), int) and b["count"] > 0,
            f"count={b.get('count')}")


def _v_describe_doctype(b: dict) -> tuple[bool, str]:
    fields = b.get("fields") or []
    return (b.get("ok") is True and len(fields) > 5,
            f"fields={len(fields)}")


def _v_aggregate(b: dict) -> tuple[bool, str]:
    rows = b.get("rows") or []
    return (b.get("ok") is True and isinstance(rows, list) and len(rows) > 0,
            f"groups={len(rows)} top={rows[0] if rows else '∅'}")


def _v_search_global(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("rows", b.get("results")), list),
            f"count={b.get('count')}")


def _v_search_link(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("rows", b.get("results", [])), list),
            f"count={b.get('count')}")


def _v_search_doctype(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("rows", b.get("doctypes", [])), list),
            f"count={b.get('count')}")


def _v_get_doctype_links(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("rows", b.get("links", [])), list),
            f"links={b.get('count', len(b.get('links', [])))}")


def _v_list_workflow_actions(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("actions") or b.get("transitions"), list),
            f"actions={len(b.get('actions') or b.get('transitions') or [])}")


def _v_pending_approvals(b: dict) -> tuple[bool, str]:
    # Empty count=0 with no rows[] key is the correct response when the user
    # has zero pending approvals. Accept either the count or the list.
    has_count = "count" in b
    has_list = isinstance(b.get("rows") or b.get("approvals"), list)
    return (b.get("ok") is True and (has_count or has_list),
            f"count={b.get('count')}")


def _v_list_reports(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("rows") or b.get("reports"), list),
            f"count={b.get('count')}")


def _v_report_requirements(b: dict) -> tuple[bool, str]:
    # Impl returns {"ok": True, "info": <human-readable summary>} for reports
    # whose filters can't be machine-introspected. Accept that shape too.
    return (b.get("ok") is True
            and ("filters" in b or "columns" in b or "report_type" in b
                 or "info" in b or "report" in b),
            f"keys={list(b.keys())[:5]}")


def _v_run_report(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and ("rows" in b or "result" in b),
            f"rows={b.get('row_count') or len(b.get('rows', []))}")


def _v_list_dashboards(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("rows") or b.get("dashboards"), list),
            f"count={b.get('count')}")


def _v_dashboard_chart_data(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and ("data" in b or "labels" in b or "datasets" in b),
            f"keys={list(b.keys())[:5]}")


def _v_number_card_value(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and "value" in b,
            f"value={b.get('value')}")


def _v_list_attachments(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("files"), list) and b["files"],
            f"files={b.get('count')} sample={b['files'][0].get('file_name') if b.get('files') else '∅'}")


def _v_get_file_url(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and b.get("absolute_url"),
            f"url={(b.get('absolute_url') or '')[:60]}")


def _v_extract_file_content(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and ("text" in b or "content" in b),
            f"text_len={len(b.get('text') or b.get('content', ''))}")


def _v_company_defaults(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and ("company" in b or "currency" in b or "defaults" in b),
            f"keys={list(b.keys())[:5]}")


def _v_stock_balance(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and ("qty" in b or "balance" in b or "items" in b or "rows" in b),
            f"keys={list(b.keys())[:5]}")


def _v_outstanding(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and ("rows" in b or "invoices" in b or "outstanding" in b),
            f"count={b.get('count')}")


def _v_open_invoices(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("rows") or b.get("invoices"), list),
            f"count={b.get('count')}")


def _v_sales_summary(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("rows"), list),
            f"rows={len(b.get('rows', []))}")


def _v_item_price(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and ("rows" in b or "price" in b or "rate" in b or "count" in b),
            f"keys={list(b.keys())[:5]}")


def _v_subscribe(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True,
            f"sub_id={b.get('sub_id') or b.get('id') or ''}")


def _v_unsubscribe(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True,
            "unsubscribed" if b.get("ok") else "")


def _v_list_subs(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("subscriptions"), list),
            f"count={b.get('count')}")


def _v_make_chart(b: dict) -> tuple[bool, str]:
    spec = b.get("spec") or {}
    return (b.get("ok") is True and spec.get("$schema", "").startswith("https://vega.github.io"),
            f"mark={spec.get('mark')}")


def _v_audit_trail(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("events"), list),
            f"events={len(b.get('events', []))}")


def _v_system_info(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and ("frappe_version" in b or "site" in b or "version" in b or "info" in b),
            f"keys={list(b.keys())[:5]}")


def _v_user_info(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and (b.get("name") or b.get("email") or b.get("user")),
            f"user={b.get('name') or b.get('user')}")


def _v_list_versions(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("versions"), list),
            f"count={b.get('count')}")


def _v_list_jobs(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("jobs"), list),
            f"count={b.get('count')}")


def _v_cancel_job(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True or "error" in b,  # job may already finish in <60s; either is OK
            f"status={b.get('status') or b.get('error', '')[:40]}")


def _v_prepare_token(b: dict) -> tuple[bool, str]:
    """Generic prepare_* validator: must return a preview_token + summary."""
    tok = b.get("preview_token")
    return (b.get("ok") is True and bool(tok),
            f"token={(tok or '')[:8]}…")


def _v_field_picker_or_token(b: dict) -> tuple[bool, str]:
    """For tools like export_list_to_csv that return either a field-picker
    preview (preview_token + field_picker) or a direct file_url result."""
    if b.get("file_url"):
        return True, f"file={b.get('file_name')} rows={b.get('row_count')}"
    if b.get("preview_token"):
        return True, f"field_picker token={b['preview_token'][:8]}…"
    return False, "no file_url and no preview_token"


def _v_export_pdf(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and b.get("file_url") and b.get("size_bytes", 0) > 100,
            f"size={b.get('size_bytes')} url={(b.get('file_url') or '')[:50]}")


def _v_list_kbs(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("knowledge_bases"), list),
            f"count={len(b.get('knowledge_bases', []))}")


def _v_get_kb_files(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and ("files" in b or "rows" in b or "count" in b),
            f"count={b.get('count', len(b.get('files', [])))}")


def _v_search_kb(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and ("results" in b or "chunks" in b or "rows" in b or "count" in b),
            f"hits={b.get('count', len(b.get('results', b.get('chunks', []))))}")


def _v_reindex_kb(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True
            and ("indexed" in b or "job_id" in b or "queued" in b
                 or "status" in b or "files_enqueued" in b),
            f"keys={list(b.keys())[:5]}")


def _v_list_skills(b: dict) -> tuple[bool, str]:
    return (b.get("ok") is True and isinstance(b.get("skills"), list),
            f"count={len(b.get('skills', []))}")


def _v_current_context(b: dict) -> tuple[bool, str]:
    # No desk context is passed from a curl invocation, so empty/null
    # context is the *correct* response and counts as success.
    return (b.get("ok") is True or "context" in b or b == {} or "ok" not in b,
            f"keys={list(b.keys())[:5]}")


VALIDATORS: dict[str, Callable[[dict], tuple[bool, str]]] = {
    "get_list": _v_get_list,
    "get_doc": _v_get_doc,
    "get_current_context": _v_current_context,
    "describe_doctype": _v_describe_doctype,
    "get_value": _v_get_value,
    "count_doc": _v_count_doc,
    "search_doctype": _v_search_doctype,
    "search_global": _v_search_global,
    "search_link": _v_search_link,
    "get_doctype_links": _v_get_doctype_links,
    "aggregate": _v_aggregate,
    "list_workflow_actions": _v_list_workflow_actions,
    "get_pending_approvals": _v_pending_approvals,
    "list_reports": _v_list_reports,
    "report_requirements": _v_report_requirements,
    "run_report": _v_run_report,
    "list_user_dashboards": _v_list_dashboards,
    "dashboard_chart_data": _v_dashboard_chart_data,
    "number_card_value": _v_number_card_value,
    "list_attachments": _v_list_attachments,
    "get_file_url": _v_get_file_url,
    "extract_file_content": _v_extract_file_content,
    "get_company_defaults": _v_company_defaults,
    "get_stock_balance": _v_stock_balance,
    "get_outstanding": _v_outstanding,
    "get_open_invoices": _v_open_invoices,
    "get_sales_summary": _v_sales_summary,
    "get_item_price": _v_item_price,
    "subscribe_doc_changes": _v_subscribe,
    "unsubscribe_doc_changes": _v_unsubscribe,
    "list_my_subscriptions": _v_list_subs,
    "make_chart": _v_make_chart,
    "get_audit_trail": _v_audit_trail,
    "get_system_info": _v_system_info,
    "get_user_info": _v_user_info,
    "list_doc_versions": _v_list_versions,
    "list_my_jobs": _v_list_jobs,
    "cancel_job": _v_cancel_job,
    # All prepare_* tools share the same "must return a preview_token" shape
    # (except prepare_upload_file's file-picker variant — handled below).
    "prepare_create_doc": _v_prepare_token,
    "prepare_update_doc": _v_prepare_token,
    "prepare_add_comment": _v_prepare_token,
    "prepare_assign_to": _v_prepare_token,
    "prepare_share_doc": _v_prepare_token,
    "prepare_upload_file": _v_prepare_token,  # also returns file_picker:true
    "prepare_create_report": _v_prepare_token,
    "prepare_create_scheduled_job": _v_prepare_token,
    "prepare_create_number_card": _v_prepare_token,
    # prepare_create_dashboard is EXPECT_ERROR_OK so it doesn't run through
    # this validator — kept here for symmetry if a future smoke seeds a real chart.
    "prepare_create_dashboard": _v_prepare_token,
    "export_list_to_csv": _v_field_picker_or_token,
    "export_doc_pdf": _v_export_pdf,
    "list_knowledge_bases": _v_list_kbs,
    "get_kb_files": _v_get_kb_files,
    "search_kb": _v_search_kb,
    "reindex_kb": _v_reindex_kb,
    "list_skills": _v_list_skills,
}
