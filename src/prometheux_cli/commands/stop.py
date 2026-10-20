"""`px stop` — stop evaluations running on the platform."""

from __future__ import annotations

import sys
from typing import Optional

import click

from ..sdk import SdkError, connected_sdk


@click.command()
@click.argument("execution_id", required=False)
@click.option("--all", "stop_all", is_flag=True,
              help="Stop every evaluation and run on the workspace, other users' included.")
def stop(execution_id: Optional[str], stop_all: bool) -> None:
    """Stop the evaluations sent with EXECUTION_ID, or the run with that id.

    `px test` sends every case of a suite with the same id (its
    --execution-id), so `px stop ID` stops that suite and leaves everyone
    else's evaluations running. The engine itself is stopped only when nothing
    else is running on it.

    \b
    Examples:
      px test tests/ --execution-id nightly-1234 &
      px stop nightly-1234
    """
    if bool(execution_id) == stop_all:
        raise click.UsageError("give an EXECUTION_ID, or --all to stop everything on the workspace")
    try:
        px, _, _ = connected_sdk(require_token=True)
        data = px.stop_evaluation(execution_id) or {}
    except Exception as exc:  # SdkError, or the platform refusing the stop
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    if stop_all:
        click.echo("Stopped every evaluation on the workspace.")
    elif data.get("engine_stopped") is False:
        click.echo(f"Stopped {execution_id}. Other evaluations are running, so the engine was left running.")
    else:
        click.echo(f"Stopped {execution_id}.")
