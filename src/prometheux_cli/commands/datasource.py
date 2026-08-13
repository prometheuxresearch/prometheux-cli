"""`px datasource` — inspect and disconnect connected data sources.

Connecting datasources is declarative (`datasources/*.yaml` + `px apply`); these
subcommands cover the imperative reads/removals that `apply` doesn't: previewing
rows and disconnecting a source.
"""

from __future__ import annotations

import json as _json
import sys

import click

from ..sdk import SdkError, connected_sdk, rest_data

_SCOPE = click.option("--scope", default="user", type=click.Choice(["user", "organization"]))


@click.group()
def datasource() -> None:
    """Inspect and disconnect data sources (preview / delete)."""


def _connect():
    try:
        return connected_sdk(require_token=True)
    except SdkError as exc:
        _fail(str(exc))


def _fail(msg: str) -> None:
    click.echo(click.style("FAIL", fg="red", bold=True) + f": {msg}", err=True)
    sys.exit(1)


@datasource.command("preview")
@click.argument("bind_annotation")
@click.option("--limit", default=10, show_default=True, help="Rows to preview.")
@_SCOPE
def preview_cmd(bind_annotation: str, limit: int, scope: str) -> None:
    """Preview the first rows of the datasource with BIND_ANNOTATION."""
    px, _, _ = _connect()
    try:
        res = px.preview_datasource(bind_annotation, scope=scope, limit=limit)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    click.echo(_json.dumps(res, indent=2, default=str))


@datasource.command("delete")
@click.argument("bind_or_id")
@click.option("--by-id", is_flag=True, help="Treat the argument as a datasource id, not a bind annotation.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@_SCOPE
def delete_cmd(bind_or_id: str, by_id: bool, assume_yes: bool, scope: str) -> None:
    """Disconnect a datasource by its BIND annotation (or id with --by-id)."""
    px, _, _ = _connect()
    source_id = bind_or_id
    if not by_id:
        # Resolve the bind annotation to a datasource id (the REST /data/cleanup
        # route deletes by id, not bind — mirror the MCP tool's resolution).
        try:
            sources = px.list_sources(scope) or []
        except Exception as exc:  # noqa: BLE001
            _fail(str(exc))
        norm = " ".join(bind_or_id.split())
        match = next(
            (s for s in sources
             if " ".join(str(s.get("bind_annotation") or "").split()) == norm
             or s.get("predicate_placeholder") == bind_or_id),
            None,
        )
        if not match:
            _fail(f"no datasource matches bind/predicate '{bind_or_id}'. "
                  "Run `px list datasources` to see binds, or pass an id with --by-id.")
        source_id = match.get("id") or match.get("datasource_id")

    if not assume_yes and not click.confirm(f"Disconnect datasource {source_id}?", default=False):
        click.echo("Aborted.")
        sys.exit(1)
    try:
        data = rest_data("POST", "/api/v1/data/cleanup",
                         json={"source_ids": [source_id], "scope": scope}) or {}
    except SdkError as exc:
        _fail(str(exc))
    n = data.get("deleted_count") if isinstance(data, dict) else None
    click.echo(click.style("Disconnected", fg="green", bold=True)
               + f" datasource {source_id}" + (f" ({n} removed)." if n is not None else "."))
