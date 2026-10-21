"""px must reflect every tool the platform exposes through prometheux_chain.

Every public SDK export is either called by px (`px.<name>` in src/) or listed in
sdk-coverage.yaml with a reason. A new SDK export fails here until it is exposed or
classified, so nothing the platform adds can slip past the CLI unnoticed.
"""

import inspect
import re
from pathlib import Path

import click
import yaml

import prometheux_chain
from prometheux_cli.cli import cli

ROOT = Path(__file__).resolve().parents[1]
REASONS = {"gap", "covered", "helper", "internal", "ui-only", "deprecated"}


def _exports():
    return {n for n in dir(prometheux_chain)
            if not n.startswith("_") and not inspect.ismodule(getattr(prometheux_chain, n))}


def _called_by_px():
    src = "\n".join(p.read_text("utf-8") for p in (ROOT / "src").rglob("*.py"))
    return set(re.findall(r"\bpx\.(\w+)", src))


def _coverage():
    return yaml.safe_load((ROOT / "sdk-coverage.yaml").read_text("utf-8"))["not_exposed"]


def _commands(cmd=cli, path=("px",)):
    yield " ".join(path)
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            yield from _commands(sub, path + (name,))


def test_every_sdk_export_is_exposed_or_classified():
    unclassified = sorted(_exports() - _called_by_px() - set(_coverage()))
    assert not unclassified, (
        f"prometheux_chain {prometheux_chain.__version__} exports that px neither calls nor lists in "
        f"sdk-coverage.yaml: {unclassified}. Expose them, or add an entry with a reason."
    )


def test_coverage_entries_are_current():
    exports, called = _exports(), _called_by_px()
    for name in _coverage():
        assert name in exports, f"sdk-coverage.yaml lists `{name}`, which prometheux_chain no longer exports"
        assert name not in called, f"px now calls `{name}`: it is exposed, remove it from sdk-coverage.yaml"


def test_coverage_entries_are_well_formed():
    commands = set(_commands())
    for name, entry in _coverage().items():
        assert entry.get("reason") in REASONS, f"`{name}`: reason must be one of {sorted(REASONS)}"
        assert entry.get("note"), f"`{name}`: say why in a note"
        if entry["reason"] == "covered":
            assert entry.get("px"), f"`{name}`: a covered export names the px command(s) that cover it"
            for command in entry["px"]:
                assert command in commands, f"`{name}`: `{command}` is not a px command"
        if entry["reason"] == "gap":
            assert entry.get("area"), f"`{name}`: a gap names its area, so the backlog can be batched"
