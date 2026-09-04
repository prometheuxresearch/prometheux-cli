"""`px pull` — export a live ontology and write it as a workspace file tree.

The tree is built by the server (``POST /ontologies/export-tree``); the CLI only
writes the files down. That is the whole point of the endpoint: a pull and a
browser download of the same ontology are the same bytes, because one engine
produced both. It also means `px pull` needs a server that has the route, which
is checked for explicitly so the failure reads as "update the server" rather than
as a bare 404.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import click

from ..resources import iter_schema_files
from ..sdk import SdkError, connected_sdk, rest_data

_EXPORT_TREE_ROUTE = "/api/v1/ontologies/export-tree"


@dataclass
class FileOut:
    """A file to write: workspace-relative path + text content."""

    path: str
    content: str


@dataclass
class _PulledTree:
    """One ontology's files, before anything touches the disk."""

    files: List[FileOut]
    name: str
    slug: str
    warnings: List[str] = field(default_factory=list)
    app_count: int = 0

    @property
    def file_count(self) -> int:
        """Files excluding the apps, which the summary line reports separately."""
        return len(self.files) - self.app_count


@click.command()
@click.argument("ontology", required=False)
@click.option("--out", "out", default=".", type=click.Path(path_type=Path), help="Workspace directory.")
@click.option("--slug", default=None, help="Directory name under ontologies/ (default: from ontology name).")
@click.option("--with-files", "with_files", is_flag=True,
              help="Download uploaded file-datasource content into files/ and write file: "
                   "specs, so the ontology (with its files) can be re-applied elsewhere.")
def pull(ontology: str, out: Path, slug: str, with_files: bool) -> None:
    """Pull ONTOLOGY (a server ontology id) into ./ontologies/<slug>.

    With no ONTOLOGY, lists the ontologies visible to you and exits.
    """
    try:
        px, url, _ = connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)

    if not ontology:
        _list_ontologies(px, url)
        return

    try:
        tree = _server_tree(ontology, slug, url)
    except Exception as exc:  # noqa: BLE001 - surface SDK/HTTP errors cleanly
        click.echo(
            click.style("FAIL", fg="red", bold=True) + f": export failed: {exc}", err=True
        )
        sys.exit(1)

    dest = out.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    for f in tree.files:
        target = dest / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, "utf-8")

    file_count = _download_datasource_files(px, dest, tree.slug) if with_files else 0

    _ensure_workspace(dest, tree.slug)
    _ensure_schemas(dest)

    for w in tree.warnings:
        click.echo(f"{click.style('warning', fg='yellow')}  {w}")
    app_note = f" + {tree.app_count} app(s)" if tree.app_count else ""
    dl_note = f" + {file_count} datasource file(s)" if file_count else ""
    click.echo(
        click.style("Pulled", fg="green", bold=True)
        + f" '{tree.name}' ({ontology}) to {dest / 'ontologies' / tree.slug}"
        + f" — {tree.file_count} file(s){app_note}{dl_note}."
    )
    click.echo("Next: `px validate`")


def _server_tree(ontology: str, slug: str, url: str) -> _PulledTree:
    """The tree as the server builds it.

    Only the ontology's own files are kept. The response also carries the
    workspace manifest and the JSON Schemas, but both are written here instead:
    writing the manifest verbatim would drop the other ontologies an existing
    workspace lists, where ``_ensure_workspace`` merges into it, and the schemas
    have to be the ones this CLI validates against, not the ones the server ships.
    """
    payload = {"ontology_id": ontology}
    if slug:
        payload["slug"] = slug
    try:
        data = rest_data("POST", _EXPORT_TREE_ROUTE, json=payload)
    except SdkError as exc:
        if _route_absent(str(exc)):
            raise SdkError(
                "this server has no /ontologies/export-tree route, so it cannot "
                f"build the file tree.\n  Update the platform at {url} to a "
                "version that supports it, or use an older `px` (0.3.x)."
            ) from exc
        raise

    meta = (data or {}).get("ontology") or {}
    files = _ontology_files(data or {})
    return _PulledTree(
        files=files,
        name=meta.get("name") or ontology,
        slug=meta.get("slug") or slug or ontology,
        warnings=list((data or {}).get("warnings") or []),
        app_count=sum(1 for f in files if f.path.endswith(".app.yaml")),
    )


def _ontology_files(payload: dict) -> List[FileOut]:
    """The ``ontologies/…`` entries of an export-tree response."""
    files = []
    for entry in payload.get("files") or []:
        path = str((entry or {}).get("path") or "")
        if path.startswith("ontologies/"):
            files.append(FileOut(path, entry.get("content") or ""))
    return files


def _route_absent(message: str) -> bool:
    """Does this error mean the server has no export-tree route, or a real failure?

    A server predating the endpoint answers 404, which the SDK surfaces as a
    "Not Found" message. The endpoint itself never 404s — a missing or unknown
    ontology id comes back as a 400. Telling the two apart is what lets the
    version problem be reported as one, instead of as a puzzling "Not Found".
    """
    lowered = (message or "").lower()
    return "not found: the requested resource" in lowered or "http error 404" in lowered


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


def _list_ontologies(px, url: str) -> None:
    try:
        ontologies = px.list_ontologies()
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    if not ontologies:
        click.echo(f"No ontologies visible at {url}.")
        return
    click.echo(f"Ontologies at {url}:\n")
    for p in ontologies:
        click.echo(f"  {p.get('id'):<16} {p.get('name', '')}")
    click.echo("\nPull one with: px pull <id>")


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
