"""`px compute` — inspect and control the caller's compute machines.

Runs (`px run`) need a running compute resource. These subcommands let you
check machine state and start/stop it from the terminal instead of the UI.
"""

from __future__ import annotations

import sys
from typing import List, Optional

import click

from ..sdk import SdkError, connected_sdk, rest_data


def _enabled_machines(px) -> List[dict]:
    resp = px.list_machines_combined() or {}
    data = resp.get("data") if isinstance(resp, dict) else None
    data = data or (resp if isinstance(resp, dict) else {})
    return data.get("user_machines_enabled") or []


def _name_of(um: dict) -> str:
    m = um.get("machines") or {}
    return m.get("name") or um.get("machine_name") or "?"


def _resolve(machines: List[dict], name: Optional[str]) -> dict:
    if name:
        hits = [m for m in machines if _name_of(m).lower() == name.lower()]
        if not hits:
            raise click.ClickException(
                f"no enabled machine named '{name}'. Seen: "
                + (", ".join(sorted(_name_of(m) for m in machines)) or "none")
            )
        return hits[0]
    if not machines:
        raise click.ClickException("no enabled machines on this account. Add one in the UI first.")
    if len(machines) > 1:
        raise click.ClickException(
            "multiple machines enabled; name one: "
            + ", ".join(sorted(_name_of(m) for m in machines))
        )
    return machines[0]


@click.group()
def compute() -> None:
    """Inspect and control compute machines (status / start / stop)."""


@compute.command("status")
def status_cmd() -> None:
    """List the caller's enabled machines and their active state."""
    try:
        px, _, _ = connected_sdk(require_token=True)
        machines = _enabled_machines(px)
    except (SdkError, Exception) as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    if not machines:
        click.echo("No enabled machines.")
        return
    for m in machines:
        active = m.get("is_active")
        dot = click.style("●", fg="green") if active else click.style("○", fg="yellow")
        state = "active" if active else "stopped"
        click.echo(f"  {dot} {_name_of(m):<16} {state:<8} id={m.get('id')}")


@compute.command("start")
@click.argument("name", required=False)
@click.option("--autotermination", "autotermination", type=int, default=None,
              help="Auto-terminate after N idle minutes.")
def start_cmd(name, autotermination) -> None:
    """Start machine NAME (or the only enabled one)."""
    _toggle(name, True, autotermination)


@compute.command("stop")
@click.argument("name", required=False)
def stop_cmd(name) -> None:
    """Stop machine NAME (or the only enabled one)."""
    _toggle(name, False, None)


@compute.command("catalog")
def catalog_cmd() -> None:
    """List catalog machines available to provision (with their ids)."""
    try:
        px, _, _ = connected_sdk(require_token=True)
        resp = px.list_machines_combined() or {}
    except (SdkError, Exception) as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    data = resp.get("data") if isinstance(resp, dict) and "data" in resp else resp
    catalog = (data or {}).get("machines") or (data or {}).get("machines_catalog") or []
    if not catalog:
        click.echo("No catalog machines available.")
        return
    click.echo(click.style("Catalog machines:", bold=True))
    for m in catalog:
        click.echo(f"  {str(m.get('id')):<38}  {m.get('name', '')}")
    click.echo("\nProvision one with: px compute provision <id>")


@compute.command("provision")
@click.argument("machine_id")
@click.option("--name", "machine_name", default=None, help="Optional label for your copy.")
def provision_cmd(machine_id: str, machine_name: str) -> None:
    """Add catalog machine MACHINE_ID to your machine list (not billable yet)."""
    try:
        connected_sdk(require_token=True)
        body = {"machine_id": machine_id}
        if machine_name:
            body["machine_name"] = machine_name
        data = rest_data("POST", "/api/v1/machines/user-machines/use", json=body) or {}
    except (SdkError, Exception) as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    um = (data.get("user_machine") if isinstance(data, dict) else None) or {}
    click.echo(click.style("Provisioned", fg="green", bold=True)
               + f" machine {um.get('id') or machine_id}. Power on with `px compute start`.")


@compute.command("remove")
@click.argument("user_machine_id")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
def remove_cmd(user_machine_id: str, assume_yes: bool) -> None:
    """Remove (soft-disable) USER_MACHINE_ID from your list. Usage history is kept."""
    if not assume_yes and not click.confirm(f"Remove machine {user_machine_id}?", default=False):
        click.echo("Aborted.")
        sys.exit(1)
    try:
        connected_sdk(require_token=True)
        rest_data("DELETE", f"/api/v1/machines/user-machines/{user_machine_id}")
    except (SdkError, Exception) as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    click.echo(click.style("Removed", fg="green", bold=True) + f" machine {user_machine_id}.")


def _toggle(name: Optional[str], active: bool, autotermination: Optional[int]) -> None:
    verb = "start" if active else "stop"
    try:
        px, _, _ = connected_sdk(require_token=True)
        target = _resolve(_enabled_machines(px), name)
        px.set_machine_active(target.get("id"), active, autotermination_minutes=autotermination)
    except (SdkError, Exception) as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {verb} failed: {exc}", err=True)
        sys.exit(1)
    word = "Starting" if active else "Stopping"
    click.echo(click.style(word, fg="green", bold=True) + f" {_name_of(target)}.")
    if active:
        click.echo("  Machines take a moment to become ready — check `px compute status`.")
