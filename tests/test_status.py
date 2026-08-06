from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli


class _FakePx:
    def __init__(self, statuses):
        self._statuses = statuses

    def list_ontologies(self, scopes):
        return [{"id": "p1", "name": "Alpha"}, {"id": "p2", "name": "Beta"}]

    def get_execution_statuses(self, scope):
        return self._statuses


def _wire(monkeypatch, statuses):
    fake = _FakePx(statuses)
    monkeypatch.setattr(cli_module.status_cmd, "connected_sdk",
                        lambda **k: (fake, "http://x", "t"))


def test_status_shows_running_and_idle(monkeypatch):
    _wire(monkeypatch, {"p1": {"status": "running", "total": 3, "target_concept": "c",
                               "statuses": {"c": {"status": "running"}}}})
    result = CliRunner().invoke(cli, ["status"])
    assert result.exit_code == 0, result.output
    assert "1 running" in result.output
    assert "running    Alpha" in result.output          # running row
    assert "0/3" in result.output                        # progress
    assert "idle" in result.output and "Beta" in result.output
    # a one-shot render (no prior state) announces the running project
    assert "Alpha started running" in result.output


def test_status_all_idle(monkeypatch):
    _wire(monkeypatch, {})  # nothing non-idle -> all idle
    result = CliRunner().invoke(cli, ["status"])
    assert result.exit_code == 0, result.output
    assert "0 running" in result.output
    assert result.output.count("idle") >= 2  # both projects idle


def test_status_running_sorted_first(monkeypatch):
    # p2 (Beta) running, p1 (Alpha) idle -> Beta must appear above Alpha
    _wire(monkeypatch, {"p2": {"status": "running", "total": 1, "target_concept": "x",
                               "statuses": {}}})
    result = CliRunner().invoke(cli, ["status"])
    assert result.exit_code == 0, result.output
    assert result.output.index("Beta") < result.output.index("Alpha")
