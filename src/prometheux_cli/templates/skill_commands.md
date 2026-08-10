## The `px` CLI — command reference

`px` is installed on the user's PATH. You drive it by running shell commands. `init` and
`validate` work fully offline; `login`, `pull`, `plan`, `apply`, `run`, `context`, `status`,
and `delete` reach the platform (auth via `px login`, or `JARVISPY_URL` + `PMTX_TOKEN` env).

- **`px init [DIR]`** — scaffold a workspace (schemas, example project, this guide).
  `--name TEXT`, `--force` (write into a non-empty dir).
- **`px validate [DIR]`** — offline schema + structural checks; PASS/FAIL exit code.
  `--strict` (treat warnings as failures). Run this in a loop while authoring.
- **`px login`** — store + verify platform URL/token in `~/.prometheux/config.json`.
  `--url TEXT` (default `http://localhost:8000`), `--token TEXT` (prompted if omitted),
  `--no-verify`. In CI, set `JARVISPY_URL` + `PMTX_TOKEN` instead.
- **`px pull PROJECT`** — export a live project id into `./projects/<slug>/`.
  `--scope [user|organization]`, `--out PATH`, `--slug TEXT`, `--with-files` (download
  uploaded file-datasource content so the project round-trips on another account).
- **`px plan [DIR]`** — diff local files vs server: create / update / replace per resource +
  the downstream re-run cascade. Writes nothing. `-p/--project TEXT` (repeatable) to scope.
- **`px apply [DIR]`** — apply over REST (snapshot-first, confirm prompt). `-p/--project`,
  `-y/--yes`, `--prune` (delete server concepts absent locally), `--no-snapshot`,
  `--with-files` (force re-upload of file datasources).
- **`px run CONCEPT [DIR]`** — run an output predicate + emit OpenLineage START/COMPLETE/FAIL.
  `-p/--project`, `--param KEY=VALUE` (repeatable), `--persist` (materialize outputs),
  `--openlineage-file PATH`, `--openlineage-url TEXT`, `--no-openlineage`.
- **`px context apply [DIR]`** — apply the context layer from `*.context.md` manifests
  (idempotent via `.px/context-state.json`; commit that file). `-y/--yes`, `--prune`.
- **`px status`** — one row per ontology: current/latest run status + executing concept.
  `-w/--watch`, `-i/--interval FLOAT`, `--scope TEXT` (comma-separated).
- **`px delete PROJECT`** — permanently delete a project by id or name (server auto-snapshots
  first; local files untouched). `--scope [user|organization]`, `-y/--yes`.

**Typical loop:** author files → `px validate` (until PASS) → `px plan` (read the cascade) →
`px apply`. Never put secrets in files; reference them as `${ENV_VAR}`.
