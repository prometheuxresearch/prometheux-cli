"""Pure helpers for turning a local concept into `save_concept` arguments.

The write contract (verified against jarvispy):

- ``save_concept(definition, binds, output_predicate, existing_name, ...)``.
- The server rebuilds the annotated program from ``binds[*].annotation`` +
  ``definition`` + ``@output(output_predicate)``.
- ``existing_name`` present => update; absent => create.
- **Default parquet output binds are auto-regenerated server-side** and are
  dropped on read, so we must not re-send them (doing so would double them).

`pull` captured the raw DB ``bind_annotations`` column
(``{"input": ["@bind.."], "output": "@bind.."}`` — strings); here we lift that
into the structured shape ``save_concept`` expects.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from .loader import LocalConcept

_BIND_PRED_RE = re.compile(r'@q?bind\(\s*"([^"]+)"')


def _predicate_of(annotation: str) -> str:
    m = _BIND_PRED_RE.search(annotation or "")
    return m.group(1) if m else ""


def is_default_parquet_output(annotation: str) -> bool:
    """Heuristic mirror of the server's default-parquet detection.

    A materialized concept's output bind looks like
    ``@bind("p","parquet","<dir>/results/<project>","p").`` and is regenerated
    by the engine, so it is never re-sent.
    """
    ann = (annotation or "").strip()
    if ann.startswith("@qbind("):
        return False
    return '"parquet"' in ann and "/results/" in ann


def structured_binds(bind_column, output_predicate: str) -> Optional[dict]:
    """Convert a raw ``bind_annotations`` column into structured save binds.

    Returns None when there is nothing to send (server auto-injects defaults).
    """
    col = bind_column
    if isinstance(col, str):
        try:
            col = json.loads(col) if col.strip() else {}
        except ValueError:
            return None
    if not isinstance(col, dict):
        return None

    input_binds: List[dict] = []
    for ann in col.get("input", []) or []:
        if not ann:
            continue
        # An input entry may already be structured (from a friendly author) or a raw string.
        if isinstance(ann, dict):
            input_binds.append(ann)
        else:
            input_binds.append({"annotation": ann, "predicate": _predicate_of(ann)})

    output_binds: List[dict] = []
    out = col.get("output", "")
    if isinstance(out, list):
        out_anns = out
    else:
        out_anns = [out] if out else []
    for ann in out_anns:
        ann_str = ann.get("annotation") if isinstance(ann, dict) else ann
        if ann_str and not is_default_parquet_output(ann_str):
            output_binds.append({"annotation": ann_str, "predicate": output_predicate})

    if not input_binds and not output_binds:
        return None
    return {"input": input_binds, "output": output_binds}


def concept_save_kwargs(concept: LocalConcept, *, update: bool) -> Dict[str, object]:
    """Build the keyword arguments for ``px.save_concept`` (minus ontology_id/scope)."""
    meta = concept.meta or {}
    predicate = concept.predicate
    kwargs: Dict[str, object] = {
        "definition": concept.body,
        "concept_type": concept.concept_type,
        "output_predicate": predicate,
    }
    # Non-logic kinds require an explicit concept_name server-side.
    if concept.concept_type != "logic":
        kwargs["concept_name"] = predicate
    if meta.get("group"):
        kwargs["group"] = meta["group"]
    if meta.get("description"):
        kwargs["description"] = meta["description"]

    bind_column = (meta.get("annotations") or {}).get("bind_annotations")
    binds = structured_binds(bind_column, predicate) if bind_column is not None else None
    if binds:
        kwargs["binds"] = binds

    if update:
        kwargs["existing_name"] = predicate
        kwargs["force_overwrite"] = True
    return kwargs


def topo_order(concepts: List[LocalConcept]) -> List[LocalConcept]:
    """Best-effort dependency order (deps before dependents); cycles kept stable."""
    from .plan import referenced_predicates

    outputs = {c.predicate for c in concepts}
    deps: Dict[str, set] = {}
    for c in concepts:
        if c.is_vadalog_family:
            deps[c.predicate] = (referenced_predicates(c.body) & outputs) - {c.predicate}
        else:
            deps[c.predicate] = set()

    ordered: List[str] = []
    placed: set = set()
    remaining = [c.predicate for c in concepts]
    # Iterate: place any node whose deps are all placed; if stuck (cycle), place
    # the first remaining node to make progress.
    while remaining:
        progress = False
        for pred in list(remaining):
            if deps[pred] <= placed:
                ordered.append(pred)
                placed.add(pred)
                remaining.remove(pred)
                progress = True
        if not progress:
            stuck = remaining.pop(0)
            ordered.append(stuck)
            placed.add(stuck)

    by_pred = {c.predicate: c for c in concepts}
    return [by_pred[p] for p in ordered]
