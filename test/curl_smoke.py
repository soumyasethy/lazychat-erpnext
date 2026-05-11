#!/usr/bin/env python3
"""HTTP-level smoke test for the lazychat MCP wire (Layer 1 of the harness).

Hits POST /api/method/lazychat_erpnext.desk_assistant.mcp.handle directly
with no client-side timeout, so a slow backend completes and a stuck
connection only fails at the OS / urllib default. This brackets the bug:

    Phase 0 outcome                  → bug location
    ────────────────────────────────────────────────
    All probes <2s                   → chat-ui plumbing (CSRF, stale bundle)
    All probes ≥30s                  → backend (DB lock, worker, slow get_meta)
    Specific tool errors             → that tool's impl
    JSONRPC -32601/-32602 only       → harness invocation bug

Usage:
    cp test/.env.local.example test/.env.local
    # edit FRAPPE_URL/USER/PWD or FRAPPE_KEY/SECRET
    python3 test/curl_smoke.py            # full run, all 62 tools
    QUICK_PROBE=1 python3 test/curl_smoke.py   # only the 9 user-flagged tools

Output: test/results/layer1.json + a 1-line-per-tool table on stdout.
"""
from __future__ import annotations
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS_DIR = ROOT / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# === Load env ===
ENV_FILE = ROOT / ".env.local"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

URL = os.environ.get("FRAPPE_URL", "http://localhost:8000").rstrip("/")
KEY = os.environ.get("FRAPPE_KEY")
SECRET = os.environ.get("FRAPPE_SECRET")
USER = os.environ.get("FRAPPE_USER", "Administrator")
PWD = os.environ.get("FRAPPE_PWD", "")
QUICK = os.environ.get("QUICK_PROBE", "0") == "1"

MCP_ENDPOINT = f"{URL}/api/method/lazychat_erpnext.desk_assistant.mcp.handle"
LOGIN_ENDPOINT = f"{URL}/api/method/login"

# Pull args after env load so user can override paths in env (future).
sys.path.insert(0, str(ROOT))
from tool_args import (  # noqa: E402
    TOOL_ARGS,
    EXPECT_ERROR_OK,
    SKIP_NEEDS_FIXTURE,
    QUICK_PROBE_TOOLS,
    VALIDATORS,
)

# === HTTP plumbing — single shared opener with cookie jar ===
_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))


def _auth_headers() -> dict[str, str]:
    if KEY and SECRET:
        return {"Authorization": f"token {KEY}:{SECRET}"}
    return {}


def login() -> None:
    """Cookie auth fallback when no API key is configured."""
    if KEY and SECRET:
        return
    if not PWD:
        die("Neither FRAPPE_KEY/SECRET nor FRAPPE_PWD is set — see test/.env.local.example.")
    data = urllib.parse.urlencode({"usr": USER, "pwd": PWD}).encode()
    req = urllib.request.Request(
        LOGIN_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with _opener.open(req, timeout=10) as resp:
            if resp.status != 200:
                die(f"login failed: HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        die(f"login failed: HTTP {e.code} — check FRAPPE_USER/FRAPPE_PWD")
    except Exception as e:
        die(f"login failed: {e!r}")


def jsonrpc(method: str, params: dict | None = None, *, timeout: float = 60.0, req_id: int = 1) -> dict:
    """Send one JSONRPC envelope. Returns dict with timing + parsed body."""
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    headers = {"Content-Type": "application/json", **_auth_headers()}
    req = urllib.request.Request(
        MCP_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with _opener.open(req, timeout=timeout) as resp:
            body = resp.read().decode()
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"_parse_error": True, "raw": body[:500]}
            return {
                "ok_http": resp.status == 200,
                "http_status": resp.status,
                "latency_ms": elapsed_ms,
                "body_size": len(body),
                "json": parsed,
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok_http": False,
            "http_status": e.code,
            "latency_ms": elapsed_ms,
            "body_size": 0,
            "error": e.read().decode()[:500] if e.fp else str(e),
        }
    except Exception as e:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok_http": False,
            "http_status": None,
            "latency_ms": elapsed_ms,
            "body_size": 0,
            "error": f"{type(e).__name__}: {e}",
        }


def grade_tool_call(tool: str, raw: dict) -> tuple[str, str]:
    """Reduce a tools/call response into (status, detail).

    Status values:
        OK              — tool ran AND validator (if any) accepted the body
        OK_ERROR        — tool ran, returned error, acceptable per EXPECT_ERROR_OK
        TOOL_ERROR      — tool ran but errored (and we didn't expect that)
        VALIDATOR_FAIL  — tool ran without error but body shape was wrong
        WIRE_ERROR      — JSONRPC -32602 / -32601 / -32700 / network failure
        UNKNOWN         — unparseable response
    """
    if not raw.get("ok_http"):
        return "WIRE_ERROR", f"HTTP {raw.get('http_status')} — {str(raw.get('error', ''))[:200]}"
    j = raw.get("json", {})
    if "error" in j:
        e = j["error"]
        return "WIRE_ERROR", f"JSONRPC {e.get('code')}: {e.get('message')}"
    result = j.get("result", {})
    if "content" not in result:
        return "UNKNOWN", f"missing result.content; got {list(result)}"
    is_error = bool(result.get("isError"))
    text = ""
    body = {}
    try:
        text = result["content"][0]["text"]
        body = json.loads(text)
    except Exception:
        body = {}
    body_ok = body.get("ok") is True
    has_error = "error" in body and not body_ok
    if is_error or has_error:
        if tool in EXPECT_ERROR_OK:
            return "OK_ERROR", str(body.get("error", text))[:120]
        return "TOOL_ERROR", str(body.get("error", text))[:200]
    # No error → run validator if we have one
    validator = VALIDATORS.get(tool)
    if validator is not None:
        try:
            ok, detail = validator(body)
        except Exception as e:
            return "VALIDATOR_FAIL", f"validator threw: {type(e).__name__}: {e}"
        if not ok:
            return "VALIDATOR_FAIL", f"shape check failed — {detail}"
        return "OK", detail
    return "OK", _summarize(body)


def _summarize(body: dict) -> str:
    """One-line summary of a tool's success body — what came back, not how."""
    if not isinstance(body, dict):
        return f"({type(body).__name__})"
    interesting_keys = ("count", "rows", "result", "name", "doctype", "preview_token", "spec", "skills", "tools")
    parts = []
    for k in interesting_keys:
        if k not in body:
            continue
        v = body[k]
        if isinstance(v, list):
            parts.append(f"{k}=[{len(v)}]")
        elif isinstance(v, str) and len(v) > 32:
            parts.append(f"{k}={v[:30]}…")
        else:
            parts.append(f"{k}={v}")
        if len(parts) >= 3:
            break
    return ", ".join(parts) or "(empty result)"


def die(msg: str) -> None:
    print(f"[curl_smoke] FATAL: {msg}", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    print(f"[curl_smoke] target = {MCP_ENDPOINT}")
    print(f"[curl_smoke] auth = {'API key' if (KEY and SECRET) else f'login as {USER}'}")
    print(f"[curl_smoke] mode = {'QUICK_PROBE (9 user-flagged tools)' if QUICK else 'full run (all registered tools)'}")
    login()

    # 1. tools/list — drives the full coverage matrix
    listing = jsonrpc("tools/list", timeout=30, req_id=1)
    if not listing.get("ok_http"):
        die(f"tools/list failed at the wire: {listing}")
    j = listing["json"]
    if "error" in j:
        die(f"tools/list returned JSONRPC error: {j['error']}")
    registered = [t["name"] for t in j["result"]["tools"]]
    print(f"[curl_smoke] backend reports {len(registered)} registered tools — {listing['latency_ms']}ms")

    # 2. Decide which tools to call this run
    if QUICK:
        tools_to_call = [t for t in registered if t in QUICK_PROBE_TOOLS]
    else:
        tools_to_call = list(registered)

    # 3. Meta-probe: deliberately invalid tool name should return JSONRPC -32601
    meta = jsonrpc(
        "tools/call",
        {"name": "__lazychat_smoke_does_not_exist", "arguments": {}},
        timeout=10,
        req_id=999,
    )
    meta_err = meta.get("json", {}).get("error", {})
    if meta_err.get("code") != -32601:
        print(f"[curl_smoke] WARN: meta-probe expected JSONRPC -32601, got {meta_err}", file=sys.stderr)
    else:
        print(f"[curl_smoke] meta-probe OK — dispatcher rejects unknown tools — {meta['latency_ms']}ms")

    # 4. Run each tool with its canonical args
    results: dict[str, dict] = {}
    print()
    header = f"{'tool':<32} {'status':<10} {'latency':>8}  detail"
    print(header)
    print("-" * len(header))

    summary_counts = {"OK": 0, "OK_ERROR": 0, "TOOL_ERROR": 0, "VALIDATOR_FAIL": 0,
                      "WIRE_ERROR": 0, "MISSING_ARGS": 0, "SKIP_NEEDS_FIXTURE": 0, "UNKNOWN": 0}

    for n, tool in enumerate(tools_to_call, start=10):
        if tool in SKIP_NEEDS_FIXTURE:
            status, detail = "SKIP_NEEDS_FIXTURE", SKIP_NEEDS_FIXTURE[tool]
            results[tool] = {"status": status, "latency_ms": None, "detail": detail}
            print(f"{tool:<32} {status:<10} {'':>8}  {detail[:80]}")
            summary_counts[status] += 1
            continue
        if tool not in TOOL_ARGS:
            status, detail = "MISSING_ARGS", "no entry in tool_args.py — add canonical args"
            results[tool] = {"status": status, "latency_ms": None, "detail": detail}
            print(f"{tool:<32} {status:<10} {'':>8}  {detail[:80]}")
            summary_counts[status] += 1
            continue
        raw = jsonrpc("tools/call", {"name": tool, "arguments": TOOL_ARGS[tool]}, timeout=60, req_id=n)
        status, detail = grade_tool_call(tool, raw)
        results[tool] = {
            "status": status,
            "http_status": raw.get("http_status"),
            "latency_ms": raw.get("latency_ms"),
            "body_size": raw.get("body_size"),
            "detail": detail,
        }
        summary_counts[status] += 1
        print(f"{tool:<32} {status:<10} {raw['latency_ms']:>5}ms  {detail[:90]}")

    print()
    summary = " | ".join(f"{k}={v}" for k, v in summary_counts.items() if v)
    print(f"[curl_smoke] summary: {summary}")
    print(f"[curl_smoke] tools registered: {len(registered)}, called: {len(tools_to_call)}")

    # Tools registered but missing from our run (gap report)
    missing = [t for t in registered if t not in tools_to_call and t not in SKIP_NEEDS_FIXTURE]

    # 5. Persist
    out = {
        "endpoint": MCP_ENDPOINT,
        "auth": "api_key" if (KEY and SECRET) else f"login:{USER}",
        "ran_at": int(time.time()),
        "registered_tools": registered,
        "registered_count": len(registered),
        "called_count": len(tools_to_call),
        "summary": summary_counts,
        "results": results,
        "missing_from_args": missing,
    }
    out_path = RESULTS_DIR / ("layer1-quick.json" if QUICK else "layer1.json")
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"[curl_smoke] results → {out_path.relative_to(ROOT.parent)}")

    # Non-zero exit if anything failed beyond the expected categories
    bad = (summary_counts["TOOL_ERROR"] + summary_counts["WIRE_ERROR"]
           + summary_counts["UNKNOWN"] + summary_counts["VALIDATOR_FAIL"])
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
