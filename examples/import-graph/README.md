# Import a graph (the usable way)

You have a graph in another tool, exported as a **node list** and an **edge list** (the common
Neo4j / CSV shape). This example imports it into Prometheux.

## The key lesson

A Prometheux ontology is **concept-centric** — the platform draws it from concept *lineage*. So
writing a bare `ontology_schema` into an *empty* ontology shows up **empty** in the UI (and `px
validate` will warn you: "concept-less ontology… will show as EMPTY"). The real import path is to
ingest the external nodes/edges **as concepts**, which populates the lineage; a type ontology on
top is then meaningful.

## What `run.sh` authors

```
ontologies/graph/
  files/           nodes.csv, edges.csv           (the external export)
  datasources/     nodes_csv, edges_csv
  concepts/
    graph_node     ingest nodes.csv
    graph_edge     ingest edges.csv
    edge_enriched  derive: join edges with node kinds (the join IS the lineage)
  ontology/schema.yaml   a type graph derived from the node list (id + label + color)
```

## Run

```bash
export JARVISPY_URL="https://api.prometheux.ai/jarvispy/<org>/<user>"
export PMTX_TOKEN="<your JWT>"
./run.sh
```

`px validate` → `px apply` → `px run edge_enriched`.

## What to look at

- **Lineage view**: `nodes.csv → graph_node`, `edges.csv → graph_edge`, both → `edge_enriched`.
- **Ontology → Schema tab**: the `company / person / product` type graph.
- Because the ontology has concepts, `validate` does **not** warn about a hollow ontology schema — contrast
  with importing only a type graph into an empty ontology.

## Clean up

```bash
px delete "Imported Graph Example" -y
```
