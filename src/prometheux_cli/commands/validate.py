"""`px validate` — offline schema + structural checks (PASS/FAIL exit code)."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from ..validation import find_workspace_root, validate_workspace


@click.command()
@click.argument("path", required=False, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--strict", is_flag=True, help="Treat warnings as failures.")
@click.option("--online", is_flag=True,
              help="Also validate each concept body server-side (Vadalog engine). Requires login.")
def validate(path: Path, strict: bool, online: bool) -> None:
    """Validate a workspace against the published schemas.

    Offline by default (schema + structure). With --online, each concept body is
    additionally checked by the platform's Vadalog engine.

    PATH is the workspace directory (defaults to searching up from the current
    directory for prometheux.workspace.yaml).
    """
    start = path or Path.cwd()
    root = find_workspace_root(start)
    if root is None:
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": no prometheux.workspace.yaml found in or above {start}",
            err=True,
        )
        sys.exit(2)

    report = validate_workspace(root)

    for f in report.errors:
        click.echo(f"{click.style('error', fg='red')}  {f.location}: {f.message}")
    for f in report.warnings:
        click.echo(f"{click.style('warning', fg='yellow')}  {f.location}: {f.message}")

    counts = ", ".join(f"{n} {k}" for k, n in sorted(report.checked.items())) or "nothing"
    click.echo(f"\nChecked: {counts}.")

    online_errors = _validate_online(root) if online else 0

    failed = not report.ok or (strict and report.warnings) or online_errors > 0
    if failed:
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": {len(report.errors)} error(s), {len(report.warnings)} warning(s)."
        )
        sys.exit(1)

    click.echo(
        click.style("PASS", fg="green", bold=True)
        + f": {len(report.warnings)} warning(s)."
    )


def _validate_online(root: Path) -> int:
    """Server-validate each concept body via the Vadalog engine. Returns error count."""
    from ..loader import load_workspace
    from ..sdk import SdkError, connected_sdk, rest_data

    try:
        connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": --online needs login: {exc}", err=True)
        return 1

    workspace = load_workspace(root)
    errors = 0
    checked = 0
    click.echo("\nOnline concept validation:")
    for onto in workspace.ontologies:
        for c in onto.concepts:
            if not c.is_vadalog_family:
                continue  # engine validation applies to logic/sql/cypher/python bodies
            checked += 1
            try:
                res = rest_data("POST", "/api/v1/vadalog/validate", json={
                    "definition": c.body,
                    "concept_type": c.concept_type,
                    "concept_name": c.predicate,
                    "project_id": onto.id,
                }) or {}
            except SdkError as exc:
                click.echo(f"  {click.style('error', fg='red')}  {onto.slug}/{c.predicate}: {exc}")
                errors += 1
                continue
            if isinstance(res, dict) and res.get("valid") is False:
                click.echo(f"  {click.style('error', fg='red')}  {onto.slug}/{c.predicate}: {res.get('error', 'invalid')}")
                errors += 1
    click.echo(f"  checked {checked} concept(s), {errors} invalid.")
    return errors
