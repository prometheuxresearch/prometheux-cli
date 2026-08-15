from pathlib import Path

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli
from prometheux_cli.loader import LocalApp, LocalConcept, LocalOntology
from prometheux_cli.plan import build_dependents, plan_ontology, referenced_predicates


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
    return LocalOntology(
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
    result = plan_ontology(local, export_dict)
    assert not result.has_changes
    assert all(c.action == "unchanged" for c in result.concept_changes)


def test_rules_change_cascades_downstream(export_dict):
    local = _local([
        _concept("customer", "customer(Id, Name, Country) :- source_customers(Id, Name, Country)."),
        _concept("risk", "risk(Id) :- customer(Id, _)."),
    ])
    result = plan_ontology(local, export_dict)
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
    result = plan_ontology(local, export_dict)
    actions = {c.predicate: c.action for c in result.concept_changes}
    assert actions["brand_new"] == "create"
    assert actions["risk"] == "delete"
    assert result.to_create == 1
    assert result.to_delete == 1


# ---- unit: datasource diff (connection-identity match) --------------------

def _local_ds(datasources):
    return LocalOntology(slug="s", id="abc123", name="D", scope="user", datasources=datasources)


def test_datasource_reused_when_connection_matches():
    # a shared postgres connection already on the account -> reuse its bind, no re-connect
    server = [{"datasource_type": "postgresql", "host": "db.example", "port": "5432",
               "table_name": "prometheux.public.companies",
               "bind_annotation": '@bind("companies","postgresql ...","prometheux","prometheux.public.companies").'}]
    local = _local_ds({"pg_companies": {"type": "postgresql", "host": "db.example", "port": 5432,
                                        "tables": ["prometheux.public.companies"]}})
    result = plan_ontology(local, None, server_datasources=server)
    ch = result.datasource_changes[0]
    assert ch.action == "unchanged"
    assert ch.bind and "prometheux.public.companies" in ch.bind
    assert not result.has_changes


def test_datasource_create_when_no_match():
    server = [{"datasource_type": "mariadb", "host": "other", "port": "3306",
               "table_name": "x", "bind_annotation": "@bind(...)."}]
    local = _local_ds({"pg_companies": {"type": "postgresql", "host": "db.example", "port": 5432,
                                        "tables": ["prometheux.public.companies"]}})
    result = plan_ontology(local, None, server_datasources=server)
    assert result.datasource_changes[0].action == "create"


def test_datasource_reused_via_pulled_table_name():
    # `pull` writes `table_name` (not `tables`); it must still match its connection
    server = [{"datasource_type": "postgresql", "host": "db.example", "port": "5432",
               "table_name": "prometheux.public.es_airports",
               "bind_annotation": '@bind("es","postgresql ...","prometheux","prometheux.public.es_airports").'}]
    local = _local_ds({"pulled": {"type": "postgresql", "host": "db.example", "port": "5432",
                                  "database_name": "prometheux",
                                  "table_name": "prometheux.public.es_airports"}})
    result = plan_ontology(local, None, server_datasources=server)
    ch = result.datasource_changes[0]
    assert ch.action == "unchanged" and ch.bind


def test_file_datasource_reused_when_already_uploaded():
    # a file datasource whose content is already on the account (matched by
    # disk/<diskPath> + filename) is reused, not re-uploaded
    server = [{"datasource_type": "csv", "host": "disk/project_x", "port": "",
               "table_name": "save_event.csv",
               "bind_annotation": '@bind("save_event_csv","csv useHeaders=\'true\'","disk/project_x","save_event.csv").'}]
    local = _local_ds({"save_event": {"type": "csv", "file": "../files/save_event.csv",
                                      "diskPath": "project_x"}})
    result = plan_ontology(local, None, server_datasources=server)
    assert result.datasource_changes[0].action == "unchanged"
    assert not result.has_changes


def test_file_datasource_reupload_forced_with_files():
    server = [{"datasource_type": "csv", "host": "disk/project_x", "port": "",
               "table_name": "save_event.csv", "bind_annotation": "@bind(...)."}]
    local = _local_ds({"save_event": {"type": "csv", "file": "../files/save_event.csv",
                                      "diskPath": "project_x"}})
    result = plan_ontology(local, None, server_datasources=server, with_files=True)
    assert result.datasource_changes[0].action == "create"  # forced re-upload


def test_file_datasource_new_always_uploads():
    local = _local_ds({"save_event": {"type": "csv", "file": "../files/save_event.csv",
                                      "diskPath": "project_x"}})
    result = plan_ontology(local, None, server_datasources=[])
    assert result.datasource_changes[0].action == "create"  # not on the account yet


def test_datasource_port_normalization_matches():
    # local port 0 / server port '' should be treated as equal (e.g. S3 csv)
    server = [{"datasource_type": "csv", "host": "s3a://b/airports", "port": "",
               "table_name": "a.csv", "bind_annotation": "@bind(...)."}]
    local = _local_ds({"s3": {"type": "csv", "host": "s3a://b/airports", "port": 0,
                              "tables": ["a.csv"]}})
    result = plan_ontology(local, None, server_datasources=server)
    assert result.datasource_changes[0].action == "unchanged"


# ---- unit: ontology diff --------------------------------------------------

def _local_with_ontology(ontology):
    return LocalOntology(
        slug="s", id="abc123", name="Demo", scope="user",
        concepts=[
            _concept("customer", "customer(Id, Name) :- source_customers(Id, Name)."),
            _concept("risk", "risk(Id) :- customer(Id, _)."),
        ],
        datasources={"snowflake_prod": {"name": "snowflake_prod", "type": "snowflake"}},
        ontology_schema=ontology,
    )


def test_ontology_unchanged(export_dict):
    # fixture server ontology is {"nodes": [], "edges": []}
    result = plan_ontology(_local_with_ontology({"nodes": [], "edges": []}), export_dict)
    assert result.ontology_change == "unchanged"
    assert not result.has_changes


def test_ontology_update_when_differs(export_dict):
    result = plan_ontology(
        _local_with_ontology({"nodes": [{"id": "customer"}], "edges": []}), export_dict
    )
    assert result.ontology_change == "update"
    assert result.has_changes


def test_ontology_create_when_server_empty():
    export = {"project_id": "abc123", "scope": "user", "tables": {
        "projects_workspace_id": {"data": [{"project_id": "abc123", "name": "T"}]},
        "concepts_abc123": {"data": []},
    }}
    result = plan_ontology(_local_with_ontology({"nodes": [], "edges": []}), export)
    assert result.ontology_change == "create"
    assert result.has_changes


def test_ontology_unchanged_ignores_server_derived_edge_id():
    # Server enriches edges with a derived `id`; a hand-authored edge omits it.
    server = '{"nodes": [{"id": "customer"}], "edges": [{"from": "customer", "to": "order", "label": "places", "id": "customer_places_order"}]}'
    export = {"project_id": "abc123", "scope": "user", "tables": {
        "projects_workspace_id": {"data": [{"project_id": "abc123", "name": "T"}]},
        "concepts_abc123": {"data": []},
        "ontology_schema_abc123": {"data": [{"ontology_schema_data": server}]},
    }}
    local = LocalOntology(
        slug="s", id="abc123", name="Demo", scope="user",
        ontology_schema={"nodes": [{"id": "customer"}], "edges": [{"from": "customer", "to": "order", "label": "places"}]},
    )
    result = plan_ontology(local, export)
    assert result.ontology_change == "unchanged"


def test_ontology_none_when_no_local_file(export_dict):
    # _local() builds a project with ontology_schema=None
    result = plan_ontology(_local([
        _concept("customer", "customer(Id, Name) :- source_customers(Id, Name)."),
        _concept("risk", "risk(Id) :- customer(Id, _)."),
    ]), export_dict)
    assert result.ontology_change is None


# ---- unit: sql/cypher source diff -----------------------------------------

def _sql_concept(pred, body):
    return LocalConcept(predicate=pred, concept_type="sql", body=body, meta={}, path=f"{pred}.sql")


def _sql_server_export(pred):
    return {"project_id": "abc123", "scope": "user", "tables": {
        "projects_workspace_id": {"data": [{"project_id": "abc123", "name": "P"}]},
        "concepts_abc123": {"data": [{
            "predicate_name": pred, "concept_type": "sql",
            "definition": f"{pred}(X) <- SELECT X FROM t.",
        }]},
    }}


def test_sql_unchanged_compares_source_not_rules():
    local = LocalOntology(slug="s", id="abc123", name="D", scope="user",
                         concepts=[_sql_concept("acme", "SELECT X FROM t")])
    result = plan_ontology(local, _sql_server_export("acme"),
                          server_sources={"acme": "SELECT X FROM t"})
    assert result.concept_changes[0].action == "unchanged"
    assert not result.has_changes


def test_sql_update_when_source_edited():
    local = LocalOntology(slug="s", id="abc123", name="D", scope="user",
                         concepts=[_sql_concept("acme", "SELECT X, Y FROM t")])
    result = plan_ontology(local, _sql_server_export("acme"),
                          server_sources={"acme": "SELECT X FROM t"})
    ch = result.concept_changes[0]
    assert ch.action == "update" and ch.definition_changed


# ---- unit: apps diff ------------------------------------------------------

def _app(identity, name, definition, has_id=True):
    return LocalApp(identity=identity, name=name, definition=definition, path=f"{name}.app.yaml", has_id=has_id)


def _local_with_apps(apps):
    return LocalOntology(slug="s", id="abc123", name="Demo", scope="user", apps=apps)


def _server_app(app_id, name, definition):
    return {"id": app_id, "name": name, "definition": definition}


def test_app_create_when_no_id_and_no_name_match():
    local = _local_with_apps([_app("New", "New", {"name": "New", "pages": []}, has_id=False)])
    result = plan_ontology(local, None, server_apps=[])
    assert [(a.name, a.action) for a in result.app_changes] == [("New", "create")]
    assert result.has_changes


def test_app_update_when_id_matches_and_definition_differs():
    server = [_server_app("a1", "Sales", {"id": "a1", "name": "Sales", "pages": [1]})]
    local = _local_with_apps([_app("a1", "Sales", {"id": "a1", "name": "Sales", "pages": [2]})])
    result = plan_ontology(local, None, server_apps=server)
    ch = result.app_changes[0]
    assert (ch.action, ch.server_id) == ("update", "a1")


def test_app_unchanged_ignores_id_and_schema_key():
    server = [_server_app("a1", "Sales", {"id": "a1", "name": "Sales", "pages": [1]})]
    # local has no id and a $schema-less definition (loader strips $schema); same content
    local = _local_with_apps([_app("Sales", "Sales", {"name": "Sales", "pages": [1]}, has_id=False)])
    result = plan_ontology(local, None, server_apps=server)
    ch = result.app_changes[0]
    assert (ch.action, ch.server_id) == ("unchanged", "a1")  # matched by name
    assert not result.has_changes


def test_app_delete_when_server_only():
    server = [_server_app("a1", "Ghost", {"id": "a1", "name": "Ghost"})]
    result = plan_ontology(_local_with_apps([]), None, server_apps=server)
    ch = result.app_changes[0]
    assert (ch.action, ch.server_id, ch.name) == ("delete", "a1", "Ghost")


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

    body = tmp_path / "ontologies" / "al-dente-supply-chain" / "concepts" / "customer.vadalog"
    body.write_text(body.read_text() + "\ncustomer(Id, Name) :- extra(Id, Name).\n")

    result = runner.invoke(cli, ["plan", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "~ concept customer" in result.output
    assert "cascades to downstream" in result.output
    assert "risk" in result.output
