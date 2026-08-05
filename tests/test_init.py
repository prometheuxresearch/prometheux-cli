from pathlib import Path

from click.testing import CliRunner

from prometheux_cli.cli import cli


def test_init_scaffolds_workspace(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(tmp_path), "--name", "acme"])
    assert result.exit_code == 0, result.output

    assert (tmp_path / "prometheux.workspace.yaml").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / "CLAUDE.md").is_file()
    assert (tmp_path / ".cursor" / "rules" / "prometheux.mdc").is_file()
    assert (tmp_path / ".px" / "schemas" / "workspace.schema.json").is_file()
    assert (tmp_path / "projects" / "example" / "prometheux.yaml").is_file()
    assert (tmp_path / "projects" / "example" / "concepts" / "customers.vadalog").is_file()

    ws = (tmp_path / "prometheux.workspace.yaml").read_text()
    assert "name: acme" in ws


def test_init_refuses_nonempty_without_force(tmp_path: Path):
    (tmp_path / "existing.txt").write_text("hi")
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(tmp_path)])
    assert result.exit_code == 1
    assert "not empty" in result.output


def test_init_force_into_nonempty(tmp_path: Path):
    (tmp_path / "existing.txt").write_text("hi")
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(tmp_path), "--force"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "prometheux.workspace.yaml").is_file()
