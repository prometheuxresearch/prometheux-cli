"""`px list` — browse the platform's resources (read-only).

Each subcommand prints a small table whose first column is the identifier you
pass to other `px` commands (the id) and whose remaining columns are the
human-readable name and a little context. Nothing is written; these are pure
reads over the SDK's `list_*` endpoints.
"""

from __future__ import annotations

import sys
from typing import List, Sequence

import click

from ..sdk import SdkError, connected_sdk

_SCOPE = click.option(
    "--scope",
    default="user",
    type=click.Choice(["user", "organization"]),
    help="Which scope to list from.",
)


@click.group()
def list_() -> None:
    """List platform resources (ontologies, apps, datasources, context)."""


@list_.command("ontologies")
@_SCOPE
def list_ontologies(scope: str) -> None:
    """List ontologies. The ID is what `px pull` / `px delete` take."""
    px, url, _ = _connect()
    rows = _call(lambda: px.list_ontologies([scope]) or [])
    _print_table(
        f"Ontologies at {url} (scope: {scope})",
        ["ID", "NAME", "AUTHOR"],
        [[o.get("id"), o.get("name"), o.get("author")] for o in rows],
        empty=f"No {scope}-scoped ontologies.",
        hint="Pull one with: px pull <id>",
    )


@list_.command("concepts")
@click.option("--ontology", "ontology_id", required=True, help="Ontology id whose concepts to list.")
@_SCOPE
def list_concepts(ontology_id: str, scope: str) -> None:
    """List an ontology's concepts. The PREDICATE is what `px run` / `px show` take."""
    px, url, _ = _connect()
    rows = _call(lambda: px.list_concepts(ontology_id, scope) or [])
    _print_table(
        f"Concepts in {ontology_id} at {url}",
        ["PREDICATE", "TYPE", "GROUP", "POPULATED"],
        [[c.get("predicate_name") or c.get("id"), c.get("concept_type"),
          c.get("group"), "yes" if c.get("is_populated") else "no"] for c in rows],
        empty=f"No concepts in ontology {ontology_id}.",
    )


@list_.command("apps")
@_SCOPE
def list_apps(scope: str) -> None:
    """List apps across all your ontologies. The ID is the app identifier."""
    px, url, _ = _connect()
    rows = _call(lambda: px.list_all_apps(scope) or [])
    _print_table(
        f"Apps at {url} (scope: {scope})",
        ["ID", "NAME", "ONTOLOGY", "STATUS"],
        [[a.get("id"), a.get("name"), a.get("project_name") or a.get("project_id"),
          a.get("status")] for a in rows],
        empty=f"No {scope}-scoped apps.",
    )


@list_.command("datasources")
@_SCOPE
def list_datasources(scope: str) -> None:
    """List connected datasources. The ID is the datasource identifier."""
    px, url, _ = _connect()
    rows = _call(lambda: px.list_sources(scope) or [])
    _print_table(
        f"Datasources at {url} (scope: {scope})",
        ["ID", "TABLE", "TYPE", "PREDICATE"],
        [[s.get("id") or s.get("datasource_id"), s.get("table_name"),
          s.get("datasource_type"), s.get("predicate_placeholder")] for s in rows],
        empty=f"No {scope}-scoped datasources.",
    )


@list_.command("context")
@click.option("--scope", default="global", type=click.Choice(["global", "project"]),
              help="Context scope. `project` = scoped to one ontology (requires --ontology).")
@click.option("--ontology", "ontology_id", default=None,
              help="Ontology id — required when --scope project.")
def list_context(scope: str, ontology_id: str) -> None:
    """List context notes. The ID is what `px context` state / edges reference."""
    if scope == "project" and not ontology_id:
        _fail("--scope project requires --ontology <id>.")
    px, url, _ = _connect()
    rows = _call(lambda: px.list_context_notes(scope, ontology_id) or [])
    loc = f"{scope}:{ontology_id}" if ontology_id else scope
    _print_table(
        f"Context notes at {url} (scope: {loc})",
        ["ID", "KIND", "SCOPE", "TEXT"],
        [[n.get("id"), n.get("kind"),
          (n.get("scope") or "") + (f":{n['scope_id']}" if n.get("scope_id") else ""),
          _snippet(n.get("text"))] for n in rows],
        empty=f"No context notes in scope {loc}.",
    )


# ── helpers ─────────────────────────────────────────────────────────────────

def _connect():
    try:
        return connected_sdk(require_token=True)
    except SdkError as exc:
        _fail(str(exc))


def _call(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - surface SDK/HTTP errors cleanly
        _fail(str(exc))


def _fail(msg: str) -> None:
    click.echo(click.style("FAIL", fg="red", bold=True) + f": {msg}", err=True)
    sys.exit(1)


def _snippet(text, width: int = 60) -> str:
    """One-line, bounded preview of a note body so listings stay scannable."""
    if not text:
        return ""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def _print_table(title: str, headers: Sequence[str], rows: List[List[object]],
                 *, empty: str, hint: str = "") -> None:
    """Print a fixed-width table; the first column is the copy-me id."""
    click.echo(click.style(title, bold=True))
    cells = [["" if c is None else str(c) for c in row] for row in rows]
    if not cells:
        click.echo(f"  {empty}")
        return
    widths = [len(h) for h in headers]
    for row in cells:
        for i, c in enumerate(row):
            widths[i] = max(widths[i], len(c))
    click.echo("  " + "  ".join(click.style(h.ljust(widths[i]), dim=True)
                                for i, h in enumerate(headers)))
    for row in cells:
        click.echo("  " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))
    click.echo(f"\n  {len(cells)} result(s).")
    if hint:
        click.echo(hint)
