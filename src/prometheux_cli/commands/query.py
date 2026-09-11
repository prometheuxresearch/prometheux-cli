"""`px query` — run a read-only SQL SELECT over one populated concept."""

from __future__ import annotations

import json as _json
import sys

import click

from ..sdk import SdkError, connected_sdk


@click.command()
@click.argument("ontology_id")
@click.argument("concept_name")
@click.argument("sql")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON instead of a table.")
def query(ontology_id: str, concept_name: str, sql: str, as_json: bool) -> None:
    """Run SQL (a single SELECT/WITH) over CONCEPT_NAME in ONTOLOGY_ID.

    Example: px query 1db22ad122a tx "SELECT country, count(*) FROM tx GROUP BY country"
    """
    try:
        px, _, _ = connected_sdk(require_token=True)
        data = px.query_concept(ontology_id, concept_name, sql) or {}
    except (SdkError, Exception) as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)

    if as_json:
        click.echo(_json.dumps(data, indent=2, default=str))
        return

    results = data.get("results") or {} if isinstance(data, dict) else {}
    cols = results.get("columnNames") or []
    facts = results.get("facts") or []
    if not facts:
        click.echo("0 rows.")
        return
    widths = [len(str(c)) for c in cols]
    norm = [[str(v) for v in (row if isinstance(row, list) else [row])] for row in facts]
    for row in norm:
        for i, v in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(v))
    if cols:
        click.echo("  " + "  ".join(click.style(str(c).ljust(widths[i]), dim=True)
                                    for i, c in enumerate(cols)))
    for row in norm:
        click.echo("  " + "  ".join(v.ljust(widths[i]) if i < len(widths) else v
                                    for i, v in enumerate(row)))
    click.echo(f"\n  {data.get('row_count', len(facts))} row(s).")
