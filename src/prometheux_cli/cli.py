"""`px` command-line entry point."""

from __future__ import annotations

import click

from . import __version__
from .commands import apply as apply_cmd
from .commands import context as context_cmd
from .commands import init as init_cmd
from .commands import login as login_cmd
from .commands import plan as plan_cmd
from .commands import pull as pull_cmd
from .commands import run as run_cmd
from .commands import validate as validate_cmd


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, "-V", "--version", prog_name="px")
def cli() -> None:
    """px — Prometheux as code.

    Author a workspace (lineage + context) as files, then plan and apply it.
    `init` and `validate` run fully offline; `login`, `pull`, `plan`, and
    `apply` reach the platform.
    """


cli.add_command(init_cmd.init)
cli.add_command(validate_cmd.validate)
cli.add_command(login_cmd.login)
cli.add_command(pull_cmd.pull)
cli.add_command(plan_cmd.plan)
cli.add_command(apply_cmd.apply)
cli.add_command(run_cmd.run)
cli.add_command(context_cmd.context)


def main() -> None:
    """Console-script entry point (see ``[project.scripts]`` in pyproject)."""
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()
