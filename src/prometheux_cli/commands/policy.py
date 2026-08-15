"""`px policy` — schedule / trigger concept runs (evaluation policies).

A policy runs a concept on a cron schedule or when its inputs change. These
subcommands mirror the platform's policy API: list, inspect, create, update,
delete, trigger now, and view run history.
"""

from __future__ import annotations

import json as _json
import sys

import click

from ..sdk import SdkError, connected_sdk, rest_data

_SCOPE = click.option("--scope", default="user", type=click.Choice(["user", "organization"]))


@click.group()
def policy() -> None:
    """Manage evaluation policies (scheduled / triggered concept runs)."""


def _connect():
    try:
        return connected_sdk(require_token=True)
    except SdkError as exc:
        _fail(str(exc))


def _fail(msg: str) -> None:
    click.echo(click.style("FAIL", fg="red", bold=True) + f": {msg}", err=True)
    sys.exit(1)


def _parse_config(cron, config):
    """Build trigger_config from --cron or raw --config JSON."""
    if config:
        try:
            return _json.loads(config)
        except ValueError as exc:
            _fail(f"--config is not valid JSON: {exc}")
    if cron:
        return {"cron": cron}
    return None


@policy.command("list")
@click.argument("ontology_id")
@click.option("--concept", "concept_name", default=None, help="Only policies for this concept.")
@_SCOPE
def list_cmd(ontology_id: str, concept_name: str, scope: str) -> None:
    """List policies for ONTOLOGY_ID."""
    px, url, _ = _connect()
    try:
        rows = px.list_policies(ontology_id, scope, concept_name=concept_name) or []
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    if not rows:
        click.echo(f"No policies in ontology {ontology_id}.")
        return
    click.echo(click.style(f"Policies in {ontology_id} at {url}:", bold=True))
    for p in rows:
        state = click.style("on ", fg="green") if p.get("enabled") else click.style("off", fg="yellow")
        trig = p.get("trigger_type") or "?"
        click.echo(f"  {str(p.get('id')):<38}  {state}  {trig:<12}  {p.get('concept_name', '')}")
    click.echo(f"\n  {len(rows)} policy(ies).")


@policy.command("get")
@click.argument("ontology_id")
@click.argument("policy_id")
@_SCOPE
def get_cmd(ontology_id: str, policy_id: str, scope: str) -> None:
    """Show one policy's full config + last-run status."""
    px, _, _ = _connect()
    try:
        p = px.get_policy(ontology_id, policy_id, scope)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    click.echo(_json.dumps(p, indent=2, default=str))


@policy.command("create")
@click.argument("ontology_id")
@click.argument("concept_name")
@click.option("--trigger-type", type=click.Choice(["cron", "data_change"]), default="cron",
              show_default=True)
@click.option("--cron", default=None, help="Cron expression (for --trigger-type cron).")
@click.option("--config", default=None, help="Raw trigger_config as a JSON object.")
@click.option("--disabled", is_flag=True, help="Create the policy disabled.")
@_SCOPE
def create_cmd(ontology_id, concept_name, trigger_type, cron, config, disabled, scope) -> None:
    """Create a policy that runs CONCEPT_NAME on a schedule/trigger."""
    trigger_config = _parse_config(cron, config)
    px, _, _ = _connect()
    try:
        res = px.create_policy(ontology_id, concept_name, trigger_type=trigger_type,
                               trigger_config=trigger_config, scope=scope, enabled=not disabled) or {}
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    pid = res.get("id") if isinstance(res, dict) else res
    click.echo(click.style("Created policy", fg="green", bold=True)
               + f" {pid} for concept '{concept_name}'.")


@policy.command("update")
@click.argument("ontology_id")
@click.argument("policy_id")
@click.option("--cron", default=None, help="New cron expression.")
@click.option("--config", default=None, help="New trigger_config as a JSON object.")
@click.option("--enable/--disable", "enabled", default=None, help="Enable or disable the policy.")
@_SCOPE
def update_cmd(ontology_id, policy_id, cron, config, enabled, scope) -> None:
    """Change a policy's schedule and/or enabled state."""
    trigger_config = _parse_config(cron, config)
    if trigger_config is None and enabled is None:
        _fail("nothing to update — pass --cron/--config and/or --enable/--disable.")
    px, _, _ = _connect()
    try:
        px.update_policy(ontology_id, policy_id, scope=scope,
                         trigger_config=trigger_config, enabled=enabled)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    click.echo(click.style("Updated policy", fg="green", bold=True) + f" {policy_id}.")


@policy.command("delete")
@click.argument("ontology_id")
@click.argument("policy_id")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@_SCOPE
def delete_cmd(ontology_id, policy_id, assume_yes, scope) -> None:
    """Delete a policy (and unschedule it)."""
    if not assume_yes and not click.confirm(f"Delete policy {policy_id}?", default=False):
        click.echo("Aborted.")
        sys.exit(1)
    px, _, _ = _connect()
    try:
        px.delete_policy(ontology_id, policy_id, scope)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    click.echo(click.style("Deleted policy", fg="green", bold=True) + f" {policy_id}.")


@policy.command("trigger")
@click.argument("ontology_id")
@click.argument("policy_id")
@_SCOPE
def trigger_cmd(ontology_id, policy_id, scope) -> None:
    """Run a policy's concept immediately."""
    px, _, _ = _connect()
    try:
        px.trigger_policy(ontology_id, policy_id, scope)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))
    click.echo(click.style("Triggered policy", fg="green", bold=True) + f" {policy_id}.")


@policy.command("runs")
@click.argument("ontology_id")
@click.argument("policy_id")
@click.option("--limit", default=50, show_default=True, help="Max runs to show.")
@click.option("--offset", default=0, help="Skip this many runs.")
@_SCOPE
def runs_cmd(ontology_id, policy_id, limit, offset, scope) -> None:
    """Show a policy's execution history."""
    _connect()
    try:
        data = rest_data(
            "GET", f"/api/v1/schedules/{ontology_id}/policies/{policy_id}/runs",
            params={"scope": scope, "limit": limit, "offset": offset},
        ) or {}
    except SdkError as exc:
        _fail(str(exc))
    runs = data.get("runs") if isinstance(data, dict) else data
    runs = runs or []
    if not runs:
        click.echo(f"No runs for policy {policy_id}.")
        return
    click.echo(click.style(f"Runs of policy {policy_id}:", bold=True))
    for r in runs:
        when = str(r.get("created_at") or r.get("timestamp") or "")[:19]
        status = r.get("status") or r.get("state") or "?"
        click.echo(f"  {when:<19}  {status}")
    click.echo(f"\n  {len(runs)} run(s).")
