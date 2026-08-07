#!/usr/bin/env bash
#
# Scenario 3 — import a graph from an external source, the USABLE way.
#
# Key lesson (verified on staging 2026-08-07): a Prometheux ontology is
# concept-centric — the platform renders it from concept LINEAGE, so a project
# with an ontology_schema but zero concepts shows up EMPTY and is useless. So
# the real "import a graph from another tool" path is NOT "write a type-graph
# into an empty project"; it is "ingest the external nodes/edges as concepts
# bound to the data", which yields populated lineage (a real knowledge graph).
#
# This scenario has two parts:
#   A. Guard (offline): a concept-less ontology must WARN. Proves the new
#      hollow-ontology guard in `px validate`.
#   B. Real import: external node/edge CSVs → concepts + a type ontology →
#      apply → run → pull → assert concepts AND ontology survived.
#
# Run:  JARVISPY_URL=... PMTX_TOKEN=... ./03-import-ontology.sh

SCENARIO="pxst-import-graph"
source "$(dirname "$0")/_lib.sh"

hr; printf '%sScenario 3: import a graph from an external source%s\n' "$C_BLD" "$C_RST"; hr

# ─── Part A — guard: a concept-less ontology must WARN (offline, no auth) ────
step "Guard: a concept-less ontology_schema must warn (it renders empty)"
GUARD_WS="$STATE_DIR/$SCENARIO/guard"
rm -rf "$GUARD_WS"
mkdir -p "$GUARD_WS/projects/hollow"/{concepts,ontology}
cat > "$GUARD_WS/prometheux.workspace.yaml" <<'YAML'
schemaVersion: 1
workspace:
  name: guard
projects:
  - ./projects/hollow
YAML
cat > "$GUARD_WS/projects/hollow/prometheux.yaml" <<'YAML'
schemaVersion: 1
project:
  name: hollow
  scope: user
concepts: ./concepts
ontology: ./ontology/schema.yaml
YAML
cat > "$GUARD_WS/projects/hollow/ontology/schema.yaml" <<'YAML'
nodes:
  - id: company
    label: Company
    color: "#97c2fc"
    customFields: {}
edges: []
YAML
assert_ok validate "$GUARD_WS"          # warning, not error → still exit 0
assert_out_has "will show as EMPTY"     # the hollow-ontology guard fired

# ─── Part B — the real import (needs the platform) ──────────────────────────
require_auth
new_workspace
PROJ="$WS/projects/$SCENARIO"
mkdir -p "$PROJ"/{concepts,datasources,files,ontology} "$WS/external"

# 1. external export: a property graph as node list + edge list (instances)
step "Author external export (graph data: nodes + edges)"
cat > "$WS/external/nodes.csv" <<'CSV'
id,kind
acme,company
globex,company
ada,person
alan,person
gizmo,product
CSV
cat > "$WS/external/edges.csv" <<'CSV'
from,label,to
ada,works_at,acme
alan,works_at,globex
acme,makes,gizmo
CSV
cp "$WS/external/nodes.csv" "$PROJ/files/nodes.csv"
cp "$WS/external/edges.csv" "$PROJ/files/edges.csv"

# 2. manifests
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
  echo "  - ./datasources/nodes_csv.yaml"
  echo "  - ./datasources/edges_csv.yaml"
  echo "concepts: ./concepts"
  echo "ontology: ./ontology/schema.yaml"
} > "$PROJ/prometheux.yaml"

cat > "$PROJ/datasources/nodes_csv.yaml" <<'YAML'
name: nodes_csv
type: csv
file: ../files/nodes.csv
useHeaders: "true"
YAML
cat > "$PROJ/datasources/edges_csv.yaml" <<'YAML'
name: edges_csv
type: csv
file: ../files/edges.csv
useHeaders: "true"
YAML

# 3. ingest the graph AS CONCEPTS (this is what populates the lineage/ontology)
step "Author concepts: ingest nodes + edges, then a derived join"
cat > "$PROJ/concepts/graph_node.vadalog" <<'VL'
graph_node(Id, Kind) :- source_nodes(Id, Kind).
VL
cat > "$PROJ/concepts/graph_node.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: graph_node
group: ingest
binds:
  input:
    - predicate: source_nodes
      datasource: nodes_csv
      table_name: nodes.csv
YAML

cat > "$PROJ/concepts/graph_edge.vadalog" <<'VL'
graph_edge(FromId, Label, ToId) :- source_edges(FromId, Label, ToId).
VL
cat > "$PROJ/concepts/graph_edge.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: graph_edge
group: ingest
binds:
  input:
    - predicate: source_edges
      datasource: edges_csv
      table_name: edges.csv
YAML

# derived: joins the two ingest concepts — the references ARE the lineage edges.
cat > "$PROJ/concepts/edge_enriched.vadalog" <<'VL'
edge_enriched(FromId, FromKind, Label, ToId) :-
    graph_edge(FromId, Label, ToId),
    graph_node(FromId, FromKind).
VL
cat > "$PROJ/concepts/edge_enriched.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: edge_enriched
group: derive
YAML

# 4. a type-level ontology (now legitimate — concepts back the project)
cat > "$PROJ/ontology/schema.yaml" <<'YAML'
nodes:
  - id: company
    label: Company
    color: "#97c2fc"
    customFields: {}
  - id: person
    label: Person
    color: "#fb7e81"
    customFields: {}
  - id: product
    label: Product
    color: "#6ecc8b"
    customFields: {}
edges:
  - id: person-works_at-company
    from: person
    to: company
    label: works_at
    customFields: {}
  - id: company-makes-product
    from: company
    to: product
    label: makes
    customFields: {}
YAML

# 5. validate — concepts present, so NO hollow warning this time
step "Validate (must NOT warn — the project has concepts)"
assert_ok validate "$WS"
assert_out_lacks "will show as EMPTY"

# 6. apply + idempotency
step "Apply: connect data, create concepts + ontology"
assert_ok apply "$WS" --yes
assert_out_lacks "skipped"
remember_project_id
step "Re-plan is clean"
assert_plan_clean "$WS"

# 7. run the derived concept (proves the graph is queryable end-to-end)
step "Run the derived concept"
if px_run run edge_enriched "$WS" --persist; then
  pass "run edge_enriched exited 0"
else
  fail "run edge_enriched failed (exit $?)"
fi

# 8. pull back and assert BOTH concepts and ontology survived
step "Pull into a fresh dir; assert concepts + ontology round-trip"
PID="$(sed -n 's/^[[:space:]]*id:[[:space:]]*//p' "$PROJ/prometheux.yaml" | head -1)"
if [[ -z "$PID" ]]; then
  fail "no project id written back — cannot pull"
else
  PULLED="$WS/pulled"; rm -rf "$PULLED"; mkdir -p "$PULLED"
  if px_run pull "$PID" --out "$PULLED"; then
    pass "pull exited 0"
    for c in graph_node graph_edge edge_enriched; do
      if find "$PULLED" -name "$c.*" | grep -q .; then pass "concept round-tripped: $c"; else fail "concept lost: $c"; fi
    done
    SCHEMA="$(find "$PULLED" -name schema.yaml -path '*/ontology/*' | head -1)"
    if [[ -f "$SCHEMA" ]] && grep -qF "label: Company" "$SCHEMA"; then
      pass "ontology type-graph round-tripped (label preserved)"
    else
      fail "ontology did not round-trip"
    fi
  else
    fail "pull failed (exit $?)"
  fi
fi

step "Done. Workspace at: $WS"
