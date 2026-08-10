"""`px run` — run a concept and emit OpenLineage START/COMPLETE/FAIL events."""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import click

from ..loader import LocalProject, load_workspace, select_projects
from ..openlineage import concept_datasets, dataset_namespace, make_run_event
from ..sdk import SdkError, connected_sdk
from ..validation import find_workspace_root


def _ssl_context_from_env() -> Optional[ssl.SSLContext]:
    """SSL context honouring the corporate-CA env vars ``requests`` reads.

    Returns a context loading the CA bundle named by ``REQUESTS_CA_BUNDLE`` /
    ``CURL_CA_BUNDLE`` / ``SSL_CERT_FILE`` (first that exists), or ``None`` to
    use urllib's default (which already reads ``SSL_CERT_FILE``/``SSL_CERT_DIR``).
    This keeps the OpenLineage emit consistent with the SDK's proxy/CA behaviour.
    """
    for var in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
        bundle = os.environ.get(var)
        if bundle and os.path.exists(bundle):
            return ssl.create_default_context(cafile=bundle)
    return None


@click.command()
@click.argument("concept")
@click.argument("path", required=False, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--project", "-p", "project_selectors", multiple=True,
              help="Limit the search to the named project(s). Repeatable.")
@click.option("--param", "params", multiple=True, metavar="KEY=VALUE",
              help="Run parameter (repeatable).")
@click.option("--persist", is_flag=True, help="Persist (materialize) the concept's outputs.")
@click.option("--openlineage-file", "ol_file", default=None, type=click.Path(path_type=Path),
              help="Append OpenLineage events here (default: <workspace>/.px/openlineage.jsonl).")
@click.option("--openlineage-url", "ol_url", default=None,
              help="Also POST each OpenLineage event to this URL (e.g. a Marquez /api/v1/lineage).")
@click.option("--no-openlineage", is_flag=True, help="Do not emit OpenLineage events.")
def run(concept, path, project_selectors, params, persist, ol_file, ol_url, no_openlineage):
    """Run CONCEPT (an output predicate) and emit OpenLineage lineage events."""
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
        click.echo(click.style("FAIL", fg="red", bold=True) + f": unknown project(s): {', '.join(unknown)}", err=True)
        sys.exit(2)

    project, local_concept = _resolve_concept(projects, concept)
    if project is None:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": concept '{concept}' not found in the workspace.", err=True)
        sys.exit(1)
    if project.id is None:
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": project '{project.name}' has no server id yet — run `px apply` first.",
            err=True,
        )
        sys.exit(1)

    emitter = _Emitter(
        enabled=not no_openlineage,
        file_path=(ol_file or (root / ".px" / "openlineage.jsonl")),
        url=ol_url,
    )
    ns = dataset_namespace(project.id, project.slug)
    outputs_local = {c.predicate for c in project.concepts}
    inputs, outputs = concept_datasets(local_concept, outputs_local, ns)
    run_id = uuid.uuid4().hex
    job_name = f"{project.slug}.{concept}"

    emitter.emit("START", run_id, job_name, inputs, outputs)
    try:
        px.run_concept(
            project.id, concept, scope=project.scope,
            params=_parse_params(params), persist_outputs=persist,
        )
    except Exception as exc:  # noqa: BLE001
        emitter.emit("FAIL", run_id, job_name, inputs, outputs, error=str(exc))
        click.echo(click.style("FAIL", fg="red", bold=True) + f": run of '{concept}' failed: {exc}", err=True)
        emitter.report()
        sys.exit(1)

    emitter.emit("COMPLETE", run_id, job_name, inputs, outputs)
    click.echo(click.style("Ran", fg="green", bold=True) + f" concept '{concept}' in '{project.name}'.")
    emitter.report()


def _resolve_concept(projects: List[LocalProject], predicate: str):
    matches = [(p, c) for p in projects for c in p.concepts if c.predicate == predicate]
    if not matches:
        return None, None
    if len(matches) > 1:
        names = ", ".join(sorted({p.name for p, _ in matches}))
        raise click.ClickException(
            f"concept '{predicate}' exists in multiple projects ({names}); use --project."
        )
    return matches[0]


def _parse_params(pairs) -> dict:
    out = {}
    for pair in pairs:
        if "=" not in pair:
            raise click.ClickException(f"--param must be KEY=VALUE, got {pair!r}")
        k, v = pair.split("=", 1)
        out[k.strip()] = v
    return out


class _Emitter:
    def __init__(self, *, enabled: bool, file_path: Path, url: Optional[str]):
        self.enabled = enabled
        self.file_path = file_path
        self.url = url
        self.count = 0
        self.errors: List[str] = []

    def emit(self, event_type, run_id, job_name, inputs, outputs, error=None):
        if not self.enabled:
            return
        event = make_run_event(
            event_type=event_type,
            run_id=run_id,
            event_time=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            job_namespace="prometheux",
            job_name=job_name,
            inputs=inputs,
            outputs=outputs,
            error_message=error,
        )
        line = json.dumps(event)
        try:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with self.file_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self.count += 1
        except OSError as exc:
            self.errors.append(f"file: {exc}")
        if self.url:
            self._post(line)

    def _post(self, line: str):
        req = urllib.request.Request(
            self.url, data=line.encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            # Honour the corporate CA the same way `requests` does (trust_env),
            # so a TLS-intercepting proxy doesn't break the OpenLineage emit.
            ctx = _ssl_context_from_env()
            urllib.request.urlopen(req, timeout=10, context=ctx)  # noqa: S310 - user-supplied URL
        except (urllib.error.URLError, OSError) as exc:
            self.errors.append(f"http: {exc}")

    def report(self):
        if not self.enabled:
            return
        if self.count:
            click.echo(f"  emitted {self.count} OpenLineage event(s) → {self.file_path}")
        for e in self.errors:
            click.echo(f"  {click.style('warning', fg='yellow')} OpenLineage {e}")
