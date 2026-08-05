from pathlib import Path

from click.testing import CliRunner

from prometheux_cli.cli import cli


def _init(tmp_path: Path) -> Path:
    runner = CliRunner()
    result = runner.invoke(cli, ["init", str(tmp_path), "--name", "acme"])
    assert result.exit_code == 0, result.output
    return tmp_path


def test_scaffold_validates_clean(tmp_path: Path):
    root = _init(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(root)])
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output


def test_missing_meta_fails(tmp_path: Path):
    root = _init(tmp_path)
    (root / "projects" / "example" / "concepts" / "customers.meta.yaml").unlink()
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(root)])
    assert result.exit_code == 1
    assert "missing envelope" in result.output


def test_duplicate_output_predicate_fails(tmp_path: Path):
    root = _init(tmp_path)
    # Make risk_score claim the same output predicate as customers.
    meta = root / "projects" / "example" / "concepts" / "risk_score.meta.yaml"
    meta.write_text(
        "conceptType: logic\noutputPredicate: customer\n",
        "utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(root)])
    assert result.exit_code == 1
    assert "duplicate outputPredicate" in result.output


def test_unknown_datasource_fails(tmp_path: Path):
    root = _init(tmp_path)
    meta = root / "projects" / "example" / "concepts" / "customers.meta.yaml"
    text = meta.read_text().replace("datasource: snowflake_prod", "datasource: nope")
    meta.write_text(text, "utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(root)])
    assert result.exit_code == 1
    assert "unknown datasource" in result.output


def test_no_workspace_found(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(tmp_path)])
    assert result.exit_code == 2
