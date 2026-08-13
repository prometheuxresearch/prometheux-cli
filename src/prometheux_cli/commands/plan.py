"""`px plan` — diff local files against server state, with the downstream cascade."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from ..context import build_note_resolver
from ..loader import load_workspace, select_ontologies
from ..plan import (
    PlanResult,
    fetch_server_apps,
    fetch_server_datasources,
    fetch_server_sources,
    plan_ontology,
)
from ..sdk import SdkError, connected_sdk
from ..validation import find_workspace_root


@click.command()
@click.argument("path", required=False, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--ontology", "-o", "ontology_selectors", multiple=True,
              help="Only plan the named ontology(s), by name / directory slug / id. Repeatable.")
def plan(path: Path, ontology_selectors) -> None:
    """Show what `px apply` would change (nothing is written).

    Diffs every ontology in the workspace that has a server id against its live
    state, classifying each concept create / update / delete and rendering the
    downstream re-run cascade for definition changes. Use --ontology to target a
    subset.
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

    try:
        px, _, _ = connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)

    workspace = load_workspace(root)
    ontologies, unknown = select_ontologies(workspace.ontologies, ontology_selectors)
    if unknown:
        available = ", ".join(sorted({p.name for p in workspace.ontologies})) or "(none)"
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": unknown ontology(s): {', '.join(unknown)}. Available: {available}",
            err=True,
        )
        sys.exit(2)

    resolve_notes = build_note_resolver(root)
    any_changes = False
    for ontology in ontologies:
        export = None
        server_apps = None
        server_sources = None
        server_datasources = fetch_server_datasources(px, ontology.scope)
        if ontology.id:
            try:
                export = px.export_ontology(ontology.id, ontology.scope)
            except Exception as exc:  # noqa: BLE001
                click.echo(
                    click.style("FAIL", fg="red", bold=True)
                    + f": export of ontology {ontology.id} failed: {exc}",
                    err=True,
                )
                sys.exit(1)
            server_apps = fetch_server_apps(px, ontology.id, ontology.scope)
            server_sources = fetch_server_sources(px, ontology.id, ontology.scope)
        result = plan_ontology(ontology, export, note_resolver=resolve_notes,
                              server_apps=server_apps, server_sources=server_sources,
                              server_datasources=server_datasources)
        any_changes = _render(result, is_new=ontology.id is None) or any_changes

    if not any_changes:
        click.echo("\nNo changes. Local files match server state.")
    else:
        click.echo("\nRun `px apply` to proceed. Nothing is deleted without --prune.")


def _render(result: PlanResult, is_new: bool) -> bool:
    new_note = "  (new ontology — everything is create)" if is_new else ""
    click.echo(f'\nPlan against ontology "{result.ontology_name}" (scope: {result.scope}){new_note}')

    for w in result.warnings:
        click.echo(f"  {click.style('warning', fg='yellow')} {w}")

    unchanged = 0
    for c in result.concept_changes:
        if c.action == "create":
            click.echo("  " + click.style(f"+ concept {c.predicate}", fg="green") + "  create")
        elif c.action == "delete":
            click.echo(
                "  "
                + click.style(f"- concept {c.predicate}", fg="red")
                + "  delete (withheld — needs --prune)"
            )
        elif c.action == "update":
            click.echo("  " + click.style(f"~ concept {c.predicate}", fg="yellow") + f"  update in-place ({c.reason})")
            if c.definition_changed and c.server_populated:
                click.echo(
                    "    "
                    + click.style(f"! results for `{c.predicate}` invalidated", fg="magenta")
                )
            _render_cascade(result, c.predicate)
        else:
            unchanged += 1

    for d in result.datasource_changes:
        if d.action == "create":
            click.echo("  " + click.style(f"+ datasource {d.name}", fg="green") + "  create")
        elif d.action == "delete":
            click.echo("  " + click.style(f"- datasource {d.name}", fg="red") + "  delete (withheld)")

    if result.ontology_change == "create":
        click.echo("  " + click.style("+ ontology schema", fg="green") + "  create")
    elif result.ontology_change == "update":
        click.echo("  " + click.style("~ ontology schema", fg="yellow") + "  update in-place")

    for a in result.app_changes:
        if a.action == "create":
            click.echo("  " + click.style(f"+ app {a.name}", fg="green") + "  create")
        elif a.action == "update":
            click.echo("  " + click.style(f"~ app {a.name}", fg="yellow") + "  update in-place")
        elif a.action == "delete":
            click.echo("  " + click.style(f"- app {a.name}", fg="red") + "  delete (withheld — needs --prune)")

    if unchanged:
        click.echo(f"  = {unchanged} concept(s) unchanged")

    click.echo(
        "\n  Plan: "
        f"{result.to_create} to create, "
        f"{result.to_update} to update, "
        f"{result.rerun_count} downstream re-run(s), "
        f"{result.to_delete} to destroy (withheld)."
    )
    return result.has_changes


def _render_cascade(result: PlanResult, predicate: str) -> None:
    downstream = result.cascade.get(predicate)
    if not downstream:
        return
    click.echo("    └─ cascades to downstream concepts (derived lineage):")
    for d in downstream:
        state = "will need re-run" if d in result.populated else "will be stale"
        click.echo("       " + click.style(f"~ {d}", fg="yellow") + f"  {state}")
