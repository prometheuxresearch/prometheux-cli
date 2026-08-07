"""Offline validation engine.

Runs schema + structural checks against a workspace on disk with **no platform
connection**. Deep Vadalog predicate-graph resolution is deferred to the `plan`
engine (which reads the server graph); what is checked here is everything that
is decidable from the files alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from jsonschema import Draft202012Validator

from .parsing import ParseError, load_yaml, split_frontmatter
from .resources import load_schema

# Body extensions that pair with a sibling *.meta.yaml envelope.
_BODY_KINDS = {
    ".vadalog": "logic",
    ".sql": "sql",
    ".cypher": "cypher",
    ".py": "python",
}


@dataclass
class Finding:
    level: str  # "error" | "warning"
    location: str
    message: str


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)
    checked: Dict[str, int] = field(default_factory=dict)

    def error(self, location: str, message: str) -> None:
        self.findings.append(Finding("error", location, message))

    def warn(self, location: str, message: str) -> None:
        self.findings.append(Finding("warning", location, message))

    def bump(self, key: str) -> None:
        self.checked[key] = self.checked.get(key, 0) + 1

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def find_workspace_root(start: Path) -> Optional[Path]:
    """Walk up from ``start`` looking for a prometheux.workspace.yaml."""
    start = start.resolve()
    candidates = [start, *start.parents] if start.is_dir() else [start.parent, *start.parent.parents]
    for d in candidates:
        if (d / "prometheux.workspace.yaml").is_file():
            return d
    return None


def _schema_errors(kind: str, data: dict) -> List[str]:
    validator = Draft202012Validator(load_schema(kind))
    out = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in err.path) or "<root>"
        out.append(f"{where}: {err.message}")
    return out


def validate_workspace(root: Path) -> Report:
    """Validate the workspace rooted at ``root``. Never raises for content errors."""
    report = Report()
    ws_file = root / "prometheux.workspace.yaml"

    try:
        ws = load_yaml(ws_file)
    except ParseError as exc:
        report.error(_rel(root, ws_file), str(exc))
        return report

    for msg in _schema_errors("workspace", ws):
        report.error(_rel(root, ws_file), msg)
    report.bump("workspace")

    # Shared context vault.
    ctx_dir = root / (ws.get("context") or "./context")
    if ctx_dir.is_dir():
        _validate_context_vault(root, ctx_dir, report)
    elif "context" in ws:
        report.error(_rel(root, ws_file), f"context vault not found: {_rel(root, ctx_dir)}")

    # Projects.
    for proj_ref in ws.get("projects", []) or []:
        proj_dir = (root / proj_ref).resolve()
        _validate_project(root, proj_dir, report)

    return report


def _validate_project(root: Path, proj_dir: Path, report: Report) -> None:
    manifest = proj_dir / "prometheux.yaml"
    loc = _rel(root, manifest)
    if not manifest.is_file():
        report.error(_rel(root, proj_dir), "missing prometheux.yaml")
        return
    try:
        proj = load_yaml(manifest)
    except ParseError as exc:
        report.error(loc, str(exc))
        return

    for msg in _schema_errors("project", proj):
        report.error(loc, msg)
    report.bump("project")

    datasource_names = _validate_datasources(root, proj_dir, proj, report)
    concepts_dir = proj_dir / (proj.get("concepts") or "./concepts")
    concept_count = _validate_concepts(root, concepts_dir, datasource_names, report)

    # Ontology file existence (schema for it is out of scope for this slice).
    if proj.get("ontology"):
        onto = proj_dir / proj["ontology"]
        if not onto.is_file():
            report.error(loc, f"ontology file not found: {_rel(root, onto)}")
        else:
            _warn_hollow_ontology(root, onto, concept_count, loc, report)

    # Project-scoped context vault.
    if proj.get("context"):
        pctx = proj_dir / proj["context"]
        if pctx.is_dir():
            _validate_context_vault(root, pctx, report)
        else:
            report.error(loc, f"project context vault not found: {_rel(root, pctx)}")


def _warn_hollow_ontology(root: Path, onto: Path, concept_count: int, loc: str, report: Report) -> None:
    """Warn when a project ships an ontology schema graph but has no concepts.

    In Prometheux the ontology is concept-centric: the platform's default
    ontology view is the concept-lineage graph, so a project with 0 concepts
    renders an EMPTY ontology no matter what the schema graph contains. Such a
    concept-less schema is a hollow artifact — flag it rather than silently
    creating a useless ontology.
    """
    if concept_count > 0:
        return
    try:
        onto_data = load_yaml(onto)
    except ParseError:
        return  # a parse issue is not our concern here
    if not isinstance(onto_data, dict):
        return
    node_count = len(onto_data.get("nodes") or [])
    if node_count == 0:
        return  # an empty schema on an empty project is fine (nothing to render)
    report.warn(
        loc,
        f"ontology schema declares {node_count} node(s) but the project has no concepts; "
        "the platform renders the ontology from concept lineage, so this will show as EMPTY. "
        "Import the graph as concepts bound to data (or add concepts), or drop the ontology.",
    )


def _validate_datasources(root: Path, proj_dir: Path, proj: dict, report: Report) -> set:
    names = set()
    for ds_ref in proj.get("datasources", []) or []:
        ds_file = proj_dir / ds_ref
        loc = _rel(root, ds_file)
        if not ds_file.is_file():
            report.error(loc, "datasource file not found")
            continue
        try:
            ds = load_yaml(ds_file)
        except ParseError as exc:
            report.error(loc, str(exc))
            continue
        for msg in _schema_errors("datasource", ds):
            report.error(loc, msg)
        if ds.get("name"):
            names.add(ds["name"])
        report.bump("datasource")
    return names


def _validate_concepts(root: Path, concepts_dir: Path, datasource_names: set, report: Report) -> int:
    """Validate every concept in the dir; return the number of concepts found."""
    if not concepts_dir.is_dir():
        report.error(_rel(root, concepts_dir), "concepts directory not found")
        return 0

    output_predicates: Dict[str, str] = {}  # predicate -> first location seen
    count = 0

    for path in sorted(concepts_dir.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if name.endswith(".meta.yaml"):
            continue  # validated alongside its body
        if name.endswith(".context.yaml"):
            _validate_context_concept(root, path, output_predicates, report)
            count += 1
        elif name.endswith(".llm.md"):
            _validate_llm_concept(root, path, output_predicates, report)
            count += 1
        elif path.suffix in _BODY_KINDS:
            _validate_body_concept(root, path, datasource_names, output_predicates, report)
            count += 1
        # anything else in concepts/ is ignored (e.g. README)

    return count


def _register_predicate(
    predicate: Optional[str], loc: str, seen: Dict[str, str], report: Report
) -> None:
    if not predicate:
        return
    if predicate in seen:
        report.error(loc, f"duplicate outputPredicate '{predicate}' (also in {seen[predicate]})")
    else:
        seen[predicate] = loc


def _validate_body_concept(
    root: Path, body: Path, datasource_names: set, seen: Dict[str, str], report: Report
) -> None:
    expected_type = _BODY_KINDS[body.suffix]
    meta_path = body.with_name(body.stem + ".meta.yaml")
    loc = _rel(root, body)

    if not meta_path.is_file():
        report.error(loc, f"missing envelope {meta_path.name} for this {expected_type} concept")
        return
    try:
        meta = load_yaml(meta_path)
    except ParseError as exc:
        report.error(_rel(root, meta_path), str(exc))
        return

    for msg in _schema_errors("concept-meta", meta):
        report.error(_rel(root, meta_path), msg)

    declared = meta.get("conceptType")
    if declared and declared != expected_type:
        report.error(
            _rel(root, meta_path),
            f"conceptType '{declared}' does not match body extension {body.suffix} "
            f"(expected '{expected_type}')",
        )

    # Datasource references in input binds must resolve to a datasources/ file.
    binds = meta.get("binds") or {}
    for entry in binds.get("input", []) or []:
        ds = entry.get("datasource") if isinstance(entry, dict) else None
        if ds and ds not in datasource_names:
            report.error(
                _rel(root, meta_path),
                f"bind references unknown datasource '{ds}' "
                f"(no datasources/ file declares name: {ds})",
            )

    _register_predicate(meta.get("outputPredicate"), _rel(root, meta_path), seen, report)
    report.bump("concept")


def _validate_context_concept(
    root: Path, path: Path, seen: Dict[str, str], report: Report
) -> None:
    loc = _rel(root, path)
    try:
        data = load_yaml(path)
    except ParseError as exc:
        report.error(loc, str(exc))
        return
    for msg in _schema_errors("context-concept", data):
        report.error(loc, msg)
    # static note paths are resolved by `apply` against the vault; existence
    # under the project vault is checked there, not here.
    _register_predicate(data.get("outputPredicate"), loc, seen, report)
    report.bump("concept")


def _validate_llm_concept(root: Path, path: Path, seen: Dict[str, str], report: Report) -> None:
    loc = _rel(root, path)
    try:
        fm, body = split_frontmatter(path)
    except ParseError as exc:
        report.error(loc, str(exc))
        return
    if fm.get("conceptType") != "llm":
        report.error(loc, "llm concept frontmatter must set conceptType: llm")
    if not fm.get("outputPredicate"):
        report.error(loc, "llm concept frontmatter must set outputPredicate")
    if not body.strip():
        report.warn(loc, "llm concept has an empty prompt body")
    _register_predicate(fm.get("outputPredicate"), loc, seen, report)
    report.bump("concept")


def _validate_context_vault(root: Path, vault: Path, report: Report) -> None:
    for manifest in sorted(vault.rglob("*.context.md")):
        loc = _rel(root, manifest)
        try:
            fm, _ = split_frontmatter(manifest)
        except ParseError as exc:
            report.error(loc, str(exc))
            continue
        if not fm:
            report.error(loc, "context manifest has no frontmatter")
            continue
        for msg in _schema_errors("context-set", fm):
            report.error(loc, msg)
        # Body files the manifest points at must exist on disk.
        for note in fm.get("notes", []) or []:
            note_path = note["path"] if isinstance(note, dict) else note
            body = (manifest.parent / note_path).resolve()
            if not body.is_file():
                report.error(loc, f"referenced body not found: {note_path}")
        report.bump("context-set")
