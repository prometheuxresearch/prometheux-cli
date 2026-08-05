"""`px validate` — offline schema + structural checks (PASS/FAIL exit code)."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from ..validation import find_workspace_root, validate_workspace


@click.command()
@click.argument("path", required=False, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--strict", is_flag=True, help="Treat warnings as failures.")
def validate(path: Path, strict: bool) -> None:
    """Validate a workspace against the published schemas, fully offline.

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

    failed = not report.ok or (strict and report.warnings)
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
