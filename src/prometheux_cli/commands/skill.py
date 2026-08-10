"""`px skill install` — install the Prometheux authoring skill into a coding agent.

The skill is generated from THIS package's bundled schemas + curated prose (the same
source as `AGENTS.md`), so a user gets the knowledge with no repo to clone and it always
matches the installed `px`. Targets:

- ``claude``         -> ~/.claude/skills/prometheux/         (global Claude Code skill)
- ``claude-project`` -> <dir>/.claude/skills/prometheux/     (per-repo Claude Code skill)
- ``cursor``         -> <dir>/.cursor/rules/prometheux.mdc    (Cursor project rule)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

import click

from ..agents_guide import (
    SKILL_NAME,
    render_cursor_rule,
    render_schema_reference,
    render_skill_md,
)
from ..resources import iter_schema_files

_TARGETS = ["claude", "claude-project", "cursor"]


@click.group()
def skill() -> None:
    """Install the Prometheux authoring skill into Claude Code / Cursor."""


def _claude_skill_dir(base: Path) -> Path:
    return base / ".claude" / "skills" / SKILL_NAME


def _write_claude_skill(skill_dir: Path) -> List[Path]:
    """Write SKILL.md + reference/ (schema guide + raw schemas). Returns written paths."""
    written: List[Path] = []
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(render_skill_md(), "utf-8")
    written.append(skill_md)

    ref = skill_dir / "reference"
    ref.mkdir(parents=True, exist_ok=True)
    schemas_md = ref / "schemas.md"
    schemas_md.write_text(render_schema_reference().rstrip() + "\n", "utf-8")
    written.append(schemas_md)
    for filename, text in iter_schema_files():
        path = ref / filename
        path.write_text(text, "utf-8")
        written.append(path)
    return written


def _install_target(target: str, base: Path, force: bool) -> Tuple[str, List[Path]]:
    """Install one target. Returns (status, written_paths). status in skipped|ok."""
    if target in ("claude", "claude-project"):
        root = Path.home() if target == "claude" else base
        dest = _claude_skill_dir(root)
        if (dest / "SKILL.md").exists() and not force:
            click.echo(
                f"  {click.style('skip', fg='yellow')} {target}: {dest} already exists "
                "(use --force to overwrite)."
            )
            return "skipped", []
        written = _write_claude_skill(dest)
        click.echo(f"  {click.style('ok', fg='green')} {target}: {dest}")
        return "ok", written

    # cursor
    dest = base / ".cursor" / "rules" / f"{SKILL_NAME}.mdc"
    if dest.exists() and not force:
        click.echo(
            f"  {click.style('skip', fg='yellow')} cursor: {dest} already exists "
            "(use --force to overwrite)."
        )
        return "skipped", []
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(render_cursor_rule(), "utf-8")
    click.echo(f"  {click.style('ok', fg='green')} cursor: {dest}")
    return "ok", [dest]


@skill.command("install")
@click.option(
    "--target", "-t", "targets", multiple=True,
    type=click.Choice(_TARGETS),
    help="Where to install (repeatable). Default: claude (global Claude Code skill).",
)
@click.option(
    "--dir", "base", default=".", type=click.Path(path_type=Path),
    help="Base directory for project targets (claude-project, cursor). Default: current dir.",
)
@click.option("--force", is_flag=True, help="Overwrite an existing install.")
def skill_install(targets: Tuple[str, ...], base: Path, force: bool) -> None:
    """Generate and install the Prometheux skill (no repo clone needed)."""
    chosen = list(targets) or ["claude"]
    base = base.resolve()

    click.echo(f"Installing the '{SKILL_NAME}' skill → {', '.join(chosen)}")
    results = [_install_target(t, base, force) for t in chosen]

    ok = sum(1 for status, _ in results if status == "ok")
    skipped = sum(1 for status, _ in results if status == "skipped")
    files = sum(len(paths) for _, paths in results)

    if ok:
        click.echo(
            click.style("Installed", fg="green", bold=True)
            + f" {ok} target(s), {files} file(s)."
        )
        click.echo(
            "The agent will use it when you work on Vadalog / Prometheux. "
            "Claude Code: reload skills or restart. Cursor: the rule is picked up per project."
        )
    if skipped and not ok:
        # Nothing installed and something was skipped -> non-zero so scripts notice.
        sys.exit(1)
