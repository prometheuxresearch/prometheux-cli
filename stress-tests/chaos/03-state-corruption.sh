#!/usr/bin/env bash
#
# Chaos #3 — corrupt the context state and check for duplicate context notes.
#
# `px context apply` is idempotent via .px/context-state.json (identity
# (manifest, path) → server note id + hash). But _load_state() silently treats a
# missing/corrupt state file as EMPTY — so every note reclassifies as `create`
# and gets pushed AGAIN, duplicating notes that already exist on the server.
# Invariant under test: losing/corrupting local state must not create duplicate
# notes (identity should be recoverable, or re-create should be reconciled).
#
# Usage:  JARVISPY_URL=... PMTX_TOKEN=... ./03-state-corruption.sh
# Creates one project, pushes 3 notes, corrupts state, re-pushes; reports whether
# the second push re-creates already-pushed notes. Deletes the project at the end.

SCENARIO="pxst-chaos-state"
source "$(dirname "$0")/../_lib.sh"

NAME="Chaos State Test"
NOTES=3

hr; printf '%sChaos: corrupt context state → duplicate-notes check%s\n' "$C_BLD" "$C_RST"; hr
require_auth
new_workspace                       # persistent ws under .state/, reuses the project id
PROJ="$WS/projects/ctx"
VAULT="$PROJ/context"
mkdir -p "$PROJ/concepts" "$VAULT"

# A trivial fact concept so `apply` creates the project (context needs a real id).
cat > "$WS/prometheux.workspace.yaml" <<YAML
schemaVersion: 1
workspace:
  name: chaos-state
projects:
  - ./projects/ctx
YAML
{
  echo "schemaVersion: 1"
  echo "project:"
  if [[ -n "${SAVED_PROJECT_ID:-}" ]]; then echo "  id: $SAVED_PROJECT_ID"; fi
  echo "  name: $NAME"
  echo "  scope: user"
  echo "concepts: ./concepts"
  echo "context: ./context"
} > "$PROJ/prometheux.yaml"
printf 'seed("a").\nseed("b").\n' > "$PROJ/concepts/seed.vadalog"
printf 'conceptType: logic\noutputPredicate: seed\n' > "$PROJ/concepts/seed.meta.yaml"

# K distinct note bodies + a project-scoped manifest referencing them.
step "Author $NOTES context notes + manifest"
entries=""
for ((i = 1; i <= NOTES; i++)); do
  printf '# Note %d\n\nStable content for note %d — should exist exactly once.\n' "$i" "$i" > "$VAULT/note-$i.md"
  entries+="  - note-$i.md
"
done
{ printf -- '---\nscope: project\nactivation: retrieved\nkind: fact\nnotes:\n%s---\nchaos state test\n' "$entries"; } > "$VAULT/notes.context.md"

step "Apply the project (creates it + writes the id back)"
assert_ok apply "$WS" -y
remember_project_id

step "First context apply — should CREATE $NOTES notes"
px_run context apply "$WS" -y
assert_out_has "$NOTES create"

step "Second context apply — should be idempotent (all unchanged)"
px_run context apply "$WS" -y
if grep -qE "$NOTES unchanged" <<<"$LAST_OUT"; then
  pass "idempotent: $NOTES unchanged (baseline works)"
else
  fail "not idempotent even before corruption"
fi

step "Corrupt the context state, then apply again (the attack)"
STATE="$WS/.px/context-state.json"
if [[ -f "$STATE" ]]; then
  echo '{ this is not valid json' > "$STATE"     # truncate/garble
  info "garbled $STATE"
else
  warn "no context-state.json found (unexpected)"
fi
px_run context apply "$WS" -y
if grep -qE "$NOTES create" <<<"$LAST_OUT"; then
  fail "STATE LOSS → RE-CREATE: corrupt state made px re-push all $NOTES notes as new (duplicates on the server)"
elif grep -qE "$NOTES unchanged" <<<"$LAST_OUT"; then
  pass "recovered: notes still recognized as unchanged despite corrupt state"
else
  warn "inconclusive — inspect output above"
fi

step "Teardown: delete the project"
PID="$(sed -n 's/^[[:space:]]*id:[[:space:]]*//p' "$PROJ/prometheux.yaml" | head -1)"
[[ -n "$PID" ]] && ( "$PX" delete "$PID" -y >/dev/null 2>&1 && info "deleted $PID" || warn "could not delete $PID" )
rm -rf "$WS"   # drop the local ws so the deleted id isn't reused next run
