#!/usr/bin/env bash
#
# Example: import a graph from another tool — the USABLE way.
#
# A Prometheux ontology is concept-centric: the platform renders it from concept
# lineage, so writing a bare ontology_schema into an empty project shows up EMPTY.
# The real import path is to ingest the external nodes/edges AS CONCEPTS (which
# populates the lineage), and optionally attach a type ontology on top.
#
# This authors: two CSV "exports" (a node list + an edge list) → three concepts
# (graph_node, graph_edge, edge_enriched) → a type ontology derived from the node
# list → apply → run.
#
# Prereqs: `px` installed; JARVISPY_URL + PMTX_TOKEN set (see ../README.md).

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WS="$HERE/workspace"
PX="${PX:-px}"
PROJ="$WS/projects/graph"

: "${JARVISPY_URL:?set JARVISPY_URL, e.g. https://api.prometheux.ai/jarvispy/<org>/<user>}"
: "${PMTX_TOKEN:?set PMTX_TOKEN (your account JWT)}"
export JARVISPY_URL PMTX_TOKEN

say() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

if [[ ! -f "$WS/prometheux.workspace.yaml" ]]; then
  say "Authoring workspace at $WS (first run)"
  mkdir -p "$PROJ"/{concepts,datasources,files,ontology} "$WS/external"

  # --- external export: a property graph as a node list + an edge list ---
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
  # px uploads the file datasources it binds, so copy the CSVs into the project.
  cp "$WS/external/nodes.csv" "$PROJ/files/nodes.csv"
  cp "$WS/external/edges.csv" "$PROJ/files/edges.csv"

  # --- manifests ---
  cat > "$WS/prometheux.workspace.yaml" <<'YAML'
schemaVersion: 1
workspace:
  name: import-graph-example
projects:
  - ./projects/graph
YAML
  cat > "$PROJ/prometheux.yaml" <<'YAML'
schemaVersion: 1
project:
  name: Imported Graph Example
  scope: user
datasources:
  - ./datasources/nodes_csv.yaml
  - ./datasources/edges_csv.yaml
concepts: ./concepts
ontology: ./ontology/schema.yaml
YAML
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

  # --- ingest the graph AS CONCEPTS (this is what populates the lineage) ---
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

  # --- derive a TYPE ontology from the node list (id -> node, with a display
  # label + color so it renders in the ontology editor). Concepts back the
  # project, so this ontology is not "hollow". ---
  {
    echo "nodes:"
    awk -F, 'NR>1 && $1!="" {
      # one node per distinct kind
      k=$2
      if (!(k in seen)) {
        seen[k]=1
        label = toupper(substr(k,1,1)) substr(k,2)
        pal[0]="#97c2fc"; pal[1]="#fb7e81"; pal[2]="#6ecc8b"; pal[3]="#ffd166"
        printf "  - id: %s\n    label: %s\n    color: \"%s\"\n    customFields: {}\n", k, label, pal[n++ % 4]
      }
    }' "$WS/external/nodes.csv"
    echo "edges:"
    # Map each edge label to a TYPE edge: from/to are the kinds of the endpoint
    # instances (looked up in nodes.csv), so works_at = person→company, etc.
    awk -F, '
      NR==FNR { if (FNR>1 && $1!="") kind[$1]=$2; next }
      FNR>1 && $2!="" {
        lbl=$2
        if (!(lbl in seen)) {
          seen[lbl]=1
          printf "  - id: %s\n    from: %s\n    to: %s\n    label: %s\n    customFields: {}\n", lbl, kind[$1], kind[$3], lbl
        }
      }' "$WS/external/nodes.csv" "$WS/external/edges.csv"
  } > "$PROJ/ontology/schema.yaml"
else
  say "Reusing existing workspace at $WS (delete it to start over)"
fi

say "Validate (note: no 'hollow ontology' warning — the project has concepts)"
"$PX" validate "$WS"

say "Apply (connect the CSVs, create the concepts, save the ontology)"
"$PX" apply "$WS" -y

say "Run the derived concept (joins nodes + edges)"
"$PX" run edge_enriched "$WS" --persist

cat <<EOF

Done. Open "Imported Graph Example" in the app:
  - Lineage view: nodes.csv → graph_node, edges.csv → graph_edge → edge_enriched
  - Ontology (Schema tab): the company/person/product type graph

Clean up when finished:
  $PX delete "Imported Graph Example" -y
EOF
