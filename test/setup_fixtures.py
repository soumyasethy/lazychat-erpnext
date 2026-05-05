"""Provision the test fixtures every tool's smoke needs.

Idempotent — every doc has a deterministic name or unique title beginning
with `_lz_smoke_`, so re-running just refreshes / no-ops. Pair with
`teardown_fixtures.py` to remove them all.

Run via:
    cp test/setup_fixtures.py <bench>/.../lazychat_mcp_erpnext/_setup_fixtures.py
    bench --site <site> execute lazychat_mcp_erpnext._setup_fixtures.run

Side-effect: writes the resolved fixture names to
    test/results/fixtures.json
so the curl harness can read them next run. Path is relative to this
file's location once it's been copied into the app.
"""
import json
import os
from pathlib import Path
import frappe


PREFIX = "_lz_smoke_"


def _exists(doctype: str, name: str) -> bool:
    return bool(frappe.db.exists(doctype, name))


def _ensure_note(title: str = f"{PREFIX}note") -> str:
    """A Note we can attach files to / add comments on / version-revert.

    Note autonames as 'hash' so we can't predict the name. Look up by title.
    """
    existing = frappe.get_all("Note", filters={"title": title}, fields=["name"], limit=1)
    if existing:
        print(f"[SKIP] Note/{existing[0].name} (title={title}) already exists")
        return existing[0].name
    doc = frappe.get_doc({
        "doctype": "Note",
        "title": title,
        "content": "Lazychat smoke fixture — safe to delete.",
        "public": 1,
    }).insert(ignore_permissions=True)
    print(f"[PROV] Note/{doc.name} (title={title})")
    return doc.name


def _ensure_file_on_note(note_name: str) -> str:
    """A public File attached to the smoke Note."""
    fname = f"{PREFIX}attachment.txt"
    existing = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Note",
            "attached_to_name": note_name,
            "file_name": fname,
        },
        fields=["name"],
        limit=1,
    )
    if existing:
        print(f"[SKIP] File/{existing[0].name} already attached to Note/{note_name}")
        return existing[0].name
    doc = frappe.get_doc({
        "doctype": "File",
        "file_name": fname,
        "is_private": 0,
        "attached_to_doctype": "Note",
        "attached_to_name": note_name,
        "content": "lazychat smoke file payload — tiny text file.",
        "decode": False,
    }).insert(ignore_permissions=True)
    print(f"[PROV] File/{doc.name} attached to Note/{note_name}")
    return doc.name


def _ensure_kb() -> str:
    """A Lazychat Knowledge Base — pick an existing one if any, else create.

    KB doctype autoname is from `slug` field. We try our prefix first, fall
    back to whatever's already on the site (smoke is read-only on KB so we
    don't pollute existing rows).
    """
    # The KB doctype's slug field is named `kb_name` (not `slug`).
    slug = f"{PREFIX}kb"
    if _exists("Lazychat Knowledge Base", slug):
        print(f"[SKIP] Lazychat Knowledge Base/{slug} already exists")
        return slug
    try:
        doc = frappe.get_doc({
            "doctype": "Lazychat Knowledge Base",
            "kb_name": slug,
            "title": "Lazychat Smoke KB",
            "description": "Lazychat smoke KB. Safe to delete.",
            "enabled": 1,
            "is_public": 1,
        }).insert(ignore_permissions=True)
        print(f"[PROV] Lazychat Knowledge Base/{doc.name}")
        return doc.name
    except Exception as e:
        # Reuse an existing KB if creation fails — smoke is read-only here.
        print(f"[WARN] could not create KB ({e}); falling back to existing.")
        existing = frappe.get_all("Lazychat Knowledge Base", fields=["name"], limit=1)
        if existing:
            print(f"[SKIP] reusing existing Lazychat Knowledge Base/{existing[0].name}")
            return existing[0].name
        return ""


def _ensure_queued_job() -> str:
    """A short background job we can probe via list_my_jobs / cancel_job.

    Uses frappe.enqueue with a no-op long-ish task so it sits in the queue
    long enough for the smoke to inspect. Returns the job_id.
    """
    try:
        from frappe.utils.background_jobs import enqueue
        # Sleep for 60s — gives the smoke plenty of time to list + cancel
        # before it would naturally finish. The function reference must be
        # importable from the worker's path.
        job = enqueue(
            "frappe.utils.sleep",
            seconds=60,
            queue="short",
            timeout=120,
            job_name=f"{PREFIX}sleep_job",
            now=False,
        )
        # job is a rq.Job instance
        job_id = job.id if hasattr(job, "id") else str(job)
        print(f"[PROV] queued background job id={job_id}")
        return job_id
    except Exception as e:
        print(f"[WARN] could not enqueue job: {e}")
        return ""


def _resolve_extras(out: dict) -> None:
    """Attach derived URLs the smoke needs:
       - file_url   absolute path of the attached File row (e.g. /files/foo.txt)
       - company    the calling user's default Company (run_report needs it)
    """
    if out.get("file"):
        try:
            f = frappe.get_doc("File", out["file"])
            out["file_url"] = f.file_url or ""
        except Exception:
            out["file_url"] = ""
    company = (
        frappe.db.get_default("company")
        or (frappe.get_all("Company", fields=["name"], limit=1) or [{"name": ""}])[0].get("name")
    )
    out["company"] = company or ""


def _real_existing(out: dict) -> None:
    """Look up real existing rows the smoke can read against (no creation)."""
    cust = frappe.get_all(
        "Customer", filters={"disabled": 0}, fields=["name", "customer_name"], limit=1
    )
    out["customer"] = cust[0].name if cust else ""
    so = frappe.get_all(
        "Sales Order", filters={"docstatus": 1}, fields=["name"], limit=1
    )
    out["sales_order"] = so[0].name if so else ""
    item = frappe.get_all(
        "Item", filters={"disabled": 0}, fields=["name", "item_code"], limit=1
    )
    out["item_code"] = item[0].item_code if item else ""
    chart = frappe.get_all("Dashboard Chart", fields=["name"], limit=1)
    out["dashboard_chart"] = chart[0].name if chart else ""
    nc = frappe.get_all("Number Card", filters={"type": "Document Type"}, fields=["name"], limit=1)
    out["number_card"] = nc[0].name if nc else ""
    rep = frappe.get_all("Report", filters={"is_standard": "Yes", "disabled": 0}, fields=["name"], limit=1)
    out["report"] = rep[0].name if rep else ""
    wf = frappe.get_all("Workflow", filters={"is_active": 1, "document_type": "Customer"}, fields=["name"], limit=1)
    out["workflow_doctype"] = "Customer" if wf else ""
    pf = frappe.get_all("Print Format", filters={"doc_type": "Sales Order", "disabled": 0}, fields=["name"], limit=1)
    out["print_format"] = pf[0].name if pf else "Standard"


def _write_results_file(out: dict) -> None:
    """Persist fixture handles where curl_smoke.py can read them.

    The setup script lives in two places:
      - source: lazychat-mcp-erpnext/test/setup_fixtures.py
      - bench:  <bench>/.../lazychat_mcp_erpnext/_setup_fixtures.py (copy)

    From the bench copy, walk back to the source by env var or by best-effort
    repo discovery. If neither works, we still print to stdout so the user
    can paste it.
    """
    env_dst = os.environ.get("LAZYCHAT_FIXTURES_PATH")
    candidates = []
    if env_dst:
        candidates.append(Path(env_dst))
    # Common dev path on this machine — works for the user.
    candidates.append(Path("/Users/<you>/Desktop/code-chat/lazychat-mcp-erpnext/test/results/fixtures.json"))
    written = []
    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(out, indent=2))
            written.append(str(p))
        except Exception as e:
            print(f"[WARN] could not write {p}: {e}")
    if written:
        print(f"[FIXTURES WRITTEN] {written}")


def run() -> dict:
    """Provision every fixture. Returns + persists a dict of fixture handles."""
    frappe.set_user("Administrator")
    out = {}
    out["note"] = _ensure_note()
    out["file"] = _ensure_file_on_note(out["note"])
    out["kb"] = _ensure_kb()
    out["job_id"] = _ensure_queued_job()
    _real_existing(out)
    _resolve_extras(out)
    frappe.db.commit()
    _write_results_file(out)
    print(f"\n[FIXTURES READY] {out}")
    return out
