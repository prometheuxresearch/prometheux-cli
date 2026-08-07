# px CLI — stress tests

End-to-end scenario scripts that drive the installed `px` against a **live
account**, simulating natural new-customer adoption paths. They exist to shake
out bugs before productionization; findings go in
`engineering-docs/notes/px-cli-stress-test-bugs.md`.

Each script is self-contained, prints a `PASS`/`FAIL` summary, and exits `0`
(all checks passed) or `1` (a check failed) / `2` (setup error) so they can run
in CI later.

## Prerequisites

- `px` on `PATH` (or set `PX=/path/to/px`, or run from a repo with `.venv/bin/px`).
- A reachable account and its JWT:

```bash
export JARVISPY_URL="https://api.prometheux.ai/jarvispy/prometheux/staging"
export PMTX_TOKEN="<your JWT>"
```

Scenarios that use CSV file datasources (1, 2) require the account's **Data
Manager** service (file upload). Scenario 3 is ontology-only.

## Run

```bash
./01-csv-cold-start.sh      # CSV folder → knowledge graph (widest pipeline coverage)
./02-gitops-sync.sh         # idempotency, drift, downstream cascade, prune
./03-import-ontology.sh     # external graph → concepts + ontology (+ hollow-ontology guard)

# or all of them:
for s in ./0*.sh; do "$s" || echo "^ $s FAILED"; done
```

## How state is handled

The CLI has **no delete-project command**, so to avoid littering the account
each scenario reuses **one** project per script:

- Generated workspaces live under `stress-tests/.state/<scenario>/ws`
  (git-ignored). The project `id` written back into `prometheux.yaml` on the
  first apply is reused on later runs, so re-running **updates** that project.
- `PX_FRESH=1` starts a brand-new project instead. The previous one becomes an
  orphan (the script warns) — clean it up via the platform UI / MCP
  `delete_ontology` if needed.
- `PX_KEEP=1` is a no-op today (workspaces are always kept under `.state/`).

## Env knobs

| Var | Meaning |
|---|---|
| `JARVISPY_URL`, `PMTX_TOKEN` | account + JWT (required) |
| `PX` | path to the `px` binary (default: PATH, else `../.venv/bin/px`) |
| `PX_FRESH=1` | create a new project this run (orphans the old one) |
| `PG_PASSWORD`, `S3_*`, … | secrets any scenario's datasources reference via `${ENV}` |

## Adding a scenario

1. `source "$(dirname "$0")/_lib.sh"` after setting `SCENARIO=<unique-name>`.
2. `require_auth` then `new_workspace` (sets `$WS`, honors id reuse).
3. Build files under `$WS`, then use the helpers: `assert_ok`,
   `assert_out_has`, `assert_out_lacks`, `assert_plan_clean`, `remember_project_id`.
4. The `EXIT` trap prints the PASS/FAIL summary and sets the exit code.
