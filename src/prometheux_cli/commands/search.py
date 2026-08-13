"""`px search` — semantic search across the platform (concepts, company KB)."""

from __future__ import annotations

import sys

import click

from ..sdk import SdkError, connected_sdk, rest_data


@click.group()
def search() -> None:
    """Semantic search (concepts / company knowledge)."""


def _connect():
    try:
        connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)


@search.command("concepts")
@click.argument("query_text")
@click.option("--top-k", "top_k", default=5, show_default=True, help="Max matches.")
@click.option("--exclude", "exclude_ontology_id", default="", help="Ontology id to exclude from results.")
@click.option("--scope", default="user", type=click.Choice(["user", "organization"]))
def concepts_cmd(query_text: str, top_k: int, exclude_ontology_id: str, scope: str) -> None:
    """Find existing concepts across ontologies similar to QUERY_TEXT (to reuse)."""
    _connect()
    try:
        data = rest_data("GET", "/api/v1/concepts/search-similar", params={
            "query": query_text, "top_k": top_k,
            "exclude_project_id": exclude_ontology_id,  # wire alias for exclude_ontology_id
            "scope": scope,
        }) or {}
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    matches = (data.get("matches") if isinstance(data, dict) else data) or []
    if not matches:
        click.echo(f"No concepts similar to '{query_text}'.")
        return
    click.echo(click.style(f"{len(matches)} similar concept(s) for '{query_text}':", bold=True))
    for m in matches:
        sim = m.get("similarity")
        sim_s = f"{sim:.2f}" if isinstance(sim, (int, float)) else str(sim or "")
        click.echo(f"  {click.style(sim_s, dim=True)}  {m.get('concept_name', '')}"
                   f"  ({m.get('ontology_name') or m.get('ontology_id')})")


@search.command("company")
@click.argument("query_text")
def company_cmd(query_text: str) -> None:
    """Search the Prometheux company knowledge base."""
    _connect()
    try:
        data = rest_data("GET", "/api/v1/assistant/company-info", params={"query": query_text}) or {}
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    content = data.get("content") if isinstance(data, dict) else data
    click.echo(content or "(no content)")
