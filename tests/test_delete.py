"""Tests for `px delete` — project resolution, confirmation gating, SDK call."""

from __future__ import annotations

from click.testing import CliRunner

from prometheux_cli.cli import cli
from prometheux_cli.commands import delete as delete_cmd


class _FakePx:
    def __init__(self, projects):
        self._projects = projects
        self.deleted = []  # (ontology_id, ontology_scope)

    def list_ontologies(self, scopes):
        return self._projects

    def cleanup_ontologies(self, ontology_id=None, ontology_scope="user"):
        self.deleted.append((ontology_id, ontology_scope))
        return {"status": "success"}


def _wire(monkeypatch, fake):
    monkeypatch.setattr(delete_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))


def test_delete_by_id_with_yes(monkeypatch):
    fake = _FakePx([{"id": "abc123", "name": "Demo"}])
    _wire(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["delete", "abc123", "--yes"])
    assert result.exit_code == 0, result.output
    assert fake.deleted == [("abc123", "user")]
    assert "Deleted" in result.output


def test_delete_by_name(monkeypatch):
    fake = _FakePx([{"id": "abc123", "name": "Demo"}])
    _wire(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["delete", "Demo", "--yes"])
    assert result.exit_code == 0, result.output
    assert fake.deleted == [("abc123", "user")]


def test_delete_prompt_abort_does_not_delete(monkeypatch):
    fake = _FakePx([{"id": "abc123", "name": "Demo"}])
    _wire(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["delete", "abc123"], input="n\n")
    assert result.exit_code == 1
    assert fake.deleted == []
    assert "Aborted" in result.output


def test_delete_unknown_project_fails(monkeypatch):
    fake = _FakePx([{"id": "abc123", "name": "Demo"}])
    _wire(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["delete", "nope", "--yes"])
    assert result.exit_code == 1
    assert fake.deleted == []
    assert "no user-scoped ontology" in result.output


def test_delete_ambiguous_name_fails(monkeypatch):
    fake = _FakePx([
        {"id": "id1", "name": "Twin"},
        {"id": "id2", "name": "Twin"},
    ])
    _wire(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["delete", "Twin", "--yes"])
    assert result.exit_code == 1
    assert fake.deleted == []
    assert "ambiguous" in result.output
