# px examples

Self-contained, copy-and-run examples of using the Prometheux CLI (`px`) to author a
workspace as files and apply it to a live platform. Each folder stands on its own — copy it,
read its `README.md`, run its script. They double as templates you can hand to an LLM ("author
me a workspace like `examples/csv-to-knowledge-graph`").

Each `run.sh` **authors its workspace inline** (via heredocs) and then calls `px`, so the script
itself is the annotated template — you can read exactly what each file should contain.

## Examples

| Folder | What it shows |
|---|---|
| [`csv-to-knowledge-graph/`](csv-to-knowledge-graph/) | Cold start: drop CSVs → concepts → a queryable graph you can `px run`. |
| [`gitops-sync/`](gitops-sync/) | Files as the source of truth: `plan`/`apply`, idempotency, the downstream re-run cascade, and safe delete with `--prune`. |
| [`import-graph/`](import-graph/) | Import an external property graph (node/edge CSVs) **as concepts** + a type ontology — the way that actually renders on the platform. |
| [`continuous-context/`](continuous-context/) | Watch a folder and push each new markdown file to an ontology's **context layer** as a note (`px context apply` in a loop). |

## Prerequisites (all examples)

1. **Install `px`** (from a checkout of this repo; not yet on PyPI):
   ```bash
   pip install -e ".[dev]"
   px --help
   ```
2. **Authenticate.** Either `px login`, or set env vars (what the scripts use):
   ```bash
   export JARVISPY_URL="https://api.prometheux.ai/jarvispy/<org>/<user>"   # no /api suffix
   export PMTX_TOKEN="<your JWT>"
   ```
   Local dev default is `http://localhost:8000` with token `devtoken`.

## Notes

- The scripts author their workspace into a local `./workspace/` on first run and reuse it after,
  so re-running is idempotent (a fresh `apply` reports "No changes"). Delete `./workspace/` to
  start over.
- Applying an example **creates an ontology on your account**. Clean it up when done:
  ```bash
  px delete "<ontology name>" -y
  ```
- Examples that use CSV file datasources require the account's Data Manager service (file upload).
