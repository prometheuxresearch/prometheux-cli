import re
from pathlib import Path

import click
from click.testing import CliRunner

from prometheux_cli.agents_guide import _SKILL_COMMANDS, _read, render_cursor_rule, render_skill_md
from prometheux_cli.cli import cli


def test_skill_md_has_frontmatter_body_and_reference_pointer():
    md = render_skill_md()
    assert md.startswith("---\nname: prometheux\n")
    assert "description:" in md.split("---")[1]
    # shared guide body + command reference
    assert "## Mental model" in md and "The `px` CLI — command reference" in md
    assert "`px apply`" in md and "ENGINE_BUSY" in md
    # points at the sibling schema reference (not inlined in SKILL.md)
    assert "reference/schemas.md" in md


def test_cursor_rule_inlines_schema_reference():
    mdc = render_cursor_rule()
    assert mdc.startswith("---\n") and "alwaysApply: false" in mdc
    # single-file rule: the schema reference is inlined, with real fields
    assert "## Schema reference" in mdc
    assert "`conceptType`" in mdc and "`outputPredicate`" in mdc


def _fake_home(monkeypatch, home: Path):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows


def test_install_claude_global(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    _fake_home(monkeypatch, home)

    result = CliRunner().invoke(cli, ["skill", "install"])
    assert result.exit_code == 0, result.output

    skill_dir = home / ".claude" / "skills" / "prometheux"
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "reference" / "schemas.md").is_file()
    assert (skill_dir / "reference" / "concept-meta.schema.json").is_file()


def test_install_project_and_cursor(tmp_path: Path):
    result = CliRunner().invoke(
        cli,
        ["skill", "install", "-t", "claude-project", "-t", "cursor", "--dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "skills" / "prometheux" / "SKILL.md").is_file()
    assert (tmp_path / ".cursor" / "rules" / "prometheux.mdc").is_file()


def test_install_is_idempotent_and_respects_force(tmp_path: Path):
    args = ["skill", "install", "-t", "claude-project", "--dir", str(tmp_path)]
    runner = CliRunner()

    assert runner.invoke(cli, args).exit_code == 0
    # second run without --force skips (nothing installed -> exit 1)
    second = runner.invoke(cli, args)
    assert second.exit_code == 1
    assert "skip" in second.output and "already exists" in second.output
    # with --force it overwrites (exit 0)
    assert runner.invoke(cli, args + ["--force"]).exit_code == 0


# The command reference is the only way an agent using the skill learns what px can do, so it
# must name every command and flag, and nothing that does not exist. A new command or flag
# fails here until it is documented in templates/skill_commands.md.
_FLAG = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")


def _leaf_commands(cmd=cli, path=()):
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            yield from _leaf_commands(sub, path + (name,))
    else:
        yield " ".join(path), cmd


def _reference_bullets():
    """`px <command> ARGS` header → the bullet's full text (header + indented lines)."""
    bullets, current = {}, None
    for line in _read(_SKILL_COMMANDS).splitlines():
        m = re.match(r"- \*\*`px ([^`]+)`\*\*", line)
        if m:
            current = m.group(1)
            bullets[current] = line
        elif current and line.startswith("  "):
            bullets[current] += "\n" + line
        else:
            current = None
    return bullets


def _documented():
    """command path → its bullet, matching each header to the command it documents."""
    leaves = dict(_leaf_commands())
    bullets = _reference_bullets()
    out = {}
    for header, text in bullets.items():
        matches = [p for p in leaves if header == p or header.startswith(p + " ")]
        assert matches, f"reference documents `px {header}`, which is not a px command"
        path = max(matches, key=len)
        assert path not in out, f"`px {path}` is documented twice"
        out[path] = text
    return leaves, out


def test_command_reference_lists_every_command():
    leaves, documented = _documented()
    missing = sorted(set(leaves) - set(documented))
    assert not missing, f"commands missing from templates/skill_commands.md: {missing}"


def test_command_reference_flags_match_the_cli():
    leaves, documented = _documented()
    for path, text in documented.items():
        cmd = leaves[path]
        real = {o for p in cmd.params if isinstance(p, click.Option) for o in p.opts + p.secondary_opts}
        real.discard("--help")
        named = set(_FLAG.findall(text))
        assert not (real - named), f"`px {path}`: flags not documented: {sorted(real - named)}"
        assert not (named - real), f"`px {path}`: documented flags that do not exist: {sorted(named - real)}"
