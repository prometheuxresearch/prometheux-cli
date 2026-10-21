## The `px` CLI — command reference

`px` is installed on the user's PATH. You drive it by running shell commands. `init`,
`validate` and `skill install` work fully offline; every other command reaches the platform
(auth via `px login`, or `JARVISPY_URL` + `PMTX_TOKEN` env). Every command takes `-h/--help`.

### Workspace as code

- **`px init [DIRECTORY]`** — scaffold a workspace (schemas, example ontology, this guide).
  `--name TEXT`, `--force` (write into a non-empty dir).
- **`px validate [PATH]`** — offline schema + structural checks; PASS/FAIL exit code.
  `--strict` (treat warnings as failures), `--online` (also check each concept body on the
  platform's Vadalog engine; needs login). Run this in a loop while authoring.
- **`px login`** — store + verify platform URL/token in `~/.prometheux/config.json`.
  `--url TEXT` (default `http://localhost:8000`), `--token TEXT` (prompted if omitted),
  `--no-verify`. In CI, set `JARVISPY_URL` + `PMTX_TOKEN` instead.
- **`px pull [ONTOLOGY]`** — export a live ontology id into `./ontologies/<slug>/` (with no
  ONTOLOGY, list the ontologies you can pull). `--out PATH`, `--slug TEXT`, `--with-files`
  (download uploaded file-datasource content so the ontology round-trips on another account).
- **`px plan [PATH]`** — diff local files vs server: create / update / delete per concept +
  the downstream re-run cascade. Writes nothing. `-o/--ontology TEXT` (repeatable) to scope.
- **`px apply [PATH]`** — apply over REST (snapshot-first, confirm prompt). `-o/--ontology`
  (repeatable), `-y/--yes`, `--prune` (delete server concepts absent locally), `--no-snapshot`,
  `--with-files` (force re-upload of file datasources), `--no-context` (skip the ontologies'
  project-scoped context layer).
- **`px context apply [PATH]`** — apply the context layer from `*.context.md` manifests
  (idempotent via `.px/context-state.json`; commit that file). `-y/--yes`, `--prune` (delete
  notes no longer in any manifest).
- **`px context pull`** — pull the global context notes into `<workspace>/context/pulled.context.md`
  (`px pull` already brings an ontology's own notes). `--out PATH`, `--ontology ID` (also pull
  that ontology's project-scoped notes).
- **`px context search QUERY`** — semantic search across saved context notes.
  `--scope global|project` (`project` needs `--ontology ID`), `--top-k N` (default 10).
- **`px skill install`** — install this skill. `-t/--target claude|claude-project|cursor`
  (repeatable; default `claude`, the global Claude Code skill), `--dir PATH` (base for the
  project targets), `--force` (overwrite an existing install).

### Run, query and test

- **`px run CONCEPT [PATH]`** — run an output predicate + emit OpenLineage START/COMPLETE/FAIL.
  `-o/--ontology` (repeatable), `--param KEY=VALUE` (repeatable), `--persist` (materialize
  outputs), `--run-mode single|auto|all` (how much of the dependency chain to rebuild; default
  `auto`), `--openlineage-file PATH`, `--openlineage-url URL`, `--no-openlineage`.
- **`px show CONCEPT [PATH]`** — print the rows of an output predicate. `-o/--ontology`
  (repeatable), `--page N` (1-based), `--page-size N` (default 100), `--order-by '0:asc,2:desc'`
  (column positions), `--json`.
- **`px query ONTOLOGY_ID CONCEPT_NAME SQL`** — run one SELECT/WITH over a concept's rows,
  e.g. `px query 1db22ad122a tx "SELECT country, count(*) FROM tx GROUP BY country"`. `--json`.
- **`px status`** — one row per ontology: current/latest run status + executing concept.
  `-w/--watch`, `-i/--interval SECONDS` (default 3).
- **`px stop [EXECUTION_ID]`** — stop the evaluations sent with that id (the id `px test` ran a
  suite with) or the run with that id; other users' work keeps running. `--all` stops every
  evaluation and run on the workspace, other users' included.
- **`px test [TARGET]`** — unit-test Vadalog programs on the platform engine. TARGET is a
  `.vada` program (with `--expect PRED=CSV`, repeatable), a `*.test.yaml` case, or a folder of
  cases; or `-q/--question TEXT` + `--expect-csv FILE` checks the program the NL translator
  writes (`--context TEXT`, `--expect-pred PRED`, `--save-vada FILE`). `--mode exact|contains`,
  `--header`, `--param KEY=VALUE`, `--json`, `--junit-xml FILE`, `-j/--jobs N`,
  `--replicas N|auto` (billed engine workers for the suite), `--replicas-timeout SECONDS`,
  `--keep-replicas`, `--execution-id ID`. Exit 0 all pass / 1 a check failed / 2 could not run.

### Look things up

- **`px list ontologies`** — ontologies and their ids (what `px pull` / `px delete` take).
- **`px list concepts`** — an ontology's concepts and predicates (what `px run` / `px show`
  take). `--ontology ID`.
- **`px list datasources`** — connected datasources and their ids.
- **`px list apps`** — apps across all your ontologies and their ids.
- **`px list context`** — context notes and their ids. `--scope global|project` (`project`
  needs `--ontology ID`).
- **`px search concepts QUERY_TEXT`** — find existing concepts similar to the text, to reuse
  them. `--top-k N` (default 5), `--exclude ONTOLOGY_ID`.
- **`px search company QUERY_TEXT`** — search the Prometheux company knowledge base.
- **`px playbook list`** — the platform's skill playbooks and their ids.
- **`px playbook show SKILL_ID`** — print one playbook in full.
- **`px template list`** — catalogue template ontologies and their ids.
- **`px template import TEMPLATE_ID`** — clone a template into a new ontology. `--name TEXT`.

### Manage platform resources

- **`px policy list ONTOLOGY_ID`** — the ontology's evaluation policies. `--concept NAME`.
- **`px policy get ONTOLOGY_ID POLICY_ID`** — one policy's config + last-run status.
- **`px policy create ONTOLOGY_ID CONCEPT_NAME`** — run a concept on a schedule or trigger.
  `--trigger-type cron|data_change` (default `cron`), `--cron EXPR`, `--config JSON` (raw
  trigger config), `--disabled`.
- **`px policy update ONTOLOGY_ID POLICY_ID`** — change the schedule or state. `--cron EXPR`,
  `--config JSON`, `--enable` / `--disable`.
- **`px policy trigger ONTOLOGY_ID POLICY_ID`** — run the policy's concept now.
- **`px policy runs ONTOLOGY_ID POLICY_ID`** — execution history. `--limit N` (default 50),
  `--offset N`.
- **`px policy delete ONTOLOGY_ID POLICY_ID`** — delete and unschedule. `-y/--yes`.
- **`px snapshot list ONTOLOGY_ID`** — snapshots, newest first.
- **`px snapshot create ONTOLOGY_ID`** — snapshot the ontology. `-d/--description TEXT`.
- **`px snapshot restore ONTOLOGY_ID SNAPSHOT_ID`** — overwrite the ontology with a snapshot
  (takes a safety snapshot first). `--no-safety`, `-y/--yes`.
- **`px snapshot delete ONTOLOGY_ID SNAPSHOT_ID`** — `-y/--yes`.
- **`px app publish ONTOLOGY_ID APP_ID`** — publish a frozen, shareable snapshot of the app's draft.
- **`px app unpublish ONTOLOGY_ID APP_ID`** — remove the published snapshot (back to draft-only).
- **`px datasource preview BIND_ANNOTATION`** — first rows of a datasource. `--limit N` (default 10).
- **`px datasource delete BIND_OR_ID`** — disconnect a datasource by its bind annotation.
  `--by-id` (the argument is a datasource id), `-y/--yes`.
- **`px compute status`** — your enabled machines and whether each is active.
- **`px compute start [NAME]`** — start a machine (or the only enabled one).
  `--autotermination MINUTES` (stop after that many idle minutes).
- **`px compute stop [NAME]`** — stop a machine (or the only enabled one).
- **`px compute catalog`** — machines available to provision, with their ids.
- **`px compute provision MACHINE_ID`** — add a catalog machine to your list (not billed until
  started). `--name TEXT`.
- **`px compute remove USER_MACHINE_ID`** — remove a machine from your list (usage history
  kept). `-y/--yes`.
- **`px delete ONTOLOGY`** — permanently delete an ontology by id or name (server auto-snapshots
  first; local files untouched). `-y/--yes`.

**Typical loop:** author files → `px validate` (until PASS) → `px plan` (read the cascade) →
`px apply`. Never put secrets in files; reference them as `${ENV_VAR}`.
