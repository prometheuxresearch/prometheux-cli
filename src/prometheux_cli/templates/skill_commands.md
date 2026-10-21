## The `px` CLI — command reference

`px` is installed on the user's PATH. You drive it by running shell commands. `init` and
`validate` work fully offline; `login`, `pull`, `plan`, `apply`, `run`, `test`, `stop`, `context`,
`status`, and `delete` reach the platform (auth via `px login`, or `JARVISPY_URL` + `PMTX_TOKEN` env).

- **`px init [DIR]`** — scaffold a workspace (schemas, example ontology, this guide).
  `--name TEXT`, `--force` (write into a non-empty dir).
- **`px validate [DIR]`** — offline schema + structural checks; PASS/FAIL exit code.
  `--strict` (treat warnings as failures). Run this in a loop while authoring.
- **`px login`** — store + verify platform URL/token in `~/.prometheux/config.json`.
  `--url TEXT` (default `http://localhost:8000`), `--token TEXT` (prompted if omitted),
  `--no-verify`. In CI, set `JARVISPY_URL` + `PMTX_TOKEN` instead.
- **`px pull ONTOLOGY`** — export a live ontology id into `./ontologies/<slug>/`.
  `--out PATH`, `--slug TEXT`, `--with-files` (download
  uploaded file-datasource content so the ontology round-trips on another account).
- **`px plan [DIR]`** — diff local files vs server: create / update / replace per resource +
  the downstream re-run cascade. Writes nothing. `-p/--ontology TEXT` (repeatable) to scope.
- **`px apply [DIR]`** — apply over REST (snapshot-first, confirm prompt). `-p/--ontology`,
  `-y/--yes`, `--prune` (delete server concepts absent locally), `--no-snapshot`,
  `--with-files` (force re-upload of file datasources).
- **`px run CONCEPT [DIR]`** — run an output predicate + emit OpenLineage START/COMPLETE/FAIL.
  `-p/--ontology`, `--param KEY=VALUE` (repeatable), `--persist` (materialize outputs),
  `--openlineage-file PATH`, `--openlineage-url TEXT`, `--no-openlineage`.
- **`px context apply [DIR]`** — apply the context layer from `*.context.md` manifests
  (idempotent via `.px/context-state.json`; commit that file). `-y/--yes`, `--prune`.
- **`px status`** — one row per ontology: current/latest run status + executing concept.
  `-w/--watch`, `-i/--interval FLOAT`.
- **`px test [TARGET]`** — unit-test Vadalog programs on the platform engine. TARGET is a
  `.vada` program (with `--expect PRED=CSV`, repeatable), a `*.test.yaml` case, or a folder of
  cases; or `-q/--question TEXT` + `--expect-csv FILE` checks the program the NL translator
  writes. `--mode exact|contains`, `--header`, `--param KEY=VALUE`, `--json`,
  `--junit-xml FILE`, `-j/--jobs N`, `--replicas N|auto` (billed engine workers for the
  suite), `--execution-id ID`. Exit 0 all pass / 1 a check failed / 2 could not run.
- **`px stop [EXECUTION_ID]`** — stop the evaluations sent with that id (a `px test
  --execution-id`) or the run with that id; other users' work keeps running. `--all` stops
  every evaluation and run on the workspace, other users' included.
- **`px delete ONTOLOGY`** — permanently delete an ontology by id or name (server auto-snapshots
  first; local files untouched). `-y/--yes`.

**Typical loop:** author files → `px validate` (until PASS) → `px plan` (read the cascade) →
`px apply`. Never put secrets in files; reference them as `${ENV_VAR}`.
