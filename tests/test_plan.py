from pathlib import Path

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli
from prometheux_cli.loader import LocalConcept, LocalProject
from prometheux_cli.plan import build_dependents, plan_project, referenced_predicates


def _concept(pred, body, **meta):
    return LocalConcept(predicate=pred, concept_type="logic", body=body, meta=meta, path=f"{pred}.vadalog")


# ---- unit: DAG derivation -------------------------------------------------

def test_referenced_predicates_ignores_comments():
    body = "risk(Id) :- customer(Id, _). % ignore ghost(X)"
    refs = referenced_predicates(body)
    assert "customer" in refs
    assert "ghost" not in refs


def test_build_dependents_edges():
    concepts = [
        _concept("customer", "customer(Id, Name) :- source(Id, Name)."),
        _concept("risk", "risk(Id) :- customer(Id, _)."),
        _concept("report", "report(Id) :- risk(Id)."),
    ]
    dep = build_dependents(concepts)
    assert dep["customer"] == {"risk"}
    assert dep["risk"] == {"report"}


# ---- unit: the engine -----------------------------------------------------

def _local(concepts):
    return LocalProject(
        slug="s",
        id="abc123",
        name="Demo",
        scope="user",
        concepts=concepts,
        datasources={"snowflake_prod": {"name": "snowflake_prod", "type": "snowflake"}},
    )


def test_unchanged(export_dict):
    local = _local([
        _concept("customer", "customer(Id, Name) :- source_customers(Id, Name)."),
        _concept("risk", "risk(Id) :- customer(Id, _)."),
    ])
    result = plan_project(local, export_dict)
    assert not result.has_changes
    assert all(c.action == "unchanged" for c in result.concept_changes)


def test_rules_change_cascades_downstream(export_dict):
    local = _local([
        _concept("customer", "customer(Id, Name, Country) :- source_customers(Id, Name, Country)."),
        _concept("risk", "risk(Id) :- customer(Id, _)."),
    ])
    result = plan_project(local, export_dict)
    customer = next(c for c in result.concept_changes if c.predicate == "customer")
    assert customer.action == "update"
    assert customer.definition_changed
    assert customer.server_populated  # export marks customer is_populated: true
    assert result.cascade["customer"] == ["risk"]
    assert result.rerun_count == 1


def test_create_and_delete(export_dict):
    local = _local([
        _concept("customer", "customer(Id, Name) :- source_customers(Id, Name)."),
        # risk removed -> withheld delete; brand_new added -> create
        _concept("brand_new", "brand_new(X) :- customer(X, _)."),
    ])
    result = plan_project(local, export_dict)
    actions = {c.predicate: c.action for c in result.concept_changes}
    assert actions["brand_new"] == "create"
    assert actions["risk"] == "delete"
    assert result.to_create == 1
    assert result.to_delete == 1


# ---- end to end: pull then plan (round-trip is clean) --------------------

class _FakePx:
    def __init__(self, export):
        self._export = export

    def list_ontologies(self, scopes):
        return [{"id": "abc123", "name": "Al Dente Supply Chain"}]

    def export_ontology(self, project, scope):
        return self._export


def _wire(monkeypatch, export):
    fake = _FakePx(export)
    monkeypatch.setattr(cli_module.pull_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    monkeypatch.setattr(cli_module.plan_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))


def test_pull_then_plan_no_changes(tmp_path: Path, export_dict, monkeypatch):
    _wire(monkeypatch, export_dict)
    runner = CliRunner()
    assert runner.invoke(cli, ["pull", "abc123", "--out", str(tmp_path)]).exit_code == 0
    result = runner.invoke(cli, ["plan", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "No changes" in result.output


def test_pull_edit_then_plan_shows_cascade(tmp_path: Path, export_dict, monkeypatch):
    _wire(monkeypatch, export_dict)
    runner = CliRunner()
    runner.invoke(cli, ["pull", "abc123", "--out", str(tmp_path)])

    body = tmp_path / "projects" / "al-dente-supply-chain" / "concepts" / "customer.vadalog"
    body.write_text(body.read_text() + "\ncustomer(Id, Name) :- extra(Id, Name).\n")

    result = runner.invoke(cli, ["plan", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "~ concept customer" in result.output
    assert "cascades to downstream" in result.output
    assert "risk" in result.output
