# CSV → knowledge graph

The day-one path: you have a couple of CSVs and want them turned into linked, queryable
concepts on the platform.

`run.sh` authors this workspace (into `./workspace`) and then runs the core `px` loop:

```
projects/customers/
  files/           customers.csv, orders.csv     (the raw data)
  datasources/     customers_csv, orders_csv      (one file per datasource)
  concepts/
    customer       ingest customers.csv
    order          ingest orders.csv
    customer_order derive: join customer + order  (the join IS the lineage)
```

## Run

```bash
export JARVISPY_URL="https://api.prometheux.ai/jarvispy/<org>/<user>"
export PMTX_TOKEN="<your JWT>"
./run.sh
```

What it does: `px validate` (offline) → `px plan` (preview) → `px apply` (creates the project,
uploads + connects the CSVs, saves the concepts) → `px run customer_order --persist`.

## What to look at

- Open **Customers Example** in the app — you'll see the lineage `customer` + `order → customer_order`.
- The `.meta.yaml` files are the "envelope" (output predicate, group, input binds); the `.vadalog`
  files are the concept bodies. Edges between concepts are **derived** from body references.
- Re-run `./run.sh` — `px plan` now reports **No changes** (idempotent). The project id was written
  back into `projects/customers/prometheux.yaml` on the first apply.

## Clean up

```bash
px delete "Customers Example" -y
```
