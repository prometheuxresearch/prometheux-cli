"""`px show` — fetch and print the rows of a populated concept.

A read-only companion to `px run`: it calls the SDK's ``fetch_results`` over the
same backend/credentials the rest of the CLI uses, so you can inspect a concept's
materialised output straight from the terminal (no UI, no MCP).
"""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path
from typing import List

import click

from ..loader import LocalOntology, load_workspace, select_ontologies
from ..sdk import SdkError, connected_sdk
from ..validation import find_workspace_root


@click.command()
@click.argument("concept")
@click.argument("path", required=False, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--ontology", "-o", "ontology_selectors", multiple=True,
              help="Limit the search to the named ontology(s). Repeatable.")
@click.option("--page", default=1, show_default=True, help="1-based page number.")
@click.option("--page-size", "page_size", default=100, show_default=True, help="Rows per page.")
@click.option("--order-by", "order_by", default=None,
              help="Ordering, e.g. '0:asc,2:desc' (column positions).")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON instead of a table.")
def show(concept, path, ontology_selectors, page, page_size, order_by, as_json):
    """Fetch and print the rows of CONCEPT (an output predicate)."""
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
        click.echo(click.style("FAIL", fg="red", bold=True) + f": unknown ontology(s): {', '.join(unknown)}", err=True)
        sys.exit(2)

    ontology, _local = _resolve_concept(ontologies, concept)
    if ontology is None:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": concept '{concept}' not found in the workspace.", err=True)
        sys.exit(1)
    if ontology.id is None:
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": ontology '{ontology.name}' has no server id yet — run `px apply` first.",
            err=True,
        )
        sys.exit(1)

    try:
        resp = px.fetch_results(
            ontology.id, concept, page=page, page_size=page_size,
            scope=ontology.scope, order_by=order_by,
        )
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": fetch of '{concept}' failed: {exc}", err=True)
        sys.exit(1)

    if as_json:
        click.echo(_json.dumps(resp, indent=2, ensure_ascii=False))
        return

    cols, rows, total = _extract(resp)
    if not rows:
        click.echo(f"'{concept}': 0 row(s).")
        return
    _print_table(cols, rows)
    shown = len(rows)
    suffix = f" (page {page}, {shown} shown)" if total is None else f" of {total} (page {page}, {shown} shown)"
    click.echo(f"\n'{concept}': {shown} row(s){suffix}.")


def _extract(resp):
    """Pull (columnNames, facts, total) out of the fetch response, tolerant of shape."""
    if not isinstance(resp, dict):
        return [], [], None
    results = resp.get("results") if isinstance(resp.get("results"), dict) else resp
    cols = results.get("columnNames") or results.get("columns") or []
    rows = results.get("facts") or results.get("rows") or []
    pag = resp.get("pagination") or {}
    total = pag.get("total_count")
    return cols, rows, total


def _print_table(cols: List[str], rows: List[list]):
    ncol = max([len(cols)] + [len(r) for r in rows])
    cols = list(cols) + [f"c{i}" for i in range(len(cols), ncol)]

    def cell(v):
        s = "" if v is None else str(v)
        s = s.replace("\n", " ")
        return (s[:57] + "...") if len(s) > 60 else s

    widths = [len(cols[i]) for i in range(ncol)]
    disp = []
    for r in rows:
        cells = [cell(r[i]) if i < len(r) else "" for i in range(ncol)]
        disp.append(cells)
        for i in range(ncol):
            widths[i] = max(widths[i], len(cells[i]))

    header = "  ".join(cols[i].ljust(widths[i]) for i in range(ncol))
    click.echo(click.style(header, bold=True))
    click.echo("  ".join("-" * widths[i] for i in range(ncol)))
    for cells in disp:
        click.echo("  ".join(cells[i].ljust(widths[i]) for i in range(ncol)))


def _resolve_concept(ontologies: List[LocalOntology], predicate: str):
    matches = [(p, c) for p in ontologies for c in p.concepts if c.predicate == predicate]
    if not matches:
        return None, None
    if len(matches) > 1:
        names = ", ".join(sorted({p.name for p, _ in matches}))
        raise click.ClickException(
            f"concept '{predicate}' exists in multiple ontologies ({names}); use --ontology."
        )
    return matches[0]
