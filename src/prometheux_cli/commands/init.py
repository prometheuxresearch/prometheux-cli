"""`px init` — scaffold a new Prometheux workspace (fully offline)."""

from __future__ import annotations

import sys
from importlib import resources
from pathlib import Path

import click

from ..resources import iter_schema_files

_SCAFFOLD_DIR = "scaffold"
_TEXT_SUFFIXES = {".yaml", ".yml", ".md", ".mdc", ".txt", ".json", ".vadalog", ".sql", ".cypher"}

_CURSOR_RULE = "See ../../AGENTS.md for how to author and apply this Prometheux workspace.\n"
_GITIGNORE = "# px\n.px/state/\n*.pyc\n__pycache__/\n.env\n"


@click.command()
@click.argument("directory", required=False, default=".", type=click.Path(path_type=Path))
@click.option("--name", "name", default=None, help="Workspace name (defaults to the directory name).")
@click.option("--force", is_flag=True, help="Write into a non-empty directory.")
def init(directory: Path, name: str, force: bool) -> None:
    """Scaffold a workspace skeleton in DIRECTORY (default: current directory)."""
    dest = directory.resolve()
    dest.mkdir(parents=True, exist_ok=True)

    if any(dest.iterdir()) and not force:
        click.echo(
            click.style("FAIL", fg="red", bold=True)
            + f": {dest} is not empty. Use --force to scaffold into it anyway.",
            err=True,
        )
        sys.exit(1)

    workspace_name = name or dest.name

    root = resources.files("prometheux_cli").joinpath(_SCAFFOLD_DIR)
    written = _copy_tree(root, dest, workspace_name)

    # Generated (not part of the bundled scaffold): schemas + editor pointers.
    schemas_dir = dest / ".px" / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in iter_schema_files():
        (schemas_dir / filename).write_text(text, "utf-8")
        written += 1

    cursor_dir = dest / ".cursor" / "rules"
    cursor_dir.mkdir(parents=True, exist_ok=True)
    (cursor_dir / "prometheux.mdc").write_text(_CURSOR_RULE, "utf-8")

    gitignore = dest / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE, "utf-8")

    click.echo(
        click.style("Created", fg="green", bold=True)
        + f" workspace '{workspace_name}' in {dest} ({written} files)."
    )
    click.echo("\nNext:")
    click.echo("  1. Read AGENTS.md")
    click.echo("  2. Edit the example under projects/example/")
    click.echo("  3. Run `px validate`")


def _copy_tree(node, dest: Path, workspace_name: str) -> int:
    """Recursively copy a scaffold Traversable into ``dest``. Returns file count."""
    count = 0
    for child in node.iterdir():
        target = dest / child.name
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            count += _copy_tree(child, target, workspace_name)
            continue
        suffix = Path(child.name).suffix
        if suffix in _TEXT_SUFFIXES:
            text = child.read_text("utf-8").replace("{{WORKSPACE_NAME}}", workspace_name)
            target.write_text(text, "utf-8")
        else:
            target.write_bytes(child.read_bytes())
        count += 1
    return count
