"""`px delete` — permanently delete a whole project (ontology) from the account."""

from __future__ import annotations

import sys

import click

from ..sdk import SdkError, connected_sdk


@click.command()
@click.argument("project", required=True)
@click.option("--scope", default="user", type=click.Choice(["user", "organization"]))
@click.option("-y", "--yes", is_flag=True, help="Skip the confirmation prompt.")
def delete(project: str, scope: str, yes: bool) -> None:
    """Permanently delete PROJECT (a server project id or name) and everything in it.

    Hard delete of the whole project — concepts, datasource binds, ontology,
    apps, and notes. The server takes an auto-snapshot first when versioning is
    available. Local workspace files are NOT touched.

    Resolves PROJECT by id first, then by exact name (ambiguous names must be
    deleted by id). With no confirmation flag you are prompted before deletion.
    """
    try:
        px, url, _ = connected_sdk(require_token=True)
    except SdkError as exc:
        _fail(str(exc))

    target_id, target_name = _resolve(px, project, scope)

    label = f"'{target_name}' ({target_id})" if target_name else f"'{target_id}'"
    if not yes:
        click.echo(
            click.style("WARNING", fg="red", bold=True)
            + f": this permanently deletes project {label} and everything in it."
        )
        if not click.confirm("Delete it?", default=False):
            click.echo("Aborted.")
            sys.exit(1)

    try:
        px.cleanup_ontologies(ontology_id=target_id, ontology_scope=scope)
    except Exception as exc:  # noqa: BLE001 - surface SDK/HTTP errors cleanly
        _fail(f"delete failed: {exc}")

    click.echo(click.style("Deleted", fg="green", bold=True) + f" project {label} at {url}.")
    click.echo(
        "Local workspace files (if any) are unchanged — remove the project's `id:` from "
        "prometheux.yaml if you don't intend to recreate it."
    )


def _resolve(px, project: str, scope: str) -> tuple:
    """Resolve PROJECT (id or exact name) to (id, name) against the account."""
    try:
        projects = px.list_ontologies([scope]) or []
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))

    by_id = {str(p.get("id")): p for p in projects}
    if project in by_id:
        return project, by_id[project].get("name", "")

    matches = [p for p in projects if p.get("name") == project]
    if not matches:
        _fail(
            f"no {scope}-scoped project matches id/name '{project}'. "
            "Run `px pull` (no args) to list projects."
        )
    if len(matches) > 1:
        ids = ", ".join(str(m.get("id")) for m in matches)
        _fail(
            f"'{project}' is ambiguous — {len(matches)} projects share that name ({ids}). "
            "Delete by id instead."
        )
    return str(matches[0].get("id")), matches[0].get("name", "")


def _fail(msg: str) -> None:
    click.echo(click.style("FAIL", fg="red", bold=True) + f": {msg}", err=True)
    sys.exit(1)
