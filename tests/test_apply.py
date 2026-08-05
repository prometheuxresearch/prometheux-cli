from pathlib import Path

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.apply import (
    concept_save_kwargs,
    ensure_output_atom,
    is_default_parquet_output,
    structured_binds,
    topo_order,
)
from prometheux_cli.cli import cli
from prometheux_cli.loader import LocalConcept


def _c(pred, body, **meta):
    return LocalConcept(predicate=pred, concept_type=meta.pop("ct", "logic"), body=body, meta=meta, path=f"{pred}")


# ---- unit: binds + kwargs -------------------------------------------------

def test_default_parquet_output_detection():
    assert is_default_parquet_output('@bind("p","parquet","disk/results/x","p").')
    assert not is_default_parquet_output('@bind("p","snowflake","DB","T").')
    assert not is_default_parquet_output('@qbind("p","parquet","disk/results/x").')


def test_structured_binds_drops_default_parquet_only():
    col = {"input": [], "output": '@bind("p","parquet","disk/results/x","p").'}
    assert structured_binds(col, "p") is None


def test_structured_binds_keeps_input_and_real_output():
    col = {
        "input": ['@bind("src","snowflake","DB","T").'],
        "output": '@bind("p","postgres","DB","OUT").',
    }
    binds = structured_binds(col, "p")
    assert binds["input"][0]["predicate"] == "src"
    assert binds["output"][0]["predicate"] == "p"


def test_concept_save_kwargs_create_vs_update():
    c = _c("customer", "customer(X) :- s(X).", group="ingest", description="d")
    create = concept_save_kwargs(c, update=False)
    assert create["definition"].startswith("customer(X)")
    assert create["output_predicate"] == "customer"
    assert create["group"] == "ingest"
    assert "existing_name" not in create

    update = concept_save_kwargs(c, update=True)
    assert update["existing_name"] == "customer"
    assert update["force_overwrite"] is True


def test_project_missing_detects_deleted_project():
    from prometheux_cli.commands.apply import _project_missing
    assert _project_missing(None) is True
    assert _project_missing({"tables": {}}) is True
    assert _project_missing({"tables": {"projects_x": {"data": []}}}) is True
    assert _project_missing({"tables": {"projects_x": {"data": [{"project_id": "x"}]}}}) is False


def test_ensure_output_atom_appends_when_missing():
    out = ensure_output_atom("risk(X) :- customer(X).", "risk", has_output_bind=False)
    assert '@output("risk").' in out
    assert out.startswith("risk(X)")


def test_ensure_output_atom_noop_when_bind_or_inline():
    body = "risk(X) :- customer(X)."
    assert ensure_output_atom(body, "risk", has_output_bind=True) == body
    inline = 'risk(X) :- customer(X).\n@output("risk").'
    assert ensure_output_atom(inline, "risk", has_output_bind=False) == inline


def test_concept_save_kwargs_adds_output_atom_for_logic():
    c = _c("risk", "risk(X) :- customer(X).")
    kw = concept_save_kwargs(c, update=False)
    assert '@output("risk").' in kw["definition"]


def test_concept_save_kwargs_wires_friendly_input_bind():
    c = _c(
        "person",
        "person(Id, Name, Age) :- people_csv(Id, Name, Age).",
        binds={"input": [{"predicate": "people_csv", "datasource": "people_ds"}]},
    )
    ds_binds = {"people_ds": '@bind("people_ds_placeholder","csv useHeaders=\'true\'","disk","people.csv").'}
    kw = concept_save_kwargs(c, update=False, datasource_binds=ds_binds)
    inputs = kw["binds"]["input"]
    assert len(inputs) == 1
    # predicate rewritten to match the body reference
    assert inputs[0]["predicate"] == "people_csv"
    assert '@bind("people_csv","csv useHeaders=\'true\'","disk","people.csv").' == inputs[0]["annotation"]


def test_topo_order_deps_first():
    concepts = [
        _c("report", "report(X) :- risk(X)."),
        _c("risk", "risk(X) :- customer(X, _)."),
        _c("customer", "customer(X, N) :- s(X, N)."),
    ]
    order = [c.predicate for c in topo_order(concepts)]
    assert order.index("customer") < order.index("risk") < order.index("report")


# ---- end to end -----------------------------------------------------------

import os


class _FakePx:
    def __init__(self, export):
        self._export = export
        self.saved = []
        self.snapshots = 0
        self.pruned = []
        self.connected = []
        self.uploads = []
        self.dirs = []

    def list_ontologies(self, scopes):
        return [{"id": "abc123", "name": "Al Dente Supply Chain"}]

    def export_ontology(self, project, scope):
        return self._export

    def save_concept(self, **kwargs):
        self.saved.append(kwargs)
        return {"id": "x"}

    def create_snapshot(self, ontology_id, scope, description=None):
        self.snapshots += 1
        return {"snapshot_id": "s1"}

    def cleanup_concepts(self, ontology_id, scope, names):
        self.pruned = names
        return {}

    # datasource surface
    def Database(self, **kwargs):
        return kwargs

    def connect_sources(self, db, scope="user", compute_row_count=False):
        self.connected.append(db)
        fn = db.get("database_name") or "data.csv"
        return {
            "connectionStatus": True,
            "sources": [{
                "table_name": fn,
                "bind_annotation": f'@bind("{fn.split(".")[0]}","csv useHeaders=\'true\'","disk","{fn}").',
            }],
        }

    def upload_file(self, file_path, path=""):
        self.uploads.append((file_path, path))
        name = os.path.basename(file_path)
        prefix = f"{path}/" if path else ""
        return {"filePath": f"disk/{prefix}{name}", "fileName": name}

    def make_directory(self, path):
        self.dirs.append(path)
        return {}


def _wire(monkeypatch, fake):
    monkeypatch.setattr(cli_module.pull_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))


def _pull(runner, tmp_path):
    assert runner.invoke(cli, ["pull", "abc123", "--out", str(tmp_path)]).exit_code == 0
    return tmp_path / "projects" / "al-dente-supply-chain" / "concepts"


def test_apply_updates_edited_concept(tmp_path: Path, export_dict, monkeypatch):
    fake = _FakePx(export_dict)
    _wire(monkeypatch, fake)
    runner = CliRunner()
    concepts = _pull(runner, tmp_path)

    body = concepts / "customer.vadalog"
    body.write_text(body.read_text() + "\ncustomer(Id, Name) :- extra(Id, Name).\n")

    result = runner.invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output

    assert fake.snapshots == 1
    saved = {s.get("existing_name") or s["output_predicate"]: s for s in fake.saved}
    assert "customer" in saved
    assert saved["customer"]["existing_name"] == "customer"
    assert saved["customer"]["force_overwrite"] is True
    assert "extra(Id, Name)" in saved["customer"]["definition"]


def test_apply_creates_new_concept(tmp_path: Path, export_dict, monkeypatch):
    fake = _FakePx(export_dict)
    _wire(monkeypatch, fake)
    runner = CliRunner()
    concepts = _pull(runner, tmp_path)

    (concepts / "flag.vadalog").write_text("flag(Id) :- risk(Id).\n")
    (concepts / "flag.meta.yaml").write_text("conceptType: logic\noutputPredicate: flag\n")

    result = runner.invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    saved = {s["output_predicate"]: s for s in fake.saved}
    assert "flag" in saved
    assert "existing_name" not in saved["flag"]  # create


def test_apply_abort_without_yes(tmp_path: Path, export_dict, monkeypatch):
    fake = _FakePx(export_dict)
    _wire(monkeypatch, fake)
    runner = CliRunner()
    concepts = _pull(runner, tmp_path)
    (concepts / "customer.vadalog").write_text("customer(X) :- changed(X).\n")

    result = runner.invoke(cli, ["apply", str(tmp_path)], input="n\n")
    assert result.exit_code == 1
    assert fake.saved == []  # nothing written on abort


def _empty_export():
    return {
        "project_id": "abc123",
        "scope": "user",
        "tables": {
            "projects_workspace_id": {"schema": [], "data": [{"project_id": "abc123", "name": "T"}]},
            "concepts_abc123": {"schema": [], "data": [], "row_count": 0},
            "datasources_workspace_id": {"schema": [], "data": [], "row_count": 0},
        },
    }


def _ds_workspace(tmp_path: Path):
    proj = tmp_path / "projects" / "t"
    (proj / "concepts").mkdir(parents=True)
    (proj / "datasources").mkdir(parents=True)
    (proj / "data").mkdir(parents=True)
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nprojects:\n  - ./projects/t\n"
    )
    (tmp_path / "context").mkdir()
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nproject:\n  id: abc123\n  name: T\n  scope: user\n"
        "concepts: ./concepts\ndatasources:\n"
        "  - ./datasources/sf.yaml\n  - ./datasources/cust.yaml\n"
    )
    (proj / "concepts" / "c.vadalog").write_text("c(1).\n")
    (proj / "concepts" / "c.meta.yaml").write_text("conceptType: logic\noutputPredicate: c\n")
    (proj / "datasources" / "sf.yaml").write_text(
        "name: sf\ntype: snowflake\naccount: ${SF_ACCOUNT}\nwarehouse: WH\n"
    )
    (proj / "datasources" / "cust.yaml").write_text(
        "name: cust\ntype: csv\nfile: ../data/cust.csv\n"
    )
    (proj / "data" / "cust.csv").write_text("id,name\n1,ada\n")


def test_apply_connects_db_and_uploads_csv(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    monkeypatch.setenv("SF_ACCOUNT", "acme")
    _ds_workspace(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output

    # CSV uploaded then connected.
    assert any(fp.endswith("cust.csv") for fp, _ in fake.uploads)
    types = {db.get("database_type") for db in fake.connected}
    assert "csv" in types and "snowflake" in types
    sf = next(db for db in fake.connected if db["database_type"] == "snowflake")
    assert sf["options"]["account"] == "acme"  # ${SF_ACCOUNT} resolved
    csv = next(db for db in fake.connected if db["database_type"] == "csv")
    assert csv["database_name"] == "cust.csv"


def test_apply_wires_concept_to_csv_datasource(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))

    proj = tmp_path / "projects" / "t"
    (proj / "concepts").mkdir(parents=True)
    (proj / "datasources").mkdir(parents=True)
    (proj / "data").mkdir(parents=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nprojects:\n  - ./projects/t\n"
    )
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nproject:\n  id: abc123\n  name: T\n  scope: user\n"
        "concepts: ./concepts\ndatasources:\n  - ./datasources/people.yaml\n"
    )
    (proj / "datasources" / "people.yaml").write_text("name: people_ds\ntype: csv\nfile: ../data/people.csv\n")
    (proj / "data" / "people.csv").write_text("id,name\n1,ada\n")
    (proj / "concepts" / "person.vadalog").write_text("person(Id, Name) :- people_ds(Id, Name).\n")
    (proj / "concepts" / "person.meta.yaml").write_text(
        "conceptType: logic\noutputPredicate: person\n"
        "binds:\n  input:\n    - predicate: people_ds\n      datasource: people_ds\n"
    )

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    person = next(s for s in fake.saved if s["output_predicate"] == "person")
    inputs = person["binds"]["input"]
    assert any(b["predicate"] == "people_ds" and "people.csv" in b["annotation"] for b in inputs)


def test_apply_missing_secret_warns_but_concepts_apply(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    monkeypatch.delenv("SF_ACCOUNT", raising=False)
    _ds_workspace(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["apply", str(tmp_path), "--yes"])
    # A missing secret is a non-fatal warning: the concept still applies.
    assert result.exit_code == 0, result.output
    assert "SF_ACCOUNT" in result.output
    assert any(s["output_predicate"] == "c" for s in fake.saved)


def _two_projects(tmp_path: Path):
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\n"
        "projects:\n  - ./projects/one\n  - ./projects/two\n"
    )
    for slug, name, pred in [("one", "One", "a"), ("two", "Two", "b")]:
        c = tmp_path / "projects" / slug / "concepts"
        c.mkdir(parents=True)
        (tmp_path / "projects" / slug / "prometheux.yaml").write_text(
            f"schemaVersion: 1\nproject:\n  id: abc123\n  name: {name}\n  scope: user\nconcepts: ./concepts\n"
        )
        (c / f"{pred}.vadalog").write_text(f"{pred}(1).\n")
        (c / f"{pred}.meta.yaml").write_text(f"conceptType: logic\noutputPredicate: {pred}\n")


def test_apply_project_filter_targets_one(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    _two_projects(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["apply", str(tmp_path), "--project", "Two", "--yes"])
    assert result.exit_code == 0, result.output
    preds = {s["output_predicate"] for s in fake.saved}
    assert preds == {"b"}  # only project Two's concept


def test_apply_unknown_project_fails(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    _two_projects(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["apply", str(tmp_path), "--project", "Nope", "--yes"])
    assert result.exit_code == 2
    assert "unknown project" in result.output
    assert fake.saved == []


def test_apply_prune_deletes(tmp_path: Path, export_dict, monkeypatch):
    fake = _FakePx(export_dict)
    _wire(monkeypatch, fake)
    runner = CliRunner()
    concepts = _pull(runner, tmp_path)
    (concepts / "risk.vadalog").unlink()
    (concepts / "risk.meta.yaml").unlink()

    result = runner.invoke(cli, ["apply", str(tmp_path), "--yes", "--prune"])
    assert result.exit_code == 0, result.output
    assert fake.pruned == ["risk"]
