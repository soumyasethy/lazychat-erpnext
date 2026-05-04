#!/usr/bin/env bash
# Start Frappe Bench dev processes (web UI on http://127.0.0.1:8000 by default).
# Run this in a dedicated terminal and leave it open; Ctrl+C stops all workers.
#
# Usage:
#   chmod +x scripts/start-bench-desk.sh
#   ./scripts/start-bench-desk.sh
# If you see "Address already in use" on :11000 or :8000, another bench session is running:
#   ./scripts/stop-bench-desk.sh && ./scripts/start-bench-desk.sh
# Or one-shot:  START_REPLACE=1 ./scripts/start-bench-desk.sh
# Requires scripts/deploy.env with BENCH_ROOT=..., or export BENCH_ROOT.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# shellcheck source=/dev/null
[[ -f "$SCRIPT_DIR/deploy.env" ]] && set -a && source "$SCRIPT_DIR/deploy.env" && set +a

BENCH_ROOT="${BENCH_ROOT:-}"
if [[ -z "$BENCH_ROOT" && -f "$SCRIPT_DIR/bench-root.local" ]]; then
	BENCH_ROOT="$(grep -v '^[[:space:]]*#' "$SCRIPT_DIR/bench-root.local" | head -1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
fi

if [[ -z "$BENCH_ROOT" || ! -d "$BENCH_ROOT/apps" ]]; then
	echo "start-bench-desk: Set BENCH_ROOT (e.g. in scripts/deploy.env) to your frappe-bench directory." >&2
	exit 1
fi

if [[ "${START_REPLACE:-0}" == "1" ]]; then
	bash "$SCRIPT_DIR/stop-bench-desk.sh" || true
fi

if lsof -nP -iTCP:11000 -sTCP:LISTEN >/dev/null 2>&1 || lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
	echo "start-bench-desk: Ports already in use (bench or Redis already running?)." >&2
	echo "start-bench-desk: Run: \"$SCRIPT_DIR/stop-bench-desk.sh\"  then start again." >&2
	echo "start-bench-desk: Or: START_REPLACE=1 \"$SCRIPT_DIR/start-bench-desk.sh\"" >&2
	exit 1
fi

echo "==> Starting bench from: $BENCH_ROOT"
echo "==> Desk URL (after login): http://127.0.0.1:8000/app"
echo ""
cd "$BENCH_ROOT"
exec bench start
