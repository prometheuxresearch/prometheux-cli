"""The generated AGENTS.md must carry the curated prose AND a schema-derived
reference, so it cannot drift from what `px validate` enforces (design §8)."""

from prometheux_cli.agents_guide import generate_agents_md, render_schema_reference
from prometheux_cli.resources import SCHEMA_FILES, load_schema


def test_reference_covers_every_bundled_schema():
    ref = render_schema_reference()
    for kind in SCHEMA_FILES:
        title = load_schema(kind).get("title")
        assert title and title in ref, f"schema {kind} ({title!r}) missing from reference"


def test_reference_renders_fields_and_enums_from_the_schema():
    ref = render_schema_reference()
    # Fields are pulled from the schema, not hand-written.
    assert "`conceptType`" in ref
    assert "`outputPredicate`" in ref
    # Enum values are surfaced verbatim from the schema.
    for value in load_schema("concept-meta")["properties"]["conceptType"]["enum"]:
        assert f"`{value}`" in ref
    # Nested (array-of-object) properties recurse.
    assert "`predicate`" in ref and "`datasource`" in ref


def test_full_guide_has_preamble_then_reference():
    md = generate_agents_md()
    assert md.startswith("# Authoring a Prometheux workspace")
    assert "## Schema reference" in md
    # Curated guardrails survive.
    assert "Guardrails" in md and "ENGINE_BUSY" in md
    assert md.index("Mental model") < md.index("## Schema reference")
