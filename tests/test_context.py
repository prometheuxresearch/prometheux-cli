from pathlib import Path

from prometheux_cli.context import collect_context
from prometheux_cli.loader import load_workspace


def _ws(tmp_path: Path):
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/p\n"
    )
    ctx = tmp_path / "context" / "facts"
    ctx.mkdir(parents=True)
    (tmp_path / "context" / "market.context.md").write_text(
        "---\nscope: global\nactivation: retrieved\nkind: fact\n"
        "notes:\n  - facts/a.md\n  - facts/b.md\n"
        "links:\n  - from: facts/a.md\n    to: facts/b.md\n    relation: relates_to\n---\n"
    )
    (ctx / "a.md").write_text("# Segment A\nAlpha details.\n")
    (ctx / "b.md").write_text("# Segment B\nBeta details.\n")

    proj = tmp_path / "ontologies" / "p"
    (proj / "context").mkdir(parents=True)
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: pid1\n  name: P\n  scope: user\ncontext: ./context\n"
    )
    (proj / "context" / "domain.context.md").write_text(
        "---\nscope: project\nactivation: always\nkind: rule\nnotes:\n  - policy.md\n"
        "links:\n  - from: policy.md\n    to: concept:risk\n    relation: describes\n---\n"
    )
    (proj / "context" / "policy.md").write_text("# Policy\nMust do X.\n")
    return tmp_path


def test_collect_context(tmp_path: Path):
    ws = load_workspace(_ws(tmp_path))
    notes, links, warnings = collect_context(ws)
    assert warnings == []

    by_path = {n.ref_key[1]: n for n in notes}
    assert set(by_path) == {"facts/a.md", "facts/b.md", "policy.md"}

    # global note
    assert by_path["facts/a.md"].scope == "global"
    assert by_path["facts/a.md"].scope_id is None
    assert by_path["facts/a.md"].title == "Segment A"

    # project note, resolved scope_id + activation
    assert by_path["policy.md"].scope == "project"
    assert by_path["policy.md"].scope_id == "pid1"
    assert by_path["policy.md"].activation == "always"

    # note->note link between the two global notes
    note_links = [l for l in links if l.src.kind == "note" and l.dst.kind == "note"]
    assert len(note_links) == 1
    assert note_links[0].relation == "relates_to"

    # note->concept link (project-scoped) resolves the concept node id
    concept_links = [l for l in links if l.dst.kind == "concept"]
    assert len(concept_links) == 1
    assert concept_links[0].dst.concept_id == "pid1:risk"
    assert concept_links[0].src.note_key[1] == "policy.md"


def test_collect_context_missing_body_warns(tmp_path: Path):
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies: []\n"
    )
    c = tmp_path / "context"
    c.mkdir()
    (c / "x.context.md").write_text("---\nscope: global\nnotes:\n  - missing.md\n---\n")
    ws = load_workspace(tmp_path)
    notes, links, warnings = collect_context(ws)
    assert notes == []
    assert any("not found" in w for w in warnings)
