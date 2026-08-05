"""The plan/diff engine — the one net-new, no-precedent piece of the design.

Pure functions: given a local project model and a server export dict, classify
each concept as create / update / delete / unchanged, and — for a concept whose
*definition* (rules or binds) changed — compute the transitive set of downstream
concepts that a change forces to re-run, along the derived lineage DAG.

The DAG is derived locally: a concept's body predicate references that resolve to
another concept's output predicate ARE the edges. No server graph, no hand-written
edges (design §1).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .loader import LocalConcept, LocalProject

_PREDICATE_RE = re.compile(r"([a-zA-Z_]\w*)\s*\(")
_TRUTHY = {True, "true", "True", "t", "1", 1}


@dataclass
class ConceptChange:
    predicate: str
    action: str  # create | update | delete | unchanged
    definition_changed: bool = False
    reason: str = ""
    server_populated: bool = False


@dataclass
class DatasourceChange:
    name: str
    action: str  # create | update | delete | unchanged


@dataclass
class PlanResult:
    project_name: str
    scope: str
    project_id: Optional[str]
    concept_changes: List[ConceptChange] = field(default_factory=list)
    datasource_changes: List[DatasourceChange] = field(default_factory=list)
    cascade: Dict[str, List[str]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    populated: Set[str] = field(default_factory=set)

    def _count(self, action: str) -> int:
        return sum(1 for c in self.concept_changes if c.action == action)

    @property
    def to_create(self) -> int:
        return self._count("create")

    @property
    def to_update(self) -> int:
        return self._count("update")

    @property
    def to_delete(self) -> int:
        return self._count("delete")

    @property
    def rerun_count(self) -> int:
        return len({p for downstream in self.cascade.values() for p in downstream})

    @property
    def has_changes(self) -> bool:
        return any(c.action != "unchanged" for c in self.concept_changes) or any(
            d.action != "unchanged" for d in self.datasource_changes
        )


def _table(export: dict, prefix: str) -> List[dict]:
    for name, tbl in (export.get("tables") or {}).items():
        if name.startswith(prefix):
            return list((tbl or {}).get("data") or [])
    return []


def _normalize_rules(text: str) -> str:
    return (text or "").replace("\r\n", "\n").strip()


def _canon(value) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value.strip()
    return json.dumps(value, sort_keys=True, default=str)


def referenced_predicates(body: str) -> Set[str]:
    """Predicate names called in a Vadalog body, ignoring `%` line comments."""
    cleaned = "\n".join(line.split("%", 1)[0] for line in body.splitlines())
    return set(_PREDICATE_RE.findall(cleaned))


def build_dependents(concepts: List[LocalConcept]) -> Dict[str, Set[str]]:
    """Map each output predicate -> the set of concepts that depend on it."""
    outputs = {c.predicate for c in concepts}
    dependents: Dict[str, Set[str]] = {p: set() for p in outputs}
    for c in concepts:
        if not c.is_vadalog_family:
            continue  # python/context/llm are leaf nodes: no body-derived deps
        for dep in referenced_predicates(c.body) & outputs:
            if dep != c.predicate:
                dependents[dep].add(c.predicate)
    return dependents


def _transitive_downstream(start: str, dependents: Dict[str, Set[str]]) -> List[str]:
    """Ordered (BFS) transitive dependents of ``start``, excluding ``start``."""
    seen: Set[str] = set()
    order: List[str] = []
    queue = sorted(dependents.get(start, set()))
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        order.append(node)
        queue.extend(sorted(dependents.get(node, set()) - seen))
    return order


def plan_project(local: LocalProject, export: Optional[dict]) -> PlanResult:
    """Diff a local project against its server export (None => brand-new project)."""
    result = PlanResult(project_name=local.name, scope=local.scope, project_id=local.id)

    server_rows = _table(export or {}, "concepts_")
    server = {r.get("predicate_name"): r for r in server_rows if r.get("predicate_name")}
    local_by_pred = {c.predicate: c for c in local.concepts}
    dependents = build_dependents(local.concepts)

    # Duplicate output predicates locally would make the DAG ambiguous.
    if len(local_by_pred) != len(local.concepts):
        result.warnings.append(
            "duplicate output predicates in local project; plan may be inaccurate "
            "(run `px validate`)"
        )

    changed_defs: List[str] = []

    for concept in local.concepts:
        row = server.get(concept.predicate)
        if row is None:
            result.concept_changes.append(ConceptChange(concept.predicate, "create"))
            continue
        change = _classify(concept, row)
        result.concept_changes.append(change)
        if change.definition_changed:
            changed_defs.append(concept.predicate)

    # Withheld deletions: on server, absent locally.
    for pred in server:
        if pred not in local_by_pred:
            result.concept_changes.append(ConceptChange(pred, "delete"))

    # Cascade: transitive downstream re-runs for each definition change.
    populated = {
        p for p, r in server.items() if r.get("is_populated") in _TRUTHY
    }
    for pred in changed_defs:
        downstream = _transitive_downstream(pred, dependents)
        if downstream:
            result.cascade[pred] = downstream
    result.populated = populated

    _diff_datasources(local, export, result)
    return result


def _classify(concept: LocalConcept, row: dict) -> ConceptChange:
    populated = row.get("is_populated") in _TRUTHY
    rules_changed = _normalize_rules(row.get("rules") or "") != _normalize_rules(concept.body)

    binds_changed = False
    local_binds = (concept.meta.get("annotations") or {}).get("bind_annotations")
    if local_binds is not None:
        binds_changed = _canon(row.get("bind_annotations")) != _canon(local_binds)

    if rules_changed or binds_changed:
        reasons = []
        if rules_changed:
            reasons.append("rules")
        if binds_changed:
            reasons.append("binds")
        return ConceptChange(
            concept.predicate,
            "update",
            definition_changed=True,
            reason=" & ".join(reasons) + " changed",
            server_populated=populated,
        )

    if _metadata_changed(concept, row):
        return ConceptChange(
            concept.predicate, "update", reason="metadata changed", server_populated=populated
        )

    return ConceptChange(concept.predicate, "unchanged", server_populated=populated)


def _metadata_changed(concept: LocalConcept, row: dict) -> bool:
    meta = concept.meta
    if "group" in meta and (meta.get("group") or "") != (row.get("concept_group") or ""):
        return True
    if "description" in meta and (meta.get("description") or "") != (row.get("description") or ""):
        return True
    return False


def _diff_datasources(local: LocalProject, export: Optional[dict], result: PlanResult) -> None:
    server_rows = _table(export or {}, "datasources_")
    server_names = {r.get("datasource_id") for r in server_rows if r.get("datasource_id")}
    for name in local.datasources:
        action = "unchanged" if name in server_names else "create"
        # A finer field-level diff is deferred; secrets live only in env, so we
        # cannot compare connection details here.
        result.datasource_changes.append(DatasourceChange(name, action))
    for name in server_names:
        if name not in local.datasources:
            result.datasource_changes.append(DatasourceChange(name, "delete"))
