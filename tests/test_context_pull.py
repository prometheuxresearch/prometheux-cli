"""`px pull` / `px context pull` — pulling the context layer back to files.

The load-bearing property: a pulled note's seeded idempotency state must equal
what `px context apply` recomputes when it re-reads the written files, so the
first apply after a pull is a clean no-op (no duplicate notes on the platform).
"""

from pathlib import Path

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli
from prometheux_cli.commands.context import _classify, _load_state
from prometheux_cli.context import build_pulled_context, collect_context
from prometheux_cli.loader import load_workspace


def _notes():
    return [
        {"id": "n1", "scope": "ontology", "scope_id": "pid1", "kind": "fact",
         "activation": "retrieved", "title": "Customer risk", "text": "# Customer risk\nHigh churn.\n"},
        {"id": "n2", "scope": "ontology", "scope_id": "pid1", "kind": "rule",
         "activation": "always", "title": None, "text": "Always flag negative balances."},
    ]


def test_build_pulled_context_seeds_matching_hash():
    built = build_pulled_context(_notes(), scope="project", scope_id="pid1",
                                 manifest_rel="ontologies/p/context/pulled.context.md")
    assert built.count == 2
    # Two body files, named from title / first line.
    names = {f for f, _ in built.body_files}
    assert "customer-risk.md" in names
    # State keyed by (manifest_rel, filename), carrying the server note id.
    assert built.state_entries["ontologies/p/context/pulled.context.md::customer-risk.md"]["id"] == "n1"
    # Keys must be posix so the committed state matches on every OS (Windows too).
    assert all("\\" not in k for k in built.state_entries)


def test_pulled_context_round_trips_as_unchanged(tmp_path: Path):
    # A workspace with one ontology, no context yet.
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/p\n"
    )
    proj = tmp_path / "ontologies" / "p"
    proj.mkdir(parents=True)
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: pid1\n  name: P\n"
    )

    built = build_pulled_context(_notes(), scope="project", scope_id="pid1",
                                 manifest_rel="ontologies/p/context/pulled.context.md")
    out_dir = proj / "context"
    out_dir.mkdir()
    (out_dir / "pulled.context.md").write_text(built.manifest_text, "utf-8")
    for fname, text in built.body_files:
        (out_dir / fname).write_text(text, "utf-8")

    # Re-read the written files exactly as `px context apply` would.
    ws = load_workspace(tmp_path)
    notes, _, warnings = collect_context(ws)
    assert warnings == []
    assert {n.scope for n in notes} == {"project"}
    assert all(n.scope_id == "pid1" for n in notes)

    # Every collected note classifies as `unchanged` against the seeded state —
    # this is what prevents a re-create/duplicate on the first apply.
    for n in notes:
        assert _classify(n, built.state_entries) == "unchanged", n.ref_key


class _FakePx:
    def __init__(self, notes):
        self._notes = notes

    def list_context_notes(self, scope, scope_id=None, kinds=None):
        # Server speaks 'ontology'; global asks with scope_id None.
        if scope == "ontology" and scope_id == "pid1":
            return self._notes
        return []


def test_context_pull_command_writes_global(tmp_path: Path, monkeypatch):
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies: []\n"
    )
    global_notes = [{"id": "g1", "scope": "global", "scope_id": None, "kind": "fact",
                     "activation": "retrieved", "title": "Company", "text": "# Company\nWe sell pasta.\n"}]

    class _Px:
        def list_context_notes(self, scope, scope_id=None, kinds=None):
            return global_notes if scope == "global" else []

    monkeypatch.setattr(cli_module.context_cmd, "connected_sdk",
                        lambda **k: (_Px(), "http://x", "tok"))
    runner = CliRunner()
    result = runner.invoke(cli, ["context", "pull", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "context" / "pulled.context.md").is_file()
    assert (tmp_path / "context" / "company.md").is_file()
    # State seeded so a later apply is a no-op.
    state = _load_state(tmp_path)
    assert any(k.endswith("::company.md") for k in state)
