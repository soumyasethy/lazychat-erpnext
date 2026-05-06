#!/usr/bin/env bash
# deploy-remote.sh — SSH-push lazychat_mcp_erpnext to a remote frappe-bench, clear-cache.
#
# Twin of deploy-local.sh, but the bench lives on another box. Use this for staging /
# teammate machines you have SSH to.
#
# Usage:
#   ./scripts/deploy-remote.sh user@host:/home/frappe/frappe-bench
#   REMOTE_SITE=stage.example.com ./scripts/deploy-remote.sh user@host:/abs/bench
#   REMOTE_RESTART=1 ./scripts/deploy-remote.sh user@host:/abs/bench   # also bench restart
#
# Env (read from environment OR scripts/deploy.env):
#   REMOTE_SITE      — site to clear-cache on (required if you want cache cleared)
#   REMOTE_RESTART   — 1 to also `bench restart` on remote (Linux/Supervisor box)
#   SSH_OPTS         — extra ssh args (e.g. "-i ~/.ssh/deploy_key -p 2222")
#
# Pre-req on the remote bench:
#   apps/lazychat_mcp_erpnext must already exist (one-time bootstrap):
#     ssh user@host "cd /abs/bench && bench get-app https://github.com/soumyasethy/lazychat-mcp-erpnext --branch release"
#     ssh user@host "cd /abs/bench && bench --site <site> install-app lazychat_mcp_erpnext"
#
set -euo pipefail
if [ -z "${BASH_VERSION:-}" ]; then exec /usr/bin/env bash "$0" "$@"; fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="lazychat_mcp_erpnext"
APP_SRC="$REPO_ROOT/$APP_NAME"

# shellcheck source=/dev/null
[[ -f "$SCRIPT_DIR/deploy.env" ]] && set -a && source "$SCRIPT_DIR/deploy.env" && set +a

TARGET="${1:-${REMOTE_BENCH:-}}"
[[ -n "$TARGET" ]] || { echo "deploy-remote: missing target. Usage: $0 user@host:/abs/path/to/frappe-bench" >&2; exit 1; }

if [[ "$TARGET" != *:* ]]; then
	echo "deploy-remote: target must be user@host:/abs/path (got: $TARGET)" >&2
	exit 1
fi
SSH_HOST="${TARGET%%:*}"
REMOTE_BENCH_PATH="${TARGET#*:}"
REMOTE_APP_PATH="$REMOTE_BENCH_PATH/apps/$APP_NAME"
REMOTE_SITE="${REMOTE_SITE:-}"
REMOTE_RESTART="${REMOTE_RESTART:-0}"
SSH_OPTS="${SSH_OPTS:-}"

[[ -d "$APP_SRC" ]] || { echo "deploy-remote: $APP_SRC missing" >&2; exit 1; }

# Sanity: confirm the app exists on the remote (avoid creating an unowned dir).
# shellcheck disable=SC2086
if ! ssh $SSH_OPTS "$SSH_HOST" "[ -d '$REMOTE_APP_PATH' ]"; then
	echo "deploy-remote: $REMOTE_APP_PATH does not exist on $SSH_HOST." >&2
	echo "deploy-remote: Bootstrap once with bench get-app on the remote (see header of this script)." >&2
	exit 1
fi

echo "==> rsync $APP_SRC/ → $SSH_HOST:$REMOTE_APP_PATH/"
# shellcheck disable=SC2086
rsync -az --delete \
	-e "ssh $SSH_OPTS" \
	--exclude '.git/' \
	--exclude '__pycache__/' \
	--exclude '*.pyc' \
	--exclude '.eggs/' \
	--exclude '*.egg-info/' \
	--exclude '.mypy_cache/' \
	--exclude '.pytest_cache/' \
	--exclude '.ruff_cache/' \
	"$APP_SRC/" "$SSH_HOST:$REMOTE_APP_PATH/"

remote_cmds="cd '$REMOTE_BENCH_PATH' && bench build --app $APP_NAME"
if [[ -n "$REMOTE_SITE" ]]; then
	remote_cmds+=" && bench --site '$REMOTE_SITE' clear-cache"
fi
if [[ "$REMOTE_RESTART" == "1" ]]; then
	remote_cmds+=" && bench restart"
fi

echo "==> ssh $SSH_HOST  →  $remote_cmds"
# shellcheck disable=SC2086
ssh $SSH_OPTS "$SSH_HOST" "$remote_cmds"

echo "deploy-remote: done. Hard-refresh the Desk on the remote site."
