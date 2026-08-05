# Authoring a Prometheux workspace — guide for humans and agents

This repo is a **Prometheux workspace as code**: the lineage (concepts, datasources,
ontology, apps) and the context layer (notes) live as files you author locally and apply
to the platform with the `px` CLI. This file is the canonical guide; `CLAUDE.md` and
`.cursor/rules/` just point here.

Every YAML/manifest carries a `$schema` reference to a file under `.px/schemas/`, so a
language server gives you autocomplete and validation with zero guesswork. When in doubt,
read the schema — it is the single source of truth.

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

- **Connection** (snowflake / postgres / databricks / …) — reference every secret as
  `${ENV_VAR}`; `px apply` resolves them from the environment and never stores them.
  ```yaml
  name: snowflake_prod
  type: snowflake
  account: ${SNOWFLAKE_ACCOUNT}
  password: ${SNOWFLAKE_PASSWORD}
  ```
- **Local file** (csv / parquet / json / excel / …) — add a `file:` path (relative to the
  datasource file). `px apply` uploads it to the workspace disk, then connects it.
  ```yaml
  name: customers_csv
  type: csv
  file: ../data/customers.csv
  ```

A concept reads from a datasource via an input bind in its `.meta.yaml` (`binds.input`),
referencing the datasource `name`.

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

1. `px init` scaffolds this repo (already done if you are reading this).
2. Author files — bodies + `*.meta.yaml`, context manifests + bodies.
3. `px validate` — offline schema + structural checks. Loop until it passes.
4. `px plan` — reads the server state and shows create/update/replace + the downstream
   re-run cascade. Read it.
5. `px apply` — applies over REST; registers a lineage version and who applied it.

## Guardrails — do NOT

- Put secrets in files. Reference them as `${ENV_VAR}`; they are resolved from the
  environment at apply.
- Hand-write lineage edges, or bind a predicate that another concept produces.
- Author `derived_from` context links.
- Reference predicates across projects (v1 concepts refer only within their own lineage;
  the only cross-project sharing is `scope: global` context).

## Vadalog gotchas (so you don't rediscover them)

- `substring` is **1-based** (the docs say otherwise).
- Parenthesize division-then-multiply: write `(A/B)*100`, not `A/B*100`.
- Postgres numerics need `as_double()`.
- Run concepts sequentially — concurrent runs hit `ENGINE_BUSY`.
