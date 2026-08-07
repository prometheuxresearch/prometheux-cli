#!/usr/bin/env bash
#
# Chaos #1 — kill `px apply` mid-flight and check for duplicate projects.
#
# Hypothesis (from apply.py:179-180): _create_project() creates the project on
# the server, then _persist_project_id() writes the new id back on the NEXT line.
# If the process dies in that window (or during the create HTTP call), the server
# has a project but the manifest never learned its id — so RE-APPLYING the same
# files creates a TWIN. Invariant under test: an interrupted apply + retry must
# leave EXACTLY ONE project, never a duplicate.
#
# Each attempt uses a fresh, id-less workspace with the SAME project name, runs
# `apply` and SIGKILLs it after a small random delay, then re-applies to
# completion. After N attempts we count projects with that name: if there are
# more than N, the interrupt produced orphans → the race is real.
#
# Usage:  JARVISPY_URL=... PMTX_TOKEN=... ./02-kill-mid-apply.sh [ATTEMPTS]
# Cleans up every project it created (by id) at the end.

SCENARIO="pxst-chaos-kill"
source "$(dirname "$0")/../_lib.sh"

NAME="Chaos Kill Test"
ATTEMPTS="${1:-16}"

hr; printf '%sChaos: kill px apply mid-flight → duplicate-project check%s\n' "$C_BLD" "$C_RST"; hr
require_auth

build_ws() {  # build_ws <dir> — a tiny id-less project (no datasources → no data-manager needed)
  local d="$1"
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
  name: $NAME
  scope: user
concepts: ./concepts
YAML
  printf 'a(1).\na(2).\n' > "$d/projects/k/concepts/a.vadalog"
  printf 'conceptType: logic\noutputPredicate: a\n' > "$d/projects/k/concepts/a.meta.yaml"
  printf 'b(X) :- a(X).\n' > "$d/projects/k/concepts/b.vadalog"
  printf 'conceptType: logic\noutputPredicate: b\n' > "$d/projects/k/concepts/b.meta.yaml"
}

ids_for_name() {  # print server project ids whose name == $NAME, one per line
  "$PX" pull 2>/dev/null | awk -v n="$NAME" '{ id=$1; $1=""; sub(/^ +/,""); if ($0==n) print id }'
}

pre="$(ids_for_name | wc -l | tr -d ' ')"
info "projects named \"$NAME\" before: $pre (expected 0 on a clean account)"

for ((i = 1; i <= ATTEMPTS; i++)); do
  ws="$STATE_DIR/$SCENARIO/attempt-$i"
  build_ws "$ws"
  # Sweep the create HTTP window finely: apply often finishes in <0.2s on a
  # fast account, so bias delays SMALL (early) to catch it mid-create rather
  # than after it has already completed.
  delay="$(awk -v i="$i" 'BEGIN { srand(i*7+1); printf "%.3f", 0.005 + rand()*0.20 }')"
  "$PX" apply "$ws" -y >"$ws/apply.log" 2>&1 &
  pid=$!
  sleep "$delay"
  kill -9 "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  # retry the SAME id-less workspace to completion
  "$PX" apply "$ws" -y >"$ws/retry.log" 2>&1 || true
  now="$(ids_for_name | wc -l | tr -d ' ')"
  printf '  attempt %d: killed after %ss → projects now = %s\n' "$i" "$delay" "$now"
done

post="$(ids_for_name | wc -l | tr -d ' ')"
made=$((post - pre))
hr
info "attempts: $ATTEMPTS   projects created: $made"
if [[ "$made" -le "$ATTEMPTS" ]]; then
  pass "no duplicate projects (created $made ≤ $ATTEMPTS attempts)"
else
  fail "DUPLICATE PROJECTS: $made created from $ATTEMPTS attempts → interrupt race reproduced $((made - ATTEMPTS)) time(s)"
fi

step "Teardown: delete every \"$NAME\" project by id"
while read -r pid; do
  [[ -n "$pid" ]] || continue
  if "$PX" delete "$pid" -y >/dev/null 2>&1; then info "deleted $pid"; else warn "could not delete $pid"; fi
done < <(ids_for_name)
