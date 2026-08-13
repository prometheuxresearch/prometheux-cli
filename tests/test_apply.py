from pathlib import Path

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.apply import (
    concept_save_kwargs,
    ensure_output_atom,
    generative_concept_config,
    is_default_parquet_output,
    is_generative,
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
    from prometheux_cli.commands.apply import _ontology_missing
    assert _ontology_missing(None) is True
    assert _ontology_missing({"tables": {}}) is True
    assert _ontology_missing({"tables": {"projects_x": {"data": []}}}) is True
    assert _ontology_missing({"tables": {"projects_x": {"data": [{"project_id": "x"}]}}}) is False


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


def test_rewrite_results_project_id():
    from prometheux_cli.apply import rewrite_results_ontology_id
    ann = '@bind("up","parquet","disk/results/OLDID","up").'
    assert rewrite_results_ontology_id(ann, "NEWID") == '@bind("up","parquet","disk/results/NEWID","up").'
    # datasource-file paths (disk/project_...) are NOT touched
    csv = '@bind("x_csv","csv useHeaders=\'true\'","disk/project_OLDID","x.csv").'
    assert rewrite_results_ontology_id(csv, "NEWID") == csv


def test_concept_save_kwargs_retargets_sibling_output_path():
    c = _c("downstream", "downstream(X) :- upstream(X).",
           annotations={"bind_annotations": {
               "input": ['@bind("upstream","parquet","disk/results/OLDID","upstream").'],
               "output": ""}})
    kw = concept_save_kwargs(c, update=False, ontology_id="NEWID")
    assert "disk/results/NEWID" in kw["binds"]["input"][0]["annotation"]
    assert "OLDID" not in kw["binds"]["input"][0]["annotation"]


def test_concept_save_kwargs_sql_source_sent_verbatim():
    c = _c("acme", "SELECT Id FROM customer WHERE Name = 'Acme'", ct="sql")
    kw = concept_save_kwargs(c, update=False)
    # sql source is the transpile input: no @output atom is appended
    assert kw["definition"] == "SELECT Id FROM customer WHERE Name = 'Acme'"
    assert "@output" not in kw["definition"]
    assert kw["concept_type"] == "sql"
    assert kw["concept_name"] == "acme"


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


# ---- unit: context / llm concept_config ----------------------------------

def test_is_generative():
    assert is_generative(_c("s", "", ct="context"))
    assert is_generative(_c("s", "prompt", ct="llm"))
    assert not is_generative(_c("s", "s(1).", ct="logic"))


def test_generative_config_llm_passthrough():
    c = _c("summary", "Summarize {{ customer }}.", ct="llm",
           llmConfig={"provider": "anthropic", "model": "claude-sonnet-4-6",
                      "output_columns": [{"name": "Id", "type": "string"}]})
    cfg = generative_concept_config(c)
    assert cfg["provider"] == "anthropic"
    assert cfg["output_columns"][0]["name"] == "Id"


def test_generative_config_context_dynamic():
    c = _c("policy", "", ct="context", contextMode="dynamic",
           query="credit-risk scoring policy", top_k=5, kinds=["fact"])
    cfg = generative_concept_config(c)
    assert cfg == {"mode": "dynamic", "query": "credit-risk scoring policy",
                   "top_k": 5, "kinds": ["fact"]}


def test_generative_config_context_static_uses_resolved_ids():
    c = _c("policy", "", ct="context", contextMode="static",
           notes=["facts/a.md", "facts/b.md"])
    cfg = generative_concept_config(c, note_ids=["n1", "n2"])
    assert cfg == {"mode": "static", "note_ids": ["n1", "n2"]}


def test_generative_config_context_static_explicit_ids_override():
    c = _c("policy", "", ct="context", contextMode="static", noteIds=["direct1"])
    cfg = generative_concept_config(c, note_ids=["ignored"])
    assert cfg == {"mode": "static", "note_ids": ["direct1"]}


def test_generative_config_none_for_logic():
    assert generative_concept_config(_c("s", "s(1).", ct="logic")) is None


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
        self.ontologies_saved = []
        self.apps_saved = []
        self.apps_deleted = []
        self.server_apps = []  # [{id, name, definition}]

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

    def save_ontology_schema(self, ontology_id, ontology_schema_data, scope="user"):
        self.ontologies_saved.append((ontology_id, ontology_schema_data, scope))
        return {}

    # apps surface
    def list_apps(self, ontology_id, scope="user"):
        return [{"id": a["id"], "name": a["name"]} for a in self.server_apps]

    def get_app(self, ontology_id, app_id, scope="user"):
        for a in self.server_apps:
            if a["id"] == app_id:
                return {"id": a["id"], "name": a["name"], "definition": a["definition"]}
        return {}

    def save_app(self, ontology_id, app, scope="user"):
        self.apps_saved.append((ontology_id, app, scope))
        return {"id": app.get("id") or "app-new-id"}

    def delete_app(self, ontology_id, app_id, scope="user"):
        self.apps_deleted.append((ontology_id, app_id, scope))
        return {"status": "success"}

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
    return tmp_path / "ontologies" / "al-dente-supply-chain" / "concepts"


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
    proj = tmp_path / "ontologies" / "t"
    (proj / "concepts").mkdir(parents=True)
    (proj / "datasources").mkdir(parents=True)
    (proj / "data").mkdir(parents=True)
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/t\n"
    )
    (tmp_path / "context").mkdir()
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: abc123\n  name: T\n  scope: user\n"
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


def test_remap_app_project_ids():
    from prometheux_cli.commands.apply import _remap_app_project_ids
    defn = {"id": "app1", "pages": [
        {"id": "p1", "project": {"id": "OLD"}},
        {"id": "p2", "project": {"id": "OTHER"}},
        {"id": "p3"},  # no project block
        7,             # non-dict page (defensive)
    ]}
    out = _remap_app_project_ids(defn, {"OLD": "NEW"})
    assert out["pages"][0]["project"]["id"] == "NEW"   # rewritten via remap
    assert out["pages"][1]["project"]["id"] == "OTHER"  # untouched (no owning_id, not in remap)
    # no remap, no owning -> unchanged
    assert _remap_app_project_ids({"pages": [{"project": {"id": "X"}}]}, {})["pages"][0]["project"]["id"] == "X"


def test_remap_app_project_ids_stale_foreign_id_falls_back_to_owning():
    from prometheux_cli.commands.apply import _remap_app_project_ids
    # a copy where the manifest id was cleared: the app embeds the SOURCE id, which
    # isn't in the remap; it should fall back to the owning (new) project id.
    defn = {"pages": [
        {"project": {"id": "SOURCE"}},       # stale foreign id -> owning
        {"project": {"id": "OWNING"}},       # already correct -> untouched
        {"project": {"id": "SIBLING_NEW"}},  # a real applied project (in remap values) -> untouched
    ]}
    out = _remap_app_project_ids(defn, {"SIBLING_OLD": "SIBLING_NEW"}, owning_id="OWNING")
    assert out["pages"][0]["project"]["id"] == "OWNING"
    assert out["pages"][1]["project"]["id"] == "OWNING"
    assert out["pages"][2]["project"]["id"] == "SIBLING_NEW"


def test_apply_rewrites_app_project_id_on_recreate(tmp_path: Path, monkeypatch):
    """A recreated project's app has its stale page project.id rewritten to the new id."""
    # server has no such project id -> triggers recreate; save_app captures the definition
    fake = _FakePx({"project_id": "STALE", "scope": "user", "tables": {}})  # _ontology_missing -> True
    saved_defs = []
    fake.save_app = lambda ontology_id, app, scope="user": (saved_defs.append(app), {"id": "app-x"})[1]
    fake.save_ontology = lambda oid, name, scope, description=None: "NEWID"
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))

    proj = _apps_workspace(tmp_path, "")  # placeholder; overwrite manifest + app below
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: STALE\n  name: T\n  scope: user\n"
        "concepts: ./concepts\napps: ./apps\n"
    )
    (proj / "concepts" / "c.vadalog").write_text("c(1).\n")
    (proj / "concepts" / "c.meta.yaml").write_text("conceptType: logic\noutputPredicate: c\n")
    (proj / "apps" / "sales.app.yaml").write_text(
        "schemaVersion: 2\nname: Sales\npages:\n  - id: page_1\n    label: P\n    project:\n      id: STALE\n"
    )

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert saved_defs, "app was not saved"
    # the page's project.id was rewritten from the stale id to the recreated id
    assert saved_defs[0]["pages"][0]["project"]["id"] == "NEWID"


def test_is_unresolved_reference():
    from prometheux_cli.commands.apply import _is_unresolved_reference
    assert _is_unresolved_reference("body reference(s) do not resolve to any existing concept")
    assert _is_unresolved_reference("please create upstream concepts first")
    assert not _is_unresolved_reference("Parsing exception: unexpected symbol")


def test_apply_retries_concept_with_hidden_dependency(tmp_path: Path, monkeypatch):
    """A concept whose upstream dep is hidden from topo_order (e.g. inside a SQL
    FROM clause) still applies: the failed save is deferred and retried after its
    upstream is created."""
    fake = _FakePx(_empty_export())
    saved = set()

    def strict_save(**kwargs):
        pred = kwargs["output_predicate"]
        # `downstream` references `upstream` only inside a FROM clause, which
        # topo_order can't see — the server rejects it until upstream exists.
        if pred == "downstream" and "upstream" not in saved:
            raise Exception("HTTP 500: body reference(s) do not resolve: 'upstream'")
        saved.add(pred)
        return {"id": pred}

    fake.save_concept = strict_save
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))

    proj = tmp_path / "ontologies" / "t"
    (proj / "concepts").mkdir(parents=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/t\n"
    )
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: abc123\n  name: T\n  scope: user\nconcepts: ./concepts\n"
    )
    # `downstream` sorts before `upstream`; its dep is hidden in a FROM clause,
    # so topo_order leaves it first -> first save fails -> must be retried.
    (proj / "concepts" / "downstream.vadalog").write_text("downstream(X) <- SELECT X FROM upstream.\n")
    (proj / "concepts" / "downstream.meta.yaml").write_text("conceptType: logic\noutputPredicate: downstream\n")
    (proj / "concepts" / "upstream.vadalog").write_text("upstream(1).\n")
    (proj / "concepts" / "upstream.meta.yaml").write_text("conceptType: logic\noutputPredicate: upstream\n")

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert {"upstream", "downstream"} <= saved


def test_apply_skips_unresolvable_but_applies_rest(tmp_path: Path, monkeypatch):
    """An unresolvable concept is skipped (not fatal); the rest + the ontology
    schema still apply, and the run exits non-zero with a skip summary."""
    fake = _FakePx(_empty_export())
    saved = []

    def selective_save(**kwargs):
        pred = kwargs["output_predicate"]
        if pred == "orphan":
            raise Exception("HTTP 500: body reference(s) do not resolve: 'ghost'")
        saved.append(pred)
        return {"id": pred}

    fake.save_concept = selective_save
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))

    proj = tmp_path / "ontologies" / "t"
    (proj / "concepts").mkdir(parents=True)
    (proj / "ontology").mkdir(parents=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/t\n"
    )
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: abc123\n  name: T\n  scope: user\n"
        "concepts: ./concepts\nontologySchema: ./ontology/schema.yaml\n"
    )
    (proj / "concepts" / "good.vadalog").write_text("good(1).\n")
    (proj / "concepts" / "good.meta.yaml").write_text("conceptType: logic\noutputPredicate: good\n")
    (proj / "concepts" / "orphan.vadalog").write_text("orphan(X) <- ghost(X).\n")
    (proj / "concepts" / "orphan.meta.yaml").write_text("conceptType: logic\noutputPredicate: orphan\n")
    (proj / "ontology" / "schema.yaml").write_text("nodes: []\nedges: []\n")

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 1                       # skips make it non-zero
    assert "good" in saved and "orphan" not in saved   # good applied, orphan skipped
    assert fake.ontologies_saved                        # ontology still applied
    assert "skipped" in result.output and "orphan" in result.output


def test_apply_genuine_error_still_aborts(tmp_path: Path, monkeypatch):
    """A non-reference error (e.g. a parse error) aborts fast, not skipped."""
    fake = _FakePx(_empty_export())

    def parse_fail(**kwargs):
        raise Exception("HTTP 500: Parsing exception: unexpected symbol")

    fake.save_concept = parse_fail
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))

    proj = tmp_path / "ontologies" / "t"
    (proj / "concepts").mkdir(parents=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/t\n"
    )
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: abc123\n  name: T\n  scope: user\nconcepts: ./concepts\n"
    )
    (proj / "concepts" / "c.vadalog").write_text("c(1).\n")
    (proj / "concepts" / "c.meta.yaml").write_text("conceptType: logic\noutputPredicate: c\n")

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 1
    assert "FAIL" in result.output and "Parsing exception" in result.output


def test_single_table_helper():
    from prometheux_cli.commands.apply import _single_table
    assert _single_table({"tables": "prometheux.public.companies"}) == "prometheux.public.companies"
    assert _single_table({"tables": ["schema.t"]}) == "schema.t"
    assert _single_table({"tables": ["a", "b"]}) is None
    assert _single_table({}) is None


def test_apply_wires_concept_to_postgres_table(tmp_path: Path, monkeypatch):
    """A DB datasource binds the concept to the matching table, not sources[0]."""
    fake = _FakePx(_empty_export())

    def connect(db, scope="user", compute_row_count=False):
        # A real postgres connect returns EVERY source in the group; the wanted
        # table must be selected by name, not by position.
        return {"connectionStatus": True, "sources": [
            {"table_name": "prometheux.public.other",
             "bind_annotation": '@bind("other","postgresql ...","prometheux","prometheux.public.other").'},
            {"table_name": "prometheux.public.companies",
             "bind_annotation": '@bind("companies","postgresql ...","prometheux","prometheux.public.companies").'},
        ]}

    fake.connect_sources = connect
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    monkeypatch.setenv("PG_PASSWORD", "secret")

    proj = tmp_path / "ontologies" / "t"
    (proj / "concepts").mkdir(parents=True)
    (proj / "datasources").mkdir(parents=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/t\n"
    )
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: abc123\n  name: T\n  scope: user\n"
        "concepts: ./concepts\ndatasources:\n  - ./datasources/pg_companies.yaml\n"
    )
    (proj / "datasources" / "pg_companies.yaml").write_text(
        "name: pg_companies\ntype: postgresql\nhost: db.example\nport: 5432\n"
        "username: u\npassword: ${PG_PASSWORD}\ndatabase: prometheux\n"
        "tables:\n  - prometheux.public.companies\n"
    )
    (proj / "concepts" / "company.vadalog").write_text("company(Id, Name) :- companies_src(Id, Name).\n")
    (proj / "concepts" / "company.meta.yaml").write_text(
        "conceptType: logic\noutputPredicate: company\n"
        "binds:\n  input:\n    - predicate: companies_src\n      datasource: pg_companies\n"
    )

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    company = next(s for s in fake.saved if s["output_predicate"] == "company")
    ann = company["binds"]["input"][0]["annotation"]
    # bound to the companies table (matched by name), rewritten to the body predicate
    assert "prometheux.public.companies" in ann
    assert '@bind("companies_src"' in ann


def test_apply_wires_concept_to_csv_datasource(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))

    proj = tmp_path / "ontologies" / "t"
    (proj / "concepts").mkdir(parents=True)
    (proj / "datasources").mkdir(parents=True)
    (proj / "data").mkdir(parents=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/t\n"
    )
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: abc123\n  name: T\n  scope: user\n"
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
        "ontologies:\n  - ./ontologies/one\n  - ./ontologies/two\n"
    )
    for slug, name, pred in [("one", "One", "a"), ("two", "Two", "b")]:
        c = tmp_path / "ontologies" / slug / "concepts"
        c.mkdir(parents=True)
        (tmp_path / "ontologies" / slug / "prometheux.yaml").write_text(
            f"schemaVersion: 1\nontology:\n  id: abc123\n  name: {name}\n  scope: user\nconcepts: ./concepts\n"
        )
        (c / f"{pred}.vadalog").write_text(f"{pred}(1).\n")
        (c / f"{pred}.meta.yaml").write_text(f"conceptType: logic\noutputPredicate: {pred}\n")


def test_apply_project_filter_targets_one(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    _two_projects(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["apply", str(tmp_path), "--ontology", "Two", "--yes"])
    assert result.exit_code == 0, result.output
    preds = {s["output_predicate"] for s in fake.saved}
    assert preds == {"b"}  # only project Two's concept


def test_apply_unknown_project_fails(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    _two_projects(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["apply", str(tmp_path), "--ontology", "Nope", "--yes"])
    assert result.exit_code == 2
    assert "unknown ontology" in result.output
    assert fake.saved == []


def _capture_requests(monkeypatch):
    """Patch JarvisPyClient._request to record (method, path, json) and succeed."""
    calls = []

    def fake_request(method, path, json=None, params=None):
        calls.append((method, path, json))
        return {"status": "success", "data": {"id": (json or {}).get("concept_name")}}

    from prometheux_chain.client.jarvispy_client import JarvisPyClient
    monkeypatch.setattr(JarvisPyClient, "_request", staticmethod(fake_request))
    return calls


def _generative_workspace(tmp_path: Path):
    proj = tmp_path / "ontologies" / "t"
    (proj / "concepts").mkdir(parents=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/t\n"
    )
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: abc123\n  name: T\n  scope: user\nconcepts: ./concepts\n"
    )
    return proj


def test_apply_wires_llm_and_dynamic_context(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    calls = _capture_requests(monkeypatch)
    proj = _generative_workspace(tmp_path)

    (proj / "concepts" / "summary.llm.md").write_text(
        "---\nconceptType: llm\noutputPredicate: summary\n"
        "llmConfig:\n  provider: anthropic\n  model: claude-sonnet-4-6\n---\n"
        "Summarize {{ customer }}.\n"
    )
    (proj / "concepts" / "policy.context.yaml").write_text(
        "conceptType: context\noutputPredicate: policy\ncontextMode: dynamic\n"
        "query: credit-risk scoring policy\n"
    )

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output

    saves = {c[2]["concept_name"]: c[2] for c in calls if c[1].endswith("/save")}
    assert saves["summary"]["concept_type"] == "llm"
    assert saves["summary"]["concept_config"]["provider"] == "anthropic"
    assert "Summarize" in saves["summary"]["definition"]
    assert saves["policy"]["concept_type"] == "context"
    assert saves["policy"]["concept_config"] == {"mode": "dynamic", "query": "credit-risk scoring policy"}
    # generative concepts never go through the SDK save_concept path
    assert fake.saved == []


def test_apply_static_context_resolves_notes_from_state(tmp_path: Path, monkeypatch):
    import json as _json

    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    calls = _capture_requests(monkeypatch)
    proj = _generative_workspace(tmp_path)

    (tmp_path / ".px").mkdir()
    (tmp_path / ".px" / "context-state.json").write_text(_json.dumps({
        "context/domain.context.md::facts/a.md": {"id": "note-a", "hash": "h1"},
        "context/domain.context.md::facts/b.md": {"id": "note-b", "hash": "h2"},
    }))
    (proj / "concepts" / "pinned.context.yaml").write_text(
        "conceptType: context\noutputPredicate: pinned\ncontextMode: static\n"
        "notes:\n  - facts/a.md\n  - facts/b.md\n"
    )

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    saves = {c[2]["concept_name"]: c[2] for c in calls if c[1].endswith("/save")}
    assert saves["pinned"]["concept_config"] == {"mode": "static", "note_ids": ["note-a", "note-b"]}


def test_apply_static_context_warns_on_unresolved_note(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    calls = _capture_requests(monkeypatch)
    proj = _generative_workspace(tmp_path)

    # no context-state -> the referenced note cannot resolve
    (proj / "concepts" / "pinned.context.yaml").write_text(
        "conceptType: context\noutputPredicate: pinned\ncontextMode: static\n"
        "notes:\n  - facts/missing.md\n"
    )

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert "not found in context-state" in result.output
    saves = {c[2]["concept_name"]: c[2] for c in calls if c[1].endswith("/save")}
    assert saves["pinned"]["concept_config"] == {"mode": "static", "note_ids": []}


def _apps_workspace(tmp_path: Path, app_yaml: str):
    proj = tmp_path / "ontologies" / "t"
    (proj / "concepts").mkdir(parents=True)
    (proj / "apps").mkdir(parents=True)
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/t\n"
    )
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: abc123\n  name: T\n  scope: user\n"
        "concepts: ./concepts\napps: ./apps\n"
    )
    (proj / "apps" / "sales.app.yaml").write_text(app_yaml)
    return proj


def test_apply_creates_app_and_persists_id(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())  # no server apps
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    proj = _apps_workspace(tmp_path, "schemaVersion: 2\nname: Sales\npages: []\n")

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert len(fake.apps_saved) == 1
    _, saved_def, _ = fake.apps_saved[0]
    assert saved_def["name"] == "Sales"
    # the assigned id is written back into the file for idempotent re-apply
    import yaml
    on_disk = yaml.safe_load((proj / "apps" / "sales.app.yaml").read_text())
    assert on_disk["id"] == "app-new-id"


def test_apply_updates_existing_app_by_id(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    fake.server_apps = [{"id": "a1", "name": "Sales", "definition": {"id": "a1", "name": "Sales", "pages": [1]}}]
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    _apps_workspace(tmp_path, "id: a1\nschemaVersion: 2\nname: Sales\npages:\n  - 2\n")

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert len(fake.apps_saved) == 1
    _, saved_def, _ = fake.apps_saved[0]
    assert saved_def["id"] == "a1" and saved_def["pages"] == [2]


def test_apply_skips_unchanged_app(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    fake.server_apps = [{"id": "a1", "name": "Sales",
                         "definition": {"id": "a1", "schemaVersion": 2, "name": "Sales", "pages": [1]}}]
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    _apps_workspace(tmp_path, "id: a1\nschemaVersion: 2\nname: Sales\npages:\n  - 1\n")

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert fake.apps_saved == []  # identical definition -> not re-saved


def test_apply_prune_deletes_server_only_app(tmp_path: Path, monkeypatch):
    fake = _FakePx(_empty_export())
    fake.server_apps = [{"id": "gone", "name": "Ghost", "definition": {"id": "gone", "name": "Ghost"}}]
    monkeypatch.setattr(cli_module.apply_cmd, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    # local has no apps dir at all
    (tmp_path / "context").mkdir()
    (tmp_path / "prometheux.workspace.yaml").write_text(
        "schemaVersion: 1\nworkspace:\n  name: w\ncontext: ./context\nontologies:\n  - ./ontologies/t\n"
    )
    proj = tmp_path / "ontologies" / "t"
    (proj / "concepts").mkdir(parents=True)
    (proj / "prometheux.yaml").write_text(
        "schemaVersion: 1\nontology:\n  id: abc123\n  name: T\n  scope: user\nconcepts: ./concepts\n"
    )

    result = CliRunner().invoke(cli, ["apply", str(tmp_path), "--yes", "--prune"])
    assert result.exit_code == 0, result.output
    assert fake.apps_deleted == [("abc123", "gone", "user")]


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


def test_apply_pushes_edited_ontology(tmp_path: Path, export_dict, monkeypatch):
    fake = _FakePx(export_dict)
    _wire(monkeypatch, fake)
    runner = CliRunner()
    _pull(runner, tmp_path)

    onto = tmp_path / "ontologies" / "al-dente-supply-chain" / "ontology" / "schema.yaml"
    onto.write_text('nodes:\n  - id: customer\nedges: []\n')

    result = runner.invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert len(fake.ontologies_saved) == 1
    ontology_id, data, scope = fake.ontologies_saved[0]
    assert ontology_id == "abc123"
    assert data == {"nodes": [{"id": "customer"}], "edges": []}
    assert "ontology schema" in result.output


def test_apply_skips_unchanged_ontology(tmp_path: Path, export_dict, monkeypatch):
    fake = _FakePx(export_dict)
    _wire(monkeypatch, fake)
    runner = CliRunner()
    concepts = _pull(runner, tmp_path)
    # change a concept only; ontology round-trips identically
    body = concepts / "customer.vadalog"
    body.write_text(body.read_text() + "\ncustomer(Id, Name) :- extra(Id, Name).\n")

    result = runner.invoke(cli, ["apply", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    assert fake.ontologies_saved == []  # unchanged ontology is not re-pushed
