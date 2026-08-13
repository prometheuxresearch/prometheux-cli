"""`px pull` — export a live ontology and write it as a workspace file tree."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click

from ..plan import fetch_server_apps, fetch_server_sources
from ..reshape import reshape_ontology
from ..resources import iter_schema_files
from ..sdk import SdkError, connected_sdk


@click.command()
@click.argument("ontology", required=False)
@click.option("--scope", default="user", type=click.Choice(["user", "organization"]))
@click.option("--out", "out", default=".", type=click.Path(path_type=Path), help="Workspace directory.")
@click.option("--slug", default=None, help="Directory name under ontologies/ (default: from ontology name).")
@click.option("--with-files", "with_files", is_flag=True,
              help="Download uploaded file-datasource content into files/ and write file: "
                   "specs, so the ontology (with its files) can be re-applied elsewhere.")
def pull(ontology: str, scope: str, out: Path, slug: str, with_files: bool) -> None:
    """Pull ONTOLOGY (a server ontology id) into ./ontologies/<slug>.

    With no ONTOLOGY, lists the ontologies visible to you and exits.
    """
    try:
        px, url, _ = connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)

    if not ontology:
        _list_ontologies(px, scope, url)
        return

    try:
        export = px.export_ontology(ontology, scope)
    except Exception as exc:  # noqa: BLE001 - surface SDK/HTTP errors cleanly
        click.echo(
            click.style("FAIL", fg="red", bold=True) + f": export failed: {exc}", err=True
        )
        sys.exit(1)

    name = _ontology_name(export, ontology)
    slug = slug or _slugify(name) or ontology
    sources = fetch_server_sources(px, ontology, scope)
    result = reshape_ontology(export, ontology_name=name, slug=slug, sources=sources)

    dest = out.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    for f in result.files:
        target = dest / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, "utf-8")

    app_count = _write_apps(px, ontology, scope, dest, slug)
    file_count = _download_datasource_files(px, dest, slug) if with_files else 0

    _ensure_workspace(dest, slug)
    _ensure_schemas(dest)

    for w in result.warnings:
        click.echo(f"{click.style('warning', fg='yellow')}  {w}")
    app_note = f" + {app_count} app(s)" if app_count else ""
    dl_note = f" + {file_count} datasource file(s)" if file_count else ""
    click.echo(
        click.style("Pulled", fg="green", bold=True)
        + f" '{name}' ({ontology}) to {dest / 'ontologies' / slug} — {len(result.files)} file(s){app_note}{dl_note}."
    )
    click.echo("Next: `px validate`")


def _download_datasource_files(px, dest: Path, slug: str) -> int:
    """Download each uploaded (disk) datasource's content and rewrite its spec.

    A pulled datasource whose host is under ``disk/…`` is server-side uploaded
    content. Download the file into ``files/`` and rewrite the spec to a `file:`
    form with ``diskPath`` = the original subdir, so `px apply` re-uploads it to
    the same location the concept binds hardcode — making the ontology portable.
    """
    import yaml

    ds_dir = dest / "ontologies" / slug / "datasources"
    files_dir = dest / "ontologies" / slug / "files"
    if not ds_dir.is_dir():
        return 0
    count = 0
    for dsf in sorted(ds_dir.glob("*.yaml")):
        spec = yaml.safe_load(dsf.read_text("utf-8")) or {}
        host = str(spec.get("host") or "")
        table = spec.get("table_name")
        if not table or not host.startswith("disk"):
            continue  # not an uploaded-file datasource
        subdir = host[len("disk"):].lstrip("/")   # e.g. "project_212b77ea132" or ""
        remote = f"{subdir}/{table}" if subdir else table
        files_dir.mkdir(parents=True, exist_ok=True)
        try:
            px.download_file(remote, dest_path=str(files_dir / table))
        except Exception as exc:  # noqa: BLE001 - report and skip
            click.echo(f"{click.style('warning', fg='yellow')}  could not download {remote}: {exc}")
            continue
        new_spec = {"$schema": spec.get("$schema"), "name": spec.get("name"),
                    "type": spec.get("type"), "file": f"../files/{table}"}
        if subdir:
            new_spec["diskPath"] = subdir
        dsf.write_text(
            yaml.safe_dump({k: v for k, v in new_spec.items() if v is not None},
                           sort_keys=False, allow_unicode=True), "utf-8")
        count += 1
    return count


def _write_apps(px, ontology: str, scope: str, dest: Path, slug: str) -> int:
    """Write each app's definition to ontologies/<slug>/apps/<slug>.app.yaml.

    Apps are fetched via the SDK (not the export) and the ontology manifest gains
    an `apps: ./apps` entry so a pulled ontology round-trips through `px apply`.
    """
    import yaml

    apps = fetch_server_apps(px, ontology, scope)
    if not apps:
        return 0
    apps_dir = dest / "ontologies" / slug / "apps"
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

    manifest = dest / "ontologies" / slug / "prometheux.yaml"
    if manifest.is_file():
        data = yaml.safe_load(manifest.read_text("utf-8")) or {}
        if not data.get("apps"):
            data["apps"] = "./apps"
            manifest.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), "utf-8")
    return len(apps)


def _list_ontologies(px, scope: str, url: str) -> None:
    try:
        ontologies = px.list_ontologies([scope])
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    if not ontologies:
        click.echo(f"No {scope}-scoped ontologies visible at {url}.")
        return
    click.echo(f"Ontologies at {url} (scope: {scope}):\n")
    for p in ontologies:
        click.echo(f"  {p.get('id'):<16} {p.get('name', '')}")
    click.echo("\nPull one with: px pull <id>")


def _ontology_name(export: dict, fallback: str) -> str:
    for tname, tbl in (export.get("tables") or {}).items():
        if tname.startswith("projects_"):  # server export wire prefix — unchanged
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
    proj_ref = f"./ontologies/{slug}"
    if ws_file.is_file():
        data = yaml.safe_load(ws_file.read_text("utf-8")) or {}
        ontologies = data.get("ontologies") or []
        if proj_ref not in ontologies:
            ontologies.append(proj_ref)
            data["ontologies"] = ontologies
            ws_file.write_text(
                yaml.safe_dump(data, sort_keys=False, allow_unicode=True), "utf-8"
            )
        return

    data = {
        "$schema": "./.px/schemas/workspace.schema.json",
        "schemaVersion": 1,
        "workspace": {"name": dest.name},
        "context": "./context",
        "ontologies": [proj_ref],
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
