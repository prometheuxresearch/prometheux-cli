"""Tests for the MCP-parity commands: list concepts, context search, snapshot,
policy, template, datasource, app, query, search, playbook, compute lifecycle."""

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli


class _FakePx:
    def __init__(self):
        self.calls = []

    # concepts / context
    def list_concepts(self, ontology_id, scope="user"):
        return [{"predicate_name": "customer", "concept_type": "logic",
                 "group": "g", "is_populated": True}]

    def search_context_notes(self, query, scope, scope_id=None, kinds=None, top_k=10):
        return [{"id": "n1", "kind": "fact", "text": "hello world"}]

    # snapshots
    def list_snapshots(self, ontology_id, scope="user"):
        return [{"id": "snap1", "created_at": "2026-01-01T00:00:00", "description": "d"}]

    def create_snapshot(self, ontology_id, scope="user", description=None):
        self.calls.append(("create_snapshot", ontology_id)); return {"id": "snapNEW"}

    def restore_snapshot(self, snapshot_id, ontology_id, scope="user", create_safety_snapshot=True):
        self.calls.append(("restore", snapshot_id, create_safety_snapshot))

    def delete_snapshot(self, snapshot_id, ontology_id, scope="user"):
        self.calls.append(("delete_snapshot", snapshot_id))

    # policies
    def list_policies(self, ontology_id, scope="user", concept_name=None):
        return [{"id": "p1", "enabled": True, "trigger_type": "cron", "concept_name": "customer"}]

    def create_policy(self, ontology_id, concept_name, trigger_type="cron",
                      trigger_config=None, scope="user", enabled=True):
        self.calls.append(("create_policy", concept_name, trigger_type, trigger_config, enabled))
        return {"id": "pNEW"}

    def trigger_policy(self, ontology_id, policy_id, scope="user"):
        self.calls.append(("trigger", policy_id))

    # templates
    def list_templates(self):
        return [{"id": "t1", "name": "Al Dente"}]

    def import_template(self, template_id, new_ontology_name=None, ontology_scope="user", compute=None):
        self.calls.append(("import", template_id, new_ontology_name)); return {"id": "ontNEW"}

    # datasources
    def preview_datasource(self, bind_annotation, scope="user", limit=10, **kw):
        return {"facts": [[1, 2]], "columnNames": ["a", "b"]}

    def list_sources(self, scope="user"):
        return [{"id": "ds1", "bind_annotation": '@bind("p","csv","h","t").',
                 "predicate_placeholder": "p"}]

    # compute
    def list_machines_combined(self):
        return {"machines": [{"id": "m1", "name": "PX_4_16"}],
                "user_machines_enabled": []}


def _wire_sdk(monkeypatch, module, fake=None):
    fake = fake or _FakePx()
    monkeypatch.setattr(module, "connected_sdk", lambda **k: (fake, "http://x", "t"))
    return fake


def _wire_rest(monkeypatch, module, payload):
    monkeypatch.setattr(module, "rest_data", lambda *a, **k: payload)


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


def test_policy_runs_rest(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.policy_cmd)
    _wire_rest(monkeypatch, cli_module.policy_cmd,
               {"runs": [{"created_at": "2026-01-01T00:00:00", "status": "success"}], "count": 1})
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
    captured = {}
    monkeypatch.setattr(cli_module.datasource_cmd, "rest_data",
                        lambda m, p, **k: captured.update(k) or {"deleted_count": 1})
    out = R.invoke(cli, ["datasource", "delete", "p", "--yes"])  # resolve by predicate placeholder
    assert out.exit_code == 0, out.output
    assert captured["json"]["source_ids"] == ["ds1"]


def test_app_publish(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.app_cmd)
    seen = {}
    monkeypatch.setattr(cli_module.app_cmd, "rest_data", lambda m, p, **k: seen.update({"path": p}))
    out = R.invoke(cli, ["app", "publish", "ont1", "app1"])
    assert out.exit_code == 0 and seen["path"].endswith("/ont1/app1/publish")


def test_query(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.query_cmd)
    _wire_rest(monkeypatch, cli_module.query_cmd,
               {"results": {"columnNames": ["n"], "facts": [[5]]}, "row_count": 1})
    out = R.invoke(cli, ["query", "ont1", "tx", "SELECT count(*) AS n FROM tx"])
    assert out.exit_code == 0 and "5" in out.output


def test_search_concepts(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.search_cmd)
    _wire_rest(monkeypatch, cli_module.search_cmd,
               {"matches": [{"concept_name": "company", "ontology_name": "O", "similarity": 0.4}]})
    out = R.invoke(cli, ["search", "concepts", "companies"])
    assert out.exit_code == 0 and "company" in out.output


def test_playbook_list(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.playbook_cmd)
    _wire_rest(monkeypatch, cli_module.playbook_cmd,
               {"skills": [{"id": "author-concept", "name": "Author a concept"}]})
    out = R.invoke(cli, ["playbook", "list"])
    assert out.exit_code == 0 and "author-concept" in out.output


def test_compute_catalog(monkeypatch):
    _wire_sdk(monkeypatch, cli_module.compute_cmd)
    out = R.invoke(cli, ["compute", "catalog"])
    assert out.exit_code == 0 and "PX_4_16" in out.output
