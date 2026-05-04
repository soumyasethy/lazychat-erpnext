#!/usr/bin/env bash
# Stop local `bench start` (honcho) workers so Redis/web ports are free for a fresh start.
# Targets typical Frappe bench dev ports (8000 web, 9000 socketio, 11000/13000 Redis). Dev machine only —
# do not run if something unrelated intentionally uses those ports.
# Safe to run when nothing is running (no-op).
#
# Usage:
#   ./scripts/stop-bench-desk.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "==> Stopping honcho / bench dev processes (if any)..."
# bench start is implemented via honcho reading the bench Procfile
pkill -TERM -f "honcho start" 2>/dev/null || true
sleep 2

# If workers outlived honcho, free typical bench dev ports (web, socketio, Redis)
for port in 8000 9000 11000 13000; do
	pids="$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
	if [[ -n "${pids:-}" ]]; then
		echo "==> Freeing :$port (pid $pids)" >&2
		kill -TERM $pids 2>/dev/null || true
	fi
done
sleep 2

busy=""
for port in 8000 9000 11000 13000; do
	if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
		busy="$busy $port"
	fi
done
if [[ -n "${busy:-}" ]]; then
	echo "stop-bench-desk: Still listening —$busy; sending SIGKILL to listeners on dev ports" >&2
	for port in 8000 9000 11000 13000; do
		pids="$(lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
		if [[ -n "${pids:-}" ]]; then
			kill -KILL $pids 2>/dev/null || true
		fi
	done
	sleep 1
	busy=""
	for port in 8000 9000 11000 13000; do
		if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
			busy="$busy $port"
		fi
	done
fi
if [[ -n "${busy:-}" ]]; then
	echo "stop-bench-desk: Ports still busy —$busy" >&2
	echo "stop-bench-desk: Inspect with: lsof -nP -iTCP:8000 -sTCP:LISTEN" >&2
	exit 1
fi

echo "==> Bench dev ports are free. Start again with: \"$SCRIPT_DIR/start-bench-desk.sh\""
