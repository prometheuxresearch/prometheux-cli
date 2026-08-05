"""Shared test fixtures: a realistic project export dict."""

import pytest


@pytest.fixture
def export_dict():
    """A minimal but realistic export, shaped like prometheux_chain.export_ontology."""
    pid = "abc123"
    return {
        "project_id": pid,
        "scope": "user",
        "tables": {
            "user_migrations": {"schema": [], "data": [{"x": 1}], "row_count": 1},
            "projects_workspace_id": {
                "schema": [],
                "data": [{"project_id": pid, "name": "Al Dente Supply Chain", "scope": "user"}],
                "row_count": 1,
            },
            "datasources_workspace_id": {
                "schema": [],
                "data": [
                    {
                        "datasource_id": "snowflake_prod",
                        "datasource_type": "snowflake",
                        "host": "acme.snowflakecomputing.com",
                        "database_name": "PROD",
                        "username": "svc_user",
                        "password": "SUPER_SECRET",
                        "connection_params": "{'token': 'xyz'}",
                    }
                ],
                "row_count": 1,
            },
            f"ontology_schema_{pid}": {
                "schema": [],
                "data": [{"id": f"ontology_schema_{pid}", "ontology_schema_data": '{"nodes": [], "edges": []}'}],
                "row_count": 1,
            },
            f"concepts_{pid}": {
                "schema": [],
                "data": [
                    {
                        "predicate_name": "customer",
                        "concept_type": "logic",
                        "rules": "customer(Id, Name) :- source_customers(Id, Name).",
                        "fields": '{"Id": "string", "Name": "string"}',
                        "bind_annotations": '{"input": [], "output": "@bind(\\"customer\\",\\"parquet\\",\\"disk/results/abc123\\",\\"customer\\")"}',
                        "param_annotations": "",
                        "post_annotations": "",
                        "model_annotation": "",
                        "concept_group": "ingest",
                        "description": "Ingest customers.",
                        "is_populated": "true",
                        "author": "devuser",
                    },
                    {
                        "predicate_name": "risk",
                        "concept_type": "logic",
                        "rules": "risk(Id) :- customer(Id, _).",
                        "fields": '{"Id": "string"}',
                        "bind_annotations": "",
                        "concept_group": "group_id",
                        "description": "",
                    },
                ],
                "row_count": 2,
            },
        },
    }
