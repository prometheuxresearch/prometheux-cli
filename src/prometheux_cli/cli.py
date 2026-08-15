"""`px` command-line entry point."""

from __future__ import annotations

import click

from . import __version__
from .commands import app as app_cmd
from .commands import apply as apply_cmd
from .commands import compute as compute_cmd
from .commands import context as context_cmd
from .commands import datasource as datasource_cmd
from .commands import delete as delete_cmd
from .commands import init as init_cmd
from .commands import list as list_cmd
from .commands import login as login_cmd
from .commands import plan as plan_cmd
from .commands import playbook as playbook_cmd
from .commands import policy as policy_cmd
from .commands import pull as pull_cmd
from .commands import query as query_cmd
from .commands import run as run_cmd
from .commands import search as search_cmd
from .commands import show as show_cmd
from .commands import skill as skill_cmd
from .commands import snapshot as snapshot_cmd
from .commands import status as status_cmd
from .commands import template as template_cmd
from .commands import validate as validate_cmd


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    epilog=(
        "Examples:\n\n"
        "  px init        Scaffold a new workspace\n"
        "  px validate    Check the workspace offline\n"
        "  px plan        Preview changes against the platform\n"
        "  px apply       Apply the workspace to the platform\n"
    ),
)
@click.version_option(__version__, "-V", "--version", prog_name="px")
def cli() -> None:
    """px — Prometheux as code.

    Author a workspace (lineage + context) as files, then plan and apply it.
    `init` and `validate` run fully offline; `login`, `pull`, `plan`, `apply`,
    `run`, and `status` reach the platform. `status --watch` live-monitors each
    ontology's run state.
    """


cli.add_command(init_cmd.init)
cli.add_command(validate_cmd.validate)
cli.add_command(login_cmd.login)
cli.add_command(pull_cmd.pull)
cli.add_command(list_cmd.list_, name="list")
cli.add_command(delete_cmd.delete)
cli.add_command(plan_cmd.plan)
cli.add_command(apply_cmd.apply)
cli.add_command(run_cmd.run)
cli.add_command(show_cmd.show)
cli.add_command(query_cmd.query)
cli.add_command(search_cmd.search)
cli.add_command(status_cmd.status)
cli.add_command(context_cmd.context)
cli.add_command(snapshot_cmd.snapshot)
cli.add_command(policy_cmd.policy)
cli.add_command(template_cmd.template)
cli.add_command(datasource_cmd.datasource)
cli.add_command(app_cmd.app)
cli.add_command(playbook_cmd.playbook)
cli.add_command(compute_cmd.compute)
cli.add_command(skill_cmd.skill)


def main() -> None:
    """Console-script entry point (see ``[project.scripts]`` in pyproject)."""
    # Silence urllib3's LibreSSL notice so `px` output stays clean for scripting.
    # Message-matched (not category) so it needs no urllib3 import and works offline.
    import warnings

    warnings.filterwarnings("ignore", message=r"urllib3 v2 only supports OpenSSL")
    cli()


if __name__ == "__main__":  # pragma: no cover
    main()
