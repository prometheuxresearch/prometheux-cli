"""Shared test fixtures: an ontology as the server hands it over, both ways.

``export_dict`` is the raw export blob `px plan` / `px apply` diff against.
``tree_response`` is what ``/ontologies/export-tree`` returns for that same
ontology — recorded from the real server engine, since the CLI no longer builds
trees itself and hand-writing one would only encode our assumptions about it.
"""

import json
from pathlib import Path

import pytest

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tree_response():
    """A recorded ``/export-tree`` response for the `export_dict` ontology."""
    return json.loads((_FIXTURES / "export_tree_response.json").read_text("utf-8"))


@pytest.fixture
def pulls_tree(monkeypatch, tree_response):
    """Make `px pull` return the recorded tree instead of calling a server."""
    from prometheux_cli.commands import pull as pull_cmd

    monkeypatch.setattr(pull_cmd, "rest_data", lambda *a, **k: tree_response)
    return tree_response


@pytest.fixture
def export_dict():
    """A minimal but realistic export, shaped like prometheux_chain.export_ontology."""
    pid = "abc123"
    return {
        "ontology_id": pid,
        "tables": {
            "user_migrations": {"schema": [], "data": [{"x": 1}], "row_count": 1},
            "ontologies_workspace_id": {
                "schema": [],
                "data": [{"ontology_id": pid, "name": "Al Dente Supply Chain"}],
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
                        "definition": "customer(Id, Name) :- source_customers(Id, Name).",
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
                        "definition": "risk(Id) :- customer(Id, _).",
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
