# prometheux-cli

`px` — author a Prometheux workspace (lineage + context) as files, then plan and apply it
over REST. A thin, files-first layer over the `prometheux_chain` SDK.

Design: `engineering-docs/designs/lineage-as-code.md`.

## Status

Early. Working commands:

Offline (no platform, no SDK):
- `px init [dir]` — scaffold a workspace (schemas, `AGENTS.md`, a worked example of each
  concept kind).
- `px validate [dir]` — schema + structural checks against the bundled JSON Schemas.
  Returns a PASS/FAIL exit code.

Platform (over the `prometheux_chain` SDK):
- `px login` — store + verify the platform URL and token (`~/.prometheux/config.json`;
  `PMTX_TOKEN` / `JARVISPY_URL` override for CI).
- `px pull [project]` — export a live project into `projects/<slug>/` (concepts → body +
  `.meta.yaml`, datasources, ontology). No project id lists what's visible.
- `px plan [dir]` — diff local files against live server state: create / update / delete
  per concept, plus the downstream re-run cascade for any definition change. Read-only.
  `--project <name|slug|id>` (repeatable) targets a subset.
- `px apply [dir]` — apply the plan: connect datasources then create/update concepts
  (`--prune` also deletes, `--yes` skips the prompt, `--project <name|slug|id>` targets a
  subset). Creates the project if new, snapshots each project first. A datasource that
  fails to connect is a warning, not fatal — concepts still apply.
  - **Connection datasources** (snowflake/postgres/…): `${ENV_VAR}` secrets resolved from
    the environment at apply, never stored in files.
  - **Local files** (csv/parquet/json/…): add `file: ../data/x.csv` and apply uploads it to
    the workspace disk, then connects it. (Requires the Data Manager service.)

- `px run <concept> [dir]` — run a concept and emit OpenLineage START/COMPLETE/FAIL
  events (append to `<workspace>/.px/openlineage.jsonl` and/or `--openlineage-url` for a
  catalog like Marquez). `--project` scopes the lookup; `--persist` materializes outputs;
  `--no-openlineage` disables emit.
- `px context apply [dir]` — apply the context layer from `*.context.md` manifests:
  one note per referenced body file (scope/activation/kind), plus links
  (`relates_to`/`defines`/… note↔note or note→`concept:<predicate>`). **Idempotent** —
  a `.px/context-state.json` map keyed by `(manifest, path)` drives create / update /
  skip-unchanged; `--prune` deletes notes dropped from the manifests. Commit that state
  file so re-apply stays idempotent across machines.

Next: ontology/app apply, richer `context` sync.

## Connect to a platform

```bash
px login --url http://localhost:8000 --token devtoken
px pull                 # list projects
px pull <project-id>    # write it to files
px validate             # a freshly pulled workspace validates clean
px plan                 # a freshly pulled workspace plans clean (no changes)
```

## Install (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
px --help
```

## Try it

```bash
px init /tmp/my-workspace --name demo
cd /tmp/my-workspace
px validate
```

## Layout

```
src/prometheux_cli/
  cli.py            # `px` entry point (click)
  commands/         # init, validate, login, pull, plan, apply, run, context
  validation.py     # offline schema + structural engine
  reshape.py        # export dict -> file tree (pull)
  loader.py         # file tree -> typed model (plan/apply)
  plan.py           # diff engine + downstream cascade (pure functions)
  apply.py          # local concept -> save_concept args (pure functions)
  datasources.py    # secret resolution + connect payloads (pure functions)
  openlineage.py    # OpenLineage RunEvent builder (pure functions)
  context.py        # collect notes+links from *.context.md manifests (pure)
  sdk.py            # lazy bridge to prometheux_chain
  credentials.py    # CLI credential store (login)
  parsing.py        # yaml / frontmatter helpers
  resources.py      # access to bundled schemas + scaffold
  schemas/          # published JSON Schemas — the single source of truth
  scaffold/         # `px init` starter workspace
tests/
```

## Test

```bash
pytest -q
```
