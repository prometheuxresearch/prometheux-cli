"""Collect the context layer from `*.context.md` manifests (§7).

A manifest carries `scope` / `activation` / `kind` / `notes` / `links` and points
at pristine body files. Note identity is `(manifest, referenced path)` (design
decision A): the same body in two sets is two notes. Pure collection here; the
`px context apply` command performs the platform writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .parsing import ParseError, split_frontmatter

RefKey = Tuple[str, str]  # (manifest path, referenced body path)


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
class ContextLink:
    from_key: RefKey
    to_key: RefKey
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
            if frm in key_by_path and to in key_by_path:
                links.append(ContextLink(key_by_path[frm], key_by_path[to], relation))
            else:
                warnings.append(f"{rel}: link references a path not in this set ({frm} -> {to})")

    return notes, links, warnings
