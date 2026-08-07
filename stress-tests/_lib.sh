# shellcheck shell=bash
# Shared harness for px CLI stress tests.
#
# Source this from a scenario script:  source "$(dirname "$0")/_lib.sh"
#
# It provides: strict mode, px resolution, auth checks, a per-scenario
# persistent workspace (so re-runs update ONE project instead of littering the
# account — the CLI has no delete-project command), colored logging, and
# assertion helpers with a PASS/FAIL exit code.
#
# Env knobs:
#   JARVISPY_URL   platform base URL, e.g. https://api.prometheux.ai/jarvispy/prometheux/staging  (required)
#   PMTX_TOKEN     JWT for that account                                                            (required)
#   PX             path to the px binary (default: `px` on PATH, else repo .venv/bin/px)
#   PX_FRESH=1     start a brand-new project this run (creates an orphan on the account; see below)
#   PX_KEEP=1      keep the generated workspace on exit (default: kept anyway under .state/)
#   PG_PASSWORD/S3_*/…  any secrets a scenario's datasources reference via ${ENV}

set -euo pipefail

# --- resolve paths ---------------------------------------------------------
STRESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$STRESS_DIR/.." && pwd)"
STATE_DIR="$STRESS_DIR/.state"

# --- resolve the px binary -------------------------------------------------
if [[ -n "${PX:-}" ]]; then
  :
elif command -v px >/dev/null 2>&1; then
  PX="$(command -v px)"
elif [[ -x "$REPO_DIR/.venv/bin/px" ]]; then
  PX="$REPO_DIR/.venv/bin/px"
else
  echo "FATAL: no px binary found (not on PATH, no $REPO_DIR/.venv/bin/px). Set PX=." >&2
  exit 2
fi

# --- colors ----------------------------------------------------------------
if [[ -t 1 ]]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YLW=$'\033[33m'; C_CYN=$'\033[36m'; C_BLD=$'\033[1m'; C_RST=$'\033[0m'
else
  C_RED=; C_GRN=; C_YLW=; C_CYN=; C_BLD=; C_RST=
fi

# --- counters ---------------------------------------------------------------
_ASSERT_PASS=0
_ASSERT_FAIL=0
SCENARIO="${SCENARIO:-scenario}"

# --- logging ---------------------------------------------------------------
hr()   { printf '%s\n' "${C_CYN}────────────────────────────────────────────────────────${C_RST}"; }
step() { printf '\n%s▸ %s%s\n' "$C_BLD" "$*" "$C_RST"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '  %swarn%s %s\n' "$C_YLW" "$C_RST" "$*"; }

pass() { _ASSERT_PASS=$((_ASSERT_PASS+1)); printf '  %sPASS%s %s\n' "$C_GRN" "$C_RST" "$*"; }
fail() { _ASSERT_FAIL=$((_ASSERT_FAIL+1)); printf '  %sFAIL%s %s\n' "$C_RED" "$C_RST" "$*"; }
die()  { printf '%sFATAL%s %s\n' "$C_RED" "$C_RST" "$*" >&2; exit 2; }

# --- auth guard -------------------------------------------------------------
require_auth() {
  [[ -n "${JARVISPY_URL:-}" ]] || die "JARVISPY_URL is not set (e.g. https://api.prometheux.ai/jarvispy/prometheux/staging)"
  [[ -n "${PMTX_TOKEN:-}"  ]] || die "PMTX_TOKEN is not set (your account JWT)"
  export JARVISPY_URL PMTX_TOKEN
  info "account: ${JARVISPY_URL}"
}

# --- px wrapper: echoes the command, streams output ------------------------
# Usage: px_run <args...>   -> runs, tees stdout+stderr to $LAST_OUT, returns px exit code
LAST_OUT=""
px_run() {
  printf '  %s$ px %s%s\n' "$C_CYN" "$*" "$C_RST"
  LAST_OUT="$("$PX" "$@" 2>&1)" && local rc=0 || local rc=$?
  # indent the captured output for readability
  if [[ -n "$LAST_OUT" ]]; then printf '%s\n' "$LAST_OUT" | sed 's/^/    /'; fi
  return "$rc"
}

# --- assertions -------------------------------------------------------------
assert_ok()        { if px_run "$@"; then pass "px $1 exited 0"; else fail "px $1 exited $? (expected 0)"; fi; }
assert_out_has()   { if grep -qiF -- "$1" <<<"$LAST_OUT"; then pass "output contains: $1"; else fail "output missing: $1"; fi; }
assert_out_lacks() { if grep -qiF -- "$1" <<<"$LAST_OUT"; then fail "output unexpectedly contains: $1"; else pass "output lacks: $1"; fi; }
assert_file()      { if [[ -f "$1" ]]; then pass "file exists: ${1#$STATE_DIR/}"; else fail "file missing: $1"; fi; }

# Idempotency: a plan right after apply must report no drift.
assert_plan_clean() {
  if px_run plan "$@"; then
    if grep -qF "No changes. Local files match server state." <<<"$LAST_OUT"; then
      pass "plan is clean (idempotent)"
    else
      fail "plan reported drift right after apply (not idempotent)"
    fi
  else
    fail "px plan exited non-zero"
  fi
}

# --- per-scenario workspace -------------------------------------------------
# Persistent under .state/<scenario>/ws so the project id (written back into
# prometheux.yaml on first apply) survives across runs and we update ONE
# project. PX_FRESH=1 discards it and creates a new project (an orphan — the
# CLI can't delete projects; note it to the operator).
WS=""
new_workspace() {
  local ws="$STATE_DIR/$SCENARIO/ws"
  local saved_id=""
  local manifest="$ws/projects/$SCENARIO/prometheux.yaml"
  if [[ -f "$manifest" && "${PX_FRESH:-}" != "1" ]]; then
    saved_id="$(sed -n 's/^[[:space:]]*id:[[:space:]]*//p' "$manifest" | head -1 || true)"
  fi
  if [[ "${PX_FRESH:-}" == "1" && -f "$STATE_DIR/$SCENARIO/last_id" ]]; then
    warn "PX_FRESH=1: previous project $(cat "$STATE_DIR/$SCENARIO/last_id") is now orphaned on the account (no CLI delete)."
  fi
  rm -rf "$ws"
  mkdir -p "$ws"
  WS="$ws"
  SAVED_PROJECT_ID="$saved_id"
  if [[ -n "$saved_id" ]]; then
    info "reusing project id $saved_id (set PX_FRESH=1 to start a new one)"
  fi
}

# Record the applied project id for next run's reuse + the orphan warning.
remember_project_id() {
  local manifest="$WS/projects/$SCENARIO/prometheux.yaml"
  [[ -f "$manifest" ]] || return 0
  sed -n 's/^[[:space:]]*id:[[:space:]]*//p' "$manifest" | head -1 > "$STATE_DIR/$SCENARIO/last_id" || true
}

# --- summary + exit code ----------------------------------------------------
_summarize() {
  hr
  local total=$((_ASSERT_PASS+_ASSERT_FAIL))
  if [[ "$_ASSERT_FAIL" -eq 0 && "$total" -gt 0 ]]; then
    printf '%s%s: PASS%s  (%d checks)\n' "$C_GRN" "$SCENARIO" "$C_RST" "$total"
    exit 0
  else
    printf '%s%s: FAIL%s  (%d/%d checks failed)\n' "$C_RED" "$SCENARIO" "$C_RST" "$_ASSERT_FAIL" "$total"
    exit 1
  fi
}
trap _summarize EXIT
