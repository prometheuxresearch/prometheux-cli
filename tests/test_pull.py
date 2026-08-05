from pathlib import Path

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli


class _FakePx:
    def __init__(self, export):
        self._export = export

    def list_ontologies(self, scopes):
        return [{"id": "abc123", "name": "Al Dente Supply Chain"}]

    def export_ontology(self, project, scope):
        return self._export


def test_pull_writes_and_validates(tmp_path: Path, export_dict, monkeypatch):
    fake = _FakePx(export_dict)
    monkeypatch.setattr(
        cli_module.pull_cmd, "connected_sdk", lambda **k: (fake, "http://x", "tok")
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["pull", "abc123", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "projects" / "al-dente-supply-chain" / "concepts" / "customer.vadalog").is_file()
    assert (tmp_path / "prometheux.workspace.yaml").is_file()
    assert (tmp_path / ".px" / "schemas" / "workspace.schema.json").is_file()

    # A freshly pulled workspace must pass offline validation.
    v = runner.invoke(cli, ["validate", str(tmp_path)])
    assert v.exit_code == 0, v.output
    assert "PASS" in v.output


def test_pull_no_project_lists(tmp_path: Path, export_dict, monkeypatch):
    fake = _FakePx(export_dict)
    monkeypatch.setattr(
        cli_module.pull_cmd, "connected_sdk", lambda **k: (fake, "http://x", "tok")
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["pull", "--out", str(tmp_path)])
    assert result.exit_code == 0
    assert "abc123" in result.output
