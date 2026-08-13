"""`px app` — app lifecycle beyond what `apply` covers (publish / unpublish).

Creating and updating apps is declarative (`apps/*.app.yaml` + `px apply`).
Publishing (freezing a shareable snapshot of the draft) and unpublishing are
imperative state changes, so they live here.
"""

from __future__ import annotations

import sys

import click

from ..sdk import SdkError, connected_sdk, rest_data

_SCOPE = click.option("--scope", default="user", type=click.Choice(["user", "organization"]))


@click.group()
def app() -> None:
    """App lifecycle: publish / unpublish."""


def _connect():
    try:
        return connected_sdk(require_token=True)
    except SdkError as exc:
        _fail(str(exc))


def _fail(msg: str) -> None:
    click.echo(click.style("FAIL", fg="red", bold=True) + f": {msg}", err=True)
    sys.exit(1)


@app.command("publish")
@click.argument("ontology_id")
@click.argument("app_id")
@_SCOPE
def publish_cmd(ontology_id: str, app_id: str, scope: str) -> None:
    """Publish a frozen, shareable snapshot of APP_ID's current draft."""
    _connect()
    try:
        rest_data("POST", f"/api/v1/apps/{ontology_id}/{app_id}/publish", params={"scope": scope})
    except SdkError as exc:
        _fail(str(exc))
    click.echo(click.style("Published", fg="green", bold=True) + f" app {app_id}.")


@app.command("unpublish")
@click.argument("ontology_id")
@click.argument("app_id")
@_SCOPE
def unpublish_cmd(ontology_id: str, app_id: str, scope: str) -> None:
    """Remove APP_ID's published snapshot (back to draft-only)."""
    _connect()
    try:
        rest_data("POST", f"/api/v1/apps/{ontology_id}/{app_id}/unpublish", params={"scope": scope})
    except SdkError as exc:
        _fail(str(exc))
    click.echo(click.style("Unpublished", fg="green", bold=True) + f" app {app_id}.")
