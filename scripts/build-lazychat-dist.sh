#!/usr/bin/env bash
# Build the lazychat chat-ui SPA and bundle the output into the lazychat_erpnext Frappe app.
#
# After this runs, lazychat_erpnext/public/lazychat_dist/index.html exists and gets served at
#   /assets/lazychat_erpnext/lazychat_dist/index.html
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
APP_PUBLIC="$REPO_ROOT/lazychat_erpnext/public"
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

# ---------------------------------------------------------------------------
# Precompress static assets so nginx can serve `.br` / `.gz` sidecars with
# `brotli_static on; gzip_static on;` (see scripts/nginx-lazychat.conf.example).
# This shifts CPU from request-time on the production server to one-shot at
# build time and unlocks brotli quality 11 (impractical to negotiate live).
# Skipped silently when SKIP_PRECOMPRESS=1 (set in dev to keep builds fast).
# ---------------------------------------------------------------------------
SKIP_PRECOMPRESS="${SKIP_PRECOMPRESS:-0}"
if [[ "$SKIP_PRECOMPRESS" == "1" ]]; then
	echo "==> precompress: skipped (SKIP_PRECOMPRESS=1)"
else
	HAS_BROTLI=0
	command -v brotli >/dev/null 2>&1 && HAS_BROTLI=1
	if [[ "$HAS_BROTLI" == "0" ]]; then
		echo "==> precompress: brotli CLI not found — install with 'brew install brotli' (macOS) or 'apt-get install brotli' (Debian/Ubuntu). Skipping .br sidecars; .gz only." >&2
	fi

	# Only files >= 1024 bytes; smaller files cost more in compression overhead than they save on the wire.
	# Recompress when the source is newer than the sidecar (mtime check via `-nt`).
	count_br=0; count_gz=0
	while IFS= read -r -d '' f; do
		# Skip already-compressed sidecars themselves.
		case "$f" in *.br|*.gz) continue;; esac
		size=$(wc -c < "$f")
		[[ "$size" -lt 1024 ]] && continue
		if [[ "$HAS_BROTLI" == "1" ]] && { [[ ! -f "$f.br" ]] || [[ "$f" -nt "$f.br" ]]; }; then
			brotli -q 11 -f -k -o "$f.br" "$f" && count_br=$((count_br + 1))
		fi
		if [[ ! -f "$f.gz" ]] || [[ "$f" -nt "$f.gz" ]]; then
			gzip -9 -k -f -n "$f" && count_gz=$((count_gz + 1))
		fi
	done < <(find "$DIST_DST" -type f \( -name '*.js' -o -name '*.css' -o -name '*.svg' -o -name '*.json' -o -name '*.html' -o -name '*.map' \) -print0)
	echo "==> precompress: $count_br .br + $count_gz .gz sidecars written"
fi

echo ""
echo "================================================================"
echo "Built lazychat dist into lazychat_erpnext."
echo "Files:"
ls -la "$DIST_DST" | head -10
echo ""
echo "Next: ./scripts/deploy-local.sh   (rsync into bench + clear-cache)"
echo "================================================================"
