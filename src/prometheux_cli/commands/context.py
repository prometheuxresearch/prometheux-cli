"""`px context` — apply the context layer (notes + links) from manifests."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from ..context import collect_context
from ..loader import load_workspace
from ..sdk import SdkError, connected_sdk
from ..validation import find_workspace_root


@click.group()
def context() -> None:
    """Manage the context layer (knowledge notes) as code."""


@context.command("apply")
@click.argument("path", required=False, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
def context_apply(path: Path, assume_yes: bool) -> None:
    """Create context notes + links from every *.context.md in the workspace.

    Notes are created (not upserted) — re-applying adds duplicates for now.
    """
    start = path or Path.cwd()
    root = find_workspace_root(start)
    if root is None:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": no prometheux.workspace.yaml in or above {start}", err=True)
        sys.exit(2)

    try:
        px, _, _ = connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)

    workspace = load_workspace(root)
    notes, links, warnings = collect_context(workspace)
    for w in warnings:
        click.echo(f"  {click.style('warning', fg='yellow')} {w}")
    if not notes:
        click.echo("No context notes found (no *.context.md manifests).")
        return

    click.echo(f"\nContext plan: {len(notes)} note(s), {len(links)} link(s).")
    for n in notes:
        loc = f"{n.scope}" + (f":{n.scope_id}" if n.scope_id else "")
        click.echo(f"  + note {n.ref_key[1]}  ({loc}, {n.activation})")
    if not assume_yes and not click.confirm("\nApply context?", default=False):
        click.echo("Aborted.")
        sys.exit(1)

    ids = {}
    created = 0
    for n in notes:
        try:
            note_id = _create_note(px, n)
            ids[n.ref_key] = note_id
            created += 1
            click.echo(f"  created note {n.ref_key[1]} ({note_id})")
        except Exception as exc:  # noqa: BLE001
            click.echo(f"  {click.style('warning', fg='yellow')} note {n.ref_key[1]} failed: {exc}")

    edges = 0
    for link in links:
        src = _endpoint_ref(link.src, ids)
        dst = _endpoint_ref(link.dst, ids)
        if src is None or dst is None:
            continue
        try:
            _create_edge(px, src, dst, link.relation)
            edges += 1
            if link.dst.kind == "concept" or link.src.kind == "concept":
                click.echo(f"  linked {src[1]} → {dst[1]} ({link.relation})")
        except Exception as exc:  # noqa: BLE001
            click.echo(f"  {click.style('warning', fg='yellow')} link {link.relation} failed: {exc}")

    click.echo(click.style("Applied context", fg="green", bold=True) + f": {created} note(s), {edges} link(s).")


def _endpoint_ref(endpoint, note_ids):
    """Return (type, id) for an edge endpoint, or None if a note id is missing."""
    if endpoint.kind == "concept":
        return ("concept", endpoint.concept_id)
    note_id = note_ids.get(endpoint.note_key)
    return ("note", note_id) if note_id else None


def _create_note(px, note):
    """Create one note. Uses the SDK for the default activation; the REST client
    for `always`/`on_demand`, which the SDK does not yet expose."""
    if note.activation == "retrieved":
        res = px.create_context_note(scope=note.scope, kind=note.kind, text=note.text, scope_id=note.scope_id)
        return (res or {}).get("id")
    from prometheux_chain.client.jarvispy_client import JarvisPyClient
    resp = JarvisPyClient._request("POST", "/api/v1/knowledge/context", json={
        "scope": note.scope, "scope_id": note.scope_id, "kind": note.kind,
        "text": note.text, "activation": note.activation, "title": note.title, "source": "import",
    })
    return ((resp or {}).get("data") or {}).get("id")


def _create_edge(px, src, dst, relation):
    """src/dst are (type, id) tuples where type is 'note' or 'concept'."""
    from prometheux_chain.client.jarvispy_client import JarvisPyClient
    JarvisPyClient._request("POST", "/api/v1/knowledge/context/edges", json={
        "src_type": src[0], "src_id": src[1], "dst_type": dst[0], "dst_id": dst[1],
        "relation": relation, "created_by": "user",
    })
