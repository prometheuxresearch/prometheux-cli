"""Small, dependency-light parsing helpers used by the offline commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import yaml


class ParseError(Exception):
    """A file could not be read or parsed."""


def load_yaml(path: Path) -> dict:
    """Load a YAML file into a dict, raising :class:`ParseError` on failure."""
    try:
        text = path.read_text("utf-8")
    except OSError as exc:
        raise ParseError(f"cannot read {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ParseError(f"invalid YAML in {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ParseError(f"expected a mapping at the top of {path}, got {type(data).__name__}")
    return data


def split_frontmatter(path: Path) -> Tuple[dict, str]:
    """Split a markdown file into (frontmatter dict, body text).

    Frontmatter is a leading ``---`` fenced YAML block. Returns an empty dict
    when there is none.
    """
    try:
        text = path.read_text("utf-8")
    except OSError as exc:
        raise ParseError(f"cannot read {path}: {exc}") from exc

    if not text.lstrip().startswith("---"):
        return {}, text

    # Normalize leading whitespace/newlines before the opening fence.
    stripped = text.lstrip("﻿").lstrip("\n")
    lines = stripped.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\n") != "---":
        return {}, text

    closing: Optional[int] = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\n") == "---":
            closing = i
            break
    if closing is None:
        raise ParseError(f"unterminated frontmatter in {path} (missing closing '---')")

    fm_text = "".join(lines[1:closing])
    body = "".join(lines[closing + 1 :])
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise ParseError(f"invalid frontmatter YAML in {path}: {exc}") from exc
    if not isinstance(fm, dict):
        raise ParseError(f"frontmatter in {path} must be a mapping")
    return fm, body
