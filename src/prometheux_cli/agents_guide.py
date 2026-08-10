"""Generate ``AGENTS.md`` from curated prose + the bundled JSON Schemas.

The **Schema reference** section is rendered from the same schemas the package
ships (and `px validate` enforces), so the guide cannot drift from the accepted
file shape (design §8). `px init` calls :func:`generate_agents_md` at scaffold
time, so a freshly scaffolded repo always documents the schemas it was built with.
"""

from __future__ import annotations

from importlib import resources
from typing import List

from .resources import load_schema

_PREAMBLE = "templates/agents_preamble.md"

# (schema kind, the on-disk file it governs) — order = how they appear in the guide.
_REFERENCE_ORDER = [
    ("workspace", "prometheux.workspace.yaml"),
    ("project", "prometheux.yaml"),
    ("concept-meta", "concepts/*.meta.yaml"),
    ("context-concept", "concepts/*.context.yaml"),
    ("datasource", "datasources/*.yaml"),
    ("context-set", "*.context.md (frontmatter)"),
]


def _type_label(spec: dict) -> str:
    """A short human type for a schema node."""
    if "enum" in spec:
        return "enum"
    t = spec.get("type")
    if isinstance(t, list):
        return " | ".join(t)
    if t == "array":
        items = spec.get("items") or {}
        inner = _type_label(items) if items else "any"
        return f"array of {inner}"
    return t or "any"


def _object_child(spec: dict):
    """Return the sub-schema whose ``properties`` we should recurse into, if any.

    Handles both an object property and an array-of-object property.
    """
    if spec.get("type") == "object" and "properties" in spec:
        return spec
    if spec.get("type") == "array":
        items = spec.get("items") or {}
        if items.get("type") == "object" and "properties" in items:
            return items
    return None


def _render_property(name: str, spec: dict, required: bool, depth: int, lines: List[str]) -> None:
    indent = "  " * depth
    flags = [_type_label(spec)]
    if required:
        flags.append("required")
    line = f"{indent}- **`{name}`** *({', '.join(flags)})*"
    extras: List[str] = []
    if "enum" in spec:
        extras.append("one of " + " | ".join(f"`{v}`" for v in spec["enum"]))
    if spec.get("description"):
        extras.append(spec["description"])
    if extras:
        line += " — " + "; ".join(extras)
    lines.append(line)

    child = _object_child(spec)
    if child and depth < 2:  # cap nesting; deeper detail lives in the schema file
        req = set(child.get("required", []))
        for cname, cspec in child.get("properties", {}).items():
            if cname == "$schema":
                continue
            _render_property(cname, cspec, cname in req, depth + 1, lines)


def _render_schema(kind: str, heading: str) -> str:
    schema = load_schema(kind)
    lines: List[str] = [f"### {schema.get('title', kind)} — `{heading}`", ""]
    if schema.get("description"):
        lines += [schema["description"], ""]
    required = set(schema.get("required", []))
    for name, spec in schema.get("properties", {}).items():
        if name == "$schema":
            continue
        _render_property(name, spec, name in required, 0, lines)
    lines.append("")
    return "\n".join(lines)


def render_schema_reference() -> str:
    """The generated, drift-proof reference section (Markdown)."""
    parts = [
        "## Schema reference",
        "",
        "Generated from the JSON Schemas in `.px/schemas/` — the single source of truth "
        "`px validate` enforces. Fields marked *required* must be present; deeper detail "
        "(patterns, conditionals) lives in the schema files themselves.",
        "",
    ]
    for kind, heading in _REFERENCE_ORDER:
        parts.append(_render_schema(kind, heading))
    return "\n".join(parts)


def _preamble() -> str:
    return resources.files("prometheux_cli").joinpath(_PREAMBLE).read_text("utf-8")


def generate_agents_md() -> str:
    """The full ``AGENTS.md``: curated preamble + generated schema reference."""
    return _preamble().rstrip() + "\n\n" + render_schema_reference().rstrip() + "\n"
