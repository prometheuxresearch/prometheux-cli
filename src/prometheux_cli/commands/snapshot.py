"""`px snapshot` — point-in-time snapshots of a server ontology.

A snapshot captures an ontology's full state so you can roll back. `px apply`
already snapshots before it writes (unless `--no-snapshot`); these subcommands
let you list, create, restore, and delete snapshots directly.
"""

from __future__ import annotations

import sys

import click

from ..sdk import SdkError, connected_sdk

_SCOPE = click.option("--scope", default="user", type=click.Choice(["user", "organization"]))


@click.group()
def snapshot() -> None:
    """Manage ontology snapshots (list / create / restore / delete)."""


def _connect():
    try:
        return connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)


def _fail(msg: str) -> None:
    click.echo(click.style("FAIL", fg="red", bold=True) + f": {msg}", err=True)
    sys.exit(1)


@snapshot.command("list")
@click.argument("ontology_id")
@_SCOPE
def list_cmd(ontology_id: str, scope: str) -> None:
    """List snapshots of ONTOLOGY_ID, newest first."""
    px, url, _ = _connect()
    try:
        snaps = px.list_snapshots(ontology_id, scope) or []
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    if not snaps:
        click.echo(f"No snapshots for ontology {ontology_id}.")
        return
    click.echo(click.style(f"Snapshots of {ontology_id} at {url}:", bold=True))
    for s in snaps:
        sid = str(s.get("id") or "")
        created = str(s.get("created_at") or s.get("timestamp") or "")[:19]
        desc = s.get("description") or ""
        click.echo(f"  {sid:<38}  {created:<19}  {desc}")
    click.echo(f"\n  {len(snaps)} snapshot(s). Restore with: px snapshot restore {ontology_id} <id>")


@snapshot.command("create")
@click.argument("ontology_id")
@click.option("--description", "-d", default=None, help="Optional label for the snapshot.")
@_SCOPE
def create_cmd(ontology_id: str, description: str, scope: str) -> None:
    """Create a snapshot of ONTOLOGY_ID."""
    px, _, _ = _connect()
    try:
        res = px.create_snapshot(ontology_id, scope, description=description) or {}
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    sid = res.get("id") if isinstance(res, dict) else res
    click.echo(click.style("Created snapshot", fg="green", bold=True) + f" {sid} of {ontology_id}.")


@snapshot.command("restore")
@click.argument("ontology_id")
@click.argument("snapshot_id")
@click.option("--no-safety", is_flag=True, help="Skip the automatic pre-restore safety snapshot.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@_SCOPE
def restore_cmd(ontology_id: str, snapshot_id: str, no_safety: bool, assume_yes: bool, scope: str) -> None:
    """Restore ONTOLOGY_ID to SNAPSHOT_ID (overwrites current state)."""
    if not assume_yes and not click.confirm(
        f"Restore {ontology_id} to snapshot {snapshot_id}? This overwrites its current state.",
        default=False,
    ):
        click.echo("Aborted.")
        sys.exit(1)
    px, _, _ = _connect()
    try:
        px.restore_snapshot(snapshot_id, ontology_id, scope, create_safety_snapshot=not no_safety)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    click.echo(click.style("Restored", fg="green", bold=True) + f" {ontology_id} to snapshot {snapshot_id}.")


@snapshot.command("delete")
@click.argument("ontology_id")
@click.argument("snapshot_id")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@_SCOPE
def delete_cmd(ontology_id: str, snapshot_id: str, assume_yes: bool, scope: str) -> None:
    """Delete SNAPSHOT_ID of ONTOLOGY_ID."""
    if not assume_yes and not click.confirm(
        f"Permanently delete snapshot {snapshot_id}?", default=False
    ):
        click.echo("Aborted.")
        sys.exit(1)
    px, _, _ = _connect()
    try:
        px.delete_snapshot(snapshot_id, ontology_id, scope)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    click.echo(click.style("Deleted snapshot", fg="green", bold=True) + f" {snapshot_id}.")
