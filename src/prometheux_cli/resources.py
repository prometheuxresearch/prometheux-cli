"""Access to bundled package resources: JSON Schemas and the `px init` scaffold.

Everything is loaded through ``importlib.resources`` so it works from a wheel,
an editable install, or a zipapp — no reliance on ``__file__`` paths.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Dict

_SCHEMA_DIR = "schemas"


def _schema_root():
    # Resolve schemas/ as a subpath of the real package (works on py3.9, where
    # importlib.resources.files can't resolve a data-only namespace subpackage).
    return resources.files("prometheux_cli").joinpath(_SCHEMA_DIR)


# Manifest/meta kind -> bundled schema filename.
SCHEMA_FILES: Dict[str, str] = {
    "workspace": "workspace.schema.json",
    "project": "project.schema.json",
    "concept-meta": "concept-meta.schema.json",
    "context-concept": "context-concept.schema.json",
    "datasource": "datasource.schema.json",
    "context-set": "context-set.schema.json",
}


def load_schema(kind: str) -> dict:
    """Return the parsed JSON Schema for ``kind`` (see :data:`SCHEMA_FILES`)."""
    try:
        filename = SCHEMA_FILES[kind]
    except KeyError as exc:  # pragma: no cover - programmer error
        raise KeyError(f"unknown schema kind {kind!r}") from exc
    text = _schema_root().joinpath(filename).read_text("utf-8")
    return json.loads(text)


def schema_names() -> Dict[str, str]:
    """Return a copy of the kind -> filename map."""
    return dict(SCHEMA_FILES)


def iter_schema_files():
    """Yield ``(filename, text)`` for every bundled schema, for copying to ``.px/schemas``."""
    root = _schema_root()
    for filename in SCHEMA_FILES.values():
        yield filename, root.joinpath(filename).read_text("utf-8")
