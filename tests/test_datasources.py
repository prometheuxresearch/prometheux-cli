import pytest

from prometheux_cli.datasources import (
    SecretError,
    bind_template_from_sources,
    database_kwargs,
    file_database_kwargs,
    is_file_based,
    resolve_secrets,
    rewrite_bind_predicate,
)


def test_rewrite_bind_predicate():
    t = '@bind("people_csv","csv useHeaders=\'true\'","disk","people.csv").'
    out = rewrite_bind_predicate(t, "people_raw")
    assert out == '@bind("people_raw","csv useHeaders=\'true\'","disk","people.csv").'


def test_bind_template_from_sources_matches_filename():
    sources = [
        {"table_name": "a.csv", "bind_annotation": "@bind(\"a\",...)."},
        {"table_name": "people.csv", "bind_annotation": "@bind(\"people\",...)."},
    ]
    assert bind_template_from_sources(sources, "people.csv") == "@bind(\"people\",...)."
    assert bind_template_from_sources(sources) == "@bind(\"a\",...)."  # first by default
    assert bind_template_from_sources([]) is None


def test_is_file_based():
    assert is_file_based("csv")
    assert is_file_based("PARQUET")
    assert not is_file_based("snowflake")


def test_resolve_secrets_success():
    spec = {"type": "snowflake", "account": "${ACC}", "password": "${PW}"}
    out = resolve_secrets(spec, {"ACC": "acme", "PW": "s3cret"})
    assert out["account"] == "acme"
    assert out["password"] == "s3cret"
    # original is untouched
    assert spec["account"] == "${ACC}"


def test_resolve_secrets_missing_lists_all():
    spec = {"a": "${X}", "b": "${Y}", "c": "literal"}
    with pytest.raises(SecretError) as exc:
        resolve_secrets(spec, {})
    assert "X" in str(exc.value) and "Y" in str(exc.value)


def test_database_kwargs_maps_and_bundles_extras():
    spec = {
        "$schema": "x",
        "name": "sf",
        "type": "snowflake",
        "host": "acme.snowflake",
        "port": 443,
        "database": "PROD",
        "warehouse": "WH",   # unknown -> options
        "account": "acme",   # unknown -> options
    }
    kw = database_kwargs(spec)
    assert kw["database_type"] == "snowflake"
    assert kw["host"] == "acme.snowflake"
    assert kw["database_name"] == "PROD"
    assert kw["port"] == 443
    assert kw["options"] == {"warehouse": "WH", "account": "acme"}
    assert "name" not in kw and "$schema" not in kw


def test_database_kwargs_defaults_port_when_absent():
    # A null port makes the data manager 400, so it must default to 0.
    kw = database_kwargs({"type": "postgres", "host": "h", "database": "db"})
    assert kw["port"] == 0


def test_file_database_kwargs():
    kw = file_database_kwargs("csv", "disk/uploads/customers.csv", "customers.csv")
    assert kw["database_type"] == "csv"
    assert kw["host"] == "disk/uploads"
    assert kw["database_name"] == "customers.csv"
    assert kw["port"] == 0
