"""`px apply` — write local changes to the platform, gated by a plan preview."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List

import click

from ..apply import concept_save_kwargs, topo_order
from ..datasources import (
    SecretError,
    bind_template_from_sources,
    database_kwargs,
    file_database_kwargs,
    is_file_based,
    resolve_secrets,
)
from ..loader import LocalProject, load_workspace, select_projects
from ..plan import PlanResult, plan_project
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

    jobs = []
    for project in projects:
        export = _export(px, project)
        result = plan_project(project, export)
        _render(result, is_new=project.id is None)
        if result.has_changes or (prune and result.to_delete):
            jobs.append((project, result))

    if not jobs:
        click.echo("\nNo changes to apply.")
        return

    if not prune and any(r.to_delete for _, r in jobs):
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

    for project, result in jobs:
        _apply_project(px, project, result, prune=prune, snapshot=not no_snapshot)


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


def _apply_project(px, project: LocalProject, result: PlanResult, *, prune: bool, snapshot: bool) -> None:
    click.echo(f'\nApplying "{project.name}"…')

    # Create the project first if it is brand-new, and persist the id to disk.
    if not project.id:
        project.id = _create_project(px, project)
        _persist_project_id(project)
        click.echo(f"  created project {project.id}")

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
