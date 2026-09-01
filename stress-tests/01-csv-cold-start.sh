#!/usr/bin/env bash
#
# Scenario 1 — CSV folder → knowledge graph (new-customer cold start).
#
# Simulates the day-one adoption path: a customer drops a few CSVs in a folder
# and wants them turned into linked concepts + an ontology, running on the
# platform. Exercises the widest slice of the pipeline:
#   scaffold → validate (offline) → apply (file upload + connect + concepts +
#   ontology) → idempotent re-plan → run a derived concept.
#
# Run:  JARVISPY_URL=... PMTX_TOKEN=... ./01-csv-cold-start.sh

SCENARIO="pxst-csv-coldstart"
source "$(dirname "$0")/_lib.sh"

hr; printf '%sScenario 1: CSV folder → knowledge graph%s\n' "$C_BLD" "$C_RST"; hr
require_auth
new_workspace

ONTO="$WS/ontologies/$SCENARIO"
mkdir -p "$ONTO"/{concepts,datasources,files,ontology}

# --- 1. the customer's raw data (the "dropped CSVs") -----------------------
step "Author fixtures: 2 CSV files a customer would drop in"
cat > "$ONTO/files/customers.csv" <<'CSV'
Id,Name,Country
c1,Ada Lovelace,UK
c2,Alan Turing,UK
c3,Grace Hopper,US
c4,Edsger Dijkstra,NL
CSV
cat > "$ONTO/files/orders.csv" <<'CSV'
OrderId,CustomerId,Amount
o1,c1,120
o2,c1,80
o3,c3,300
o4,c4,50
o5,c3,25
CSV
info "customers.csv (4 rows), orders.csv (5 rows)"

# --- 2. workspace + ontology manifests -------------------------------------
step "Scaffold workspace files"
cat > "$WS/prometheux.workspace.yaml" <<YAML
schemaVersion: 1
workspace:
  name: $SCENARIO
ontologies:
  - ./ontologies/$SCENARIO
YAML

# Reuse the ontology id from a prior run if present (keeps the account clean).
{
  echo "schemaVersion: 1"
  echo "ontology:"
  if [[ -n "${SAVED_ONTOLOGY_ID:-}" ]]; then echo "  id: $SAVED_ONTOLOGY_ID"; fi
  echo "  name: $SCENARIO"
  echo "datasources:"
  echo "  - ./datasources/customers_csv.yaml"
  echo "  - ./datasources/orders_csv.yaml"
  echo "concepts: ./concepts"
  echo "ontologySchema: ./ontology/schema.yaml"
} > "$ONTO/prometheux.yaml"

# --- 3. datasources: local CSV files (uploaded + connected on apply) --------
cat > "$ONTO/datasources/customers_csv.yaml" <<'YAML'
name: customers_csv
type: csv
file: ../files/customers.csv
useHeaders: "true"
YAML
cat > "$ONTO/datasources/orders_csv.yaml" <<'YAML'
name: orders_csv
type: csv
file: ../files/orders.csv
useHeaders: "true"
YAML

# --- 4. concepts: 2 ingest + 1 derived join --------------------------------
step "Author concepts (2 ingest + 1 derived)"
cat > "$ONTO/concepts/customer.vadalog" <<'VL'
% Ingest customers from the uploaded CSV. The bound predicate source_customers
% is an input edge; `customer` is this concept's output.
customer(Id, Name, Country) :- source_customers(Id, Name, Country).
VL
cat > "$ONTO/concepts/customer.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: customer
group: ingest
binds:
  input:
    - predicate: source_customers
      datasource: customers_csv
      table_name: customers.csv
YAML

cat > "$ONTO/concepts/order.vadalog" <<'VL'
order(OrderId, CustomerId, Amount) :- source_orders(OrderId, CustomerId, Amount).
VL
cat > "$ONTO/concepts/order.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: order
group: ingest
binds:
  input:
    - predicate: source_orders
      datasource: orders_csv
      table_name: orders.csv
YAML

# Derived: the reference to customer(...) and order(...) in the body ARE the
# lineage edges — never hand-written.
cat > "$ONTO/concepts/customer_order.vadalog" <<'VL'
customer_order(Name, Country, Amount) :-
    customer(Id, Name, Country),
    order(_, Id, Amount).
VL
cat > "$ONTO/concepts/customer_order.meta.yaml" <<'YAML'
conceptType: logic
outputPredicate: customer_order
group: derive
YAML

# --- 5. a minimal ontology --------------------------------------------------
cat > "$ONTO/ontology/schema.yaml" <<'YAML'
nodes:
  - id: customer
  - id: order
edges:
  - from: order
    label: placed_by
    to: customer
YAML

# --- 6. offline validate ----------------------------------------------------
step "Offline validate (no platform)"
assert_ok validate "$WS"

# --- 7. plan (preview) ------------------------------------------------------
step "Plan against the account (read-only)"
assert_ok plan "$WS"

# --- 8. apply ---------------------------------------------------------------
step "Apply: upload CSVs, connect, create concepts + ontology"
assert_ok apply "$WS" --yes
assert_out_lacks "skipped"        # every concept must resolve & save
remember_ontology_id

# --- 9. idempotency ---------------------------------------------------------
step "Re-plan must be clean (idempotent)"
assert_plan_clean "$WS"

# --- 10. run the derived concept -------------------------------------------
step "Run the derived concept end-to-end"
if px_run run customer_order "$WS" --persist; then
  pass "run customer_order exited 0"
else
  fail "run customer_order failed (exit $?)"
fi

step "Done. Inspect the workspace at: $WS"
