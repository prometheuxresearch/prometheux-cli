from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli


class _FakePx:
    def list_ontologies(self, scopes):
        return [{"id": "abc123", "name": "Al Dente", "author": "mozart"}]

    def list_all_apps(self, scope):
        return [{"id": "app-1", "name": "Risk", "project_name": "Al Dente", "status": "draft"}]

    def list_sources(self, scope):
        return [{"id": "ds-1", "table_name": "orders.csv", "datasource_type": "csv",
                 "predicate_placeholder": "orders_csv"}]

    def list_context_notes(self, scope, scope_id=None, kinds=None):
        return [{"id": "note-1", "kind": "fact", "scope": scope, "scope_id": scope_id,
                 "text": "  a  long\n  note body  "}]


def _wire(monkeypatch):
    monkeypatch.setattr(cli_module.list_cmd, "connected_sdk",
                        lambda **k: (_FakePx(), "http://x", "tok"))


def test_list_ontologies(monkeypatch):
    _wire(monkeypatch)
    result = CliRunner().invoke(cli, ["list", "ontologies"])
    assert result.exit_code == 0, result.output
    assert "abc123" in result.output and "Al Dente" in result.output
    assert "1 result(s)." in result.output


def test_list_apps(monkeypatch):
    _wire(monkeypatch)
    result = CliRunner().invoke(cli, ["list", "apps"])
    assert result.exit_code == 0, result.output
    assert "app-1" in result.output and "draft" in result.output


def test_list_datasources(monkeypatch):
    _wire(monkeypatch)
    result = CliRunner().invoke(cli, ["list", "datasources"])
    assert result.exit_code == 0, result.output
    assert "ds-1" in result.output and "orders_csv" in result.output


def test_list_context_default_global(monkeypatch):
    _wire(monkeypatch)
    result = CliRunner().invoke(cli, ["list", "context"])
    assert result.exit_code == 0, result.output
    assert "note-1" in result.output
    assert "a long note body" in result.output  # snippet flattens whitespace


def test_list_context_project_requires_id(monkeypatch):
    _wire(monkeypatch)
    result = CliRunner().invoke(cli, ["list", "context", "--scope", "project"])
    assert result.exit_code == 1
    assert "requires --ontology" in result.output


def test_list_empty(monkeypatch):
    class _Empty(_FakePx):
        def list_ontologies(self, scopes):
            return []

    monkeypatch.setattr(cli_module.list_cmd, "connected_sdk",
                        lambda **k: (_Empty(), "http://x", "tok"))
    result = CliRunner().invoke(cli, ["list", "ontologies"])
    assert result.exit_code == 0, result.output
    assert "No user-scoped ontologies." in result.output
