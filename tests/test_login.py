import json
from pathlib import Path

from click.testing import CliRunner

from prometheux_cli.cli import cli


def test_login_saves_credentials(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PROMETHEUX_HOME", str(tmp_path))
    # Avoid inheriting a real token from the environment.
    monkeypatch.delenv("PMTX_TOKEN", raising=False)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["login", "--url", "http://localhost:8000", "--token", "devtoken", "--no-verify"],
    )
    assert result.exit_code == 0, result.output

    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg == {"url": "http://localhost:8000", "token": "devtoken"}


def test_login_prompts_for_token(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PROMETHEUX_HOME", str(tmp_path))
    monkeypatch.delenv("PMTX_TOKEN", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["login", "--no-verify"], input="secret-token\n")
    assert result.exit_code == 0, result.output
    cfg = json.loads((tmp_path / "config.json").read_text())
    assert cfg["token"] == "secret-token"
