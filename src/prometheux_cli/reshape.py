"""Turn a project export dict into an on-disk file tree.

The export shape (from prometheux_chain ``export_ontology``) is::

    {
      "project_id": "...", "scope": "user",
      "tables": {
        "projects_workspace_id":     {"schema": [...], "data": [ {..project row..} ]},
        "datasources_workspace_id":  {"schema": [...], "data": [ {..ds rows..} ]},
        "ontology_schema_<id>":      {"schema": [...], "data": [ {..onto row..} ]},
        "concepts_<id>":             {"schema": [...], "data": [ {..concept rows..} ]},
        ...
      }
    }

A concept row is a struct; its ``definition`` column is the body, the annotation
columns are the envelope. We project that back into ``<predicate>.<ext>`` +
``<predicate>.meta.yaml``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# concept_type -> body file extension for the Vadalog-family kinds.
_EXT_BY_TYPE = {
    "logic": ".vadalog",
    "sql": ".sql",
    "cypher": ".cypher",
    "python": ".py",
}

# Concept columns that are server-derived state and are never serialized.
_DERIVED_COLUMNS = {
    "is_populated",
    "row_count",
    "timestamp",
    "author",
    "position",
    "execution_time_ms",
    "is_deterministic",
    "metadata",
}


def concept_body(row: dict) -> str:
    """Read a concept row's body, whichever name the server uses for it.

    The column was renamed ``rules`` → ``definition``. ``px`` is installed
    separately from the server it talks to, so both spellings have to be accepted
    for as long as either version is in the wild: a pinned CLI meets an upgraded
    server, and an upgraded CLI meets a server that has not been deployed yet.
    """
    body = row.get("definition")
    if body is None:
        body = row.get("rules")
    return body or ""


@dataclass
class FileOut:
    """A file to write: repo-relative path + text content."""

    path: str
    content: str


@dataclass
class ReshapeResult:
    project_id: str
    project_name: str
    scope: str
    files: List[FileOut] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add(self, path: str, content: str) -> None:
        self.files.append(FileOut(path, content))

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _table(export: dict, prefix: str) -> Optional[dict]:
    """Return the first table whose name starts with ``prefix``."""
    for name, tbl in (export.get("tables") or {}).items():
        if name.startswith(prefix):
            return tbl
    return None


def _rows(table: Optional[dict]) -> List[dict]:
    return list((table or {}).get("data") or [])


def _maybe_json(value):
    """Parse a JSON string into a Python object; pass through non-JSON as-is."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped in {"null", "None"}:
        return None
    if stripped[0] in "[{" or stripped in {"true", "false"}:
        try:
            return json.loads(stripped)
        except ValueError:
            return value
    return value


def _clean_config(raw) -> dict:
    """Parse a ``concept_config`` column and drop null-valued keys.

    The server materializes every optional field as ``null`` (llm provider/model,
    dynamic-context top_k/kinds); dropping them keeps the pulled file lean and
    makes it compare equal to a hand-authored one.
    """
    cfg = _maybe_json(raw)
    if not isinstance(cfg, dict):
        return {}
    return {k: v for k, v in cfg.items() if v is not None}


def _fields_to_list(raw) -> List[dict]:
    """Server ``fields`` is a name->type dict; emit an ordered [{name,type}] list."""
    parsed = _maybe_json(raw)
    if isinstance(parsed, dict):
        return [{"name": k, "type": v} for k, v in parsed.items()]
    if isinstance(parsed, list):
        return parsed
    return []


def reshape_project(export: dict, project_name: str, slug: str, sources: dict = None) -> ReshapeResult:
    """Build the file set for ``projects/<slug>/`` from an export dict.

    ``sources`` maps a predicate to its recovered sql/cypher source query (from
    ``list_concepts`` parsed.code); when present, a sql/cypher concept's body
    file holds that source instead of the transpiled Vadalog in ``definition``.
    """
    import yaml  # local import keeps module import cheap

    sources = sources or {}

    project_id = export.get("project_id", "")
    scope = export.get("scope", "user")
    result = ReshapeResult(project_id=project_id, project_name=project_name, scope=scope)
    base = f"projects/{slug}"

    # --- project manifest -------------------------------------------------
    proj_rows = _rows(_table(export, "projects_"))
    name = project_name
    if proj_rows:
        name = proj_rows[0].get("name") or project_name
    manifest = {
        "$schema": "../../.px/schemas/project.schema.json",
        "schemaVersion": 1,
        "project": {"id": project_id, "name": name, "scope": scope},
        "concepts": "./concepts",
    }
    datasource_rows = _rows(_table(export, "datasources_"))
    if datasource_rows:
        manifest["datasources"] = [
            f"./datasources/{r.get('datasource_id') or f'ds_{i}'}.yaml"
            for i, r in enumerate(datasource_rows)
        ]
    if _rows(_table(export, "ontology_schema_")):
        manifest["ontology"] = "./ontology/schema.yaml"
    result.add(f"{base}/prometheux.yaml", _yaml(yaml, manifest))

    # --- datasources ------------------------------------------------------
    for i, row in enumerate(datasource_rows):
        ds_id = row.get("datasource_id") or f"ds_{i}"
        spec = _reshape_datasource(row)
        result.add(f"{base}/datasources/{ds_id}.yaml", _yaml(yaml, spec))

    # --- ontology schema --------------------------------------------------
    onto_rows = _rows(_table(export, "ontology_schema_"))
    if onto_rows:
        onto = _maybe_json(onto_rows[0].get("ontology_schema_data"))
        result.add(f"{base}/ontology/schema.yaml", _yaml(yaml, onto or {}))

    # --- concepts ---------------------------------------------------------
    concept_rows = _rows(_table(export, "concepts_"))
    for row in concept_rows:
        _reshape_concept(row, base, result, yaml, sources)

    return result


def _reshape_datasource(row: dict) -> dict:
    spec = {
        "$schema": "../../../.px/schemas/datasource.schema.json",
        "name": row.get("datasource_id") or "datasource",
        "type": row.get("datasource_type") or "unknown",
    }
    for key in ("host", "port", "database_name", "schema_name", "table_name"):
        val = row.get(key)
        if val:
            spec[key] = val
    # Secrets are never serialized: username/password/connection_params are dropped.
    return spec


def _reshape_concept(row: dict, base: str, result: ReshapeResult, yaml, sources: dict = None) -> None:
    sources = sources or {}
    predicate = row.get("predicate_name") or "concept"
    ctype = (row.get("concept_type") or "logic").strip() or "logic"
    definition = concept_body(row)

    if ctype in _EXT_BY_TYPE:
        ext = _EXT_BY_TYPE[ctype]
        body = definition
        if ctype in {"sql", "cypher"}:
            recovered = sources.get(predicate)
            if recovered is not None:
                body = recovered  # the authored source query, not the transpiled Vadalog
            else:
                result.warn(
                    f"concept '{predicate}' is {ctype}: source could not be recovered; "
                    f"the body holds the transpiled Vadalog."
                )
        result.add(f"{base}/concepts/{predicate}{ext}", _ensure_newline(body))
        meta = _concept_meta(row, ctype, predicate)
        result.add(f"{base}/concepts/{predicate}.meta.yaml", _yaml(yaml, meta))
    elif ctype == "llm":
        fm = {"conceptType": "llm", "outputPredicate": predicate}
        _copy_if(fm, "group", row.get("concept_group"))
        llm_config = _clean_config(row.get("concept_config"))
        if llm_config:
            fm["llmConfig"] = llm_config
        # body is the prompt template, stored verbatim.
        result.add(f"{base}/concepts/{predicate}.llm.md", _frontmatter(yaml, fm, definition))
    elif ctype == "context":
        cfg = _clean_config(row.get("concept_config"))
        mode = (cfg.get("mode") or "static").strip().lower()
        doc = {"conceptType": "context", "outputPredicate": predicate, "contextMode": mode}
        if mode == "dynamic":
            doc["query"] = cfg.get("query") or ""
            if cfg.get("top_k") is not None:
                doc["top_k"] = cfg["top_k"]
            if cfg.get("kinds"):
                doc["kinds"] = cfg["kinds"]
        else:
            # Static pins are stored as opaque note ids; there is no reverse
            # path mapping on pull, so emit `noteIds` (apply consumes these
            # directly, skipping path resolution).
            note_ids = cfg.get("note_ids") or []
            doc["noteIds"] = list(note_ids)
            if note_ids:
                result.warn(
                    f"concept '{predicate}': static context pinned by note id; edit to "
                    f"`notes:` body paths if you want git-tracked note bodies."
                )
        result.add(f"{base}/concepts/{predicate}.context.yaml", _yaml(yaml, doc))
    else:
        result.warn(f"concept '{predicate}' has unknown type '{ctype}'; skipped.")


def _concept_meta(row: dict, ctype: str, predicate: str) -> dict:
    meta = {
        "$schema": "../../../.px/schemas/concept-meta.schema.json",
        "conceptType": ctype,
        "outputPredicate": predicate,
    }
    _copy_if(meta, "group", row.get("concept_group"))
    _copy_if(meta, "description", row.get("description"))
    fields = _fields_to_list(row.get("fields"))
    if fields:
        meta["fields"] = fields
    annotations = _collect_annotations(row)
    if annotations:
        # Verbatim server annotations — the lossless capture apply will consume.
        meta["annotations"] = annotations
    return meta


def _collect_annotations(row: dict) -> Dict[str, object]:
    out: Dict[str, object] = {}
    for col in (
        "bind_annotations",
        "param_annotations",
        "post_annotations",
        "model_annotation",
        "mapping_annotations",
    ):
        parsed = _maybe_json(row.get(col))
        if parsed:  # skip empty strings / None / empty containers
            out[col] = parsed
    return out


def _copy_if(target: dict, key: str, value) -> None:
    if value not in (None, "", "group_id"):
        target[key] = value


def _ensure_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def _yaml(yaml, data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)


def _frontmatter(yaml, fm: dict, body: str) -> str:
    return "---\n" + _yaml(yaml, fm) + "---\n" + _ensure_newline(body)
