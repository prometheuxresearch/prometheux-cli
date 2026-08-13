"""`px apply` — write local changes to the platform, gated by a plan preview."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Dict, List

import click

from ..apply import (
    concept_save_kwargs,
    generative_concept_config,
    is_generative,
    topo_order,
)
from ..context import build_note_resolver
from ..datasources import (
    SecretError,
    bind_template_from_sources,
    database_kwargs,
    file_database_kwargs,
    is_file_based,
    resolve_secrets,
)
from ..loader import LocalOntology, load_workspace, select_ontologies
from ..plan import (
    PlanResult,
    fetch_server_apps,
    fetch_server_datasources,
    fetch_server_sources,
    plan_ontology,
)
from ..sdk import SdkError, connected_sdk
from ..validation import find_workspace_root
from .plan import _render


@click.command()
@click.argument("path", required=False, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--ontology", "-o", "ontology_selectors", multiple=True,
              help="Only apply the named ontology(s), by name / directory slug / id. Repeatable.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--prune", is_flag=True, help="Also delete concepts present on the server but not in files.")
@click.option("--no-snapshot", is_flag=True, help="Do not snapshot each ontology before applying.")
@click.option("--with-files", "with_files", is_flag=True,
              help="Re-upload file datasources even when an identical one already exists "
                   "on the account (refresh content). New files always upload.")
def apply(path: Path, ontology_selectors, assume_yes: bool, prune: bool, no_snapshot: bool,
          with_files: bool) -> None:
    """Apply the workspace to the platform.

    Shows the same diff as `px plan`, then (after confirmation) creates/updates
    concepts. Deletions happen only with --prune. Each changed ontology is
    snapshotted first so an apply is recoverable. Use --ontology to target a
    subset instead of the whole workspace. A file datasource that already exists
    on the account is reused (not re-uploaded) unless --with-files is given.
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
    jobs = []
    for ontology in ontologies:
        export = _export(px, ontology)
        original_id = ontology.id  # the manifest id before any recreate (may be from another account)
        if ontology.id and _ontology_missing(export):
            click.echo(
                f"  {click.style('warning', fg='yellow')} ontology id {ontology.id} not found on "
                f"server — recreating '{ontology.name}'."
            )
            ontology.id = None
            export = None
        server_apps = fetch_server_apps(px, ontology.id, ontology.scope) if ontology.id else None
        server_sources = fetch_server_sources(px, ontology.id, ontology.scope) if ontology.id else None
        server_datasources = fetch_server_datasources(px, ontology.scope)
        result = plan_ontology(ontology, export, note_resolver=resolve_notes,
                              server_apps=server_apps, server_sources=server_sources,
                              server_datasources=server_datasources, with_files=with_files)
        _render(result, is_new=ontology.id is None)
        if result.has_changes or (prune and result.to_delete):
            jobs.append((ontology, result, original_id))

    if not jobs:
        click.echo("\nNo changes to apply.")
        return

    if not prune and any(r.to_delete for _, r, _ in jobs):
        click.echo(
            "\n"
            + click.style("note", fg="yellow")
            + ": deletions are withheld. Re-run with --prune to remove them."
        )

    if not assume_yes:
        click.echo("")
        if not click.confirm("Apply these changes?", default=False):
            click.echo("Aborted. Nothing was changed.")
            sys.exit(1)

    # Shared across ontologies so an app in one ontology can reference another whose
    # id changed (e.g. recreated on a different account).
    id_remap: Dict[str, str] = {}
    skipped: Dict[str, List[str]] = {}
    for ontology, result, original_id in jobs:
        ontology_skips = _apply_ontology(
            px, ontology, result, prune=prune, snapshot=not no_snapshot,
            resolve_notes=resolve_notes, original_id=original_id, id_remap=id_remap)
        if ontology_skips:
            skipped[ontology.name] = ontology_skips

    if skipped:
        total = sum(len(v) for v in skipped.values())
        click.echo(
            "\n" + click.style("Done with skips", fg="yellow", bold=True)
            + f": {total} concept(s) could not be applied (unresolved references):"
        )
        for pname, preds in skipped.items():
            click.echo(f"  {pname}: {', '.join(preds)}")
        sys.exit(1)


def _ontology_missing(export) -> bool:
    """True when an export has no ontology row — the id no longer exists server-side."""
    if not export:
        return True
    for name, tbl in (export.get("tables") or {}).items():
        if name.startswith("projects_") and (tbl or {}).get("data"):
            return False
    return True


def _export(px, ontology: LocalOntology):
    if not ontology.id:
        return None
    try:
        return px.export_ontology(ontology.id, ontology.scope)
    except Exception as exc:  # noqa: BLE001
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": export of ontology {ontology.id} failed: {exc}",
            err=True,
        )
        sys.exit(1)


def _apply_ontology(px, ontology: LocalOntology, result: PlanResult, *, prune: bool, snapshot: bool,
                   resolve_notes=None, original_id=None, id_remap=None) -> None:
    click.echo(f'\nApplying "{ontology.name}"…')

    # Create the ontology first if it is brand-new, and persist the id to disk.
    if not ontology.id:
        ontology.id = _resolve_or_create_ontology(px, ontology)
        _persist_ontology_id(ontology)

    # Record how this ontology's id resolved, so apps (in any ontology) that embed
    # the manifest's original id get it rewritten to the actual server id. This
    # is what makes a ontology with an app portable across accounts.
    if id_remap is not None and ontology.id:
        if original_id and original_id != ontology.id:
            id_remap[original_id] = ontology.id
        id_remap.setdefault(ontology.id, ontology.id)

    if snapshot:
        try:
            px.create_snapshot(ontology.id, ontology.scope, "pre-apply via px")
            click.echo("  snapshot taken (pre-apply)")
        except Exception as exc:  # noqa: BLE001 - snapshot is best-effort safety
            click.echo(f"  {click.style('warning', fg='yellow')} snapshot failed: {exc}")

    failed_ds, ds_binds = _apply_datasources(px, ontology, result)

    to_write = {c.predicate for c in result.concept_changes if c.action in {"create", "update"}}
    updates = {c.predicate for c in result.concept_changes if c.action == "update"}
    by_pred = {c.predicate: c for c in ontology.concepts}

    # Save deps-before-dependents; but topo_order derives edges from body
    # predicate references and can miss a reference inside embedded SQL/Cypher
    # (e.g. `... FROM other_concept`). So retry concepts whose save failed only
    # because an upstream reference didn't resolve yet — additional passes create
    # them once their upstream exists. Genuinely-missing deps / cycles surface
    # when a pass makes no progress.
    applied = 0
    skipped: List[str] = []
    pending = topo_order([by_pred[p] for p in to_write if p in by_pred])
    last_error: Dict[str, str] = {}
    while pending:
        deferred = []
        progressed = False
        for concept in pending:
            kwargs = concept_save_kwargs(concept, update=concept.predicate in updates,
                                         datasource_binds=ds_binds, ontology_id=ontology.id)
            try:
                if is_generative(concept):
                    _save_generative_concept(ontology, concept, kwargs, resolve_notes)
                else:
                    px.save_concept(ontology_id=ontology.id, scope=ontology.scope, **kwargs)
                verb = "updated" if concept.predicate in updates else "created"
                click.echo(f"  {verb} concept {concept.predicate}")
                applied += 1
                progressed = True
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if _is_unresolved_reference(msg):
                    deferred.append(concept)
                    last_error[concept.predicate] = msg
                    continue
                # A genuine save error (parse, conflict, …) still aborts fast.
                click.echo(
                    click.style("FAIL", fg="red", bold=True)
                    + f": save of concept {concept.predicate} failed: {exc}",
                    err=True,
                )
                sys.exit(1)
        if deferred and not progressed:
            # These reference something that never resolves (a source defect, or a
            # dependency not part of this apply). Skip them and keep going — the
            # rest of the ontology (and the ontology schema / apps) still applies;
            # the skips are reported and make the apply exit non-zero.
            for concept in deferred:
                reason = _reference_detail(last_error.get(concept.predicate, ""))
                click.echo(
                    f"  {click.style('skipped', fg='yellow', bold=True)} concept "
                    f"{concept.predicate}: unresolved reference{reason}"
                )
                skipped.append(concept.predicate)
            break
        pending = deferred

    if result.ontology_change in {"create", "update"} and ontology.ontology_schema:
        try:
            px.save_ontology_schema(ontology.id, ontology.ontology_schema, ontology.scope)
            verb = "created" if result.ontology_change == "create" else "updated"
            click.echo(f"  {verb} ontology schema")
        except Exception as exc:  # noqa: BLE001
            click.echo(
                click.style("FAIL", fg="red", bold=True)
                + f": save of ontology schema failed: {exc}",
                err=True,
            )
            sys.exit(1)

    _apply_apps(px, ontology, result, prune=prune, id_remap=id_remap)

    if prune:
        deletes = [c.predicate for c in result.concept_changes if c.action == "delete"]
        if deletes:
            try:
                px.cleanup_concepts(ontology.id, ontology.scope, deletes)
                click.echo(f"  pruned {len(deletes)} concept(s): {', '.join(deletes)}")
            except Exception as exc:  # noqa: BLE001
                click.echo(f"  {click.style('warning', fg='yellow')} prune failed: {exc}")

    stale = {p for downstream in result.cascade.values() for p in downstream}
    click.echo(
        click.style("Applied", fg="green", bold=True)
        + f": {applied} concept(s) written to '{ontology.name}'."
        + (f" {len(skipped)} skipped." if skipped else "")
    )
    if failed_ds:
        click.echo(f"  {len(failed_ds)} datasource(s) not connected: {', '.join(failed_ds)}")
    if stale:
        click.echo(f"  downstream now stale: {', '.join(sorted(stale))} — `px run` to rebuild.")
    return skipped


def _remap_app_project_ids(definition: dict, id_remap, owning_id=None) -> dict:
    """Rewrite each page's ``ontology.id`` so the app points at the right ontology here.

    An app authored against one ontology id (e.g. on another account) embeds that
    id in every page; without rewriting, the server validates the app against a
    ontology that doesn't exist here and every concept reference fails. Two cases:
    - the id is in ``id_remap`` (a ontology applied in this run) -> use the mapping;
    - the id is stale/foreign (not any ontology in this run) -> assume it means the
      app's own ontology and rewrite to ``owning_id``. This covers a copy where the
      manifest id was cleared, so no old->new mapping exists.
    """
    id_remap = id_remap or {}
    known = set(id_remap.values())
    for page in definition.get("pages") or []:
        if not isinstance(page, dict):
            continue
        proj = page.get("project")
        if not isinstance(proj, dict):
            continue
        pid = proj.get("id")
        if pid in id_remap:
            proj["id"] = id_remap[pid]
        elif owning_id and pid and pid != owning_id and pid not in known:
            proj["id"] = owning_id
    return definition


def _apply_apps(px, ontology: LocalOntology, result: PlanResult, *, prune: bool, id_remap=None) -> None:
    """Create/update apps via ``save_app``; delete server-only apps with --prune.

    A file without an ``id`` that matched an existing app by name adopts that
    server id before saving (so it updates in place, not duplicates) and the id
    is written back to the file. A newly created app's assigned id is likewise
    persisted, so the next apply is idempotent.
    """
    import copy

    by_identity = {a.identity: a for a in ontology.apps}
    for change in result.app_changes:
        if change.action in {"create", "update"}:
            app = by_identity.get(change.identity)
            if app is None:
                continue
            definition = _remap_app_project_ids(copy.deepcopy(app.definition), id_remap, ontology.id)
            if change.server_id and not definition.get("id"):
                definition["id"] = change.server_id
            try:
                res = px.save_app(ontology.id, definition, ontology.scope)
                new_id = (res or {}).get("id") if isinstance(res, dict) else res
                verb = "created" if change.action == "create" else "updated"
                click.echo(f"  {verb} app {app.name}")
                if new_id and not app.has_id and app.file:
                    _persist_app_id(app.file, new_id)
            except Exception as exc:  # noqa: BLE001
                click.echo(
                    click.style("FAIL", fg="red", bold=True)
                    + f": save of app {app.name} failed: {exc}",
                    err=True,
                )
                sys.exit(1)
        elif change.action == "delete" and prune and change.server_id:
            try:
                px.delete_app(ontology.id, change.server_id, ontology.scope)
                click.echo(f"  pruned app {change.name}")
            except Exception as exc:  # noqa: BLE001
                click.echo(f"  {click.style('warning', fg='yellow')} prune app {change.name} failed: {exc}")


def _persist_app_id(app_file: Path, app_id: str) -> None:
    """Write the server-assigned id back into an app file (idempotent re-apply)."""
    import yaml

    if not app_file or not app_file.is_file():
        return
    data = yaml.safe_load(app_file.read_text("utf-8")) or {}
    if data.get("id") == app_id:
        return
    # Keep `id` near the top for readability, preserving the rest of the order.
    reordered = {}
    if "$schema" in data:
        reordered["$schema"] = data.pop("$schema")
    reordered["id"] = app_id
    reordered.update(data)
    app_file.write_text(yaml.safe_dump(reordered, sort_keys=False, allow_unicode=True), "utf-8")


def _save_generative_concept(ontology: LocalOntology, concept, kwargs: dict, resolve_notes) -> None:
    """Save a context or llm concept with its ``concept_config``.

    The SDK's ``save_concept`` does not forward ``concept_config``, so this posts
    to the same ``/save`` endpoint directly (the established SDK-gap workaround).
    A static context concept's ``notes:`` paths are resolved to server note ids
    via the context-state; unresolved or ambiguous paths are warned, never guessed.
    """
    from prometheux_chain.client.jarvispy_client import JarvisPyClient

    note_ids: List[str] = []
    meta = concept.meta or {}
    if (
        concept.concept_type == "context"
        and (meta.get("contextMode") or "static").strip().lower() != "dynamic"
        and not (meta.get("noteIds") or meta.get("note_ids"))
    ):
        for path in meta.get("notes") or []:
            matches = resolve_notes(path) if resolve_notes else []
            if len(matches) == 1:
                note_ids.append(matches[0])
            elif not matches:
                click.echo(
                    f"  {click.style('warning', fg='yellow')} context concept "
                    f"{concept.predicate}: note '{path}' not found in context-state "
                    f"(run `px context apply` first) — left unpinned."
                )
            else:
                click.echo(
                    f"  {click.style('warning', fg='yellow')} context concept "
                    f"{concept.predicate}: note '{path}' is ambiguous ({len(matches)} "
                    f"matches) — left unpinned."
                )

    config = generative_concept_config(concept, note_ids=note_ids)

    payload = {
        "definition": kwargs.get("definition") or "",
        "scope": ontology.scope,
        "concept_type": kwargs["concept_type"],
        "concept_name": kwargs.get("concept_name") or concept.predicate,
        "output_predicate": kwargs.get("output_predicate", ""),
    }
    for key in ("group", "description", "binds"):
        if kwargs.get(key):
            payload[key] = kwargs[key]
    if kwargs.get("existing_name"):
        payload["existing_name"] = kwargs["existing_name"]
        payload["force_overwrite"] = True
    if config is not None:
        payload["concept_config"] = config

    JarvisPyClient._request("POST", f"/api/v1/concepts/{ontology.id}/save", json=payload)


def _apply_datasources(px, ontology: LocalOntology, result: PlanResult):
    """Connect datasources the plan marks as create (upload local files first).

    A datasource failure is reported and skipped, not fatal: concepts are the
    core lineage and don't depend on the datasource at save time, so a broken or
    unreachable connector must not block the whole apply. Returns
    ``(failed_names, {datasource_name: bind_annotation_template})`` — the latter
    lets a concept's binds.input reference the datasource.
    """
    failed: List[str] = []
    ds_binds: dict = {}
    # Reuse the bind of a datasource that already exists on the account — no
    # re-connect, so repeated applies don't pile up duplicate datasource rows.
    for change in result.datasource_changes:
        if change.action == "unchanged" and change.bind:
            ds_binds[change.name] = change.bind
            click.echo(f"  reusing existing datasource {change.name}")
    to_connect = [d.name for d in result.datasource_changes if d.action == "create"]
    for name in to_connect:
        spec = ontology.datasources.get(name)
        if not spec:
            continue
        type_ = spec.get("type", "")
        filename = None
        try:
            if is_file_based(type_) and spec.get("file"):
                kwargs, filename = _upload_and_kwargs(px, ontology, name, spec)
                click.echo(f"  uploaded + connecting file datasource {name}")
            else:
                resolved = resolve_secrets(spec, os.environ)
                kwargs = database_kwargs(resolved)
                # A DB connect returns every source in the group, not just this
                # one; match the connected source by its (single) table so the
                # concept binds to the right table instead of sources[0].
                filename = _single_table(spec)
                click.echo(f"  connecting datasource {name} ({type_})")
            db = px.Database(**kwargs)
            connected = px.connect_sources(db, scope=ontology.scope)
            template = bind_template_from_sources((connected or {}).get("sources"), filename)
            if template:
                ds_binds[name] = template
        except (SecretError, Exception) as exc:  # noqa: BLE001 - report and continue
            failed.append(name)
            click.echo(f"  {click.style('warning', fg='yellow')} datasource {name} skipped: {exc}")
    return failed, ds_binds


def _is_unresolved_reference(message: str) -> bool:
    """True when a concept save failed only because an upstream reference is not
    yet created — safe to retry after other concepts in this apply are saved."""
    m = (message or "").lower()
    return (
        "do not resolve" in m
        or "does not resolve" in m
        or "create upstream concepts first" in m
    )


def _reference_detail(message: str) -> str:
    """Extract the offending reference name(s) from an unresolved-reference error,
    as a short `` (X, Y)`` suffix; empty string if none can be parsed."""
    names = re.findall(r"'([^']+)'", message or "")
    return f" ({', '.join(dict.fromkeys(names))})" if names else ""


def _single_table(spec: dict):
    """Return the datasource's table name when it binds exactly one table.

    Used to match the right source out of a multi-source DB connect. Accepts
    ``tables`` as a one-element list or a bare string; returns None otherwise
    (falls back to first-source selection).
    """
    t = spec.get("tables")
    if isinstance(t, str) and t.strip():
        return t.strip()
    if isinstance(t, list) and len(t) == 1 and isinstance(t[0], str):
        return t[0].strip()
    tn = spec.get("table_name")
    if isinstance(tn, str) and tn.strip():
        return tn.strip()
    return None


def _upload_and_kwargs(px, ontology: LocalOntology, name: str, spec: dict):
    ds_file = ontology.datasource_paths.get(name)
    base = ds_file.parent if ds_file else (ontology.directory or Path.cwd())
    local = (base / spec["file"]).resolve()
    if not local.is_file():
        raise FileNotFoundError(f"local file not found: {local}")
    subdir = spec.get("diskPath", "") or ""
    if subdir:
        try:
            px.make_directory(subdir)
        except Exception:  # noqa: BLE001 - directory may already exist
            pass
    up = px.upload_file(str(local), subdir)
    disk_path = up.get("filePath") if isinstance(up, dict) else None
    filename = up.get("fileName") if isinstance(up, dict) else local.name
    if not disk_path:
        # Fall back to a computed disk path if the response shape differs.
        disk_path = f"disk/{subdir + '/' if subdir else ''}{local.name}"
        filename = local.name
    return file_database_kwargs(spec["type"], disk_path, filename), filename


def _resolve_or_create_ontology(px, ontology: LocalOntology) -> str:
    """Adopt an existing same-name ontology in scope, else create a new one.

    Reconcile-on-create: if a previous apply created the ontology on the server
    but its id was never persisted back to the manifest (process killed in the
    window, or the write-back failed), the manifest is still id-less. Creating
    unconditionally would then duplicate the ontology on every retry. So first
    look for a single same-name ontology in scope and adopt its id; only create
    when there is no existing match.
    """
    try:
        existing = [p for p in (px.list_ontologies([ontology.scope]) or [])
                    if p.get("name") == ontology.name]
    except Exception:  # noqa: BLE001 - listing is best-effort; fall back to create
        existing = []

    if len(existing) == 1:
        pid = str(existing[0].get("id"))
        click.echo(f"  adopted existing ontology {pid} (same name in scope — no duplicate created)")
        return pid
    if len(existing) > 1:
        click.echo(
            f"  {click.style('warning', fg='yellow')} {len(existing)} ontologies already named "
            f"'{ontology.name}'; creating a new one (can't disambiguate — set ontology.id to target one)"
        )
    try:
        pid = px.save_ontology(None, ontology.name, ontology.scope)
        click.echo(f"  created ontology {pid}")
        return pid
    except Exception as exc:  # noqa: BLE001
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": could not create ontology '{ontology.name}': {exc}",
            err=True,
        )
        sys.exit(1)


def _persist_ontology_id(ontology: LocalOntology) -> None:
    import yaml

    path = ontology.manifest_path
    if not path or not path.is_file():
        return
    try:
        data = yaml.safe_load(path.read_text("utf-8")) or {}
        data.setdefault("ontology", {})["id"] = ontology.id
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), "utf-8")
    except Exception as exc:  # noqa: BLE001 - a failed write-back must NOT crash apply
        # The id is safe on the server and reconcile-on-create recovers it on the
        # next run; warn loudly so the user can persist it manually if they want.
        click.echo(
            f"  {click.style('warning', fg='yellow')} could not write ontology id back to "
            f"{path}: {exc}. Re-running apply will adopt the existing ontology (no duplicate)."
        )
