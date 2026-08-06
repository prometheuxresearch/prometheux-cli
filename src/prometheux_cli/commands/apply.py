"""`px apply` — write local changes to the platform, gated by a plan preview."""

from __future__ import annotations

import os
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
from ..loader import LocalProject, load_workspace, select_projects
from ..plan import (
    PlanResult,
    fetch_server_apps,
    fetch_server_datasources,
    fetch_server_sources,
    plan_project,
)
from ..sdk import SdkError, connected_sdk
from ..validation import find_workspace_root
from .plan import _render


@click.command()
@click.argument("path", required=False, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--project", "-p", "project_selectors", multiple=True,
              help="Only apply the named project(s), by name / directory slug / id. Repeatable.")
@click.option("--yes", "-y", "assume_yes", is_flag=True, help="Skip the confirmation prompt.")
@click.option("--prune", is_flag=True, help="Also delete concepts present on the server but not in files.")
@click.option("--no-snapshot", is_flag=True, help="Do not snapshot each project before applying.")
def apply(path: Path, project_selectors, assume_yes: bool, prune: bool, no_snapshot: bool) -> None:
    """Apply the workspace to the platform.

    Shows the same diff as `px plan`, then (after confirmation) creates/updates
    concepts. Deletions happen only with --prune. Each changed project is
    snapshotted first so an apply is recoverable. Use --project to target a
    subset instead of the whole workspace.
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
    projects, unknown = select_projects(workspace.projects, project_selectors)
    if unknown:
        available = ", ".join(sorted({p.name for p in workspace.projects})) or "(none)"
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": unknown project(s): {', '.join(unknown)}. Available: {available}",
            err=True,
        )
        sys.exit(2)

    resolve_notes = build_note_resolver(root)
    jobs = []
    for project in projects:
        export = _export(px, project)
        original_id = project.id  # the manifest id before any recreate (may be from another account)
        if project.id and _project_missing(export):
            click.echo(
                f"  {click.style('warning', fg='yellow')} project id {project.id} not found on "
                f"server — recreating '{project.name}'."
            )
            project.id = None
            export = None
        server_apps = fetch_server_apps(px, project.id, project.scope) if project.id else None
        server_sources = fetch_server_sources(px, project.id, project.scope) if project.id else None
        server_datasources = fetch_server_datasources(px, project.scope)
        result = plan_project(project, export, note_resolver=resolve_notes,
                              server_apps=server_apps, server_sources=server_sources,
                              server_datasources=server_datasources)
        _render(result, is_new=project.id is None)
        if result.has_changes or (prune and result.to_delete):
            jobs.append((project, result, original_id))

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

    # Shared across projects so an app in one project can reference another whose
    # id changed (e.g. recreated on a different account).
    id_remap: Dict[str, str] = {}
    for project, result, original_id in jobs:
        _apply_project(px, project, result, prune=prune, snapshot=not no_snapshot,
                       resolve_notes=resolve_notes, original_id=original_id, id_remap=id_remap)


def _project_missing(export) -> bool:
    """True when an export has no project row — the id no longer exists server-side."""
    if not export:
        return True
    for name, tbl in (export.get("tables") or {}).items():
        if name.startswith("projects_") and (tbl or {}).get("data"):
            return False
    return True


def _export(px, project: LocalProject):
    if not project.id:
        return None
    try:
        return px.export_ontology(project.id, project.scope)
    except Exception as exc:  # noqa: BLE001
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": export of project {project.id} failed: {exc}",
            err=True,
        )
        sys.exit(1)


def _apply_project(px, project: LocalProject, result: PlanResult, *, prune: bool, snapshot: bool,
                   resolve_notes=None, original_id=None, id_remap=None) -> None:
    click.echo(f'\nApplying "{project.name}"…')

    # Create the project first if it is brand-new, and persist the id to disk.
    if not project.id:
        project.id = _create_project(px, project)
        _persist_project_id(project)
        click.echo(f"  created project {project.id}")

    # Record how this project's id resolved, so apps (in any project) that embed
    # the manifest's original id get it rewritten to the actual server id. This
    # is what makes a project with an app portable across accounts.
    if id_remap is not None and project.id:
        if original_id and original_id != project.id:
            id_remap[original_id] = project.id
        id_remap.setdefault(project.id, project.id)

    if snapshot:
        try:
            px.create_snapshot(project.id, project.scope, "pre-apply via px")
            click.echo("  snapshot taken (pre-apply)")
        except Exception as exc:  # noqa: BLE001 - snapshot is best-effort safety
            click.echo(f"  {click.style('warning', fg='yellow')} snapshot failed: {exc}")

    failed_ds, ds_binds = _apply_datasources(px, project, result)

    to_write = {c.predicate for c in result.concept_changes if c.action in {"create", "update"}}
    updates = {c.predicate for c in result.concept_changes if c.action == "update"}
    by_pred = {c.predicate: c for c in project.concepts}

    applied = 0
    for concept in topo_order([by_pred[p] for p in to_write if p in by_pred]):
        kwargs = concept_save_kwargs(concept, update=concept.predicate in updates, datasource_binds=ds_binds)
        try:
            if is_generative(concept):
                _save_generative_concept(project, concept, kwargs, resolve_notes)
            else:
                px.save_concept(ontology_id=project.id, scope=project.scope, **kwargs)
            verb = "updated" if concept.predicate in updates else "created"
            click.echo(f"  {verb} concept {concept.predicate}")
            applied += 1
        except Exception as exc:  # noqa: BLE001
            click.echo(
                click.style("FAIL", fg="red", bold=True)
                + f": save of concept {concept.predicate} failed: {exc}",
                err=True,
            )
            sys.exit(1)

    if result.ontology_change in {"create", "update"} and project.ontology:
        try:
            px.save_ontology_schema(project.id, project.ontology, project.scope)
            verb = "created" if result.ontology_change == "create" else "updated"
            click.echo(f"  {verb} ontology schema")
        except Exception as exc:  # noqa: BLE001
            click.echo(
                click.style("FAIL", fg="red", bold=True)
                + f": save of ontology schema failed: {exc}",
                err=True,
            )
            sys.exit(1)

    _apply_apps(px, project, result, prune=prune, id_remap=id_remap)

    if prune:
        deletes = [c.predicate for c in result.concept_changes if c.action == "delete"]
        if deletes:
            try:
                px.cleanup_concepts(project.id, project.scope, deletes)
                click.echo(f"  pruned {len(deletes)} concept(s): {', '.join(deletes)}")
            except Exception as exc:  # noqa: BLE001
                click.echo(f"  {click.style('warning', fg='yellow')} prune failed: {exc}")

    stale = {p for downstream in result.cascade.values() for p in downstream}
    click.echo(
        click.style("Applied", fg="green", bold=True)
        + f": {applied} concept(s) written to '{project.name}'."
    )
    if failed_ds:
        click.echo(f"  {len(failed_ds)} datasource(s) not connected: {', '.join(failed_ds)}")
    if stale:
        click.echo(f"  downstream now stale: {', '.join(sorted(stale))} — `px run` to rebuild.")


def _remap_app_project_ids(definition: dict, id_remap) -> dict:
    """Rewrite each page's ``project.id`` through ``id_remap`` (old id -> actual).

    An app authored against one project id (e.g. on another account) embeds that
    id in every page; without this the server validates the app against a project
    that doesn't exist here and every concept reference fails.
    """
    if not id_remap:
        return definition
    for page in definition.get("pages") or []:
        if not isinstance(page, dict):
            continue
        proj = page.get("project")
        if isinstance(proj, dict) and proj.get("id") in id_remap:
            proj["id"] = id_remap[proj["id"]]
    return definition


def _apply_apps(px, project: LocalProject, result: PlanResult, *, prune: bool, id_remap=None) -> None:
    """Create/update apps via ``save_app``; delete server-only apps with --prune.

    A file without an ``id`` that matched an existing app by name adopts that
    server id before saving (so it updates in place, not duplicates) and the id
    is written back to the file. A newly created app's assigned id is likewise
    persisted, so the next apply is idempotent.
    """
    import copy

    by_identity = {a.identity: a for a in project.apps}
    for change in result.app_changes:
        if change.action in {"create", "update"}:
            app = by_identity.get(change.identity)
            if app is None:
                continue
            definition = _remap_app_project_ids(copy.deepcopy(app.definition), id_remap)
            if change.server_id and not definition.get("id"):
                definition["id"] = change.server_id
            try:
                res = px.save_app(project.id, definition, project.scope)
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
                px.delete_app(project.id, change.server_id, project.scope)
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


def _save_generative_concept(project: LocalProject, concept, kwargs: dict, resolve_notes) -> None:
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
        "scope": project.scope,
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

    JarvisPyClient._request("POST", f"/api/v1/concepts/{project.id}/save", json=payload)


def _apply_datasources(px, project: LocalProject, result: PlanResult):
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
        spec = project.datasources.get(name)
        if not spec:
            continue
        type_ = spec.get("type", "")
        filename = None
        try:
            if is_file_based(type_) and spec.get("file"):
                kwargs, filename = _upload_and_kwargs(px, project, name, spec)
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
            connected = px.connect_sources(db, scope=project.scope)
            template = bind_template_from_sources((connected or {}).get("sources"), filename)
            if template:
                ds_binds[name] = template
        except (SecretError, Exception) as exc:  # noqa: BLE001 - report and continue
            failed.append(name)
            click.echo(f"  {click.style('warning', fg='yellow')} datasource {name} skipped: {exc}")
    return failed, ds_binds


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
    return None


def _upload_and_kwargs(px, project: LocalProject, name: str, spec: dict):
    ds_file = project.datasource_paths.get(name)
    base = ds_file.parent if ds_file else (project.directory or Path.cwd())
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


def _create_project(px, project: LocalProject) -> str:
    try:
        return px.save_ontology(None, project.name, project.scope)
    except Exception as exc:  # noqa: BLE001
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": could not create project '{project.name}': {exc}",
            err=True,
        )
        sys.exit(1)


def _persist_project_id(project: LocalProject) -> None:
    import yaml

    path = project.manifest_path
    if not path or not path.is_file():
        return
    data = yaml.safe_load(path.read_text("utf-8")) or {}
    data.setdefault("project", {})["id"] = project.id
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), "utf-8")
