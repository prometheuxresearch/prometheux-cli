"""OpenLineage event construction — an export, never the internal model (§6).

Given a concept and its local lineage, build OpenLineage RunEvents
(START / COMPLETE / FAIL) so `px run` can emit to any OpenLineage-compatible
catalog (Marquez, DataHub, Unity Catalog, …). Pure functions: no SDK, no I/O.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import __version__
from .loader import LocalConcept
from .plan import referenced_predicates

PRODUCER = f"https://github.com/prometheuxresearch/prometheux-cli#{__version__}"
_SPEC = "https://openlineage.io/spec/1-0-5/OpenLineage.json"
_RUN_EVENT_SCHEMA = f"{_SPEC}#/$defs/RunEvent"


def dataset_namespace(project_id: Optional[str], slug: str) -> str:
    return f"prometheux://{project_id or slug}"


def concept_datasets(
    concept: LocalConcept, local_outputs, namespace: str
) -> Tuple[List[dict], List[dict]]:
    """Return (inputs, outputs) as OpenLineage dataset refs for one concept.

    Inputs are the upstream concepts it references plus its bound datasources;
    the single output is its own predicate. Edges are derived, never authored.
    """
    inputs: List[dict] = []
    seen = set()

    def add(name: str):
        if name and name not in seen:
            seen.add(name)
            inputs.append({"namespace": namespace, "name": name})

    if concept.is_vadalog_family:
        for dep in sorted(referenced_predicates(concept.body) & set(local_outputs)):
            if dep != concept.predicate:
                add(dep)

    meta = concept.meta or {}
    for b in (meta.get("binds") or {}).get("input", []) or []:
        if isinstance(b, dict) and b.get("datasource"):
            add(b["datasource"])

    outputs = [{"namespace": namespace, "name": concept.predicate}]
    return inputs, outputs


def make_run_event(
    *,
    event_type: str,
    run_id: str,
    event_time: str,
    job_namespace: str,
    job_name: str,
    inputs: List[dict],
    outputs: List[dict],
    error_message: Optional[str] = None,
) -> dict:
    """Build one OpenLineage RunEvent. ``event_type`` is START | COMPLETE | FAIL."""
    run_facets = {}
    if error_message:
        run_facets["errorMessage"] = {
            "_producer": PRODUCER,
            "_schemaURL": f"{_SPEC}#/$defs/ErrorMessageRunFacet",
            "message": error_message,
            "programmingLanguage": "VADALOG",
        }
    event = {
        "eventType": event_type,
        "eventTime": event_time,
        "run": {"runId": run_id, "facets": run_facets},
        "job": {"namespace": job_namespace, "name": job_name},
        "inputs": inputs,
        "outputs": outputs,
        "producer": PRODUCER,
        "schemaURL": _RUN_EVENT_SCHEMA,
    }
    return event
