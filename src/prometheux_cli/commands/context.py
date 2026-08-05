"""`px context` — apply the context layer (notes + links) from manifests.

Idempotent: a small CLI-owned state file (`.px/context-state.json`) maps each
note's identity `(manifest, referenced path)` to its server note id + a content
hash, so re-applying updates changed notes, skips unchanged ones, and (with
--prune) deletes notes dropped from the manifests. Note-to-note and
note-to-concept links are re-asserted each run (edges are idempotent server-side).
"""

from __future__ import annotations

import hashlib
import json
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
@click.option("--prune", is_flag=True, help="Delete notes previously applied but no longer in any manifest.")
def context_apply(path: Path, assume_yes: bool, prune: bool) -> None:
    """Apply context notes + links from every *.context.md in the workspace (idempotent)."""
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

    state = _load_state(root)
    if not notes and not state:
        click.echo("No context notes found (no *.context.md manifests).")
        return

    plan = [(n, _classify(n, state)) for n in notes]
    seen_keys = {_ref_str(n) for n, _ in plan}
    removed = [k for k in state if k not in seen_keys]

    counts = {"create": 0, "update": 0, "unchanged": 0}
    for _, action in plan:
        counts[action] += 1
    click.echo(
        f"\nContext plan: {counts['create']} create, {counts['update']} update, "
        f"{counts['unchanged']} unchanged, {len(links)} link(s)"
        + (f", {len(removed)} to prune" if removed else "")
    )
    for n, action in plan:
        if action != "unchanged":
            loc = n.scope + (f":{n.scope_id}" if n.scope_id else "")
            click.echo(f"  {_sym(action)} note {n.ref_key[1]}  ({loc}, {n.activation})")
    if removed and prune:
        for k in removed:
            click.echo(f"  - note {k}  prune")

    if not (counts["create"] or counts["update"] or (removed and prune)):
        click.echo("\nContext up to date. Re-asserting links.")
    elif not assume_yes and not click.confirm("\nApply context?", default=False):
        click.echo("Aborted.")
        sys.exit(1)

    new_state = dict(state)
    ids = {}
    for n, action in plan:
        key = _ref_str(n)
        try:
            if action == "unchanged":
                ids[n.ref_key] = state[key]["id"]
            elif action == "update":
                _update_note(px, state[key]["id"], n)
                ids[n.ref_key] = state[key]["id"]
                new_state[key] = {"id": state[key]["id"], "hash": _hash(n)}
                click.echo(f"  updated note {n.ref_key[1]}")
            else:
                note_id = _create_note(px, n)
                ids[n.ref_key] = note_id
                new_state[key] = {"id": note_id, "hash": _hash(n)}
                click.echo(f"  created note {n.ref_key[1]} ({note_id})")
        except Exception as exc:  # noqa: BLE001
            click.echo(f"  {click.style('warning', fg='yellow')} note {n.ref_key[1]} failed: {exc}")

    pruned = 0
    for key in removed:
        if prune:
            try:
                px.delete_context_note(state[key]["id"])
                new_state.pop(key, None)
                pruned += 1
            except Exception as exc:  # noqa: BLE001
                click.echo(f"  {click.style('warning', fg='yellow')} prune {key} failed: {exc}")
        else:
            click.echo(f"  {click.style('note', fg='yellow')} {key} no longer in manifests (use --prune to delete)")

    edges = 0
    for link in links:
        src, dst = _endpoint_ref(link.src, ids), _endpoint_ref(link.dst, ids)
        if src is None or dst is None:
            continue
        try:
            _create_edge(px, src, dst, link.relation)
            edges += 1
        except Exception as exc:  # noqa: BLE001
            click.echo(f"  {click.style('warning', fg='yellow')} link {link.relation} failed: {exc}")

    _save_state(root, new_state)
    click.echo(
        click.style("Applied context", fg="green", bold=True)
        + f": {counts['create']} created, {counts['update']} updated, "
        f"{counts['unchanged']} unchanged, {pruned} pruned, {edges} link(s)."
    )


# ── state + classification ────────────────────────────────────────────────

def _ref_str(note) -> str:
    return f"{note.ref_key[0]}::{note.ref_key[1]}"


def _hash(note) -> str:
    payload = "|".join([note.scope, note.scope_id or "", note.kind, note.activation, note.text])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _classify(note, state) -> str:
    prev = state.get(_ref_str(note))
    if not prev:
        return "create"
    return "unchanged" if prev.get("hash") == _hash(note) else "update"


def _state_path(root: Path) -> Path:
    return root / ".px" / "context-state.json"


def _load_state(root: Path) -> dict:
    p = _state_path(root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(root: Path, state: dict) -> None:
    p = _state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True), "utf-8")


def _sym(action: str) -> str:
    return {"create": click.style("+", fg="green"), "update": click.style("~", fg="yellow")}.get(action, "=")


# ── platform writes ───────────────────────────────────────────────────────

def _endpoint_ref(endpoint, note_ids):
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


def _update_note(px, note_id, note):
    """Update an existing note's body/kind (and activation when non-default)."""
    if note.activation == "retrieved":
        px.update_context_note(note_id, text=note.text, kind=note.kind)
        return
    from prometheux_chain.client.jarvispy_client import JarvisPyClient
    JarvisPyClient._request("PATCH", f"/api/v1/knowledge/context/{note_id}", json={
        "text": note.text, "kind": note.kind, "activation": note.activation,
    })


def _create_edge(px, src, dst, relation):
    """src/dst are (type, id) tuples where type is 'note' or 'concept'."""
    from prometheux_chain.client.jarvispy_client import JarvisPyClient
    JarvisPyClient._request("POST", "/api/v1/knowledge/context/edges", json={
        "src_type": src[0], "src_id": src[1], "dst_type": dst[0], "dst_id": dst[1],
        "relation": relation, "created_by": "user",
    })
