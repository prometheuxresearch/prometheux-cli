# GitOps sync

Your files are the source of truth; `px plan`/`apply` reconcile the platform to match. This
example is a guided walkthrough of the whole reconcile loop.

## Run

```bash
export JARVISPY_URL="https://api.prometheux.ai/jarvispy/<org>/<user>"
export PMTX_TOKEN="<your JWT>"
./run.sh
```

It pauses between steps (press Enter) so you can read each `px plan` before it applies.

## What it demonstrates

1. **Idempotency** — right after `apply`, `px plan` reports `No changes. Local files match server state.`
2. **Downstream cascade** — editing the upstream `item` concept makes `plan` mark `item` updated *and*
   flag `domestic` (which derives from it) as needing a re-run.
3. **Create** — dropping in a new `foreign.vadalog` shows up as `+ concept foreign  create`.
4. **Safe delete** — removing a concept file does **not** delete it on the server; `plan` shows
   `delete (withheld — needs --prune)`. Only `apply --prune` removes it.

Deletions being opt-in (`--prune`) is the key safety property: a vanished file never silently drops
server state.

## Clean up

```bash
px delete "Catalog Example" -y
```
