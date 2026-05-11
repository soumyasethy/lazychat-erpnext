#!/usr/bin/env bash
# Sync lazychat_erpnext into local frappe-bench, migrate DB, build assets, optional clear-cache.
#
# Typical bench sequence (this script automates when DEPLOY_SITE is set):
#   bench --site <site> migrate     — doctypes, LLM Provider Header, seed JSON (Provider/Model), branding patch
#   bench build --app lazychat_erpnext — bundles llm_setup_shared.js, llm_provider_form.js, llm_model_form.js, llm_setup.css
#   bench --site <site> clear-cache — after DB is reachable (refresh Desk hook metadata)
#
# Usage (use bash or execute directly — avoid `sh`, which skips the shebang):
#   chmod +x scripts/deploy-local.sh
#   ./scripts/deploy-local.sh
#   bash scripts/deploy-local.sh
#
# Overrides (optional):
#   BENCH_ROOT=/path/to/bench DEPLOY_SITE=erp.local ./scripts/deploy-local.sh
#   FRAPPE_BENCH_ROOT=/path/to/bench ./scripts/deploy-local.sh   # same as BENCH_ROOT if unset
#   echo /path/to/bench > scripts/bench-root.local                # one-line pin (gitignored)
#   SKIP_SYNC=1 ./scripts/deploy-local.sh
#   SKIP_MIGRATE=1 ./scripts/deploy-local.sh
#   ./scripts/deploy-local.sh --quick   # force skip migrate this run
#   ./scripts/deploy-local.sh --full    # force migrate this run (DocTypes/seeds)
set -euo pipefail

# Invoked as `sh this-script.sh` ignores the shebang; non-bash sh may break [[, arrays, etc.
if [ -z "${BASH_VERSION:-}" ]; then
	exec /usr/bin/env bash "$0" "$@"
fi

# Absolute dir of this script (works for ./scripts/x.sh, sh ./scripts/x.sh, and cwd≠repo root when path is relative)
_script_resolve="$0"
[[ $_script_resolve == */* ]] || _script_resolve="./$_script_resolve"
SCRIPT_DIR="$(cd "$(dirname "$_script_resolve")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="lazychat_erpnext"
# Repo root IS the Frappe app dir — pyproject.toml + the lazychat_erpnext/ package
# live at the top level (like every Frappe app, and what `bench get-app` expects).
# So the local rsync mirrors repo-root → <bench>/apps/lazychat_erpnext/.
APP_SRC="$REPO_ROOT"

is_valid_bench() {
	[[ -n "${1:-}" && -d "$1/apps" && -d "$1/sites" ]]
}

# shellcheck source=/dev/null
[[ -f "$SCRIPT_DIR/deploy.env" ]] && set -a && source "$SCRIPT_DIR/deploy.env" && set +a

BENCH_ROOT="${BENCH_ROOT:-}"

# deploy.env may still contain the placeholder path — treat as unset and try discovery
if [[ -n "$BENCH_ROOT" ]] && ! is_valid_bench "$BENCH_ROOT"; then
	echo "deploy-local: BENCH_ROOT is not a valid bench (needs existing apps/ and sites/): $BENCH_ROOT" >&2
	echo "deploy-local: Fix scripts/deploy.env, or remove BENCH_ROOT there to allow auto-discovery." >&2
	BENCH_ROOT=""
fi

discover_bench_root() {
	local line p
	if [[ -f "$SCRIPT_DIR/bench-root.local" ]]; then
		line="$(grep -v '^[[:space:]]*#' "$SCRIPT_DIR/bench-root.local" 2>/dev/null | head -1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
		if [[ -n "$line" ]] && is_valid_bench "$line"; then
			echo "$line"
			return 0
		fi
	fi
	for p in "${FRAPPE_BENCH_ROOT:-}" "${FRAPPE_BENCH:-}" "$REPO_ROOT/../frappe-bench" "$REPO_ROOT/../../frappe-bench" "$HOME/frappe-bench" "$HOME/bench"; do
		[[ -z "$p" ]] && continue
		if is_valid_bench "$p"; then
			echo "$p"
			return 0
		fi
	done
	return 1
}

if [[ -z "$BENCH_ROOT" ]]; then
	if discovered="$(discover_bench_root)"; then
		BENCH_ROOT="$discovered"
		echo "deploy-local: Using bench at $BENCH_ROOT (auto-discovered)." >&2
		echo "deploy-local: To pin this path: printf '%s\n' \"$BENCH_ROOT\" > \"$SCRIPT_DIR/bench-root.local\"" >&2
	fi
fi
DEPLOY_SITE="${DEPLOY_SITE:-}"
SKIP_SYNC="${SKIP_SYNC:-0}"
# Default skip migrate (fast routine deploys). Override in deploy.env or use --full when DocTypes/seeds change.
SKIP_MIGRATE="${SKIP_MIGRATE:-1}"
SKIP_CACHE="${SKIP_CACHE:-0}"

usage() {
	cat <<'EOF'
Sync lazychat_erpnext into BENCH_ROOT, migrate (optional), bench build, optional clear-cache.

  ./scripts/deploy-local.sh

  If BENCH_ROOT is unset, the script tries (in order): scripts/bench-root.local,
  FRAPPE_BENCH_ROOT / FRAPPE_BENCH, ../frappe-bench, ~/frappe-bench, ~/bench.

  cp scripts/deploy.env.example scripts/deploy.env
  edit scripts/deploy.env (BENCH_ROOT, DEPLOY_SITE; SKIP_MIGRATE defaults to 1 for speed)

With DEPLOY_SITE set:
  1) bench migrate   — optional (skipped when SKIP_MIGRATE=1 or --quick; use --full after DocType/seed changes)
  2) bench build --app lazychat_erpnext — JS/CSS bundles
  3) bench clear-cache — Desk cache

Env / flags: BENCH_ROOT, DEPLOY_SITE, SKIP_SYNC, SKIP_MIGRATE, SKIP_CACHE,
  RESTART_BENCH (unset → 0 on macOS, 1 on Linux), --quick, --full,
  START_BENCH_AFTER_DEPLOY=1 (stop honcho + free :8000/:9000/:11000/:13000, then bench start in background),
  START_BENCH_IF_DOWN=1 (start in background only if nothing on :8000/:11000; no kill)
EOF
	exit 0
}

for arg in "$@"; do
	case "$arg" in
	-h | --help) usage ;;
	--quick) SKIP_MIGRATE=1 ;;
	--full) SKIP_MIGRATE=0 ;;
	esac
done

# RESTART_BENCH: bench restart uses Supervisor (frappe:) — absent on typical macOS dev → noisy failure.
# If unset: macOS defaults to 0; Linux defaults to 1. Override in deploy.env.
if [[ -z "${RESTART_BENCH+x}" ]]; then
	RESTART_BENCH=1
	case "$(uname -s 2>/dev/null)" in
	Darwin) RESTART_BENCH=0 ;;
	esac
fi

die() {
	echo "deploy-local: $*" >&2
	exit 1
}

[[ -f "$APP_SRC/pyproject.toml" && -d "$APP_SRC/$APP_NAME" ]] || die "not a Frappe app root: $APP_SRC (expected pyproject.toml + $APP_NAME/ here)"
if [[ -z "$BENCH_ROOT" ]]; then
	echo "deploy-local: Could not find a frappe-bench directory (must contain apps/ and sites/)." >&2
	echo "" >&2
	echo "  Pick ONE of these:" >&2
	echo "" >&2
	echo "  1) Pin your bench path (one line, then re-run this script):" >&2
	echo "       printf '%s\n' /absolute/path/to/your/frappe-bench > \"$SCRIPT_DIR/bench-root.local\"" >&2
	echo "" >&2
	echo "  2) Or set BENCH_ROOT for a single run:" >&2
	echo "       BENCH_ROOT=/absolute/path/to/frappe-bench \"$SCRIPT_DIR/deploy-local.sh\"" >&2
	echo "" >&2
	echo "  3) Or use deploy.env:" >&2
	echo "       cp \"$SCRIPT_DIR/deploy.env.example\" \"$SCRIPT_DIR/deploy.env\"" >&2
	echo "       # Edit BENCH_ROOT= to your real bench path (not the placeholder)." >&2
	echo "" >&2
	echo "  Optional env (same as BENCH_ROOT): FRAPPE_BENCH_ROOT or FRAPPE_BENCH" >&2
	exit 1
fi
is_valid_bench "$BENCH_ROOT" || die "invalid BENCH_ROOT (need apps/ and sites/): $BENCH_ROOT"

APP_DST="$BENCH_ROOT/apps/$APP_NAME"
[[ -d "$APP_DST" ]] || die "bench app not installed: $APP_DST (get-app or clone the app into apps/ first)"

echo "==> Repo:     $REPO_ROOT"
echo "==> Bench:    $BENCH_ROOT"
echo "==> App:      $APP_SRC -> $APP_DST"
if [[ "$SKIP_MIGRATE" == "1" ]]; then
	echo "==> Migrate:  skipped (use --full after DocType/fixture changes)"
elif [[ -n "${DEPLOY_SITE}" ]]; then
	echo "==> Migrate:  will run bench --site ${DEPLOY_SITE} migrate"
else
	echo "==> Migrate:  not running (set DEPLOY_SITE in deploy.env to migrate)"
fi

if [[ "$SKIP_SYNC" != "1" ]]; then
	echo "==> rsync app into bench (excludes venv/git/egg caches)..."
	rsync -a \
		--delete \
		--exclude '.git/' \
		--exclude '__pycache__/' \
		--exclude '*.pyc' \
		--exclude '.eggs/' \
		--exclude '*.egg-info/' \
		--exclude '.mypy_cache/' \
		--exclude '.pytest_cache/' \
		--exclude '.ruff_cache/' \
		--exclude '.cursor/' \
		--exclude '.github/' \
		--exclude 'test/evidence/' \
		--exclude 'test/results/' \
		--exclude 'test/.env.local' \
		"$APP_SRC/" "$APP_DST/"
else
	echo "==> SKIP_SYNC=1 — not rsyncing"
fi

if [[ "$SKIP_MIGRATE" == "1" ]]; then
	: # already logged above
elif [[ -n "${DEPLOY_SITE}" ]]; then
	echo "==> bench --site ${DEPLOY_SITE} migrate (doctypes, seeds, after_migrate hooks) ..."
	(
		cd "$BENCH_ROOT"
		bench --site "${DEPLOY_SITE}" migrate
	)
else
	echo "==> DEPLOY_SITE not set — skipping migrate. Set DEPLOY_SITE in deploy.env, or run:"
	echo "    cd \"$BENCH_ROOT\" && bench --site <yoursite> migrate"
fi

echo "==> bench build --app $APP_NAME (llm_setup_shared, form scripts, llm_setup.css) ..."
(
	cd "$BENCH_ROOT"
	bench build --app "$APP_NAME"
)

if [[ "$SKIP_CACHE" == "1" ]]; then
	echo "==> SKIP_CACHE=1 — skipping clear-cache"
elif [[ -n "${DEPLOY_SITE}" ]]; then
	echo "==> bench --site ${DEPLOY_SITE} clear-cache ..."
	if (
		cd "$BENCH_ROOT"
		bench --site "${DEPLOY_SITE}" clear-cache
	); then
		echo "==> Cache cleared for site: ${DEPLOY_SITE}"
	else
		echo "deploy-local: clear-cache failed (DB off or wrong credentials?). Desk assets are still built; fix DB and run:" >&2
		echo "  cd \"$BENCH_ROOT\" && bench --site ${DEPLOY_SITE} clear-cache" >&2
	fi
else
	echo "==> DEPLOY_SITE not set — skipping clear-cache. Set it in deploy.env to refresh Desk hooks metadata."
fi

if [[ "${START_BENCH_AFTER_DEPLOY:-0}" == "1" ]]; then
	: # bench restarted below — avoid "restart manually" noise
elif [[ "${RESTART_BENCH}" == "1" ]]; then
	echo "==> bench restart (reload workers so hooks.py re-reads asset mtimes for ?v= cache-bust) ..."
	_restart_log="$(mktemp "${TMPDIR:-/tmp}/deploy-local-restart.XXXXXX")"
	if (cd "$BENCH_ROOT" && bench restart) >"${_restart_log}" 2>&1; then
		echo "==> Bench restarted."
		rm -f "${_restart_log}"
	else
		echo "deploy-local: bench restart failed — workers may still be running old code." >&2
		echo "deploy-local: On macOS without Supervisor, set RESTART_BENCH=0 in scripts/deploy.env (default there on Darwin)." >&2
		echo "deploy-local: Last lines from bench restart:" >&2
		tail -25 "${_restart_log}" >&2 || true
		rm -f "${_restart_log}"
		echo "deploy-local: Or restart manually: cd \"$BENCH_ROOT\" && bench restart   # Linux/production with Supervisor" >&2
	fi
else
	echo "==> RESTART_BENCH=0 — Shift+Reload Desk for new JS/CSS (no Supervisor on this Mac)."
fi

_bench_start_background() {
	local _logdir="$BENCH_ROOT/logs"
	mkdir -p "$_logdir"
	local _log="$_logdir/bench-dev-background.log"
	echo "==> Starting bench in background → $_log"
	nohup bash -c "cd \"$BENCH_ROOT\" && exec bench start" >>"$_log" 2>&1 &
	echo "==> tail -f \"$_log\"   # foreground: \"$SCRIPT_DIR/start-bench-desk.sh\""
}

if [[ "${START_BENCH_AFTER_DEPLOY:-0}" == "1" ]]; then
	echo "==> START_BENCH_AFTER_DEPLOY=1 — stopping existing bench/honcho on dev ports, then starting bench ..."
	if bash "$SCRIPT_DIR/stop-bench-desk.sh"; then
		_bench_start_background
	else
		echo "deploy-local: stop-bench-desk could not free all ports; not auto-starting bench." >&2
		echo "deploy-local: Inspect: lsof -nP -iTCP:8000 -sTCP:LISTEN" >&2
	fi
elif [[ "${START_BENCH_IF_DOWN:-0}" == "1" ]]; then
	if lsof -nP -iTCP:11000 -sTCP:LISTEN >/dev/null 2>&1 || lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
		echo "==> START_BENCH_IF_DOWN=1 — :8000 or :11000 already in use; not starting (use START_BENCH_AFTER_DEPLOY=1 to replace)."
	else
		_bench_start_background
	fi
fi

echo ""
echo "================================================================"
echo "Done."
if [[ "${START_BENCH_AFTER_DEPLOY:-0}" == "1" ]]; then
	echo "  Desk:      http://127.0.0.1:8000/app"
	echo "  Bench log: $BENCH_ROOT/logs/bench-dev-background.log"
	echo "  Watch log: tail -f \"$BENCH_ROOT/logs/bench-dev-background.log\""
	[[ "$SKIP_MIGRATE" == "1" ]] && echo "  Note:      migrate skipped — run $SCRIPT_DIR/deploy-local.sh --full after DocType/fixture changes."
elif [[ "$SKIP_MIGRATE" == "1" ]]; then
	echo "  DB migrate skipped. Schema/fixtures:  $SCRIPT_DIR/deploy-local.sh --full"
	echo "  Shift+Reload browser. Start bench:     $SCRIPT_DIR/start-bench-desk.sh"
	echo "  Auto stop+start bench after deploy:    START_BENCH_AFTER_DEPLOY=1 in scripts/deploy.env"
else
	echo "  Shift+Reload the browser."
fi
echo "================================================================"
