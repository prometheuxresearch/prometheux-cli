"""`px pull` — export a live project and write it as a workspace file tree."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click

from ..plan import fetch_server_apps, fetch_server_sources
from ..reshape import reshape_project
from ..resources import iter_schema_files
from ..sdk import SdkError, connected_sdk


@click.command()
@click.argument("project", required=False)
@click.option("--scope", default="user", type=click.Choice(["user", "organization"]))
@click.option("--out", "out", default=".", type=click.Path(path_type=Path), help="Workspace directory.")
@click.option("--slug", default=None, help="Directory name under projects/ (default: from project name).")
def pull(project: str, scope: str, out: Path, slug: str) -> None:
    """Pull PROJECT (a server project id) into ./projects/<slug>.

    With no PROJECT, lists the projects visible to you and exits.
    """
    try:
        px, url, _ = connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)

    if not project:
        _list_projects(px, scope, url)
        return

    try:
        export = px.export_ontology(project, scope)
    except Exception as exc:  # noqa: BLE001 - surface SDK/HTTP errors cleanly
        click.echo(
            click.style("FAIL", fg="red", bold=True) + f": export failed: {exc}", err=True
        )
        sys.exit(1)

    name = _project_name(export, project)
    slug = slug or _slugify(name) or project
    sources = fetch_server_sources(px, project, scope)
    result = reshape_project(export, project_name=name, slug=slug, sources=sources)

    dest = out.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    for f in result.files:
        target = dest / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, "utf-8")

    app_count = _write_apps(px, project, scope, dest, slug)

    _ensure_workspace(dest, slug)
    _ensure_schemas(dest)

    for w in result.warnings:
        click.echo(f"{click.style('warning', fg='yellow')}  {w}")
    app_note = f" + {app_count} app(s)" if app_count else ""
    click.echo(
        click.style("Pulled", fg="green", bold=True)
        + f" '{name}' ({project}) to {dest / 'projects' / slug} — {len(result.files)} file(s){app_note}."
    )
    click.echo("Next: `px validate`")


def _write_apps(px, project: str, scope: str, dest: Path, slug: str) -> int:
    """Write each app's definition to projects/<slug>/apps/<slug>.app.yaml.

    Apps are fetched via the SDK (not the export) and the project manifest gains
    an `apps: ./apps` entry so a pulled project round-trips through `px apply`.
    """
    import yaml

    apps = fetch_server_apps(px, project, scope)
    if not apps:
        return 0
    apps_dir = dest / "projects" / slug / "apps"
    apps_dir.mkdir(parents=True, exist_ok=True)
    used = set()
    for app in apps:
        definition = app.get("definition") or {}
        base = _slugify(app.get("name") or "") or (app.get("id") or "app")
        fname = base
        n = 2
        while fname in used:
            fname = f"{base}-{n}"
            n += 1
        used.add(fname)
        # No bundled app JSON Schema yet, so no `$schema` hint — write the
        # AppDefinition verbatim (the loader would strip `$schema` regardless).
        (apps_dir / f"{fname}.app.yaml").write_text(
            yaml.safe_dump(definition, sort_keys=False, allow_unicode=True), "utf-8"
        )

    manifest = dest / "projects" / slug / "prometheux.yaml"
    if manifest.is_file():
        data = yaml.safe_load(manifest.read_text("utf-8")) or {}
        if not data.get("apps"):
            data["apps"] = "./apps"
            manifest.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), "utf-8")
    return len(apps)


def _list_projects(px, scope: str, url: str) -> None:
    try:
        projects = px.list_ontologies([scope])
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    if not projects:
        click.echo(f"No {scope}-scoped projects visible at {url}.")
        return
    click.echo(f"Projects at {url} (scope: {scope}):\n")
    for p in projects:
        click.echo(f"  {p.get('id'):<16} {p.get('name', '')}")
    click.echo("\nPull one with: px pull <id>")


def _project_name(export: dict, fallback: str) -> str:
    for tname, tbl in (export.get("tables") or {}).items():
        if tname.startswith("projects_"):
            rows = tbl.get("data") or []
            if rows and rows[0].get("name"):
                return rows[0]["name"]
    return fallback


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (name or "").strip().lower())
    return s.strip("-")


def _ensure_workspace(dest: Path, slug: str) -> None:
    import yaml

    ws_file = dest / "prometheux.workspace.yaml"
    proj_ref = f"./projects/{slug}"
    if ws_file.is_file():
        data = yaml.safe_load(ws_file.read_text("utf-8")) or {}
        projects = data.get("projects") or []
        if proj_ref not in projects:
            projects.append(proj_ref)
            data["projects"] = projects
            ws_file.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True), "utf-8"
            )
        return

    data = {
        "$schema": "./.px/schemas/workspace.schema.json",
        "schemaVersion": 1,
        "workspace": {"name": dest.name},
        "context": "./context",
        "projects": [proj_ref],
    }
    ws_file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), "utf-8")
    # A workspace manifest requires a context vault to exist per the schema-adjacent
    # convention; create an empty one so `px validate` passes on a fresh pull.
    (dest / "context").mkdir(parents=True, exist_ok=True)


def _ensure_schemas(dest: Path) -> None:
    schemas_dir = dest / ".px" / "schemas"
    if schemas_dir.is_dir():
        return
    schemas_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in iter_schema_files():
        (schemas_dir / filename).write_text(text, "utf-8")
