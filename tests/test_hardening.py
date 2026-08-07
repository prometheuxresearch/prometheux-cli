"""Tests for the chaos-hardening fixes (#22, #23, #25)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from prometheux_cli.parsing import ParseError, load_yaml
from prometheux_cli.commands.apply import _resolve_or_create_project, _persist_project_id


# ── #22 / #23: offline parse must never traceback ───────────────────────────

def test_deeply_nested_yaml_is_parse_error(tmp_path):
    p = tmp_path / "deep.yaml"
    p.write_text("a: " + "[" * 6000 + "]" * 6000, "utf-8")
    with pytest.raises(ParseError):        # not RecursionError
        load_yaml(p)


def test_invalid_utf8_is_parse_error(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_bytes(b"a: \xff\xfe\xc3\x28")
    with pytest.raises(ParseError):        # not UnicodeDecodeError
        load_yaml(p)


# ── #25: reconcile-on-create + defensive write-back ─────────────────────────

class _FakePx:
    def __init__(self, projects):
        self.projects = projects
        self.created = []

    def list_ontologies(self, scopes):
        return self.projects

    def save_ontology(self, _id, name, scope):
        self.created.append((name, scope))
        return "NEW_ID"


def _proj():
    return SimpleNamespace(name="Demo", scope="user")


def test_resolve_adopts_single_existing_project():
    px = _FakePx([{"id": "EXIST", "name": "Demo"}])
    assert _resolve_or_create_project(px, _proj()) == "EXIST"
    assert px.created == []                 # adopted, did NOT create a duplicate


def test_resolve_creates_when_none_exist():
    px = _FakePx([{"id": "OTHER", "name": "Unrelated"}])
    assert _resolve_or_create_project(px, _proj()) == "NEW_ID"
    assert px.created == [("Demo", "user")]


def test_resolve_creates_when_name_is_ambiguous():
    px = _FakePx([{"id": "a", "name": "Demo"}, {"id": "b", "name": "Demo"}])
    assert _resolve_or_create_project(px, _proj()) == "NEW_ID"
    assert px.created == [("Demo", "user")]


def test_resolve_falls_back_to_create_if_listing_fails():
    class Broken(_FakePx):
        def list_ontologies(self, scopes):
            raise RuntimeError("network down")
    px = Broken([])
    assert _resolve_or_create_project(px, _proj()) == "NEW_ID"


def test_persist_id_failure_does_not_raise(tmp_path):
    manifest = tmp_path / "prometheux.yaml"
    manifest.write_text("schemaVersion: 1\nproject:\n  name: Demo\n", "utf-8")
    manifest.chmod(0o444)                   # write-back will fail
    project = SimpleNamespace(id="ABC", manifest_path=manifest)
    try:
        _persist_project_id(project)        # must warn, not crash
    finally:
        manifest.chmod(0o644)
