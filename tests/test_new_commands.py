"""Tests for the MCP-parity commands: list concepts, context search, snapshot,
policy, template, datasource, app, query, search, playbook, compute lifecycle."""

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli


class _FakePx:
    def __init__(self):
        self.calls = []

    # concepts / context
    def list_concepts(self, ontology_id):
        return [{"predicate_name": "customer", "concept_type": "logic",
                 "group": "g", "is_populated": True}]

    def search_context_notes(self, query, scope, scope_id=None, kinds=None, top_k=10):
        return [{"id": "n1", "kind": "fact", "text": "hello world"}]

    # snapshots
    def list_snapshots(self, ontology_id):
        return [{"id": "snap1", "created_at": "2026-01-01T00:00:00", "description": "d"}]

    def create_snapshot(self, ontology_id, description=None):
        self.calls.append(("create_snapshot", ontology_id)); return {"id": "snapNEW"}

    def restore_snapshot(self, snapshot_id, ontology_id, create_safety_snapshot=True):
        self.calls.append(("restore", snapshot_id, create_safety_snapshot))

    def delete_snapshot(self, snapshot_id, ontology_id):
        self.calls.append(("delete_snapshot", snapshot_id))

    # policies
    def list_policies(self, ontology_id, concept_name=None):
        return [{"id": "p1", "enabled": True, "trigger_type": "cron", "concept_name": "customer"}]

    def create_policy(self, ontology_id, concept_name, trigger_type="cron",
                      trigger_config=None, enabled=True):
        self.calls.append(("create_policy", concept_name, trigger_type, trigger_config, enabled))
        return {"id": "pNEW"}

    def trigger_policy(self, ontology_id, policy_id):
        self.calls.append(("trigger", policy_id))

    def get_run_history(self, ontology_id, policy_id, limit=50, offset=0):
        return {"runs": [{"created_at": "2026-01-01T00:00:00", "status": "success"}], "count": 1}

    # templates
    def list_templates(self):
        return [{"id": "t1", "name": "Al Dente"}]

    def import_template(self, template_id, new_ontology_name=None, ontology_compute=None):
        self.calls.append(("import", template_id, new_ontology_name)); return {"id": "ontNEW"}

    # datasources
    def preview_datasource(self, bind_annotation, limit=10, **kw):
        return {"facts": [[1, 2]], "columnNames": ["a", "b"]}

    def list_sources(self):
        return [{"id": "ds1", "bind_annotation": '@bind("p","csv","h","t").',
                 "predicate_placeholder": "p"}]

    def cleanup_sources(self, source_ids=None):
        self.calls.append(("cleanup_sources", source_ids))

    def query_concept(self, ontology_id, concept_name, sql, compute=None):
        return {"results": {"columnNames": ["n"], "facts": [[5]]}, "row_count": 1}

    def search_similar_concepts(self, query, top_k=0, exclude_ontology_id=None):
        return {"matches": [{"concept_name": "company", "ontology_name": "O", "similarity": 0.4}]}

    def get_company_info(self, query):
        return {"content": "about prometheux"}

    def list_skills(self):
        return {"skills": [{"id": "author-concept", "name": "Author a concept"}]}

    def get_skill(self, skill_id):
        return {"id": skill_id, "name": "Author a concept", "body": "steps"}

    def publish_app(self, ontology_id, app_id):
        self.calls.append(("publish", ontology_id, app_id))

    def unpublish_app(self, ontology_id, app_id):
        self.calls.append(("unpublish", ontology_id, app_id))

    def use_machine(self, machine_id, machine_name=None):
        self.calls.append(("use_machine", machine_id, machine_name))
        return {"data": {"user_machine": {"id": "um1"}}}

    def validate_concept(self, definition=None, concept_type=None, concept_name=None,
                         ontology_id=None):
        self.calls.append(("validate_concept", concept_name, concept_type, ontology_id))
        return {"valid": True}

    def delete_user_machine(self, user_machine_id):
        self.calls.append(("delete_user_machine", user_machine_id))

    # compute
    def list_machines_combined(self):
        return {"machines": [{"id": "m1", "name": "PX_4_16"}],
                "user_machines_enabled": []}


def _wire_sdk(monkeypatch, module, fake=None):
    fake = fake or _FakePx()
    monkeypatch.setattr(module, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    return fake


R = CliRunner()


def test_list_concepts(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.list_cmd)
    out = R.invoke(cli, ["list", "concepts", "--ontology", "abc"])
    assert out.exit_code == 0, out.output
    assert "customer" in out.output and "logic" in out.output


def test_context_search(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.context_cmd)
    out = R.invoke(cli, ["context", "search", "hello"])
    assert out.exit_code == 0, out.output
    assert "n1" in out.output and "hello world" in out.output


def test_snapshot_list_and_create(monkeypatch):
    fake = _wire_sdk(monkeypatch, cli_module.snapshot_cmd)
    assert "snap1" in R.invoke(cli, ["snapshot", "list", "abc"]).output
    out = R.invoke(cli, ["snapshot", "create", "abc", "-d", "x"])
    assert out.exit_code == 0 and "snapNEW" in out.output


def test_snapshot_restore_needs_confirm(monkeypatch):
    fake = _wire_sdk(monkeypatch, cli_module.snapshot_cmd)
    aborted = R.invoke(cli, ["snapshot", "restore", "abc", "snap1"], input="n\n")
    assert aborted.exit_code == 1 and fake.calls == []
    ok = R.invoke(cli, ["snapshot", "restore", "abc", "snap1", "--yes"])
    assert ok.exit_code == 0 and ("restore", "snap1", True) in fake.calls


def test_policy_list_create_trigger(monkeypatch):
    fake = _wire_sdk(monkeypatch, cli_module.policy_cmd)
    assert "p1" in R.invoke(cli, ["policy", "list", "abc"]).output
    out = R.invoke(cli, ["policy", "create", "abc", "customer", "--cron", "0 0 * * *"])
    assert out.exit_code == 0 and ("create_policy", "customer", "cron", {"cron": "0 0 * * *"}, True) in fake.calls
    assert R.invoke(cli, ["policy", "trigger", "abc", "p1"]).exit_code == 0


def test_policy_runs(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.policy_cmd)
    out = R.invoke(cli, ["policy", "runs", "abc", "p1"])
    assert out.exit_code == 0 and "success" in out.output


def test_template_list_import(monkeypatch):
    fake = _wire_sdk(monkeypatch, cli_module.template_cmd)
    assert "Al Dente" in R.invoke(cli, ["template", "list"]).output
    out = R.invoke(cli, ["template", "import", "t1", "--name", "Mine"])
    assert out.exit_code == 0 and ("import", "t1", "Mine") in fake.calls and "ontNEW" in out.output


def test_datasource_preview_and_delete(monkeypatch):
    fake = _wire_sdk(monkeypatch, cli_module.datasource_cmd)
    assert R.invoke(cli, ["datasource", "preview", '@bind("p","csv","h","t").']).exit_code == 0
    out = R.invoke(cli, ["datasource", "delete", "p", "--yes"])  # resolve by predicate placeholder
    assert out.exit_code == 0, out.output
    assert ("cleanup_sources", ["ds1"]) in fake.calls


def test_app_publish(monkeypatch):
    fake = _wire_sdk(monkeypatch, cli_module.app_cmd)
    out = R.invoke(cli, ["app", "publish", "ont1", "app1"])
    assert out.exit_code == 0 and ("publish", "ont1", "app1") in fake.calls


def test_app_unpublish(monkeypatch):
    fake = _wire_sdk(monkeypatch, cli_module.app_cmd)
    out = R.invoke(cli, ["app", "unpublish", "ont1", "app1"])
    assert out.exit_code == 0, out.output
    assert ("unpublish", "ont1", "app1") in fake.calls


def test_query(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.query_cmd)
    out = R.invoke(cli, ["query", "ont1", "tx", "SELECT count(*) AS n FROM tx"])
    assert out.exit_code == 0 and "5" in out.output


def test_search_concepts(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.search_cmd)
    out = R.invoke(cli, ["search", "concepts", "companies"])
    assert out.exit_code == 0 and "company" in out.output


def test_search_company(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.search_cmd)
    out = R.invoke(cli, ["search", "company", "what is prometheux"])
    assert out.exit_code == 0, out.output
    assert "about prometheux" in out.output


def test_playbook_list(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.playbook_cmd)
    out = R.invoke(cli, ["playbook", "list"])
    assert out.exit_code == 0 and "author-concept" in out.output


def test_playbook_show(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.playbook_cmd)
    out = R.invoke(cli, ["playbook", "show", "author-concept"])
    assert out.exit_code == 0, out.output
    assert "Author a concept" in out.output
    assert "steps" in out.output


def test_compute_catalog(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.compute_cmd)
    out = R.invoke(cli, ["compute", "catalog"])
    assert out.exit_code == 0 and "PX_4_16" in out.output


def test_compute_provision(monkeypatch):
    fake = _wire_sdk(monkeypatch, cli_module.compute_cmd)
    out = R.invoke(cli, ["compute", "provision", "m1", "--name", "mine"])
    assert out.exit_code == 0, out.output
    assert ("use_machine", "m1", "mine") in fake.calls
    assert "um1" in out.output


def test_compute_remove(monkeypatch):
    fake = _wire_sdk(monkeypatch, cli_module.compute_cmd)
    aborted = R.invoke(cli, ["compute", "remove", "um1"], input="n\n")
    assert aborted.exit_code == 1 and fake.calls == []
    ok = R.invoke(cli, ["compute", "remove", "um1", "--yes"])
    assert ok.exit_code == 0, ok.output
    assert ("delete_user_machine", "um1") in fake.calls
