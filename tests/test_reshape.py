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
