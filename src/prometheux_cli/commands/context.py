"""`px context` — apply the context layer (notes + links) from manifests.

Idempotent: a small CLI-owned state file (`.px/context-state.json`) maps each
note's identity `(manifest, referenced path)` to its server note id + a content
hash, so re-applying updates changed notes, skips unchanged ones, and (with
--prune) deletes notes dropped from the manifests. Note-to-note and
note-to-concept links are re-asserted each run (edges are idempotent server-side).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ..context import build_pulled_context, collect_context, note_content_hash
from ..loader import load_workspace
from ..sdk import SdkError, connected_sdk
from ..validation import find_workspace_root


@click.group()
def context() -> None:
    """Manage the context layer (knowledge notes) as code."""


@context.command("search")
@click.argument("query")
@click.option("--scope", default="global", type=click.Choice(["global", "project"]),
              help="Context scope to search. `project` = one ontology (needs --ontology).")
@click.option("--ontology", "ontology_id", default=None, help="Ontology id when --scope project.")
@click.option("--top-k", "top_k", default=10, show_default=True, help="Max results.")
def context_search(query: str, scope: str, ontology_id: str, top_k: int) -> None:
    """Semantic search across saved context notes."""
    if scope == "project" and not ontology_id:
        click.echo(click.style("FAIL", fg="red", bold=True)
                   + ": --scope project requires --ontology <id>.", err=True)
        sys.exit(1)
    try:
        px, url, _ = connected_sdk(require_token=True)
        notes = px.search_context_notes(query, scope, scope_id=ontology_id, top_k=top_k) or []
    except (SdkError, Exception) as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    if not notes:
        click.echo(f"No context notes matched '{query}'.")
        return
    click.echo(click.style(f"{len(notes)} note(s) for '{query}' at {url}:", bold=True))
    for n in notes:
        nid = str(n.get("id") or "")
        kind = n.get("kind") or ""
        text = " ".join(str(n.get("text") or "").split())
        snippet = text if len(text) <= 80 else text[:79] + "…"
        click.echo(f"  {nid}  {click.style(kind, dim=True)}  {snippet}")


def write_pulled_context_group(px, *, scope: str, scope_id, root: Path, out_dir: Path,
                               manifest_name: str = "pulled.context.md") -> int:
    """Pull the notes for one (scope, scope_id) into a `.context.md` set + seed state.

    ``scope`` is the CLI frontmatter scope (``project`` | ``global``); the server
    speaks ``ontology`` for project scope, so it's mapped here. Writes the manifest
    and body files under ``out_dir`` and merges the seeded idempotency state into
    ``root/.px/context-state.json`` so a following `px context apply` is a no-op.
    Returns the number of notes written (0 when there are none). Shared by
    `px pull` (project scope) and `px context pull` (global scope).
    """
    server_scope = "ontology" if scope == "project" else "global"
    try:
        notes = px.list_context_notes(server_scope, scope_id) or []
    except Exception:  # noqa: BLE001 - context is optional; never fail the pull over it
        return 0

    manifest_abs = out_dir / manifest_name
    try:
        manifest_rel = str(manifest_abs.resolve().relative_to(root.resolve()))
    except ValueError:
        manifest_rel = manifest_name  # out_dir outside root — degrade, still writes files

    built = build_pulled_context(notes, scope=scope, scope_id=scope_id, manifest_rel=manifest_rel)
    if built is None:
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_abs.write_text(built.manifest_text, "utf-8")
    for fname, text in built.body_files:
        (out_dir / fname).write_text(text, "utf-8")

    state = _load_state(root)
    state.update(built.state_entries)
    _save_state(root, state)
    return built.count


@context.command("pull")
@click.option("--out", "out", default=".", type=click.Path(path_type=Path), help="Workspace directory.")
@click.option("--ontology", "ontology_id", default=None,
              help="Also pull this ontology's project-scoped notes into its directory.")
def context_pull(out: Path, ontology_id: str) -> None:
    """Pull global context notes into ./context (and, with --ontology, that ontology's notes).

    Global notes land in `<workspace>/context/pulled.context.md`; the idempotency
    state is seeded so the next `px context apply` reports no changes. `px pull`
    already pulls an ontology's own project-scoped context, so this command's main
    job is the workspace-global layer.
    """
    root = find_workspace_root(out.resolve())
    if root is None:
        click.echo(click.style("FAIL", fg="red", bold=True)
                   + f": no prometheux.workspace.yaml in or above {out.resolve()}", err=True)
        sys.exit(2)
    try:
        px, url, _ = connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)

    total = write_pulled_context_group(px, scope="global", scope_id=None,
                                       root=root, out_dir=root / "context")
    click.echo(
        (click.style("Pulled", fg="green", bold=True)
         + f" {total} global context note(s) to {root / 'context'}.")
        if total else "No global context notes to pull."
    )

    if ontology_id:
        workspace = load_workspace(root)
        onto = next((o for o in workspace.ontologies if o.id == ontology_id), None)
        out_dir = (onto.directory / "context") if (onto and onto.directory) else (root / "context" / ontology_id)
        n = write_pulled_context_group(px, scope="project", scope_id=ontology_id,
                                       root=root, out_dir=out_dir)
        click.echo(
            (click.style("Pulled", fg="green", bold=True)
             + f" {n} project note(s) for {ontology_id} to {out_dir}.")
            if n else f"No project context notes for {ontology_id}."
        )
    click.echo("Next: `px context apply` (should report no changes)")


def apply_context_layer(px, root: Path, workspace, *, note_filter=None,
                        assume_yes: bool = False, prune: bool = False,
                        header: str = None) -> bool:
    """Apply context notes + links from the workspace's `*.context.md` (idempotent).

    The shared core of `px context apply`; `px apply` calls it too, passing a
    ``note_filter`` so it applies only the context that belongs to the ontologies
    it just applied (project-scoped notes whose owning ontology is in scope).

    - ``note_filter(note) -> bool`` restricts which notes are managed. When set
      (the embedded call), pruning is bounded to the manifests those notes live in,
      so an ontology apply never deletes another ontology's — or the global —
      context. When None (the standalone command), everything is in scope.
    - ``header`` prints a section title first (embedded call); standalone stays quiet.

    Returns True on success or no-op, False only when the user declined the confirm.
    """
    notes, links, warnings = collect_context(workspace)
    if note_filter is not None:
        notes = [n for n in notes if note_filter(n)]
    for w in warnings:
        click.echo(f"  {click.style('warning', fg='yellow')} {w}")

    state = _load_state(root)
    # Embedded call with nothing in scope: say nothing, do nothing.
    if note_filter is not None and not notes:
        return True
    if not notes and not state:
        click.echo("No context notes found (no *.context.md manifests).")
        return True

    adopted = _reconcile_with_server(notes, state)
    if adopted:
        click.echo(f"  reconciled {adopted} note(s) with the server (adopted matches / healed stale ids)")

    plan = [(n, _classify(n, state)) for n in notes]
    seen_keys = {_ref_str(n) for n, _ in plan}
    # When a filter is in play, only prune notes from manifests we actually manage
    # this run — never global or other-ontology notes that were filtered out.
    prune_manifests = {n.ref_key[0] for n, _ in plan} if note_filter is not None else None
    removed = [
        k for k in state
        if k not in seen_keys and (prune_manifests is None or k.split("::", 1)[0] in prune_manifests)
    ]

    counts = {"create": 0, "update": 0, "unchanged": 0}
    for _, action in plan:
        counts[action] += 1

    if header:
        click.echo(header)
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
        return False

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
            continue  # an endpoint outside the managed set (e.g. filtered out) — skip
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
    return True


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
    if not apply_context_layer(px, root, workspace, assume_yes=assume_yes, prune=prune):
        sys.exit(1)


# ── state + classification ────────────────────────────────────────────────

def _ref_str(note) -> str:
    return f"{note.ref_key[0]}::{note.ref_key[1]}"


def _hash(note) -> str:
    return note_content_hash(note.scope, note.scope_id, note.kind, note.activation, note.text)


def _classify(note, state) -> str:
    prev = state.get(_ref_str(note))
    if not prev:
        return "create"
    return "unchanged" if prev.get("hash") == _hash(note) else "update"


def _reconcile_with_server(notes, state) -> int:
    """Reconcile local state with the server's notes before classifying.

    The idempotency state (`.px/context-state.json`) drifts from the server two
    ways, and both would corrupt the plan:

    - **Missing from state** (fresh checkout, another machine, CI, corruption, or
      the state seeded by `px pull`). Without reconciling, every note reclassifies
      as `create` and is pushed again, duplicating notes already on the server. We
      adopt the server note whose text matches, so it classifies unchanged/update.

    - **Stale id in state** — the state names a note id that no longer exists on
      the server (the ontology was deleted and recreated, so its notes — and their
      ids — are gone; or the note was deleted directly). Left alone, the note
      classifies as unchanged/update and we would skip it or PATCH a dead id, so
      the note is silently never restored. We re-adopt by text when the server has
      a matching note, otherwise drop the entry so it re-creates cleanly.

    Returns the number of notes reconciled (adopted or healed).
    """
    if not notes:
        return 0
    try:
        from prometheux_chain.client.jarvispy_client import JarvisPyClient
    except Exception:  # noqa: BLE001 - SDK missing → skip reconcile
        return 0

    index: dict = {}      # (scope, scope_id) -> {text: note_id}
    live_ids: dict = {}   # (scope, scope_id) -> {note_id, …}
    loaded_ok: dict = {}  # (scope, scope_id) -> did the server list succeed?

    def _load(scope, scope_id) -> None:
        key = (scope, scope_id)
        if key in index:
            return
        by_text: dict = {}
        ids: set = set()
        ok = False
        try:
            resp = JarvisPyClient.list_context_notes(scope, scope_id)
            data = (resp or {}).get("data")
            if isinstance(data, list):
                ok = True  # a real listing — absence now means the note is gone
                for sn in data:
                    if not isinstance(sn, dict):
                        continue
                    nid = sn.get("id")
                    if nid is not None:
                        ids.add(str(nid))
                    txt = sn.get("text")
                    if txt is not None and txt not in by_text:
                        by_text[txt] = str(nid) if nid is not None else None
        except Exception:  # noqa: BLE001 - best-effort; inconclusive → don't heal
            ok = False
        index[key] = by_text
        live_ids[key] = ids
        loaded_ok[key] = ok

    reconciled = 0
    for n in notes:
        key_str = _ref_str(n)
        prev = state.get(key_str)
        scope_key = (n.scope, n.scope_id)
        if prev and prev.get("id"):
            _load(*scope_key)
            # Only heal when the listing succeeded; a failed/garbled fetch is
            # inconclusive and must not drop a note that may still exist.
            if not loaded_ok.get(scope_key) or str(prev["id"]) in live_ids.get(scope_key, set()):
                continue
            adopted_id = index.get(scope_key, {}).get(n.text)  # re-adopt by text…
            if adopted_id:
                state[key_str] = {"id": adopted_id, "hash": _hash(n)}
            else:
                state.pop(key_str, None)                        # …else re-create
            reconciled += 1
        elif not prev:
            _load(*scope_key)
            note_id = index.get(scope_key, {}).get(n.text)
            if note_id:
                state[key_str] = {"id": note_id, "hash": _hash(n)}
                reconciled += 1
    return reconciled


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
