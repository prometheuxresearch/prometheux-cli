# prometheux-cli (`px`)

`px` — author a Prometheux workspace (lineage + context) as files, then **plan** and
**apply** it to a Prometheux platform over REST. A thin, files-first layer over the
`prometheux_chain` SDK.

- `init` and `validate` run **fully offline** (no platform, no SDK).
- `login`, `pull`, `plan`, `apply`, `run`, `status`, `delete`, `context apply` reach the **platform**.

The command-by-command reference below is the source of truth for both humans and coding agents.
Runnable, copy-one-folder usage examples live in [`examples/`](examples/).

---

## Contents

- [Install](#install)
- [Authenticate](#authenticate)
- [Quickstart](#quickstart)
- [Command reference](#command-reference)
- [Workspace anatomy](#workspace-anatomy)
- [Concept kinds](#concept-kinds)
- [Datasources](#datasources)
- [Context layer](#context-layer)
- [Recipes](#recipes)
- [State, idempotency & exit codes](#state-idempotency--exit-codes)
- [Gotchas](#gotchas)
- [Repo layout](#repo-layout)

---

## Install

**pipx (recommended — isolated):**
```bash
pipx install prometheux
px --help
```

**pip / uv:**
```bash
pip install prometheux          # or:  uv tool install prometheux
```

**One-liner (macOS / Linux):**
```bash
curl -fsSL https://raw.githubusercontent.com/prometheuxresearch/prometheux-cli/main/install.sh | sh
```
Prefers `uv` (bootstraps it if absent) → `pipx` → `pip --user`.

**One-liner (Windows):**
```powershell
irm https://raw.githubusercontent.com/prometheuxresearch/prometheux-cli/main/install.ps1 | iex
```

**From source (dev):**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
px --help
```

Requires Python ≥ 3.9. The console script `px` is installed by the `prometheux` package.
`px` needs the `prometheux_chain` SDK on the path for any platform command (`login`, `pull`,
`plan`, `apply`, `run`, `status`, `delete`, `context apply`); offline commands (`init`, `validate`)
do not.

### Add the agent skill (Claude Code / Cursor)

Give your coding agent everything it needs to author Prometheux workspaces — no repo to
clone. The skill is generated from the installed `px`, so it always matches your version:

```bash
px skill install                       # global Claude Code skill (~/.claude/skills/prometheux/)
px skill install -t cursor             # Cursor project rule (./.cursor/rules/prometheux.mdc)
px skill install -t claude -t cursor   # both
```

Install `px`, add the skill, and your agent can drive `init` → `validate` → `plan` → `apply`
with full knowledge of concept kinds, datasources, the context layer, and every schema.

---

## Authenticate

```bash
px login --url https://api.prometheux.ai/jarvispy/<org>/<user> --token <JWT>
```

- Credentials persist to `~/.prometheux/config.json`.
- **CI / scripts:** skip `px login` and set env vars instead — they override the stored config:
  ```bash
  export JARVISPY_URL="https://api.prometheux.ai/jarvispy/<org>/<user>"
  export PMTX_TOKEN="<JWT>"
  ```
- `--no-verify` stores the credentials without the live auth check.
- The default URL is `http://localhost:8000` (local dev; token `devtoken`).

**URL shape:** the base URL is `.../jarvispy/<org>/<user>` with **no** `/api` suffix — the SDK
appends `/api/v1` itself. Example accounts: `.../prometheux/mozart`, `.../prometheux/staging`.

---

## Quickstart

**Author from scratch → apply:**
```bash
px init my-workspace --name demo     # scaffold (schemas, AGENTS.md, one example per kind)
cd my-workspace
# ...author concepts / datasources / apps / context...
px validate                          # offline schema + structural checks
px login --url <url> --token <jwt>
px plan                              # preview (read-only)
px apply                             # create/update on the platform
```

**Pull an existing project → edit → apply:**
```bash
px pull                              # list visible projects
px pull <project-id>                 # write it to ./projects/<slug>
px validate && px plan               # a fresh pull plans clean (no changes)
# ...edit files...
px apply
```

---

## Command reference

### `px init [DIRECTORY]`
Scaffold a workspace skeleton (JSON Schemas in `.px/schemas/`, `AGENTS.md`, `CLAUDE.md`
pointer, a worked example of each concept kind). Offline.

| Option | Meaning |
|---|---|
| `--name TEXT` | Workspace name (default: directory name). |
| `--force` | Write into a non-empty directory. |

```bash
px init .                    # scaffold in the current dir
px init /tmp/ws --name demo  # into a new dir with an explicit name
```

### `px validate [PATH]`
Schema + structural checks against the bundled JSON Schemas — **fully offline**, PASS/FAIL
exit code. Checks: manifests match their schema, concept bodies have envelopes, no duplicate
output predicates, datasource refs resolve, context bodies exist, etc. Also **warns** when a
project ships an ontology but has no concepts (a concept-less ontology renders empty on the
platform, which draws it from concept lineage).

| Option | Meaning |
|---|---|
| `--strict` | Treat warnings as failures. |

`PATH` defaults to searching up from the CWD for `prometheux.workspace.yaml`.
```bash
px validate            # find workspace from CWD
px validate /tmp/ws    # explicit
```

### `px login`
Authenticate and store URL + token. See [Authenticate](#authenticate).

| Option | Meaning |
|---|---|
| `--url TEXT` | Platform URL (default `http://localhost:8000`). |
| `--token TEXT` | API token; omit to be prompted (hidden input). |
| `--no-verify` | Skip the live auth check. |

### `px pull [PROJECT]`
Export a live project into `projects/<slug>/` (concepts → body + `.meta.yaml`, datasources,
ontology, apps). With **no** `PROJECT`, lists the projects visible to you and exits.

| Option | Meaning |
|---|---|
| `--scope [user\|organization]` | Scope to pull from. |
| `--out PATH` | Workspace directory (default: `.`). |
| `--slug TEXT` | Directory name under `projects/` (default: from project name). |
| `--with-files` | Download uploaded **file-datasource content** into `files/` and write portable `file:` specs, so the project (with its files) can be re-applied elsewhere. |

```bash
px pull                                  # list projects
px pull 1d22942b9a0                      # write to ./projects/<slug>
px pull 1d22942b9a0 --with-files --out /tmp/copy
```

### `px delete PROJECT`
Permanently delete a whole project (a server project id or exact name) and everything in it —
concepts, datasource binds, ontology, apps, notes. The server auto-snapshots first when versioning
is available. **Local workspace files are not touched.** Resolves by id first, then by exact name
(ambiguous names must be deleted by id).

| Option | Meaning |
|---|---|
| `--scope [user\|organization]` | Scope to delete from (default `user`). |
| `-y, --yes` | Skip the confirmation prompt (for scripts/CI). |

```bash
px delete 245ba23a329           # prompts, then hard-deletes
px delete "Credit Risk" -y      # by name, no prompt
```
> Wraps the SDK's `cleanup_ontologies` — the same guarded choke point used by the UI/agent/MCP; a
> concrete project is always required (there is no "delete everything" mode).

### `px plan [PATH]`
Diff local files against live server state (read-only). Classifies each concept create /
update / delete and renders the **downstream re-run cascade** for definition changes; also
diffs datasources, ontology schema, and apps.

| Option | Meaning |
|---|---|
| `-p, --project TEXT` | Only plan the named project(s), by name / slug / id. Repeatable. |

```bash
px plan
px plan -p "Credit Risk" -p fraud-detection
```

### `px apply [PATH]`
Apply the plan: connect datasources, then create/update concepts, ontology schema, and apps.
Creates the project if new; snapshots each project first (best-effort).

| Option | Meaning |
|---|---|
| `-p, --project TEXT` | Only apply the named project(s). Repeatable. |
| `-y, --yes` | Skip the confirmation prompt. |
| `--prune` | Also delete concepts present on the server but absent from files. |
| `--no-snapshot` | Do not snapshot each project before applying. |
| `--with-files` | Re-upload file datasources even when an identical one already exists (refresh content). New files always upload. |

Behavior notes:
- **Deletions are safe by default** — a concept isn't deleted just because its file vanished;
  use `--prune`. Datasources are user-scoped and never deleted.
- **A datasource already on the account is reused** (matched by type/host/port/table), not
  re-connected — so repeated applies don't pile up duplicate rows. `--with-files` forces a
  file re-upload.
- **Best-effort concepts:** a concept whose body references something that can't be resolved
  (a source defect, or a dep not in this apply) is **skipped** with a warning; the rest of the
  project, the ontology, and apps still apply, and the run exits non-zero with a skip summary.
  A genuine error (parse, conflict) still aborts fast.
- Cross-account port: a recreated project's new id is written back to `prometheux.yaml`, and
  app `project.id` references + `disk/results/<id>` sibling-output paths are retargeted at the
  new project automatically.

```bash
px apply -y
px apply -p "Credit Risk" --prune
PG_PASSWORD=... px apply --with-files   # (re)upload local file datasources
```

### `px run CONCEPT [PATH]`
Run a concept (an output predicate) and emit OpenLineage `START`/`COMPLETE`/`FAIL` events.

| Option | Meaning |
|---|---|
| `-p, --project TEXT` | Limit the lookup to the named project(s). Repeatable. |
| `--param KEY=VALUE` | Run parameter (repeatable). |
| `--persist` | Materialize the concept's outputs. |
| `--openlineage-file PATH` | Append events here (default `<workspace>/.px/openlineage.jsonl`). |
| `--openlineage-url TEXT` | Also POST each event to this URL (e.g. a Marquez `/api/v1/lineage`). |
| `--no-openlineage` | Do not emit events. |

```bash
px run risk_score
px run risk_score --persist --param year=2025 -p "Credit Risk"
```

### `px status`
Monitor run status **account-wide** — no workspace needed. One row per ontology: running /
success / error / cancelled / interrupted / idle, plus the concept executing and its progress.
The engine is globally serialized, so at most one ontology is ever `running`. Running rows are
highlighted and sorted first.

| Option | Meaning |
|---|---|
| `-w, --watch` | Refresh continuously until Ctrl-C. |
| `-i, --interval FLOAT` | Seconds between refreshes with `--watch` (default `3.0`). |
| `--scope TEXT` | Comma-separated scopes, e.g. `user,organization` (default `user`). |

```bash
px status                       # one-shot table
px status --watch               # live; announces when a run starts
px status -w -i 5 --scope user,organization
```

### `px context apply [PATH]`
Apply the context layer from every `*.context.md` manifest in the workspace: one note per
referenced body file (scope / activation / kind), plus links (`relates_to` / `defines` /
`example_of` / `contradicts`; note↔note or note→`concept:<predicate>`). **Idempotent** via
`.px/context-state.json` keyed by `(manifest, path)`.

| Option | Meaning |
|---|---|
| `-y, --yes` | Skip the confirmation prompt. |
| `--prune` | Delete notes previously applied but no longer in any manifest. |

```bash
px context apply -y
px context apply --prune
```

### `px skill install`
Install the Prometheux authoring skill into a coding agent, generated from this `px`'s
bundled schemas + guide (no repo clone; always matches the installed version). Writes a
Claude Code skill (`SKILL.md` + `reference/` schema docs) and/or a Cursor project rule.

| Option | Meaning |
|---|---|
| `-t, --target [claude\|claude-project\|cursor]` | Where to install (repeatable). Default: `claude` (global `~/.claude/skills/prometheux/`). `claude-project` → `<dir>/.claude/skills/`; `cursor` → `<dir>/.cursor/rules/prometheux.mdc`. |
| `--dir PATH` | Base directory for project targets. Default: current dir. |
| `--force` | Overwrite an existing install. |

```bash
px skill install                       # global Claude Code skill
px skill install -t cursor --dir .     # Cursor rule in this repo
```

---

## Workspace anatomy

```
my-workspace/
  prometheux.workspace.yaml     # lists the shared context vault + projects
  .px/schemas/                  # bundled JSON Schemas ($schema-referenced by files)
  context/                      # workspace-global context (*.context.md + body files)
  projects/
    credit-risk/
      prometheux.yaml           # project manifest (id, name, scope + section paths)
      concepts/
        customers.vadalog       # concept body (per-kind extension)
        customers.meta.yaml     # envelope: conceptType, outputPredicate, binds, group, …
        revenue.sql             # sql source (transpiled server-side)
        enrich.py               # python script
        summarize.llm.md        # llm prompt (frontmatter config + prompt body)
        relevant.context.yaml   # context concept (note selection)
      datasources/
        snowflake_prod.yaml     # connection or file spec
      ontology/
        schema.yaml             # node/edge graph (save_ontology_schema shape)
      apps/
        credit_risk.app.yaml    # AppDefinition v2
      context/                  # this project's project-scoped context
      files/                    # local datasource files (e.g. from `pull --with-files`)
```

**`prometheux.workspace.yaml`**
```yaml
schemaVersion: 1
workspace:
  name: acme-data
context: ./context
projects:
  - ./projects/credit-risk
  - ./projects/fraud-detection
```

**`projects/<slug>/prometheux.yaml`**
```yaml
schemaVersion: 1
project:
  id: 1d22942b9a0        # server project id; absent on a brand-new project (apply fills it)
  name: Credit Risk
  scope: user            # user | organization
concepts: ./concepts
datasources:
  - ./datasources/snowflake_prod.yaml
ontology: ./ontology/schema.yaml
apps: ./apps
context: ./context
```
> `apply` writes the assigned `id` back into this file after creating a project — keep it (commit
> it) so re-apply targets the same project. If the id is lost, `apply` reconciles by **name**
> (adopts a single existing same-name project in scope rather than creating a duplicate); a unique
> project name makes that reliable.

---

## Concept kinds

A concept = a body file (`concepts/<predicate>.<ext>`) + a `<predicate>.meta.yaml` envelope.

| Kind | Body file | `conceptType` | Notes |
|---|---|---|---|
| logic | `.vadalog` | `logic` | native Vadalog rules |
| sql | `.sql` | `sql` | SQL source; server transpiles to Vadalog on apply |
| cypher | `.cypher` | `cypher` | Cypher source; transpiled on apply |
| python | `.py` | `python` | a Python script (leaf node) |
| llm | `.llm.md` | `llm` | prompt template + `llmConfig` frontmatter |
| context | `.context.yaml` | `context` | note selection (static `notes`/`noteIds`, or dynamic `query`) |

**`concepts/customers.meta.yaml`**
```yaml
conceptType: logic
outputPredicate: customer
group: ingest
binds:
  input:
    - predicate: source_customers   # the predicate used in the body
      datasource: snowflake_prod    # a datasources/ file name
fields:
  - { name: Id, type: string }
```
Edges between concepts are **derived** from body predicate references — never hand-written.

---

## Datasources

Two shapes; secrets are always `${ENV_VAR}` placeholders resolved from the environment at
apply and **never** written to files.

**Connection** (postgres / mariadb / clickhouse / teradata / snowflake / …) — author **one
table per file** so the concept binds it unambiguously (a DB connect returns the whole group):
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

**Local file** (csv / parquet / json / excel / …) — apply uploads it to the workspace disk,
then connects it (requires the Data Manager service):
```yaml
name: customers_csv
type: csv
file: ../data/customers.csv
diskPath: uploads         # optional subdir under disk/
```

**Object store (S3)** — connect in place, no upload. Put the **full path** (bucket **and**
sub-dir) in `host`, and **do not** set `database`:
```yaml
name: s3_air_routes
type: csv
host: s3a://my-bucket/airports    # full path — bucket AND sub-dir
port: 0
s3aAccessKey: ${S3_ACCESS_KEY}
s3aSecretKey: ${S3_SECRET_KEY}
useHeaders: "true"
tables:
  - air-routes-nodes.csv
```
> ⚠️ Splitting the path (`host: s3a://my-bucket`, `database: airports`) makes the connect
> *succeed* but the stored bind drops the sub-dir — the concept then fails at **run** with
> `PATH_NOT_FOUND`. Always put the whole path in `host`.

A concept reads a datasource via an input bind in its `.meta.yaml` (`binds.input`,
referencing the datasource `name`). Datasources already on the account are reused, not
re-connected.

---

## Context layer

Context lives as `*.context.md` manifests that point at pristine body files. See
[`px context apply`](#px-context-apply-path) for the full model. Minimal manifest:
```yaml
---
scope: project            # global | project
activation: retrieved     # retrieved | always | on_demand
kind: fact
notes:
  - docs/policy.md
links:
  - from: docs/policy.md
    to: concept:credit_risk_score
    relation: relates_to
---
Optional prose for the human reader; ignored by import.
```

---

## Recipes

**Duplicate a project (same account or another):**
```bash
px pull <id> --out /tmp/copy
# edit /tmp/copy/projects/<slug>/prometheux.yaml: remove `id:`, change the name
px apply /tmp/copy -y        # creates a new project; app/results paths retargeted automatically
```

**Port a file-based project across accounts (files travel):**
```bash
px login --url <SOURCE> --token <A>
px pull <id> --with-files --out /tmp/port     # downloads files, writes portable file: specs
px login --url <TARGET> --token <B>
px apply /tmp/port -y                          # re-uploads files, recreates everything
```

**Refer to the same shared files without downloading** (parquet/csv on a shared disk/S3):
just `px pull` (no `--with-files`) and apply — the copy's binds point at the same paths, and
the datasources are reused.

**Monitor runs while you work:**
```bash
px status --watch
```

**CI apply (no interactive login):**
```bash
JARVISPY_URL=... PMTX_TOKEN=... PG_PASSWORD=... px apply -y
```

---

## State, idempotency & exit codes

- **Project id** is written into `projects/<slug>/prometheux.yaml` on create — commit it so
  re-apply targets the same project.
- **Context state** (`.px/context-state.json`, keyed by `(manifest, path)`) drives idempotent
  `context apply`. Commit it when you can; if it's lost, `context apply` reconciles against the
  server's existing notes (by content) so notes aren't duplicated.
- **Idempotent:** a clean `pull` then `plan`/`apply` reports no changes; re-applying is a
  no-op.
- **Exit codes:** `validate` → 0 PASS / non-zero FAIL. `apply` → 0 on success; non-zero if any
  concept was skipped (with a summary) or on a hard error. `plan`/`status` → 0.

---

## Gotchas

- **Keep the `id` in `prometheux.yaml`** — it targets the same project on re-apply. If it's lost,
  `apply` adopts an existing same-name project (reconcile-by-name) instead of duplicating, so a
  unique project name makes recovery reliable.
- **One table per datasource file** for DB connections (a connect returns the whole group).
- **S3 host** must be the full `bucket/sub-dir` path (see [Datasources](#datasources)).
- **Login URL** has no `/api` suffix (the SDK adds `/api/v1`).
- **Backend version differences** can change server-derived names (e.g. sql output columns),
  which can break an app's pinned `columns` when moving between platforms of different versions.

---

## Repo layout

```
src/prometheux_cli/
  cli.py            # `px` entry point (click)
  commands/         # init, validate, login, pull, plan, apply, run, status, delete, context
  validation.py     # offline schema + structural engine
  reshape.py        # export dict -> file tree (pull)
  loader.py         # file tree -> typed model (plan/apply)
  plan.py           # diff engine + downstream cascade + datasource/app diffs
  apply.py          # local concept -> save_concept args (pure functions)
  datasources.py    # secret resolution + connect payloads
  openlineage.py    # OpenLineage RunEvent builder
  context.py        # collect notes+links from *.context.md manifests
  sdk.py            # lazy bridge to prometheux_chain
  credentials.py    # CLI credential store (login)
  parsing.py        # yaml / frontmatter helpers
  resources.py      # bundled schemas + scaffold access
  schemas/          # published JSON Schemas — the single source of truth
  scaffold/         # `px init` starter workspace
tests/
examples/           # copy-and-run usage examples (one folder each)
stress-tests/       # regression scenarios + adversarial (chaos) harnesses
```

**Test:**
```bash
pytest -q
```
