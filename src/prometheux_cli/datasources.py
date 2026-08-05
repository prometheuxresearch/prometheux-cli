"""Pure helpers for applying datasources.

Two shapes of datasource file:

1. **A connection** (snowflake / postgres / …) — secrets are referenced as
   ``${ENV_VAR}`` and resolved from the environment at apply, never stored.
   Produces kwargs for ``px.Database(...)`` → ``px.connect_sources``.

2. **A local file** (csv / parquet / json / …) with a ``file:`` key — the CLI
   uploads it to the workspace ``disk/`` store, then connects it. Verified
   against jarvispy: connect wants ``host`` = the disk directory and
   ``databaseName`` = the filename.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Dict, List, Mapping

# File-based datasource types the platform recognizes (jarvispy FILE_BASED_TYPES).
FILE_BASED_TYPES = {
    "csv", "tsv", "excel", "json", "parquet", "orc",
    "text", "yaml", "ttl", "rdf", "owl", "cobol", "binaryfile",
}

# Datasource-file keys that are CLI metadata, not connection fields.
_META_KEYS = {"$schema", "name", "type", "file", "diskPath"}

# Recognized connection fields -> Database(**kwargs) name.
_FIELD_MAP = {
    "host": "host",
    "port": "port",
    "username": "username",
    "password": "password",
    "database": "database_name",
    "database_name": "database_name",
    "schema": "schema",
    "schema_name": "schema",
    "catalog": "catalog",
    "query": "query",
    "tables": "tables",
    "url": "url",
}

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_BIND_PRED_RE = re.compile(r'(@q?bind\(\s*")[^"]+(")')


class SecretError(Exception):
    """A ${ENV_VAR} referenced by a datasource is not set."""


def is_file_based(type_: str) -> bool:
    return (type_ or "").lower() in FILE_BASED_TYPES


def resolve_secrets(spec, env: Mapping[str, str]):
    """Return a deep copy of ``spec`` with every ``${VAR}`` resolved from ``env``.

    Raises :class:`SecretError` listing all missing variables (fail fast).
    """
    missing: List[str] = []

    def _resolve(value):
        if isinstance(value, str):
            def sub(m):
                name = m.group(1)
                if name not in env:
                    missing.append(name)
                    return m.group(0)
                return env[name]
            return _ENV_RE.sub(sub, value)
        if isinstance(value, dict):
            return {k: _resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_resolve(v) for v in value]
        return value

    resolved = _resolve(spec)
    if missing:
        uniq = sorted(set(missing))
        raise SecretError(
            "missing environment variable(s): " + ", ".join(uniq)
        )
    return resolved


def database_kwargs(resolved_spec: dict) -> Dict[str, object]:
    """Build ``px.Database(**kwargs)`` for a connection-style datasource."""
    kwargs: Dict[str, object] = {"database_type": resolved_spec.get("type")}
    options: Dict[str, object] = {}
    for key, value in resolved_spec.items():
        if key in _META_KEYS:
            continue
        target = _FIELD_MAP.get(key)
        if target:
            kwargs[target] = value
        else:
            # Connector-specific extras (warehouse, account, role, …) ride in options.
            options[key] = value
    if options:
        kwargs["options"] = options
    # The data manager rejects a null port; default to 0 when a spec omits it.
    kwargs.setdefault("port", 0)
    return kwargs


def bind_template_from_sources(sources, filename: str = None) -> Optional[str]:
    """Pick the ``bind_annotation`` for a connected source (by filename, else first)."""
    if isinstance(sources, dict):
        sources = list(sources.values())
    if not sources:
        return None
    if filename:
        for s in sources:
            if isinstance(s, dict) and s.get("table_name") == filename:
                return s.get("bind_annotation")
    first = sources[0]
    return first.get("bind_annotation") if isinstance(first, dict) else None


def rewrite_bind_predicate(template: str, predicate: str) -> str:
    """Rewrite the predicate (first arg) of an ``@bind``/``@qbind`` annotation."""
    return _BIND_PRED_RE.sub(lambda m: m.group(1) + predicate + m.group(2), template, count=1)


def file_database_kwargs(type_: str, disk_file_path: str, filename: str) -> Dict[str, object]:
    """Build ``px.Database(**kwargs)`` for an uploaded file.

    ``disk_file_path`` is the ``filePath`` returned by upload (e.g.
    ``disk/uploads/customers.csv``); connect wants the directory as ``host``.
    """
    host = str(PurePosixPath(disk_file_path).parent)
    return {
        "database_type": (type_ or "").lower(),
        "host": host,
        # The data manager rejects a null port; file sources use 0 (matches the UI).
        "port": 0,
        "database_name": filename,
        "options": {},
    }
