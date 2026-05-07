#!/usr/bin/env bash
# ============================================================================
# Lighthouse CI for the lazychat iframe URL.
#
# Runs Google Lighthouse against the bundled chat-ui SPA as it would be loaded
# inside the ERPNext Desk iframe, asserting performance budgets that catch
# regressions before they reach a user. Designed to be run on demand (or
# wired into CI as a non-blocking check until budgets are hardened).
#
# Usage:
#   ./scripts/lighthouse-iframe.sh                                  # against http://localhost:8000
#   SITE_URL=https://erp.example.com ./scripts/lighthouse-iframe.sh  # remote
#
# Env vars:
#   SITE_URL          base URL of the Frappe site (default: http://localhost:8000)
#   IFRAME_PATH       path to the iframe HTML (default: /assets/lazychat_mcp_erpnext/lazychat_dist/index.html?frame=sidebar)
#   PERF_MIN          performance score floor (0-100, default: 85)
#   FCP_MAX_MS        First Contentful Paint ceiling in ms (default: 1500)
#   LCP_MAX_MS        Largest Contentful Paint ceiling (default: 2500)
#   TBT_MAX_MS        Total Blocking Time ceiling (default: 300)
#   CLS_MAX           Cumulative Layout Shift ceiling (default: 0.05)
#   OUT_DIR           where to write the HTML report (default: ./lighthouse-out)
#
# Prerequisites:
#   - Node 18+ on PATH
#   - npx (bundled with npm)
#   - Chromium reachable to puppeteer (Lighthouse downloads its own copy on first run)
# ============================================================================
set -euo pipefail

SITE_URL="${SITE_URL:-http://localhost:8000}"
IFRAME_PATH="${IFRAME_PATH:-/assets/lazychat_mcp_erpnext/lazychat_dist/index.html?frame=sidebar}"
PERF_MIN="${PERF_MIN:-85}"
FCP_MAX_MS="${FCP_MAX_MS:-1500}"
LCP_MAX_MS="${LCP_MAX_MS:-2500}"
TBT_MAX_MS="${TBT_MAX_MS:-300}"
CLS_MAX="${CLS_MAX:-0.05}"
OUT_DIR="${OUT_DIR:-./lighthouse-out}"

URL="${SITE_URL}${IFRAME_PATH}"

mkdir -p "$OUT_DIR"
JSON_PATH="$OUT_DIR/lighthouse.json"
HTML_PATH="$OUT_DIR/lighthouse.html"

echo "==> Lighthouse: $URL"

# `--only-categories=performance` to keep the run fast; add a11y/seo separately if needed.
# `--preset=desktop` because the iframe always loads inside the Desk on a desktop browser.
# `--throttling-method=devtools` is the standard simulated-throttling profile.
npx --yes lighthouse "$URL" \
  --quiet \
  --chrome-flags="--headless=new --no-sandbox" \
  --preset=desktop \
  --only-categories=performance \
  --output=json --output=html \
  --output-path="$OUT_DIR/lighthouse" \
  >/dev/null

# Extract metrics with python (always available). Avoids depending on jq.
python3 - "$JSON_PATH" "$PERF_MIN" "$FCP_MAX_MS" "$LCP_MAX_MS" "$TBT_MAX_MS" "$CLS_MAX" <<'PY'
import json, sys

path, perf_min, fcp_max, lcp_max, tbt_max, cls_max = sys.argv[1:]
with open(path) as f:
    rep = json.load(f)

def m(audit_id):
    a = rep["audits"].get(audit_id, {})
    return a.get("numericValue"), a.get("displayValue")

perf_score = round((rep["categories"]["performance"]["score"] or 0) * 100)
fcp_ms, fcp_disp = m("first-contentful-paint")
lcp_ms, lcp_disp = m("largest-contentful-paint")
tbt_ms, tbt_disp = m("total-blocking-time")
cls_v,  cls_disp = m("cumulative-layout-shift")

print(f"  performance score : {perf_score:>5}    (floor {perf_min})")
print(f"  FCP               : {fcp_disp:>9}    (ceiling {fcp_max} ms)")
print(f"  LCP               : {lcp_disp:>9}    (ceiling {lcp_max} ms)")
print(f"  TBT               : {tbt_disp:>9}    (ceiling {tbt_max} ms)")
print(f"  CLS               : {cls_disp:>9}    (ceiling {cls_max})")

failures = []
if perf_score < int(perf_min):    failures.append(f"performance {perf_score} < {perf_min}")
if (fcp_ms or 0) > int(fcp_max):  failures.append(f"FCP {fcp_ms:.0f}ms > {fcp_max}ms")
if (lcp_ms or 0) > int(lcp_max):  failures.append(f"LCP {lcp_ms:.0f}ms > {lcp_max}ms")
if (tbt_ms or 0) > int(tbt_max):  failures.append(f"TBT {tbt_ms:.0f}ms > {tbt_max}ms")
if (cls_v  or 0) > float(cls_max):failures.append(f"CLS {cls_v:.3f} > {cls_max}")

if failures:
    print("\n  FAIL:")
    for f in failures: print("   - " + f)
    sys.exit(1)
print("\n  OK — all budgets met.")
PY

echo "==> Report: $HTML_PATH"
