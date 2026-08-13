"""`px login` — store the platform URL + token and verify they work."""

from __future__ import annotations

import sys

import click

from .. import credentials
from ..sdk import SdkError, load_sdk


@click.command()
@click.option("--url", default=None, help=f"Platform URL (default: {credentials.DEFAULT_URL}).")
@click.option("--token", default=None, help="API token. Omit to be prompted (hidden input).")
@click.option("--no-verify", is_flag=True, help="Skip the live authentication check.")
def login(url: str, token: str, no_verify: bool) -> None:
    """Authenticate the CLI against a Prometheux platform.

    Persists to ~/.prometheux/config.json. In CI, set PMTX_TOKEN / JARVISPY_URL
    instead of running this.
    """
    resolved_url = url or credentials.resolve_url()
    resolved_token = token or credentials.resolve_token()
    if not resolved_token:
        resolved_token = click.prompt("API token", hide_input=True)

    if not no_verify:
        try:
            px = load_sdk()
            px.config.set(credentials.ENV_URL, resolved_url)
            px.config.set(credentials.ENV_TOKEN, resolved_token)
            ontologies = px.list_ontologies(["user"])
        except SdkError as exc:
            click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
            sys.exit(1)
        except Exception as exc:  # noqa: BLE001 - surface any SDK/HTTP error cleanly
            click.echo(
                click.style("FAIL", fg="red", bold=True)
                + f": could not authenticate against {resolved_url}: {exc}",
                err=True,
            )
            sys.exit(1)
        count = len(ontologies) if isinstance(ontologies, list) else "?"
        click.echo(f"Authenticated against {resolved_url} ({count} ontology(s) visible).")

    path = credentials.save(resolved_url, resolved_token)
    click.echo(click.style("Saved", fg="green", bold=True) + f" credentials to {path}.")
