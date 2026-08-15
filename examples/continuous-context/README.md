# Continuous context ingestion

Watch a folder and stream every new markdown file into an ontology's **context layer** as a note —
a simple model for continuous document ingestion (drop a doc, it shows up as context on the
platform).

- **`gen-notes.sh`** — every N seconds writes a `note-*.md` full of random words into the folder
  (stands in for "documents landing"). Files are kept, never deleted.
- **`watch-push.sh`** — watches that folder; on each change it rebuilds a project-scoped
  `*.context.md` manifest and runs `px context apply`, pushing each new file as a context note
  whose **text is the file content**. Idempotent — only new/changed files are pushed.

## Run

Context notes attach to an **existing ontology**, so create one first and grab its id — run one of
the other examples, or create an ontology in the app.

Terminal 1 — generate notes:
```bash
./gen-notes.sh
```

Terminal 2 — watch + push (first run needs the ontology id):
```bash
export JARVISPY_URL="https://api.prometheux.ai/jarvispy/<org>/<user>"
export PMTX_TOKEN="<your JWT>"
export ONTOLOGY_ID="<your ontology id>"
./watch-push.sh
```

After the first run the id is saved in `workspace/ontologies/ctx/prometheux.yaml`, so later runs
don't need `ONTOLOGY_ID`.

## Verify

Open that ontology in the app → **Context** page. Each note's text should match a local file:
```
workspace/ontologies/ctx/context/note-*.md
```

## Notes

- Faster cadence: `./gen-notes.sh <dir> 3` and `./watch-push.sh 2`.
- Nothing is deleted. To reset: remove `workspace/ontologies/ctx/context/note-*.md`,
  `notes.context.md`, and `workspace/.px/context-state.json`.
