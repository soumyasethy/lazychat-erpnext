#!/usr/bin/env python3
"""HTTP smoke test for the Bearer-auth Streamable-HTTP MCP endpoint.

Exercises mcp.handle_bearer (added 2026-05-10 for the claude.ai web Custom
Connector path). Companion to test/curl_smoke.py which covers the original
mcp.handle endpoint with `token KEY:SECRET` auth.

Reads the Bearer token from the BEARER_TOKEN env var so no credential lands
in the script. The token must match site_config `lazychat_mcp_bearer_token`.

Usage:
    BEARER_TOKEN="..." python3 test/bearer_smoke.py
    # or
    BEARER_TOKEN="..." FRAPPE_URL="http://localhost:8000" python3 test/bearer_smoke.py

Exits non-zero on any failed assertion.
"""
from __future__ import annotations
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("FRAPPE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("BEARER_TOKEN", "")
ENDPOINT = f"{URL}/api/method/lazychat_erpnext.desk_assistant.mcp.handle_bearer"

if not TOKEN:
    print("BEARER_TOKEN env var is required. Set it to the same value as site_config.lazychat_mcp_bearer_token.", file=sys.stderr)
    sys.exit(2)


def _request(payload: dict | None, headers: dict[str, str]) -> tuple[int, dict, dict]:
    """Returns (status, response_headers, parsed_body). On HTTPError still parses the body."""
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(ENDPOINT, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8")
            return r.status, dict(r.headers), json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"_raw": raw}
        return e.code, dict(e.headers or {}), parsed


def _ok(name: str) -> None:
    print(f"  OK  {name}")


def _fail(name: str, why: str) -> None:
    print(f"  FAIL {name}: {why}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    print(f"target: {ENDPOINT}")

    # 1. No Authorization header → 401
    status, _, body = _request({"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                {"Content-Type": "application/json"})
    if status == 401 and "Bearer" in body.get("error", ""):
        _ok("missing-auth → 401")
    else:
        _fail("missing-auth", f"got status={status} body={body}")

    # 2. Wrong Bearer token → 401
    status, _, body = _request({"jsonrpc": "2.0", "id": 2, "method": "ping"},
                                {"Content-Type": "application/json",
                                 "Authorization": "Bearer not-a-real-token"})
    if status == 401 and "Invalid" in body.get("error", ""):
        _ok("wrong-bearer → 401")
    else:
        _fail("wrong-bearer", f"got status={status} body={body}")

    # 3. Correct Bearer + ping → 200 + JSONRPC ok + Mcp-Session-Id header
    status, headers, body = _request({"jsonrpc": "2.0", "id": 3, "method": "ping"},
                                      {"Content-Type": "application/json",
                                       "Authorization": f"Bearer {TOKEN}"})
    if status != 200:
        _fail("ping", f"status={status} body={body}")
    if "result" not in body or body.get("id") != 3:
        _fail("ping", f"unexpected JSONRPC shape: {body}")
    if not headers.get("Mcp-Session-Id"):
        _fail("ping", "missing Mcp-Session-Id response header")
    _ok("good-bearer + ping → 200 + Mcp-Session-Id")

    # 4. Correct Bearer + tools/list → returns >0 tools with MCP-shaped schema
    status, _, body = _request({"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
                                {"Content-Type": "application/json",
                                 "Authorization": f"Bearer {TOKEN}"})
    if status != 200:
        _fail("tools/list", f"status={status} body={body}")
    tools = (body.get("result") or {}).get("tools") or []
    if len(tools) < 10:
        _fail("tools/list", f"expected ≥10 tools, got {len(tools)}")
    sample = tools[0]
    if not all(k in sample for k in ("name", "description", "inputSchema")):
        _fail("tools/list", f"first tool missing required keys: {sample.keys()}")
    _ok(f"good-bearer + tools/list → {len(tools)} tools, MCP-shaped")

    # 5. Correct Bearer + initialize → returns serverInfo
    status, _, body = _request({"jsonrpc": "2.0", "id": 5, "method": "initialize", "params": {}},
                                {"Content-Type": "application/json",
                                 "Authorization": f"Bearer {TOKEN}"})
    if status != 200:
        _fail("initialize", f"status={status} body={body}")
    result = body.get("result") or {}
    if not result.get("protocolVersion") or not result.get("serverInfo"):
        _fail("initialize", f"unexpected initialize response: {result}")
    _ok(f"good-bearer + initialize → protocolVersion={result['protocolVersion']}")

    # 6. Correct Bearer + tools/call (read-only get_doctype_count or similar)
    #    Pick a tool that exists in any install and takes no args.
    status, _, body = _request(
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "get_current_context", "arguments": {}}},
        {"Content-Type": "application/json",
         "Authorization": f"Bearer {TOKEN}"})
    if status != 200:
        _fail("tools/call", f"status={status} body={body}")
    result = body.get("result") or {}
    if "content" not in result:
        _fail("tools/call", f"missing content array: {result}")
    _ok("good-bearer + tools/call get_current_context → 200")

    print("\n[bearer_smoke] all OK")


if __name__ == "__main__":
    main()
