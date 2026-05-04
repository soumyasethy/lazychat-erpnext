#!/usr/bin/env bash
# Build the lazychat chat-ui SPA and bundle the output into the lazychat_mcp_erpnext Frappe app.
#
# After this runs, lazychat_mcp_erpnext/public/lazychat_dist/index.html exists and gets served at
#   /assets/lazychat_mcp_erpnext/lazychat_dist/index.html
# on every bench that has the app installed. The boot extension uses that path as the iframe
# src in production (developer_mode = 0).
#
# Usage:
#   ./scripts/build-lazychat-dist.sh                # auto-discovers ../lazychat.ai
#   LAZYCHAT_REPO=/abs/path/to/lazychat.ai ./scripts/build-lazychat-dist.sh
#   SKIP_INSTALL=1 ./scripts/build-lazychat-dist.sh # skip pnpm install (faster repeat builds)
#
# Then deploy to a bench:
#   BENCH_ROOT=/abs/path DEPLOY_SITE=erp.local ./scripts/deploy-local.sh
set -euo pipefail

if [ -z "${BASH_VERSION:-}" ]; then
	exec /usr/bin/env bash "$0" "$@"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_PUBLIC="$REPO_ROOT/lazychat_mcp_erpnext/lazychat_mcp_erpnext/public"
DIST_DST="$APP_PUBLIC/lazychat_dist"

LAZYCHAT_REPO="${LAZYCHAT_REPO:-}"
SKIP_INSTALL="${SKIP_INSTALL:-0}"

discover_lazychat_repo() {
	local p
	for p in "$REPO_ROOT/../lazychat.ai" "$REPO_ROOT/../../lazychat.ai" "$HOME/code-chat/lazychat.ai" "$HOME/Desktop/code-chat/lazychat.ai"; do
		if [[ -f "$p/pnpm-workspace.yaml" || -f "$p/package.json" ]] && [[ -d "$p/apps/chat-ui" ]]; then
			echo "$p"
			return 0
		fi
	done
	return 1
}

if [[ -z "$LAZYCHAT_REPO" ]]; then
	if discovered="$(discover_lazychat_repo)"; then
		LAZYCHAT_REPO="$discovered"
	else
		echo "build-lazychat-dist: Could not find the lazychat.ai repo." >&2
		echo "  Set LAZYCHAT_REPO=/abs/path/to/lazychat.ai and re-run." >&2
		exit 1
	fi
fi

[[ -d "$LAZYCHAT_REPO/apps/chat-ui" ]] || { echo "build-lazychat-dist: not a lazychat repo: $LAZYCHAT_REPO" >&2; exit 1; }

echo "==> Source:  $LAZYCHAT_REPO"
echo "==> Target:  $DIST_DST"

if [[ "$SKIP_INSTALL" != "1" ]]; then
	echo "==> pnpm install (skip with SKIP_INSTALL=1) ..."
	(cd "$LAZYCHAT_REPO" && pnpm install --frozen-lockfile=false)
fi

echo "==> pnpm --filter chat-ui build ..."
(cd "$LAZYCHAT_REPO" && pnpm --filter chat-ui build)

DIST_SRC="$LAZYCHAT_REPO/apps/chat-ui/dist"
[[ -d "$DIST_SRC" ]] || { echo "build-lazychat-dist: build did not produce $DIST_SRC" >&2; exit 1; }

mkdir -p "$DIST_DST"
echo "==> rsync dist into app ..."
rsync -a --delete "$DIST_SRC/" "$DIST_DST/"

echo ""
echo "================================================================"
echo "Built lazychat dist into lazychat_mcp_erpnext."
echo "Files:"
ls -la "$DIST_DST" | head -10
echo ""
echo "Next: ./scripts/deploy-local.sh   (rsync into bench + clear-cache)"
echo "================================================================"
