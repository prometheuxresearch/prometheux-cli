"""Load a workspace on disk into a structured model for planning.

This is the read side that `plan` diffs against server state. It reuses the
parsing helpers and mirrors the file conventions `validate` enforces, but returns
typed objects instead of findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .parsing import ParseError, load_yaml, split_frontmatter

# Body extension -> concept type (the Vadalog-family, which carry a .meta.yaml).
_BODY_KINDS = {
    ".vadalog": "logic",
    ".sql": "sql",
    ".cypher": "cypher",
    ".py": "python",
}


@dataclass
class LocalConcept:
    predicate: str
    concept_type: str
    body: str
    meta: dict
    path: str  # repo-relative body/definition path

    @property
    def is_vadalog_family(self) -> bool:
        return self.concept_type in {"logic", "sql", "cypher"}


@dataclass
class LocalApp:
    identity: str       # definition.id when present, else the app name
    name: str
    definition: dict    # the AppDefinition (v2), minus the `$schema` editor hint
    path: str           # project-relative file path
    has_id: bool        # whether the file already carries a server id
    file: Optional[Path] = None  # absolute path, for writing the id back on create


@dataclass
class LocalProject:
    slug: str
    id: Optional[str]
    name: str
    scope: str
    concepts: List[LocalConcept] = field(default_factory=list)
    datasources: Dict[str, dict] = field(default_factory=dict)
    datasource_paths: Dict[str, Path] = field(default_factory=dict)
    ontology: Optional[dict] = None
    ontology_path: Optional[Path] = None
    apps: List[LocalApp] = field(default_factory=list)
    directory: Optional[Path] = None
    manifest_path: Optional[Path] = None


@dataclass
class LocalWorkspace:
    root: Path
    projects: List[LocalProject] = field(default_factory=list)


def select_projects(projects: List[LocalProject], selectors):
    """Filter ``projects`` by selectors (project name, directory slug, or id).

    Returns ``(matched, unknown)``. With no selectors, returns all projects.
    Order follows the selectors; duplicates are removed.
    """
    if not selectors:
        return list(projects), []
    matched: List[LocalProject] = []
    unknown: List[str] = []
    seen = set()
    for sel in selectors:
        hits = [p for p in projects if sel in {p.name, p.slug, p.id}]
        if not hits:
            unknown.append(sel)
        for p in hits:
            if id(p) not in seen:
                seen.add(id(p))
                matched.append(p)
    return matched, unknown


def load_workspace(root: Path) -> LocalWorkspace:
    """Load the workspace rooted at ``root`` (must contain prometheux.workspace.yaml)."""
    ws_file = root / "prometheux.workspace.yaml"
    ws = load_yaml(ws_file)
    workspace = LocalWorkspace(root=root)
    for proj_ref in ws.get("projects", []) or []:
        proj_dir = (root / proj_ref).resolve()
        workspace.projects.append(_load_project(proj_dir, proj_ref))
    return workspace


def _load_project(proj_dir: Path, ref: str) -> LocalProject:
    proj = load_yaml(proj_dir / "prometheux.yaml")
    meta = proj.get("project") or {}
    slug = proj_dir.name or ref.strip("./")
    project = LocalProject(
        slug=slug,
        id=meta.get("id"),
        name=meta.get("name") or slug,
        scope=meta.get("scope") or "user",
        directory=proj_dir,
        manifest_path=proj_dir / "prometheux.yaml",
    )

    concepts_dir = proj_dir / (proj.get("concepts") or "./concepts")
    if concepts_dir.is_dir():
        for path in sorted(concepts_dir.iterdir()):
            concept = _load_concept(path)
            if concept is not None:
                project.concepts.append(concept)

    for ds_ref in proj.get("datasources", []) or []:
        ds_file = proj_dir / ds_ref
        try:
            spec = load_yaml(ds_file)
        except ParseError:
            continue
        name = spec.get("name") or ds_file.stem
        project.datasources[name] = spec
        project.datasource_paths[name] = ds_file

    onto_ref = proj.get("ontology")
    if onto_ref:
        onto_file = proj_dir / onto_ref
        if onto_file.is_file():
            try:
                data = load_yaml(onto_file)
            except ParseError:
                data = None
            if data:
                # `$schema` is an editor hint, not part of the ontology graph.
                data.pop("$schema", None)
                project.ontology = data
                project.ontology_path = onto_file

    apps_ref = proj.get("apps")
    if apps_ref:
        apps_dir = proj_dir / apps_ref
        if apps_dir.is_dir():
            for path in sorted(apps_dir.glob("*.app.yaml")):
                try:
                    defn = load_yaml(path)
                except ParseError:
                    continue
                defn.pop("$schema", None)  # editor hint, not part of the AppDefinition
                app_id = defn.get("id")
                name = defn.get("name") or path.name[: -len(".app.yaml")]
                project.apps.append(LocalApp(
                    identity=app_id or name,
                    name=name,
                    definition=defn,
                    path=str(path.relative_to(proj_dir)),
                    has_id=bool(app_id),
                    file=path,
                ))

    return project


def _load_concept(path: Path) -> Optional[LocalConcept]:
    if not path.is_file():
        return None
    name = path.name
    if name.endswith(".meta.yaml"):
        return None
    if name.endswith(".context.yaml"):
        data = load_yaml(path)
        return LocalConcept(
            predicate=data.get("outputPredicate", path.stem),
            concept_type="context",
            body="",
            meta=data,
            path=path.name,
        )
    if name.endswith(".llm.md"):
        fm, body = split_frontmatter(path)
        return LocalConcept(
            predicate=fm.get("outputPredicate", path.stem),
            concept_type="llm",
            body=body,
            meta=fm,
            path=path.name,
        )
    if path.suffix in _BODY_KINDS:
        meta_path = path.with_name(path.stem + ".meta.yaml")
        meta = load_yaml(meta_path) if meta_path.is_file() else {}
        return LocalConcept(
            predicate=meta.get("outputPredicate", path.stem),
            concept_type=meta.get("conceptType") or _BODY_KINDS[path.suffix],
            body=path.read_text("utf-8"),
            meta=meta,
            path=path.name,
        )
    return None
