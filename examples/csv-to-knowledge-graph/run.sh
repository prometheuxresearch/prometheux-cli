#!/usr/bin/env bash
#
# Example: turn a folder of CSVs into a queryable knowledge graph.
#
# Authors a px workspace (two CSV datasources + three concepts), then walks the
# core loop: validate (offline) → plan (preview) → apply (upload + create) →
# run. The workspace is written to ./workspace on first run and reused after, so
# re-running is idempotent. Read the heredocs below to see each file's shape.
#
# Prereqs: `px` installed; JARVISPY_URL + PMTX_TOKEN set (see ../README.md).

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WS="$HERE/workspace"
PX="${PX:-px}"
PROJ="$WS/projects/customers"

: "${JARVISPY_URL:?set JARVISPY_URL, e.g. https://api.prometheux.ai/jarvispy/<org>/<user>}"
: "${PMTX_TOKEN:?set PMTX_TOKEN (your account JWT)}"
export JARVISPY_URL PMTX_TOKEN

say() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }

if [[ ! -f "$WS/prometheux.workspace.yaml" ]]; then
  say "Authoring workspace at $WS (first run)"
  mkdir -p "$PROJ"/{concepts,datasources,files}

  # --- the customer's raw data (the "dropped CSVs") ---
  cat > "$PROJ/files/customers.csv" <<'CSV'
Id,Name,Country
c1,Ada Lovelace,UK
c2,Alan Turing,UK
c3,Grace Hopper,US
c4,Edsger Dijkstra,NL
CSV
  cat > "$PROJ/files/orders.csv" <<'CSV'
OrderId,CustomerId,Amount
o1,c1,120
o2,c1,80
o3,c3,300
o4,c4,50
CSV

  # --- workspace + project manifests ---
  cat > "$WS/prometheux.workspace.yaml" <<'YAML'
schemaVersion: 1
workspace:
  name: csv-to-kg-example
projects:
  - ./projects/customers
YAML
  # No `id:` — the first `apply` creates the project and writes its id back here.
  cat > "$PROJ/prometheux.yaml" <<'YAML'
schemaVersion: 1
project:
  name: Customers Example
  scope: user
datasources:
  - ./datasources/customers_csv.yaml
  - ./datasources/orders_csv.yaml
concepts: ./concepts
YAML

  # --- datasources: local CSV files (uploaded + connected on apply) ---
  cat > "$PROJ/datasources/customers_csv.yaml" <<'YAML'
name: customers_csv
type: csv
file: ../files/customers.csv
useHeaders: "true"
YAML
  cat > "$PROJ/datasources/orders_csv.yaml" <<'YAML'
name: orders_csv
type: csv
file: ../files/orders.csv
useHeaders: "true"
YAML

  # --- concepts: two ingest + one derived join ---
  # A concept = a body file (<predicate>.vadalog) + a <predicate>.meta.yaml envelope.
  cat > "$PROJ/concepts/customer.vadalog" <<'VL'
% Ingest customers from the uploaded CSV. source_customers is bound to the
% datasource in the meta file, so it is an INPUT edge; `customer` is the output.
customer(Id, Name, Country) :- source_customers(Id, Name, Country).
VL
  cat > "$PROJ/concepts/customer.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: customer
group: ingest
binds:
  input:
    - predicate: source_customers
      datasource: customers_csv
      table_name: customers.csv
YAML

  cat > "$PROJ/concepts/order.vadalog" <<'VL'
order(OrderId, CustomerId, Amount) :- source_orders(OrderId, CustomerId, Amount).
VL
  cat > "$PROJ/concepts/order.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: order
group: ingest
binds:
  input:
    - predicate: source_orders
      datasource: orders_csv
      table_name: orders.csv
YAML

  # Derived: the references to customer(...) and order(...) in the body ARE the
  # lineage edges — you never hand-write edges.
  cat > "$PROJ/concepts/customer_order.vadalog" <<'VL'
customer_order(Name, Country, Amount) :-
    customer(Id, Name, Country),
    order(_, Id, Amount).
VL
  cat > "$PROJ/concepts/customer_order.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: customer_order
group: derive
YAML
else
  say "Reusing existing workspace at $WS (delete it to start over)"
fi

say "Validate (offline: schema + structural checks, no platform)"
"$PX" validate "$WS"

say "Plan (read-only preview of what apply would do)"
"$PX" plan "$WS"

say "Apply (creates the project, uploads CSVs, connects them, saves concepts)"
"$PX" apply "$WS" -y

say "Run the derived concept end-to-end"
"$PX" run customer_order "$WS" --persist

cat <<EOF

Done. Open "Customers Example" in the app to explore the graph
(customer + order → customer_order).

Clean up when finished:
  $PX delete "Customers Example" -y
EOF
