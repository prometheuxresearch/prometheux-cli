import json
from pathlib import Path

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli


class _FakePx:
    def __init__(self, fail=False):
        self.fail = fail
        self.ran = []

    def run_concept(self, ontology_id, concept_name, scope="user", params=None, **kw):
        self.ran.append((ontology_id, concept_name, scope, params))
        if self.fail:
            raise RuntimeError("engine boom")
        return {"status": "ok"}


def _workspace(tmp_path: Path):
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nprojects:\n  - ./projects/p\n"
    )
    c = tmp_path / "projects" / "p" / "concepts"
    c.mkdir(parents=True)
    (tmp_path / "projects" / "p" / "prometheux.yaml").write_text(
        "schemaVersion: 1\nproject:\n  id: pid1\n  name: P\n  scope: user\nconcepts: ./concepts\n"
    )
    (c / "customer.vadalog").write_text("customer(1).\n")
    (c / "customer.meta.yaml").write_text("conceptType: logic\noutputPredicate: customer\n")
    (c / "risk.vadalog").write_text("risk(Id) :- customer(Id).\n")
    (c / "risk.meta.yaml").write_text("conceptType: logic\noutputPredicate: risk\n")


def _events(tmp_path):
    lines = (tmp_path / ".px" / "openlineage.jsonl").read_text().splitlines()
    return [json.loads(x) for x in lines]


def test_run_emits_start_and_complete(tmp_path: Path, monkeypatch):
    fake = _FakePx()
    monkeypatch.setattr(cli_module.run_cmd, "connected_sdk", lambda **k: (fake, "u", "t"))
    _workspace(tmp_path)

    result = CliRunner().invoke(cli, ["run", "risk", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert fake.ran == [("pid1", "risk", "user", {})]

    evs = _events(tmp_path)
    assert [e["eventType"] for e in evs] == ["START", "COMPLETE"]
    assert evs[0]["job"] == {"namespace": "prometheux", "name": "p.risk"}
    # derived edge: risk depends on customer
    assert {d["name"] for d in evs[0]["inputs"]} == {"customer"}
    assert evs[1]["outputs"][0]["name"] == "risk"


def test_run_failure_emits_fail(tmp_path: Path, monkeypatch):
    fake = _FakePx(fail=True)
    monkeypatch.setattr(cli_module.run_cmd, "connected_sdk", lambda **k: (fake, "u", "t"))
    _workspace(tmp_path)

    result = CliRunner().invoke(cli, ["run", "risk", str(tmp_path)])
    assert result.exit_code == 1
    evs = _events(tmp_path)
    assert [e["eventType"] for e in evs] == ["START", "FAIL"]
    assert "engine boom" in evs[1]["run"]["facets"]["errorMessage"]["message"]


def test_run_unknown_concept(tmp_path: Path, monkeypatch):
    fake = _FakePx()
    monkeypatch.setattr(cli_module.run_cmd, "connected_sdk", lambda **k: (fake, "u", "t"))
    _workspace(tmp_path)
    result = CliRunner().invoke(cli, ["run", "nope", str(tmp_path)])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_run_no_openlineage_flag(tmp_path: Path, monkeypatch):
    fake = _FakePx()
    monkeypatch.setattr(cli_module.run_cmd, "connected_sdk", lambda **k: (fake, "u", "t"))
    _workspace(tmp_path)
    result = CliRunner().invoke(cli, ["run", "risk", str(tmp_path), "--no-openlineage"])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / ".px" / "openlineage.jsonl").exists()
