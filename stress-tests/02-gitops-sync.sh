#!/usr/bin/env bash
#
# Scenario 2 — GitOps state sync (idempotency, drift, cascade, prune).
#
# The core "workspace as code" promise: files are the source of truth, and
# `px plan`/`apply` reconcile the account to match. Exercises:
#   apply → clean re-plan (idempotent)
#   edit an upstream concept → plan shows update + downstream cascade → apply → clean
#   add a concept → plan shows create → apply → clean
#   delete a concept file → plan shows delete WITHHELD → apply is safe (no delete)
#                         → apply --prune deletes → clean
#
# Run:  JARVISPY_URL=... PMTX_TOKEN=... ./02-gitops-sync.sh

SCENARIO="pxst-gitops-sync"
source "$(dirname "$0")/_lib.sh"

hr; printf '%sScenario 2: GitOps state sync%s\n' "$C_BLD" "$C_RST"; hr
require_auth
new_workspace

PROJ="$WS/projects/$SCENARIO"
mkdir -p "$PROJ"/{concepts,datasources,files}

# --- base workspace ---------------------------------------------------------
step "Author base workspace (1 source + 1 ingest + 1 derived)"
cat > "$PROJ/files/items.csv" <<'CSV'
Id,Name,Country,Price
i1,Widget,UK,120
i2,Gadget,US,80
i3,Gizmo,UK,300
i4,Doohickey,NL,50
CSV

cat > "$WS/prometheux.workspace.yaml" <<YAML
schemaVersion: 1
workspace:
  name: $SCENARIO
projects:
  - ./projects/$SCENARIO
YAML

{
  echo "schemaVersion: 1"
  echo "project:"
  if [[ -n "${SAVED_PROJECT_ID:-}" ]]; then echo "  id: $SAVED_PROJECT_ID"; fi
  echo "  name: $SCENARIO"
  echo "  scope: user"
  echo "datasources:"
  echo "  - ./datasources/items_csv.yaml"
  echo "concepts: ./concepts"
} > "$PROJ/prometheux.yaml"

cat > "$PROJ/datasources/items_csv.yaml" <<'YAML'
name: items_csv
type: csv
file: ../files/items.csv
useHeaders: "true"
YAML

cat > "$PROJ/concepts/item.vadalog" <<'VL'
item(Id, Name, Country, Price) :- source_items(Id, Name, Country, Price).
VL
cat > "$PROJ/concepts/item.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: item
group: ingest
binds:
  input:
    - predicate: source_items
      datasource: items_csv
      table_name: items.csv
YAML

# domestic derives from item — the item(...) reference is the lineage edge.
cat > "$PROJ/concepts/domestic.vadalog" <<'VL'
domestic(Name) :- item(_, Name, "UK", _).
VL
cat > "$PROJ/concepts/domestic.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: domestic
group: derive
YAML

# --- apply + idempotency ----------------------------------------------------
step "Initial apply"
assert_ok apply "$WS" --yes
assert_out_lacks "skipped"
remember_project_id

step "Re-plan is clean"
assert_plan_clean "$WS"

# --- edit an UPSTREAM concept → update + cascade ----------------------------
step "Edit upstream concept 'item' (real definition change)"
cat > "$PROJ/concepts/item.vadalog" <<'VL'
% renamed vars: same arity/semantics, but the rule TEXT changed → definition diff
item(ItemId, ItemName, ItemCountry, ItemPrice) :-
    source_items(ItemId, ItemName, ItemCountry, ItemPrice).
VL
px_run plan "$WS" || true
assert_out_has "~ concept item"
assert_out_has "update in-place"
assert_out_has "cascades to downstream"       # domestic derives from item
step "Apply the edit, then re-plan clean"
assert_ok apply "$WS" --yes
assert_plan_clean "$WS"

# --- add a NEW concept → create ---------------------------------------------
step "Add a new concept 'foreign'"
cat > "$PROJ/concepts/foreign.vadalog" <<'VL'
foreign(Name, Country) :- item(_, Name, Country, _), Country != "UK".
VL
cat > "$PROJ/concepts/foreign.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: foreign
group: derive
YAML
px_run plan "$WS" || true
assert_out_has "+ concept foreign"
step "Apply the new concept, then re-plan clean"
assert_ok apply "$WS" --yes
assert_plan_clean "$WS"

# --- delete a concept file → safe-by-default, then --prune ------------------
step "Delete the 'foreign' file — plan must WITHHOLD the delete"
rm -f "$PROJ/concepts/foreign.vadalog" "$PROJ/concepts/foreign.meta.yaml"
px_run plan "$WS" || true
assert_out_has "- concept foreign"
assert_out_has "delete (withheld"

step "Apply WITHOUT --prune leaves it on the server (safe default)"
assert_ok apply "$WS" --yes
px_run plan "$WS" || true
assert_out_has "delete (withheld"              # still there — not deleted

step "Apply WITH --prune removes it, then re-plan clean"
assert_ok apply "$WS" --yes --prune
assert_plan_clean "$WS"

step "Done. Workspace at: $WS"
