# Continuous context ingestion

Watch a folder and stream every new markdown file into a project's **context layer** as a note —
a simple model for continuous document ingestion (drop a doc, it shows up as context on the
platform).

- **`gen-notes.sh`** — every N seconds writes a `note-*.md` full of random words into the folder
  (stands in for "documents landing"). Files are kept, never deleted.
- **`watch-push.sh`** — watches that folder; on each change it rebuilds a project-scoped
  `*.context.md` manifest and runs `px context apply`, pushing each new file as a context note
  whose **text is the file content**. Idempotent — only new/changed files are pushed.

## Run

Context notes attach to an **existing project**, so create one first and grab its id — run one of
the other examples, or create a project in the app.

Terminal 1 — generate notes:
```bash
./gen-notes.sh
```

Terminal 2 — watch + push (first run needs the project id):
```bash
export JARVISPY_URL="https://api.prometheux.ai/jarvispy/<org>/<user>"
export PMTX_TOKEN="<your JWT>"
export ONTOLOGY_ID="<your project id>"
./watch-push.sh
```

After the first run the id is saved in `workspace/projects/ctx/prometheux.yaml`, so later runs
don't need `ONTOLOGY_ID`.

## Verify

Open that project in the app → **Context** page. Each note's text should match a local file:
```
workspace/projects/ctx/context/note-*.md
```

## Notes

- Faster cadence: `./gen-notes.sh <dir> 3` and `./watch-push.sh 2`.
- Nothing is deleted. To reset: remove `workspace/projects/ctx/context/note-*.md`,
  `notes.context.md`, and `workspace/.px/context-state.json`.
