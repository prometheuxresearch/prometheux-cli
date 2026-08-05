import pytest

from prometheux_cli.datasources import (
    SecretError,
    database_kwargs,
    file_database_kwargs,
    is_file_based,
    resolve_secrets,
)


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
    assert kw["options"] == {"warehouse": "WH", "account": "acme"}
    assert "name" not in kw and "$schema" not in kw


def test_file_database_kwargs():
    kw = file_database_kwargs("csv", "disk/uploads/customers.csv", "customers.csv")
    assert kw["database_type"] == "csv"
    assert kw["host"] == "disk/uploads"
    assert kw["database_name"] == "customers.csv"
