"""Generate the authoring guide + agent skill from curated prose + the bundled schemas.

The **Schema reference** section is rendered from the same schemas the package ships
(and `px validate` enforces), so nothing drifts from the accepted file shape (design §8).
Three surfaces share the curated body (`templates/guide_body.md`):

- ``generate_agents_md`` — the in-repo ``AGENTS.md`` (`px init` writes it).
- ``render_skill_md`` — a Claude Code skill ``SKILL.md`` (`px skill install`).
- ``render_cursor_rule`` — a Cursor ``.mdc`` project rule (`px skill install --cursor`).

Because all three are generated from the installed package, a skill installed by a given
`px` build always matches that build's schemas.
"""

from __future__ import annotations

from importlib import resources
from typing import List

from .resources import load_schema

_AGENTS_INTRO = "templates/agents_preamble.md"
_GUIDE_BODY = "templates/guide_body.md"
_SKILL_COMMANDS = "templates/skill_commands.md"

# (schema kind, the on-disk file it governs) — order = how they appear in the reference.
_REFERENCE_ORDER = [
    ("workspace", "prometheux.workspace.yaml"),
    ("project", "prometheux.yaml"),
    ("concept-meta", "concepts/*.meta.yaml"),
    ("context-concept", "concepts/*.context.yaml"),
    ("datasource", "datasources/*.yaml"),
    ("context-set", "*.context.md (frontmatter)"),
]

SKILL_NAME = "prometheux"
SKILL_DESCRIPTION = (
    "Author and deploy a Prometheux knowledge-graph workspace as code with the px CLI. "
    "Use when working with Vadalog, Prometheux concepts / ontologies / datasources / apps, "
    "lineage-as-code, the context/notes layer, or any px command "
    "(init, validate, plan, apply, pull, run, context, status, delete)."
)

_SKILL_INTRO = """# Prometheux — author lineage & context as code with the `px` CLI

Prometheux is a knowledge-graph and data-orchestration platform built on **Vadalog** (a
declarative logic language). The `px` CLI lets you author a **workspace as files** —
concepts (`logic`/`sql`/`cypher`/`python`/`context`/`llm`), datasources, an ontology, apps,
and a context/notes layer — then apply it to the platform over REST. You write logic; the
lineage graph is *derived* from predicate references. This skill tells you how to author
those files and drive `px`.
"""


def _read(name: str) -> str:
    return resources.files("prometheux_cli").joinpath(name).read_text("utf-8")


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
    """Return the sub-schema whose ``properties`` to recurse into (object or array-of-object)."""
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
        "Generated from the JSON Schemas — the single source of truth `px validate` enforces. "
        "Fields marked *required* must be present; deeper detail (patterns, conditionals) "
        "lives in the schema files themselves.",
        "",
    ]
    for kind, heading in _REFERENCE_ORDER:
        parts.append(_render_schema(kind, heading))
    return "\n".join(parts)


def _join(*sections: str) -> str:
    return "\n\n".join(s.rstrip() for s in sections) + "\n"


def generate_agents_md() -> str:
    """The in-repo ``AGENTS.md``: repo intro + shared body + generated schema reference."""
    return _join(_read(_AGENTS_INTRO), _read(_GUIDE_BODY), render_schema_reference())


def render_skill_md() -> str:
    """A Claude Code ``SKILL.md`` — the full schema reference is a sibling file."""
    frontmatter = f"---\nname: {SKILL_NAME}\ndescription: {SKILL_DESCRIPTION}\n---\n"
    schema_pointer = (
        "## Schema reference\n\n"
        "See `reference/schemas.md` for the field-by-field schema reference, and the raw "
        "JSON Schemas in `reference/` — read them when authoring a manifest or `.meta.yaml`."
    )
    return _join(frontmatter + _SKILL_INTRO, _read(_GUIDE_BODY), _read(_SKILL_COMMANDS), schema_pointer)


def render_cursor_rule() -> str:
    """A Cursor ``.mdc`` project rule — single file, so the schema reference is inlined."""
    frontmatter = (
        "---\n"
        f"description: {SKILL_DESCRIPTION}\n"
        "alwaysApply: false\n"
        "---\n"
    )
    return _join(
        frontmatter + _SKILL_INTRO,
        _read(_GUIDE_BODY),
        _read(_SKILL_COMMANDS),
        render_schema_reference(),
    )
