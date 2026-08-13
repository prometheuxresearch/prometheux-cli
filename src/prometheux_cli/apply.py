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
# The ontology-id segment of a concept-output (parquet) results path.
_RESULTS_RE = re.compile(r'(disk/results/)[^/"\'\\]+')


def rewrite_results_ontology_id(annotation: str, ontology_id: str) -> str:
    """Point a ``disk/results/<id>/…`` path at the current ontology.

    A concept that reads a sibling concept's materialized output carries an input
    bind like ``@bind("up","parquet","disk/results/<oldid>","up")``. On another
    ontology/account that ``<oldid>`` is wrong — the sibling's output lives under
    the *current* ontology's results dir — so rewrite the id segment. Only touches
    ``disk/results/`` (concept outputs), never ``disk/<uploads>`` (datasource files).
    """
    if not annotation or not ontology_id:
        return annotation
    return _RESULTS_RE.sub(lambda m: m.group(1) + ontology_id, annotation)


def _predicate_of(annotation: str) -> str:
    m = _BIND_PRED_RE.search(annotation or "")
    return m.group(1) if m else ""


def is_default_parquet_output(annotation: str) -> bool:
    """Heuristic mirror of the server's default-parquet detection.

    A materialized concept's output bind looks like
    ``@bind("p","parquet","<dir>/results/<ontology>","p").`` and is regenerated
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


def _friendly_input_binds(meta: dict, datasource_binds: Dict[str, str], rewrite) -> List[dict]:
    """Turn a concept's `binds.input` (predicate + datasource) into input @bind entries."""
    out: List[dict] = []
    for entry in (meta.get("binds") or {}).get("input", []) or []:
        if not isinstance(entry, dict):
            continue
        ds = entry.get("datasource")
        pred = entry.get("predicate")
        template = datasource_binds.get(ds) if ds else None
        if template and pred:
            out.append({"annotation": rewrite(template, pred), "predicate": pred})
    return out


def ensure_output_atom(definition: str, predicate: str, has_output_bind: bool) -> str:
    """Guarantee a Vadalog concept declares an output atom.

    The save endpoint only reconstructs `@output` when binds are supplied; a
    definition sent with no output bind and no inline `@output` is stored without
    an output atom and cannot run ("No output atom specified"). If neither is
    present, append `@output("<predicate>").`.
    """
    if has_output_bind or "@output" in definition or "@qbind" in definition:
        return definition
    body = definition.rstrip()
    sep = "\n" if body else ""
    return f'{body}{sep}\n@output("{predicate}").\n'


def concept_save_kwargs(
    concept: LocalConcept, *, update: bool, datasource_binds: Dict[str, str] = None,
    ontology_id: str = None
) -> Dict[str, object]:
    """Build the keyword arguments for ``px.save_concept`` (minus ontology_id/scope).

    ``datasource_binds`` maps a datasource name to its connect-returned ``@bind``
    template, used to wire a concept's friendly ``binds.input`` (predicate +
    datasource) into a real input bind so the concept reads that datasource.
    """
    from .datasources import rewrite_bind_predicate

    meta = concept.meta or {}
    predicate = concept.predicate
    kwargs: Dict[str, object] = {
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

    # Friendly binds.input referencing a datasource -> a real input @bind.
    friendly_inputs = _friendly_input_binds(meta, datasource_binds or {}, rewrite_bind_predicate)
    if friendly_inputs:
        binds = binds or {"input": [], "output": []}
        binds.setdefault("input", [])
        binds["input"].extend(friendly_inputs)

    if binds and ontology_id:
        # Retarget sibling-output (parquet) input paths at the current ontology.
        for entry in binds.get("input") or []:
            if isinstance(entry, dict) and isinstance(entry.get("annotation"), str):
                entry["annotation"] = rewrite_results_ontology_id(entry["annotation"], ontology_id)

    if binds:
        kwargs["binds"] = binds

    definition = concept.body
    if concept.concept_type == "logic":
        has_output_bind = bool(binds and binds.get("output"))
        definition = ensure_output_atom(definition, predicate, has_output_bind)
    # sql/cypher definitions are SOURCE queries: the server transpiles them and
    # names the head after `concept_name`, so no `@output` atom is appended
    # (that would corrupt the SQL/Cypher before transpilation).
    kwargs["definition"] = definition

    if update:
        kwargs["existing_name"] = predicate
        kwargs["force_overwrite"] = True
    return kwargs


def is_generative(concept: LocalConcept) -> bool:
    """True for the non-Vadalog reasoning kinds saved with a ``concept_config``."""
    return concept.concept_type in {"context", "llm"}


def generative_concept_config(concept: LocalConcept, note_ids: List[str] = None) -> Optional[dict]:
    """Build the ``concept_config`` for a context/llm concept (None otherwise).

    - ``llm``: the ``llmConfig`` frontmatter block (provider/model/output_columns/…),
      passed through verbatim; the prompt template is the concept body (``definition``).
    - ``context`` **dynamic**: ``{"mode": "dynamic", "query", "top_k"?, "kinds"?}``.
    - ``context`` **static**: ``{"mode": "static", "note_ids": [...]}`` — ``note_ids`` are
      resolved by the caller from the manifest note paths (design §1 "How the path
      resolves"); an explicit ``noteIds``/``note_ids`` in the meta overrides resolution.
    """
    meta = concept.meta or {}
    if concept.concept_type == "llm":
        cfg = dict(meta.get("llmConfig") or {})
        return cfg or None
    if concept.concept_type == "context":
        mode = (meta.get("contextMode") or "static").strip().lower()
        if mode == "dynamic":
            cfg: dict = {"mode": "dynamic", "query": (meta.get("query") or "").strip()}
            if meta.get("top_k") is not None:
                cfg["top_k"] = meta["top_k"]
            if meta.get("kinds"):
                cfg["kinds"] = list(meta["kinds"])
            return cfg
        explicit = meta.get("noteIds") or meta.get("note_ids")
        ids = [str(n) for n in explicit] if explicit else list(note_ids or [])
        return {"mode": "static", "note_ids": ids}
    return None


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
