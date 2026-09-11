"""`px playbook` — the platform's step-by-step skill playbooks.

These are the server-side "skills" the assistant follows. (Distinct from
`px skill install`, which installs the *authoring* skill into your editor.)
"""

from __future__ import annotations

import sys

import click

from ..sdk import SdkError, connected_sdk


@click.group()
def playbook() -> None:
    """Browse the platform's skill playbooks."""


def _connect():
    try:
        return connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)


@playbook.command("list")
def list_cmd() -> None:
    """List available playbooks. The ID is what `px playbook show` takes."""
    px, _, _ = _connect()
    try:
        data = px.list_skills() or {}
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    skills = (data.get("skills") if isinstance(data, dict) else data) or []
    if not skills:
        click.echo("No playbooks available.")
        return
    click.echo(click.style("Playbooks:", bold=True))
    for s in skills:
        click.echo(f"  {str(s.get('id')):<24}  {s.get('name', '')}")
    click.echo(f"\n  {len(skills)} playbook(s). Read one with: px playbook show <id>")


@playbook.command("show")
@click.argument("skill_id")
def show_cmd(skill_id: str) -> None:
    """Print the full body of playbook SKILL_ID."""
    px, _, _ = _connect()
    try:
        data = px.get_skill(skill_id) or {}
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    if isinstance(data, dict):
        name = data.get("name")
        if name:
            click.echo(click.style(name, bold=True))
        click.echo(data.get("body") or data.get("text") or "")
    else:
        click.echo(str(data))
