from pathlib import Path

from click.testing import CliRunner

from prometheux_cli import sdk as cli_sdk
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
    (root / "ontologies" / "example" / "concepts" / "customers.meta.yaml").unlink()
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", str(root)])
    assert result.exit_code == 1
    assert "missing envelope" in result.output


def test_duplicate_output_predicate_fails(tmp_path: Path):
    root = _init(tmp_path)
    # Make risk_score claim the same output predicate as customers.
    meta = root / "ontologies" / "example" / "concepts" / "risk_score.meta.yaml"
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
    meta = root / "ontologies" / "example" / "concepts" / "customers.meta.yaml"
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


class _FakePx:
    def __init__(self, valid=True):
        self.calls = []
        self.valid = valid

    def validate_concept(self, definition=None, concept_type=None, concept_name=None,
                         ontology_id=None):
        self.calls.append((concept_name, concept_type, ontology_id))
        return {"valid": self.valid, "error": None if self.valid else "bad rules"}


def test_validate_online_calls_sdk(tmp_path: Path, monkeypatch):
    # `--online` is a local import of connected_sdk, so patch the sdk module.
    fake = _FakePx()
    monkeypatch.setattr(cli_sdk, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    root = _init(tmp_path)
    result = CliRunner().invoke(cli, ["validate", str(root), "--online"])
    assert result.exit_code == 0, result.output
    names = {c[0] for c in fake.calls}
    assert names == {"customer", "risk"}
    assert "Online concept validation" in result.output


def test_validate_online_reports_invalid(tmp_path: Path, monkeypatch):
    fake = _FakePx(valid=False)
    monkeypatch.setattr(cli_sdk, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    root = _init(tmp_path)
    result = CliRunner().invoke(cli, ["validate", str(root), "--online"])
    assert result.exit_code == 1, result.output
    assert "bad rules" in result.output
    assert "FAIL" in result.output
