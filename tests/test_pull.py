from pathlib import Path

import pytest
from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli


class _FakePx:
    """Only `px pull`'s non-tree calls: listing, and file download for --with-files."""

    def list_ontologies(self):
        return [{"id": "abc123", "name": "Al Dente Supply Chain"}]


def _wire(monkeypatch):
    monkeypatch.setattr(
        cli_module.pull_cmd, "connected_sdk", lambda **k: (_FakePx(), "http://x", "tok")
    )


def test_pull_writes_and_validates(tmp_path: Path, monkeypatch, pulls_tree):
    _wire(monkeypatch)

    runner = CliRunner()
    result = runner.invoke(cli, ["pull", "abc123", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output

    base = tmp_path / "ontologies" / "al-dente-supply-chain"
    assert (base / "concepts" / "customer.vadalog").is_file()
    assert (base / "datasources" / "snowflake_prod.yaml").is_file()
    assert (tmp_path / "prometheux.workspace.yaml").is_file()
    assert (tmp_path / ".px" / "schemas" / "workspace.schema.json").is_file()

    # A freshly pulled workspace must pass offline validation.
    v = runner.invoke(cli, ["validate", str(tmp_path)])
    assert v.exit_code == 0, v.output
    assert "PASS" in v.output


def _edit_file(tree: dict, suffix: str, edit) -> None:
    entry = next(e for e in tree["files"] if e["path"].endswith(suffix))
    entry["content"] = edit(entry["content"])


def test_pull_validates_every_field_the_server_writes(tmp_path: Path, monkeypatch, pulls_tree):
    """The fields the platform writes only on some ontologies must validate too.

    The recorded tree predates them, and these schemas reject unknown keys: a
    platform field missing here fails `px validate` on every pull that carries it.
    """
    _wire(monkeypatch)
    _edit_file(pulls_tree, "/prometheux.yaml", lambda c: c.replace(
        "  name: Al Dente Supply Chain\n",
        "  name: Al Dente Supply Chain\n  description: Supplier risk across the chain\n"))
    _edit_file(pulls_tree, "/customer.meta.yaml", lambda c: c + "refreshMode: checkpoint\n")
    _edit_file(pulls_tree, "/risk.meta.yaml", lambda c: c + "refreshMode: always\n")

    runner = CliRunner()
    result = runner.invoke(cli, ["pull", "abc123", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output

    v = runner.invoke(cli, ["validate", str(tmp_path)])
    assert v.exit_code == 0, v.output


def test_pull_writes_apps_and_counts_them_separately(tmp_path: Path, monkeypatch, tree_response):
    """Apps land under apps/, and the summary counts them apart from the file total."""
    _wire(monkeypatch)
    plain = len(tree_response["files"])
    tree_response["files"].append({
        "path": "ontologies/al-dente-supply-chain/apps/ops-dash.app.yaml",
        "content": "id: a1\nname: Ops Dash\n",
    })
    monkeypatch.setattr(cli_module.pull_cmd, "_fetch_tree", lambda *a, **k: tree_response)

    result = CliRunner().invoke(cli, ["pull", "abc123", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "ontologies" / "al-dente-supply-chain" / "apps" / "ops-dash.app.yaml").is_file()
    assert f"{plain} file(s) + 1 app(s)" in result.output


def test_pull_no_project_lists(tmp_path: Path, monkeypatch):
    _wire(monkeypatch)
    result = CliRunner().invoke(cli, ["pull", "--out", str(tmp_path)])
    assert result.exit_code == 0
    assert "abc123" in result.output


def test_pull_keeps_local_workspace_and_schemas(tmp_path: Path, monkeypatch, tree_response):
    """The server's workspace manifest and schemas never overwrite the local ones.

    A manifest listing other ontologies must survive a second pull, and `px validate`
    has to read the schemas this CLI ships rather than whatever the server bundles.
    """
    _wire(monkeypatch)
    tree_response["files"].extend([
        {"path": "prometheux.workspace.yaml", "content": "workspace:\n  name: SERVER-SIDE\n"},
        {"path": ".px/schemas/workspace.schema.json", "content": "{}"},
    ])
    monkeypatch.setattr(cli_module.pull_cmd, "_fetch_tree", lambda *a, **k: tree_response)

    CliRunner().invoke(cli, ["pull", "abc123", "--out", str(tmp_path)])

    manifest = (tmp_path / "prometheux.workspace.yaml").read_text()
    assert "SERVER-SIDE" not in manifest
    assert "./ontologies/al-dente-supply-chain" in manifest
    assert (tmp_path / ".px" / "schemas" / "workspace.schema.json").read_text() != "{}"


def test_pull_sends_the_slug_override(tmp_path: Path, monkeypatch, tree_response):
    _wire(monkeypatch)
    seen = {}

    def _fetch(px, ontology, slug):
        seen.update({"ontology_id": ontology, "slug": slug})
        return tree_response

    monkeypatch.setattr(cli_module.pull_cmd, "_fetch_tree", _fetch)

    result = CliRunner().invoke(
        cli, ["pull", "abc123", "--out", str(tmp_path), "--slug", "custom"]
    )
    assert result.exit_code == 0, result.output
    assert seen == {"ontology_id": "abc123", "slug": "custom"}


def test_pull_goes_through_the_sdk(tmp_path: Path, monkeypatch, tree_response):
    """No raw REST: the tree comes from the SDK's export_tree."""
    calls = []

    class _TreePx(_FakePx):
        def export_tree(self, ontology_id, slug=None):
            calls.append((ontology_id, slug))
            return tree_response

    monkeypatch.setattr(
        cli_module.pull_cmd, "connected_sdk", lambda **k: (_TreePx(), "http://x", "tok")
    )

    result = CliRunner().invoke(cli, ["pull", "abc123", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert calls == [("abc123", None)]


def test_pull_drops_the_servers_context_files(tmp_path: Path, monkeypatch, tree_response):
    """`px pull` writes the ontology's notes itself, seeding the context-state.

    Keeping the server's copy too would leave two manifests over the same notes,
    and `px context apply` would create each note twice.
    """
    _wire(monkeypatch)
    base = "ontologies/al-dente-supply-chain"
    tree_response["files"].extend([
        {"path": f"{base}/context/notes.context.md", "content": "---\nscope: project\n---\n"},
        {"path": f"{base}/context/policy.md", "content": "# Policy\n"},
    ])
    monkeypatch.setattr(cli_module.pull_cmd, "_fetch_tree", lambda *a, **k: tree_response)

    result = CliRunner().invoke(cli, ["pull", "abc123", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / base / "context" / "notes.context.md").exists()
    assert not (tmp_path / base / "context" / "policy.md").exists()
    assert (tmp_path / base / "concepts" / "customer.vadalog").is_file()


def test_pull_reports_a_server_without_the_route(tmp_path: Path, monkeypatch):
    """A 404 means the platform is too old — say so, don't leak a bare "Not Found"."""
    _wire(monkeypatch)

    def _absent(*a, **k):
        raise Exception("Not Found: The requested resource was not found.")

    monkeypatch.setattr(cli_module.pull_cmd, "_fetch_tree", _absent)

    result = CliRunner().invoke(cli, ["pull", "abc123", "--out", str(tmp_path)])
    assert result.exit_code == 1
    assert "no /ontologies/export-tree route" in result.output
    assert "Update the platform at http://x" in result.output
    assert not (tmp_path / "ontologies").exists()


@pytest.mark.parametrize("message", [
    "HTTP Error 400: Export Tree: Ontology 'nope' not found",
    "Unauthorized: Invalid or expired token. Please check your PMTX_TOKEN.",
    "Connection refused",
])
def test_pull_passes_a_real_failure_through(tmp_path: Path, monkeypatch, message):
    """Anything that isn't a missing route is reported as itself, not as a version problem."""
    _wire(monkeypatch)

    def _fail(*a, **k):
        raise Exception(message)

    monkeypatch.setattr(cli_module.pull_cmd, "_fetch_tree", _fail)

    result = CliRunner().invoke(cli, ["pull", "abc123", "--out", str(tmp_path)])
    assert result.exit_code == 1
    assert message in result.output
    assert "export-tree route" not in result.output
