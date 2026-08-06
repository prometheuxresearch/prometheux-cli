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
    action: str  # create | unchanged
    bind: Optional[str] = None  # existing server bind_annotation, when matched (unchanged)


@dataclass
class AppChange:
    identity: str
    name: str
    action: str  # create | update | delete | unchanged
    server_id: Optional[str] = None  # server app id (for update/delete, or name-matched create)


@dataclass
class PlanResult:
    project_name: str
    scope: str
    project_id: Optional[str]
    concept_changes: List[ConceptChange] = field(default_factory=list)
    datasource_changes: List[DatasourceChange] = field(default_factory=list)
    app_changes: List[AppChange] = field(default_factory=list)
    cascade: Dict[str, List[str]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    populated: Set[str] = field(default_factory=set)
    ontology_change: Optional[str] = None  # create | update | unchanged | None (no local ontology)

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
        return (
            any(c.action != "unchanged" for c in self.concept_changes)
            or any(d.action != "unchanged" for d in self.datasource_changes)
            or any(a.action != "unchanged" for a in self.app_changes)
            or self.ontology_change in {"create", "update"}
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


def plan_project(local: LocalProject, export: Optional[dict], note_resolver=None,
                 server_apps=None, server_sources=None, server_datasources=None) -> PlanResult:
    """Diff a local project against its server export (None => brand-new project).

    ``note_resolver`` (path -> [note id]) lets a static context concept's pinned
    note set participate in the diff, so re-pinning after `px context apply` shows
    as an update instead of being silently skipped.

    ``server_apps`` (list of ``{id, name, definition}``) is fetched by the command
    via ``list_apps``/``get_app`` — apps live in a renamed table the export can't
    reliably name, so they are diffed from this dedicated fetch instead.
    """
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
        change = _classify(concept, row, note_resolver, server_sources or {})
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

    _diff_datasources(local, export, server_datasources, result)
    _diff_ontology(local, export, result)
    _diff_apps(local, server_apps, result)
    return result


def _config_no_nulls(value) -> dict:
    """Parse a ``concept_config`` and drop null-valued keys.

    The server materializes every optional field as ``null`` (llm provider/model,
    dynamic-context top_k/kinds); the local side simply omits them. Dropping nulls
    makes the two comparable so only real differences (e.g. a static concept's
    ``note_ids``) register.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except ValueError:
            return {}
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if v is not None}


def _generative_config_changed(concept: LocalConcept, row: dict, note_resolver) -> bool:
    """True when a context/llm concept's local ``concept_config`` differs from server."""
    from .apply import generative_concept_config

    note_ids: List[str] = []
    meta = concept.meta or {}
    if (
        concept.concept_type == "context"
        and (meta.get("contextMode") or "static").strip().lower() != "dynamic"
        and not (meta.get("noteIds") or meta.get("note_ids"))
        and note_resolver is not None
    ):
        for path in meta.get("notes") or []:
            matches = note_resolver(path)
            if len(matches) == 1:
                note_ids.append(matches[0])
    local_config = generative_concept_config(concept, note_ids=note_ids) or {}
    return _canon(_config_no_nulls(local_config)) != _canon(_config_no_nulls(row.get("concept_config")))


def _classify(concept: LocalConcept, row: dict, note_resolver=None, server_sources=None) -> ConceptChange:
    populated = row.get("is_populated") in _TRUTHY
    server_sources = server_sources or {}
    if concept.concept_type in {"sql", "cypher"} and concept.predicate in server_sources:
        # The file holds the SOURCE query; compare against the server's recovered
        # source (parsed.code), not the transpiled `rules` column.
        rules_changed = _normalize_rules(server_sources[concept.predicate]) != _normalize_rules(concept.body)
    else:
        rules_changed = _normalize_rules(row.get("rules") or "") != _normalize_rules(concept.body)

    binds_changed = False
    local_binds = (concept.meta.get("annotations") or {}).get("bind_annotations")
    if local_binds is not None:
        binds_changed = _canon(row.get("bind_annotations")) != _canon(local_binds)

    if concept.concept_type in {"context", "llm"} and _generative_config_changed(concept, row, note_resolver):
        return ConceptChange(
            concept.predicate, "update", reason="config changed", server_populated=populated
        )

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


def _ds_port(value) -> str:
    """Normalize a datasource port so '', '0', 0, None all compare equal."""
    return "" if value in (None, "", 0, "0") else str(value)


def _ds_table(spec: dict) -> Optional[str]:
    """The single table a connection-style datasource binds (None for file uploads)."""
    t = spec.get("tables")
    if isinstance(t, str) and t.strip():
        return t.strip()
    if isinstance(t, list) and len(t) == 1 and isinstance(t[0], str):
        return t[0].strip()
    return None


def _ds_key(type_, host, port, table):
    return (str(type_ or "").lower(), str(host or ""), _ds_port(port), str(table or ""))


def _diff_datasources(local: LocalProject, export, server_datasources, result: PlanResult) -> None:
    """Classify each local datasource create / unchanged, avoiding needless re-connects.

    Two ways to recognize a datasource that already exists:
    - **Connection identity** (type, host, port, table) against the account's
      datasources (``list_sources``): matches shared/authored connections and
      lets apply reuse the existing bind instead of re-connecting — so repeated
      applies don't pile up duplicate datasource rows.
    - **Name** against the project export: a pulled datasource is named by its
      server datasource_id, so its own re-plan stays clean.

    Datasources are user-scoped and shared, so none are ever deleted.
    """
    server_by_key = {}
    for s in server_datasources or []:
        key = _ds_key(s.get("datasource_type"), s.get("host"), s.get("port"), s.get("table_name"))
        server_by_key.setdefault(key, s.get("bind_annotation"))
    export_names = {r.get("datasource_id") for r in _table(export or {}, "datasources_")
                    if r.get("datasource_id")}

    for name, spec in local.datasources.items():
        table = None if spec.get("file") else _ds_table(spec)
        key = _ds_key(spec.get("type"), spec.get("host"), spec.get("port"), table)
        bind = server_by_key.get(key) if table else None
        if bind:
            result.datasource_changes.append(DatasourceChange(name, "unchanged", bind=bind))
        elif name in export_names:
            result.datasource_changes.append(DatasourceChange(name, "unchanged"))
        else:
            result.datasource_changes.append(DatasourceChange(name, "create"))


def fetch_server_datasources(px, scope: str) -> List[dict]:
    """Every datasource already connected on the account (user-scoped).

    Used to match a local connection so apply can reuse its bind instead of
    re-connecting. Best-effort: returns ``[]`` if the endpoint is unavailable.
    """
    try:
        return px.list_sources(scope=scope) or []
    except Exception:  # noqa: BLE001 - never fail the plan over this
        return []


def _normalize_ontology(data) -> dict:
    """Drop server-derived fields so a hand-authored ontology round-trips.

    The server regenerates each edge's ``id`` from ``from``/``label``/``to`` on
    every save (``_normalize_ontology_schema_ids`` in jarvispy), so an author who
    never wrote an ``id`` would otherwise see a perpetual "update". Edge ``id`` is
    derived state, like ``derived_from`` — it does not belong in the diff.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return {}
    if not isinstance(data, dict):
        return {}
    edges = []
    for edge in data.get("edges") or []:
        if isinstance(edge, dict):
            edge = {k: v for k, v in edge.items() if k != "id"}
        edges.append(edge)
    return {**data, "edges": edges}


def _app_differs(local_def: dict, server_def: dict) -> bool:
    """Compare two AppDefinitions, ignoring identity/editor keys.

    ``id`` is dropped because a not-yet-applied local file has none while the
    server always does; ``$schema`` is an editor hint the server never stores.
    """
    def _clean(d):
        return {k: v for k, v in (d or {}).items() if k not in ("id", "$schema")}
    return _canon(_clean(local_def)) != _canon(_clean(server_def))


def _diff_apps(local: LocalProject, server_apps, result: PlanResult) -> None:
    """Classify each app create / update / unchanged, and server-only apps delete.

    Identity is the app's server ``id`` when the file has one; a file without an
    id is matched to an existing app by ``name`` so re-applying an authored app
    updates it in place instead of creating a duplicate.
    """
    servers = list(server_apps or [])
    by_id = {a.get("id"): (a.get("definition") or {}) for a in servers if a.get("id")}
    name_to_id = {a.get("name"): a.get("id") for a in servers if a.get("name") and a.get("id")}
    matched: Set[str] = set()

    for app in local.apps:
        sid = None
        if app.has_id and app.identity in by_id:
            sid = app.identity
        elif not app.has_id and app.name in name_to_id:
            sid = name_to_id[app.name]
        if sid is not None:
            matched.add(sid)
            action = "update" if _app_differs(app.definition, by_id.get(sid, {})) else "unchanged"
            result.app_changes.append(AppChange(app.identity, app.name, action, server_id=sid))
        else:
            result.app_changes.append(AppChange(app.identity, app.name, "create"))

    for a in servers:
        sid = a.get("id")
        if sid and sid not in matched:
            result.app_changes.append(
                AppChange(sid, a.get("name") or sid, "delete", server_id=sid)
            )


def fetch_server_sources(px, project_id: str, scope: str) -> Dict[str, str]:
    """Return ``{predicate: source query}`` for every sql/cypher concept.

    A sql/cypher concept stores transpiled Vadalog in ``rules``; the authored
    source is recovered server-side (``extract_*_from_rule``) and returned as
    ``parsed.code`` by ``list_concepts``. Diffing and pull use this so the file
    holds the source the user wrote, not the generated Vadalog. Best-effort:
    returns ``{}`` if the endpoint is unavailable.
    """
    try:
        concepts = px.list_concepts(project_id, scope) or []
    except Exception:  # noqa: BLE001 - never fail the plan over this
        return {}
    sources: Dict[str, str] = {}
    for c in concepts:
        if c.get("concept_type") in {"sql", "cypher"}:
            pred = c.get("predicate_name")
            code = (c.get("parsed") or {}).get("code")
            if pred and code is not None:
                sources[pred] = code
    return sources


def fetch_server_apps(px, project_id: str, scope: str) -> List[dict]:
    """Load every app's ``{id, name, definition}`` for a project (best-effort).

    Apps are fetched via ``list_apps`` + ``get_app`` rather than the project
    export, because the export table was renamed (``dashboards_`` -> ``apps_``)
    and cannot be named reliably across migration states. Returns ``[]`` when the
    project has no apps or the endpoint is unavailable.
    """
    try:
        metas = px.list_apps(project_id, scope) or []
    except Exception:  # noqa: BLE001 - apps are optional; never fail the plan
        return []
    apps: List[dict] = []
    for meta in metas:
        app_id = meta.get("id")
        if not app_id:
            continue
        try:
            full = px.get_app(project_id, app_id, scope) or {}
            apps.append({
                "id": full.get("id") or app_id,
                "name": full.get("name") or meta.get("name"),
                "definition": full.get("definition") or {},
            })
        except Exception:  # noqa: BLE001
            apps.append({"id": app_id, "name": meta.get("name"), "definition": {}})
    return apps


def _diff_ontology(local: LocalProject, export: Optional[dict], result: PlanResult) -> None:
    """Classify the project's ontology schema as create / update / unchanged.

    Left None when there is no local ontology file — apply never touches the
    server ontology in that case (safe-by-default, like withheld deletions).
    """
    if not local.ontology:
        return
    server_rows = _table(export or {}, "ontology_schema_")
    server_data = server_rows[0].get("ontology_schema_data") if server_rows else None
    if not server_data:
        result.ontology_change = "create"
    elif _canon(_normalize_ontology(server_data)) != _canon(_normalize_ontology(local.ontology)):
        result.ontology_change = "update"
    else:
        result.ontology_change = "unchanged"
