"""`px template` — the catalogue of starter ontologies you can clone."""

from __future__ import annotations

import sys

import click

from ..sdk import SdkError, connected_sdk


@click.group()
def template() -> None:
    """Browse and import catalogue template ontologies."""


def _connect():
    try:
        return connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)


@template.command("list")
def list_cmd() -> None:
    """List catalogue templates. The ID is what `px template import` takes."""
    px, url, _ = _connect()
    try:
        rows = px.list_templates() or []
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    if not rows:
        click.echo("No templates available.")
        return
    click.echo(click.style(f"Templates at {url}:", bold=True))
    for t in rows:
        click.echo(f"  {str(t.get('id')):<14}  {t.get('name', '')}")
    click.echo(f"\n  {len(rows)} template(s). Import with: px template import <id> --name <name>")


@template.command("import")
@click.argument("template_id")
@click.option("--name", "new_name", default=None, help="Name for the new ontology (default: template's).")
@click.option("--scope", default="user", type=click.Choice(["user", "organization"]))
def import_cmd(template_id: str, new_name: str, scope: str) -> None:
    """Clone TEMPLATE_ID into a new ontology on your account."""
    px, _, _ = _connect()
    try:
        res = px.import_template(template_id, new_ontology_name=new_name, ontology_scope=scope) or {}
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    new_id = res.get("id") or res.get("ontology_id") if isinstance(res, dict) else res
    click.echo(click.style("Imported", fg="green", bold=True)
               + f" template {template_id} -> ontology {new_id}.")
    click.echo(f"Next: px pull {new_id}")
