"""Collect the context layer from `*.context.md` manifests (§7).

A manifest carries `scope` / `activation` / `kind` / `notes` / `links` and points
at pristine body files. Note identity is `(manifest, referenced path)` (design
decision A): the same body in two sets is two notes. Pure collection here; the
`px context apply` command performs the platform writes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .parsing import ParseError, split_frontmatter

RefKey = Tuple[str, str]  # (manifest path, referenced body path)


def note_content_hash(scope: str, scope_id: Optional[str], kind: str,
                      activation: str, text: str) -> str:
    """Content hash for a context note's `.px/context-state.json` identity.

    The single source of truth for both `px context apply` (which writes the
    state) and `px pull` (which seeds it): a pulled note whose state is seeded
    here classifies as ``unchanged`` on the next apply — no re-create, no
    duplicate. Keep the payload order in lockstep with both callers.
    """
    payload = "|".join([scope or "", scope_id or "", kind or "", activation or "", text or ""])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    concept_id: Optional[str] = None    # "<ontology_id>:<predicate>" when kind == "concept"


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


def _owning_ontology(manifest: Path, ontologies):
    best, best_len = None, -1
    for o in ontologies:
        if o.directory and _is_within(manifest, o.directory):
            length = len(str(o.directory.resolve()))
            if length > best_len:
                best, best_len = o, length
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
            owner = _owning_ontology(manifest, workspace.ontologies)
            if owner is None or not owner.id:
                warnings.append(f"{rel}: project-scoped but owning ontology has no server id; skipped")
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


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _note_slug(note: dict, index: int) -> str:
    """A filename stem for a note body: its title, else its first line, else index."""
    base = (note.get("title") or "").strip()
    if not base:
        for line in (note.get("text") or "").splitlines():
            candidate = line.strip().lstrip("#").strip()
            if candidate:
                base = candidate
                break
    slug = _SLUG_RE.sub("-", base.lower()).strip("-")[:50].strip("-")
    return slug or f"note-{index + 1}"


@dataclass
class PulledContext:
    manifest_text: str
    body_files: List[Tuple[str, str]]        # (filename beside the manifest, text)
    state_entries: Dict[str, dict]           # "<manifest_rel>::<filename>" -> {id, hash}
    count: int


def build_pulled_context(server_notes: List[dict], *, scope: str, scope_id: Optional[str],
                         manifest_rel: str) -> Optional[PulledContext]:
    """Turn server context notes into a `.context.md` manifest + body files + state.

    ``scope`` is the CLI frontmatter scope (``project`` | ``global``) — NOT the
    server's ``ontology`` spelling — and ``scope_id`` is the owning ontology id for
    project scope (None for global). Both feed :func:`note_content_hash`, so the
    seeded state matches what ``px context apply`` computes when it re-reads these
    files, making the first apply after a pull a clean no-op (no duplicates).

    The body of each file is the note's text written verbatim, so even if the
    seeded state is later lost, ``px context apply``'s server reconcile (which
    matches on exact text) still adopts the existing note instead of duplicating.

    Returns None when there is nothing to write.
    """
    import yaml

    entries: List[dict] = []
    body_files: List[Tuple[str, str]] = []
    state: Dict[str, dict] = {}
    used: set = set()

    for i, note in enumerate(server_notes or []):
        text = note.get("text")
        if not text:
            continue  # nothing authorable
        kind = note.get("kind") or "fact"
        activation = note.get("activation") or "retrieved"
        stem = _note_slug(note, i)
        fname = f"{stem}.md"
        n = 2
        while fname in used:
            fname = f"{stem}-{n}.md"
            n += 1
        used.add(fname)

        entries.append({"path": fname, "activation": activation, "kind": kind})
        body_files.append((fname, text))
        note_id = note.get("id")
        if note_id:
            key = f"{manifest_rel}::{fname}"
            state[key] = {"id": str(note_id),
                          "hash": note_content_hash(scope, scope_id, kind, activation, text)}

    if not entries:
        return None

    fm = {"scope": scope, "notes": entries}
    manifest_text = (
        "---\n"
        + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + "<!-- Pulled from the platform. Edit the body files to change note text. -->\n"
    )
    return PulledContext(manifest_text, body_files, state, len(entries))


def _endpoint(ref, key_by_path, scope_id) -> Optional[Endpoint]:
    """Resolve a link endpoint: a body path (note) or `concept:[<ontology>:]<predicate>`."""
    if not isinstance(ref, str):
        return None
    if ref.startswith("concept:"):
        rest = ref[len("concept:"):]
        if ":" in rest:
            ontology, predicate = rest.split(":", 1)
        else:
            ontology, predicate = scope_id, rest
        if not ontology or not predicate:
            return None
        return Endpoint("concept", concept_id=f"{ontology}:{predicate}")
    if ref in key_by_path:
        return Endpoint("note", note_key=key_by_path[ref])
    return None
