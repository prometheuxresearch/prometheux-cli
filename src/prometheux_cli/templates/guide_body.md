## Mental model

- **Write logic, derive the graph.** You never hand-write lineage edges. A concept's
  Vadalog head/body predicates *are* the edges; `px plan` reconstructs the graph. If
  concept `risk` references predicate `customer` in its body, that reference is the edge —
  do not declare it anywhere.
- **A concept is a struct; its body text is a projection.** Each concept is a body file
  (the logic) plus, for most kinds, a sibling `*.meta.yaml` envelope (binds, params,
  output predicate, fields).
- **Context sets point at pristine bodies.** A `*.context.md` manifest carries Prometheux
  config (`scope`, `activation`) and *references* plain markdown bodies. The bodies stay
  untouched — they can be your existing docs. Identity is `(manifest, referenced path)`.

## Concept kinds

| Kind | File(s) | Body is | Notes |
|---|---|---|---|
| `logic` | `x.vadalog` + `x.meta.yaml` | native Vadalog | the default |
| `sql` | `x.sql` + `x.meta.yaml` | the SQL you wrote | transpiled to Vadalog on apply |
| `cypher` | `x.cypher` + `x.meta.yaml` | Cypher | transpiled to Vadalog on apply |
| `python` | `x.py` + `x.meta.yaml` | a Python script | leaf node, never spliced |
| `context` | `x.context.yaml` | a note selection | leaf node; project scope only |
| `llm` | `x.llm.md` (frontmatter + prompt) | a prompt template | leaf node |

- The **body extension carries the authored language.** Do not rename everything to
  `.vadalog` — keep the source language you wrote.
- Bind a predicate in `binds.input` **only** when it comes from a datasource. A predicate
  produced by another concept is a derived edge — never bind it.

## Datasources

A datasource file (`datasources/*.yaml`) is one of two shapes:

- **Connection** (postgres / mariadb / clickhouse / teradata / snowflake / …) — reference
  every secret as `${ENV_VAR}`; `px apply` resolves them from the environment and never
  stores them. Author **one table per datasource file** (`tables:` with a single
  fully-qualified name) so the concept binds it unambiguously — a database connect returns
  the whole group, and one-table-per-file is how `px` picks the right one.
  ```yaml
  name: pg_companies
  type: postgresql
  host: databases.prometheux.ai
  port: 5432
  username: prometheux
  password: ${PG_PASSWORD}
  database: prometheux
  tables:
    - prometheux.public.companies
  ```
- **Local file** (csv / parquet / json / excel / …) — add a `file:` path (relative to the
  datasource file). `px apply` uploads it to the workspace disk, then connects it.
  ```yaml
  name: customers_csv
  type: csv
  file: ../data/customers.csv
  ```
- **Object store (S3) file** — no `file:` upload; connect in place. Put the **full
  directory** (bucket **and** sub-path) in `host`, list the file in `tables`, and DO NOT set
  `database`.
  ```yaml
  name: s3_air_routes
  type: csv
  host: s3a://my-bucket/airports      # full path — bucket AND sub-dir
  port: 0
  s3aAccessKey: ${S3_ACCESS_KEY}
  s3aSecretKey: ${S3_SECRET_KEY}
  useHeaders: "true"
  tables:
    - air-routes-nodes.csv
  ```
  ⚠️ If you split it (`host: s3a://my-bucket`, `database: airports`) the connect *succeeds*
  but the stored bind drops the sub-directory and the concept fails at **run** time with
  `PATH_NOT_FOUND`. Always put the whole path in `host`.

A concept reads from a datasource via an input bind in its `.meta.yaml` (`binds.input`),
referencing the datasource `name`. `px apply` reuses a connection that already exists on the
account (matched by type/host/port/table) instead of re-connecting, so re-applying is
idempotent and an ontology can point at a shared, pre-existing datasource.

## Context conventions

- `scope` (`global` | `project`) is declared **in the manifest frontmatter**, not inferred
  from the folder.
- `activation`: `retrieved` (semantic pool, default), `always` (a rule, injected every
  request), `on_demand` (title listed, body fetched when needed). `type: rule` == `always`.
- Links go in the manifest's `links:` block. Bodies stay pristine. `derived_from`
  provenance is platform-owned — never author it.
- Duplicates are allowed: the same body in two sets becomes two notes. `px plan` surfaces
  duplicates; it never dedupes.

## Workflow

1. `px init` scaffolds a workspace skeleton (schemas, an example ontology, this guide).
2. Author files — concept bodies + `*.meta.yaml`, datasources, context manifests + bodies.
3. `px validate` — offline schema + structural checks. Loop until it passes.
4. `px plan` — reads the server state and shows create/update/replace + the downstream
   re-run cascade. Read it before applying.
5. `px apply` — applies over REST; registers a lineage version and who applied it.

## Guardrails — do NOT

- Put secrets in files. Reference them as `${ENV_VAR}`; they are resolved from the
  environment at apply.
- Hand-write lineage edges, or bind a predicate that another concept produces.
- Author `derived_from` context links.
- Reference predicates across ontologies (v1 concepts refer only within their own lineage;
  the only cross-ontology sharing is `scope: global` context).

## Vadalog gotchas (so you don't rediscover them)

- `substring` is **1-based** (the docs say otherwise).
- Parenthesize division-then-multiply: write `(A/B)*100`, not `A/B*100`.
- Postgres numerics need `as_double()`.
- Run concepts sequentially — concurrent runs hit `ENGINE_BUSY`.
