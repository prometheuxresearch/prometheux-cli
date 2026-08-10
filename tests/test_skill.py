from pathlib import Path

from click.testing import CliRunner

from prometheux_cli.agents_guide import render_cursor_rule, render_skill_md
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
