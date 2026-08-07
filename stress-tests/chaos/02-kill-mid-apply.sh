#!/usr/bin/env bash
#
# Chaos #1 — interrupted `px apply` → duplicate-project check.
#
# apply.py:179-180 does _create_project() (server insert) then, on the NEXT line,
# _persist_project_id() (writes the new id into prometheux.yaml). If the process
# dies — or the write-back fails for any reason — in that window, the server has
# a project but the files never learned its id, so a RETRY of the same id-less
# files creates a TWIN. Invariant: an interrupted apply + retry must leave
# EXACTLY ONE project.
#
# Phase A (opportunistic): SIGKILL apply at random early delays. Note this can
#   only occasionally *confirm* the race — killing at the exact microsecond is
#   nearly impossible, so a clean Phase A never *clears* it.
# Phase B (deterministic): make the manifest read-only so the id write-back
#   fails after the server insert, then retry. This forces the exact fault the
#   crash-window would cause, with no timing luck. THIS is the real verdict.
#
# Usage:  JARVISPY_URL=... PMTX_TOKEN=... ./02-kill-mid-apply.sh [PHASE_A_ATTEMPTS]
# Creates + deletes its own throwaway projects.

SCENARIO="pxst-chaos-kill"
source "$(dirname "$0")/../_lib.sh"

ATTEMPTS="${1:-8}"

hr; printf '%sChaos: interrupted apply → duplicate-project check%s\n' "$C_BLD" "$C_RST"; hr
require_auth

build_ws() {  # build_ws <dir> <project-name> — tiny id-less project, no datasources
  local d="$1" name="$2"
  rm -rf "$d"; mkdir -p "$d/projects/k/concepts"
  cat > "$d/prometheux.workspace.yaml" <<YAML
schemaVersion: 1
workspace:
  name: chaos-kill
projects:
  - ./projects/k
YAML
  cat > "$d/projects/k/prometheux.yaml" <<YAML
schemaVersion: 1
project:
  name: $name
  scope: user
concepts: ./concepts
YAML
  printf 'a(1).\na(2).\n' > "$d/projects/k/concepts/a.vadalog"
  printf 'conceptType: logic\noutputPredicate: a\n' > "$d/projects/k/concepts/a.meta.yaml"
}

ids_for_name() { "$PX" pull 2>/dev/null | awk -v n="$1" '{ id=$1; $1=""; sub(/^ +/,""); if ($0==n) print id }'; }
count_name()   { ids_for_name "$1" | grep -c . ; }
teardown_name(){ while read -r pid; do [[ -n "$pid" ]] && "$PX" delete "$pid" -y >/dev/null 2>&1 && info "deleted $pid"; done < <(ids_for_name "$1"); }

# ─── Phase A — opportunistic timing kills ───────────────────────────────────
A_NAME="Chaos Kill Test"
step "Phase A: SIGKILL apply at random early delays ($ATTEMPTS attempts)"
info "note: this can confirm the race but never clear it (timing luck)."
for ((i = 1; i <= ATTEMPTS; i++)); do
  ws="$STATE_DIR/$SCENARIO/a-$i"
  build_ws "$ws" "$A_NAME"
  delay="$(awk -v i="$i" 'BEGIN { srand(i*7+1); printf "%.3f", 0.005 + rand()*0.20 }')"
  "$PX" apply "$ws" -y >"$ws/apply.log" 2>&1 &
  pid=$!; sleep "$delay"; kill -9 "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true
  "$PX" apply "$ws" -y >"$ws/retry.log" 2>&1 || true
done
made_a="$(count_name "$A_NAME")"
if [[ "$made_a" -le "$ATTEMPTS" ]]; then
  pass "Phase A: no duplicates ($made_a projects from $ATTEMPTS attempts)"
else
  fail "Phase A: DUPLICATES — $made_a projects from $ATTEMPTS attempts (race hit $((made_a - ATTEMPTS))x)"
fi
teardown_name "$A_NAME"

# ─── Phase B — deterministic write-back fault ───────────────────────────────
B_NAME="Chaos Writeback Test"
step "Phase B: block the id write-back (read-only manifest), then retry"
teardown_name "$B_NAME"                              # ensure a clean start
ws="$STATE_DIR/$SCENARIO/b"
build_ws "$ws" "$B_NAME"
chmod 444 "$ws/projects/k/prometheux.yaml"           # write-back will fail after the server insert
info "apply #1 (creates the project server-side; id write-back should fail)"
"$PX" apply "$ws" -y >"$ws/apply1.log" 2>&1 || true
grep -q "Traceback (most recent call last)" "$ws/apply1.log" && warn "apply #1 crashed with a traceback (uncaught write-back error)"
chmod 644 "$ws/projects/k/prometheux.yaml"
has_id="$(sed -n 's/^[[:space:]]*id:[[:space:]]*//p' "$ws/projects/k/prometheux.yaml" | head -1)"
info "id persisted to manifest after apply #1: ${has_id:-<none>}"
info "apply #2 (retry of the same files)"
"$PX" apply "$ws" -y >"$ws/apply2.log" 2>&1 || true
made_b="$(count_name "$B_NAME")"
if [[ "$made_b" -le 1 ]]; then
  pass "Phase B: no duplicate ($made_b project) — write-back failure is recovered"
else
  fail "Phase B: DUPLICATE — $made_b projects from one logical apply (server-insert not recoverable without persisted id)"
fi
teardown_name "$B_NAME"
