import json
from pathlib import Path

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli


class _FakePx:
    def __init__(self):
        self.created = []
        self.updated = []
        self.deleted = []
        self._n = 0

    def create_context_note(self, scope, kind, text, scope_id=None):
        self._n += 1
        nid = f"note-{self._n}"
        self.created.append((nid, text))
        return {"id": nid}

    def update_context_note(self, note_id, text=None, kind=None):
        self.updated.append((note_id, text))
        return {"id": note_id}

    def delete_context_note(self, note_id):
        self.deleted.append(note_id)
        return {}


def _wire(monkeypatch):
    fake = _FakePx()
    monkeypatch.setattr(cli_module.context_cmd, "connected_sdk", lambda **k: (fake, "u", "t"))
    # edges (and non-retrieved notes) go through the SDK client directly; stub it.
    import prometheux_chain.client.jarvispy_client as jc
    monkeypatch.setattr(jc.JarvisPyClient, "_request", staticmethod(lambda *a, **k: {"data": {"id": "x"}}))
    return fake


def _ws(tmp_path: Path, bodies: dict, manifest: str):
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nprojects:\n  - ./projects/p\n"
    )
    (tmp_path / "context").mkdir(exist_ok=True)
    proj = tmp_path / "projects" / "p"
    ctx = proj / "context"
    ctx.mkdir(parents=True, exist_ok=True)
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nproject:\n  id: pid1\n  name: P\n  scope: user\ncontext: ./context\n"
    )
    for name, text in bodies.items():
        (ctx / name).write_text(text)
    (ctx / "set.context.md").write_text(manifest)
    return tmp_path


def test_upsert_lifecycle(tmp_path: Path, monkeypatch):
    fake = _wire(monkeypatch)
    runner = CliRunner()
    manifest = (
        "---\nscope: project\nkind: fact\nnotes:\n  - a.md\n  - b.md\n---\n"
    )
    _ws(tmp_path, {"a.md": "# A\nalpha\n", "b.md": "# B\nbeta\n"}, manifest)

    # Run 1: both created; state written.
    r1 = runner.invoke(cli, ["context", "apply", str(tmp_path), "--yes"])
    assert r1.exit_code == 0, r1.output
    assert len(fake.created) == 2
    state = json.loads((tmp_path / ".px" / "context-state.json").read_text())
    assert len(state) == 2

    # Run 2: nothing changed -> no creates, no updates.
    r2 = runner.invoke(cli, ["context", "apply", str(tmp_path), "--yes"])
    assert r2.exit_code == 0, r2.output
    assert len(fake.created) == 2  # unchanged
    assert fake.updated == []
    assert "2 unchanged" in r2.output

    # Edit a body -> exactly one update.
    (tmp_path / "projects" / "p" / "context" / "a.md").write_text("# A\nALPHA changed\n")
    r3 = runner.invoke(cli, ["context", "apply", str(tmp_path), "--yes"])
    assert r3.exit_code == 0, r3.output
    assert len(fake.updated) == 1
    assert fake.updated[0][0] == "note-1"

    # Drop b.md from the manifest, --prune -> delete note-2.
    (tmp_path / "projects" / "p" / "context" / "set.context.md").write_text(
        "---\nscope: project\nkind: fact\nnotes:\n  - a.md\n---\n"
    )
    r4 = runner.invoke(cli, ["context", "apply", str(tmp_path), "--yes", "--prune"])
    assert r4.exit_code == 0, r4.output
    assert fake.deleted == ["note-2"]
    state = json.loads((tmp_path / ".px" / "context-state.json").read_text())
    assert len(state) == 1


def test_prune_withheld_without_flag(tmp_path: Path, monkeypatch):
    fake = _wire(monkeypatch)
    runner = CliRunner()
    _ws(tmp_path, {"a.md": "# A\nx\n"}, "---\nscope: project\nnotes:\n  - a.md\n---\n")
    runner.invoke(cli, ["context", "apply", str(tmp_path), "--yes"])
    # Remove the note; apply WITHOUT --prune keeps it.
    (tmp_path / "projects" / "p" / "context" / "set.context.md").write_text(
        "---\nscope: project\nnotes: []\n---\n"
    )
    r = runner.invoke(cli, ["context", "apply", str(tmp_path), "--yes"])
    assert r.exit_code == 0, r.output
    assert fake.deleted == []
    assert "use --prune" in r.output
