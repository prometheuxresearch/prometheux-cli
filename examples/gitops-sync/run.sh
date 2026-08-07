#!/usr/bin/env bash
#
# Example: manage a workspace as code (GitOps style).
#
# Walks the reconcile loop the way you'd use px day to day:
#   apply → plan is clean (idempotent)
#   edit an upstream concept → plan shows the update + downstream cascade → apply
#   add a concept → plan shows create → apply
#   delete a concept file → plan WITHHOLDS the delete → apply --prune removes it
#
# Because this is a guided walkthrough that mutates files, it re-authors the
# workspace fresh each run (preserving the project id, so it updates ONE project).
#
# Prereqs: `px` installed; JARVISPY_URL + PMTX_TOKEN set (see ../README.md).

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WS="$HERE/workspace"
PX="${PX:-px}"
PROJ="$WS/projects/catalog"
MANIFEST="$PROJ/prometheux.yaml"

: "${JARVISPY_URL:?set JARVISPY_URL, e.g. https://api.prometheux.ai/jarvispy/<org>/<user>}"
: "${PMTX_TOKEN:?set PMTX_TOKEN (your account JWT)}"
export JARVISPY_URL PMTX_TOKEN

say()  { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
pause(){ printf '\033[2m   (press Enter to continue)\033[0m'; read -r _ || true; }

# Preserve the project id from a previous run so we update one project.
PREV_ID="$(sed -n 's/^[[:space:]]*id:[[:space:]]*//p' "$MANIFEST" 2>/dev/null | head -1 || true)"

say "Author base workspace (1 CSV source + 1 ingest + 1 derived concept)"
rm -rf "$WS"
mkdir -p "$PROJ"/{concepts,datasources,files}

cat > "$PROJ/files/items.csv" <<'CSV'
Id,Name,Country,Price
i1,Widget,UK,120
i2,Gadget,US,80
i3,Gizmo,UK,300
i4,Doohickey,NL,50
CSV

cat > "$WS/prometheux.workspace.yaml" <<'YAML'
schemaVersion: 1
workspace:
  name: gitops-sync-example
projects:
  - ./projects/catalog
YAML

{
  echo "schemaVersion: 1"
  echo "project:"
  if [[ -n "$PREV_ID" ]]; then echo "  id: $PREV_ID"; fi   # reuse across runs
  echo "  name: Catalog Example"
  echo "  scope: user"
  echo "datasources:"
  echo "  - ./datasources/items_csv.yaml"
  echo "concepts: ./concepts"
} > "$MANIFEST"

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

cat > "$PROJ/concepts/domestic.vadalog" <<'VL'
domestic(Name) :- item(_, Name, "UK", _).
VL
cat > "$PROJ/concepts/domestic.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: domestic
group: derive
YAML

say "Initial apply"
"$PX" apply "$WS" -y
say "A fresh plan is now clean — files match the server (idempotent)"
"$PX" plan "$WS"
pause

say "Edit the UPSTREAM concept 'item' (rename vars: same result, new rule text)"
cat > "$PROJ/concepts/item.vadalog" <<'VL'
item(ItemId, ItemName, ItemCountry, ItemPrice) :-
    source_items(ItemId, ItemName, ItemCountry, ItemPrice).
VL
say "plan shows 'item' updated AND the downstream cascade to 'domestic'"
"$PX" plan "$WS"
say "apply the change"
"$PX" apply "$WS" -y
pause

say "Add a NEW concept 'foreign'"
cat > "$PROJ/concepts/foreign.vadalog" <<'VL'
foreign(Name, Country) :- item(_, Name, Country, _), Country != "UK".
VL
cat > "$PROJ/concepts/foreign.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: foreign
group: derive
YAML
say "plan shows '+ concept foreign  create'"
"$PX" plan "$WS"
"$PX" apply "$WS" -y
pause

say "Delete the 'foreign' file — deletions are WITHHELD by default (safe)"
rm -f "$PROJ/concepts/foreign.vadalog" "$PROJ/concepts/foreign.meta.yaml"
say "plan shows '- concept foreign  delete (withheld — needs --prune)'"
"$PX" plan "$WS"
say "apply --prune actually removes it"
"$PX" apply "$WS" -y --prune

cat <<EOF

Done. You saw: idempotent apply, an upstream edit cascading downstream, a
create, and a safe (opt-in) delete via --prune.

Clean up when finished:
  $PX delete "Catalog Example" -y
EOF
