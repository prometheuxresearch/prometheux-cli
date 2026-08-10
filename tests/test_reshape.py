import yaml

from prometheux_cli.reshape import reshape_project


def test_reshape_produces_expected_tree(export_dict):
    result = reshape_project(export_dict, project_name="Al Dente Supply Chain", slug="al-dente")
    paths = {f.path: f.content for f in result.files}

    assert "projects/al-dente/prometheux.yaml" in paths
    assert "projects/al-dente/concepts/customer.vadalog" in paths
    assert "projects/al-dente/concepts/customer.meta.yaml" in paths
    assert "projects/al-dente/concepts/risk.vadalog" in paths
    assert "projects/al-dente/datasources/snowflake_prod.yaml" in paths
    assert "projects/al-dente/ontology/schema.yaml" in paths


def test_reshape_body_is_faithful(export_dict):
    result = reshape_project(export_dict, "n", "s")
    body = {f.path: f.content for f in result.files}["projects/s/concepts/customer.vadalog"]
    assert body.startswith("customer(Id, Name) :- source_customers(Id, Name).")


def _sql_export():
    pid = "p1"
    return {
        "project_id": pid, "scope": "user",
        "tables": {
            "projects_workspace_id": {"data": [{"project_id": pid, "name": "P"}]},
            f"concepts_{pid}": {"data": [{
                "predicate_name": "acme",
                "concept_type": "sql",
                # server stores the transpiled `head <- SQL.` rule
                "rules": "acme(Id, Name) <- SELECT Id, Name FROM customer WHERE Name = 'Acme'.",
            }]},
        },
    }


def test_reshape_sql_body_uses_recovered_source():
    export = _sql_export()
    sources = {"acme": "SELECT Id, Name FROM customer WHERE Name = 'Acme'"}
    result = reshape_project(export, "n", "s", sources=sources)
    files = {f.path: f.content for f in result.files}
    body = files["projects/s/concepts/acme.sql"]
    assert body.strip() == "SELECT Id, Name FROM customer WHERE Name = 'Acme'"
    assert "<-" not in body  # the transpiled Vadalog is NOT written
    assert not result.warnings  # source recovered cleanly


def test_reshape_sql_warns_when_source_missing():
    export = _sql_export()
    result = reshape_project(export, "n", "s")  # no sources map
    files = {f.path: f.content for f in result.files}
    assert "<-" in files["projects/s/concepts/acme.sql"]  # falls back to transpiled rule
    assert any("source could not be recovered" in w for w in result.warnings)


def _generative_export(concept_row):
    pid = "p1"
    return {"project_id": pid, "scope": "user", "tables": {
        "projects_workspace_id": {"data": [{"project_id": pid, "name": "P"}]},
        f"concepts_{pid}": {"data": [concept_row]},
    }}


def test_reshape_llm_captures_llmconfig():
    row = {
        "predicate_name": "summary", "concept_type": "llm",
        "rules": "Summarize {{ customer }}.",
        "concept_config": {"output_columns": [{"name": "Id", "type": "string"}],
                           "provider": None, "model": None, "temperature": None},
    }
    result = reshape_project(_generative_export(row), "n", "s")
    files = {f.path: f.content for f in result.files}
    md = files["projects/s/concepts/summary.llm.md"]
    assert "Summarize {{ customer }}." in md
    fm = yaml.safe_load(md.split("---")[1])
    assert fm["conceptType"] == "llm"
    assert fm["llmConfig"]["output_columns"][0]["name"] == "Id"
    assert "provider" not in fm["llmConfig"]  # null fields dropped


def test_reshape_context_dynamic_captures_query():
    row = {"predicate_name": "policy", "concept_type": "context",
           "concept_config": {"mode": "dynamic", "query": "risk policy", "top_k": 5, "kinds": None}}
    result = reshape_project(_generative_export(row), "n", "s")
    doc = yaml.safe_load({f.path: f.content for f in result.files}["projects/s/concepts/policy.context.yaml"])
    assert doc == {"conceptType": "context", "outputPredicate": "policy",
                   "contextMode": "dynamic", "query": "risk policy", "top_k": 5}


def test_reshape_context_static_captures_note_ids():
    row = {"predicate_name": "pinned", "concept_type": "context",
           "concept_config": {"mode": "static", "note_ids": ["n1", "n2"]}}
    result = reshape_project(_generative_export(row), "n", "s")
    doc = yaml.safe_load({f.path: f.content for f in result.files}["projects/s/concepts/pinned.context.yaml"])
    assert doc["contextMode"] == "static" and doc["noteIds"] == ["n1", "n2"]


def test_reshape_meta_fields_and_annotations(export_dict):
    result = reshape_project(export_dict, "n", "s")
    meta = yaml.safe_load(
        {f.path: f.content for f in result.files}["projects/s/concepts/customer.meta.yaml"]
    )
    assert meta["conceptType"] == "logic"
    assert meta["outputPredicate"] == "customer"
    assert meta["group"] == "ingest"
    assert {"name": "Id", "type": "string"} in meta["fields"]
    # bind_annotations preserved verbatim (parsed from JSON) under annotations.
    assert meta["annotations"]["bind_annotations"]["input"] == []


def test_reshape_drops_group_id_sentinel(export_dict):
    result = reshape_project(export_dict, "n", "s")
    meta = yaml.safe_load(
        {f.path: f.content for f in result.files}["projects/s/concepts/risk.meta.yaml"]
    )
    assert "group" not in meta  # 'group_id' is the server default, not a real group


def test_reshape_never_serializes_secrets(export_dict):
    result = reshape_project(export_dict, "n", "s")
    ds = {f.path: f.content for f in result.files}["projects/s/datasources/snowflake_prod.yaml"]
    assert "SUPER_SECRET" not in ds
    assert "password" not in ds
    assert "connection_params" not in ds
    assert "type: snowflake" in ds


# ── the body column rename: `rules` → `definition` ─────────────────────────
# px is installed separately from the server it talks to, so a pinned CLI meets
# an upgraded server and vice versa. Both spellings have to keep working. The
# fixtures above still use the legacy name, which covers that half.

def _body_export(concept_row: dict) -> dict:
    pid = "p1"
    return {
        "project_id": pid, "scope": "user",
        "tables": {
            "projects_workspace_id": {"data": [{"project_id": pid, "name": "P"}]},
            f"concepts_{pid}": {"data": [concept_row]},
        },
    }


def test_reshape_reads_the_current_body_column():
    export = _body_export({
        "predicate_name": "customer",
        "concept_type": "logic",
        "definition": "customer(Id) :- source(Id).",
    })
    files = {f.path: f.content for f in reshape_project(export, "n", "s").files}
    assert files["projects/s/concepts/customer.vadalog"].strip() == "customer(Id) :- source(Id)."


def test_reshape_still_reads_a_pre_rename_server():
    export = _body_export({
        "predicate_name": "customer",
        "concept_type": "logic",
        "rules": "customer(Id) :- source(Id).",
    })
    files = {f.path: f.content for f in reshape_project(export, "n", "s").files}
    assert files["projects/s/concepts/customer.vadalog"].strip() == "customer(Id) :- source(Id)."


def test_an_llm_prompt_survives_either_spelling():
    for column in ("definition", "rules"):
        export = _body_export({
            "predicate_name": "summary",
            "concept_type": "llm",
            column: "Summarize {{ customer }}.",
        })
        files = {f.path: f.content for f in reshape_project(export, "n", "s").files}
        assert "Summarize {{ customer }}." in files["projects/s/concepts/summary.llm.md"]
