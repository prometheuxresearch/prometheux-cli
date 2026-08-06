"""Collect the context layer from `*.context.md` manifests (§7).

A manifest carries `scope` / `activation` / `kind` / `notes` / `links` and points
at pristine body files. Note identity is `(manifest, referenced path)` (design
decision A): the same body in two sets is two notes. Pure collection here; the
`px context apply` command performs the platform writes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .parsing import ParseError, split_frontmatter

RefKey = Tuple[str, str]  # (manifest path, referenced body path)


def build_note_resolver(root: Path) -> Callable[[str], List[str]]:
    """Return a resolver mapping a context concept's note path -> [note id(s)].

    Reads the context-state written by `px context apply` (identity
    `(manifest, path)` -> note id). A static context concept references a note by
    its body path; we match on the full path first, then the basename. Zero or
    multiple matches are surfaced by callers so a concept never silently pins the
    wrong notes. Returns an empty list for every path when no state exists.
    """
    state_path = root / ".px" / "context-state.json"
    state: dict = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text("utf-8"))
        except (OSError, ValueError):
            state = {}

    by_path: Dict[str, List[str]] = {}
    by_base: Dict[str, List[str]] = {}
    for key, val in state.items():
        note_id = (val or {}).get("id")
        if not note_id:
            continue
        body = key.split("::", 1)[1] if "::" in key else key
        by_path.setdefault(body, []).append(note_id)
        by_base.setdefault(Path(body).name, []).append(note_id)

    def resolve(path: str) -> List[str]:
        return by_path.get(path) or by_base.get(Path(path).name) or []

    return resolve


@dataclass
class ContextNote:
    ref_key: RefKey
    body_path: Path
    text: str
    title: Optional[str]
    scope: str          # global | project
    scope_id: Optional[str]
    activation: str     # retrieved | always | on_demand
    kind: str


@dataclass
class Endpoint:
    kind: str           # "note" | "concept"
    note_key: Optional[RefKey] = None   # set when kind == "note"
    concept_id: Optional[str] = None    # "<project_id>:<predicate>" when kind == "concept"


@dataclass
class ContextLink:
    src: Endpoint
    dst: Endpoint
    relation: str


def _first_heading(text: str) -> Optional[str]:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip() or None
    return None


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _owning_project(manifest: Path, projects):
    best, best_len = None, -1
    for p in projects:
        if p.directory and _is_within(manifest, p.directory):
            length = len(str(p.directory.resolve()))
            if length > best_len:
                best, best_len = p, length
    return best


def collect_context(workspace) -> Tuple[List[ContextNote], List[ContextLink], List[str]]:
    """Walk every `*.context.md` under the workspace; return (notes, links, warnings)."""
    notes: List[ContextNote] = []
    links: List[ContextLink] = []
    warnings: List[str] = []

    for manifest in sorted(workspace.root.rglob("*.context.md")):
        rel = str(manifest.relative_to(workspace.root))
        try:
            fm, _ = split_frontmatter(manifest)
        except ParseError as exc:
            warnings.append(str(exc))
            continue
        if not fm:
            warnings.append(f"{rel}: no frontmatter")
            continue

        scope = fm.get("scope", "global")
        default_activation = fm.get("activation") or ("always" if fm.get("type") == "rule" else "retrieved")
        default_kind = fm.get("kind", "fact")

        scope_id = None
        if scope == "project":
            owner = _owning_project(manifest, workspace.projects)
            if owner is None or not owner.id:
                warnings.append(f"{rel}: project-scoped but owning project has no server id; skipped")
                continue
            scope_id = owner.id

        key_by_path = {}
        for entry in fm.get("notes", []) or []:
            path = entry["path"] if isinstance(entry, dict) else entry
            activation = (entry.get("activation") if isinstance(entry, dict) else None) or default_activation
            kind = (entry.get("kind") if isinstance(entry, dict) else None) or default_kind
            body = (manifest.parent / path).resolve()
            if not body.is_file():
                warnings.append(f"{rel}: referenced body not found: {path}")
                continue
            text = body.read_text("utf-8")
            ref = (rel, path)
            key_by_path[path] = ref
            notes.append(ContextNote(ref, body, text, _first_heading(text), scope, scope_id, activation, kind))

        for link in fm.get("links", []) or []:
            frm, to, relation = link.get("from"), link.get("to"), link.get("relation", "relates_to")
            src = _endpoint(frm, key_by_path, scope_id)
            dst = _endpoint(to, key_by_path, scope_id)
            if src is None or dst is None:
                warnings.append(f"{rel}: link references an unknown note/concept ({frm} -> {to})")
                continue
            links.append(ContextLink(src, dst, relation))

    return notes, links, warnings


def _endpoint(ref, key_by_path, scope_id) -> Optional[Endpoint]:
    """Resolve a link endpoint: a body path (note) or `concept:[<project>:]<predicate>`."""
    if not isinstance(ref, str):
        return None
    if ref.startswith("concept:"):
        rest = ref[len("concept:"):]
        if ":" in rest:
            project, predicate = rest.split(":", 1)
        else:
            project, predicate = scope_id, rest
        if not project or not predicate:
            return None
        return Endpoint("concept", concept_id=f"{project}:{predicate}")
    if ref in key_by_path:
        return Endpoint("note", note_key=key_by_path[ref])
    return None
