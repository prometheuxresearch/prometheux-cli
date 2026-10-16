import json
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

from click.testing import CliRunner

from prometheux_cli import cli as cli_module
from prometheux_cli.cli import cli


@dataclass
class _Report:
    ok: bool
    lines: list = field(default_factory=list)
    program: str = None
    model: str = None

    def summary(self):
        return "\n".join(self.lines) or ("PASS" if self.ok else "FAIL")

    def to_dict(self):
        return asdict(self)


class _FakePx:
    """Records what the CLI asked the SDK to check; fails predicates named in `failing`."""

    def __init__(self, failing=()):
        self.failing = set(failing)
        self.programs = []
        self.questions = []

    def check_program(self, program, expect=None, mode="exact", params=None, header=False, **kw):
        self.programs.append({"program": program, "expect": expect, "mode": mode,
                              "params": params, "header": header})
        return self._report(expect, program=program)

    def check_question(self, question, expect=None, mode="exact", expect_predicate=None,
                       context=None, params=None, header=False, **kw):
        self.questions.append({"question": question, "expect": expect, "mode": mode,
                               "expect_predicate": expect_predicate, "context": context})
        return self._report({expect_predicate or "tc": expect}, program='@output("tc").\ntc(1,2).',
                            model="p/m")

    def _report(self, expect, **kw):
        bad = sorted(self.failing & set(expect or {}))
        return _Report(ok=not bad, lines=[f"{p}: FAIL :: missing" for p in bad], **kw)


def _connect(monkeypatch, fake):
    monkeypatch.setattr(cli_module.checks_cmd, "connected_sdk", lambda **k: (fake, "u", "t"))


def _program(tmp_path, name="tc.vada"):
    path = tmp_path / name
    path.write_text("tc(X,Y) :- edge(X,Y).\n")
    (tmp_path / "tc.csv").write_text("1,2\n")
    return path


def test_a_program_is_checked_against_each_expected_csv(tmp_path: Path, monkeypatch):
    fake = _FakePx()
    _connect(monkeypatch, fake)
    prog = _program(tmp_path)

    result = CliRunner().invoke(cli, ["test", str(prog), "--expect", f"tc={tmp_path / 'tc.csv'}",
                                      "--mode", "contains", "--param", "year=2026"])

    assert result.exit_code == 0, result.output
    (call,) = fake.programs
    assert call["program"] == "tc(X,Y) :- edge(X,Y).\n"
    assert call["expect"] == {"tc": str(tmp_path / "tc.csv")}
    assert (call["mode"], call["params"]) == ("contains", {"year": "2026"})
    assert "PASS" in result.output


def test_a_failed_check_exits_1_and_says_why(tmp_path: Path, monkeypatch):
    _connect(monkeypatch, _FakePx(failing={"tc"}))
    prog = _program(tmp_path)

    result = CliRunner().invoke(cli, ["test", str(prog), "--expect", f"tc={tmp_path / 'tc.csv'}"])

    assert result.exit_code == 1
    assert "tc: FAIL :: missing" in result.output


def test_a_malformed_expect_is_a_usage_error(tmp_path: Path, monkeypatch):
    _connect(monkeypatch, _FakePx())
    prog = _program(tmp_path)

    result = CliRunner().invoke(cli, ["test", str(prog), "--expect", "tc.csv"])

    assert result.exit_code == 2
    assert "PRED=CSV" in result.output


def test_a_question_is_translated_then_checked(tmp_path: Path, monkeypatch):
    fake = _FakePx()
    _connect(monkeypatch, fake)
    _program(tmp_path)
    saved = tmp_path / "out.vada"

    result = CliRunner().invoke(cli, ["test", "--question", "transitive closure",
                                      "--expect-csv", str(tmp_path / "tc.csv"),
                                      "--save-vada", str(saved)])

    assert result.exit_code == 0, result.output
    (call,) = fake.questions
    assert call["question"] == "transitive closure"
    assert call["expect"] == str(tmp_path / "tc.csv")
    assert "generated program [p/m]" in result.output
    assert saved.read_text() == '@output("tc").\ntc(1,2).\n'


def test_question_only_flags_without_a_question_are_refused(tmp_path: Path, monkeypatch):
    _connect(monkeypatch, _FakePx())
    prog = _program(tmp_path)

    result = CliRunner().invoke(cli, ["test", str(prog), "--expect-pred", "tc"])

    assert result.exit_code == 2


def _suite(tmp_path: Path) -> Path:
    suite = tmp_path / "tests"
    (suite / "nested").mkdir(parents=True)
    (suite / "tc.vada").write_text("tc(X,Y) :- edge(X,Y).\n")
    (suite / "tc.csv").write_text("1,2\n")
    (suite / "tc.test.yaml").write_text("program: ./tc.vada\nexpect:\n  tc: ./tc.csv\n")
    (suite / "nested" / "owns.test.yaml").write_text(
        "program: ../tc.vada\nmode: contains\nexpect:\n  owns: [[1, 2]]\n")
    (suite / "nested" / "ask.test.yaml").write_text(
        "question: transitive closure\nexpect: ../tc.csv\n")
    return suite


def test_a_folder_runs_every_case_with_paths_relative_to_it(tmp_path: Path, monkeypatch):
    fake = _FakePx()
    _connect(monkeypatch, fake)
    suite = _suite(tmp_path)

    result = CliRunner().invoke(cli, ["test", str(suite)])

    assert result.exit_code == 0, result.output
    assert "3 test(s) passed" in result.output
    expects = sorted(json.dumps(c["expect"], sort_keys=True) for c in fake.programs)
    assert expects == sorted([json.dumps({"tc": str(suite / "tc.csv")}),
                              json.dumps({"owns": [[1, 2]]})])
    assert fake.questions[0]["expect"] == str(suite / "nested" / ".." / "tc.csv")


def test_a_suite_writes_junit_and_fails_on_one_bad_case(tmp_path: Path, monkeypatch):
    _connect(monkeypatch, _FakePx(failing={"owns"}))
    suite = _suite(tmp_path)
    report = tmp_path / "out" / "junit.xml"

    result = CliRunner().invoke(cli, ["test", str(suite), "--junit-xml", str(report)])

    assert result.exit_code == 1
    assert "1 of 3 test(s) failed" in result.output
    root = ET.parse(report).getroot()
    assert (root.get("tests"), root.get("failures")) == ("3", "1")
    failed = [tc.get("name") for tc in root if tc.find("failure") is not None]
    assert failed == ["owns"]


def test_json_output_carries_each_report(tmp_path: Path, monkeypatch):
    _connect(monkeypatch, _FakePx())
    suite = _suite(tmp_path)

    result = CliRunner().invoke(cli, ["test", str(suite), "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert sorted(item["name"] for item in data) == ["ask", "owns", "tc"]
    assert all(item["ok"] for item in data)


def test_a_case_with_both_program_and_question_is_refused(tmp_path: Path, monkeypatch):
    _connect(monkeypatch, _FakePx())
    case = tmp_path / "bad.test.yaml"
    case.write_text("program: ./x.vada\nquestion: why\n")

    result = CliRunner().invoke(cli, ["test", str(case)])

    assert result.exit_code == 2
    assert "exactly one of 'program' or 'question'" in result.output


def test_an_empty_folder_is_a_usage_error(tmp_path: Path, monkeypatch):
    _connect(monkeypatch, _FakePx())

    result = CliRunner().invoke(cli, ["test", str(tmp_path)])

    assert result.exit_code == 2
    assert "no *.test.yaml files" in result.output
