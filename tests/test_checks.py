import json
import threading
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
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


# ── parallel runs and engine workers ─────────────────────────────────────────

class _WorkersPx(_FakePx):
    """A _FakePx whose checks overlap, with engine workers that record their lifecycle."""

    def __init__(self, cap=4, refuse=None, never_ready=False, failing=()):
        super().__init__(failing=failing)
        self.cap, self.refuse, self.never_ready = cap, refuse, never_ready
        self.events = []
        self.lock = threading.Lock()
        self.active = self.max_active = 0

    def check_program(self, program, expect=None, **kw):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.02)
        with self.lock:
            self.active -= 1
        return super().check_program(program, expect=expect, **kw)

    def get_engine_workers(self):
        return {"max": self.cap, "desired": 0, "ready": 0}

    @contextmanager
    def engine_workers(self, n, timeout=600, keep=False, on_progress=None):
        if self.refuse:
            raise Exception(self.refuse)
        self.events.append(("up", n))
        try:
            if self.never_ready:
                raise TimeoutError(f"0 of {n} engine worker(s) ready after {timeout}s")
            on_progress({"ready": n, "billing": {"cost_per_worker_hour_usd": 1.5}})
            yield {"ready": n}
        finally:
            if not keep:
                self.events.append(("down", n))


def _many(tmp_path: Path, n: int) -> Path:
    suite = tmp_path / "many"
    suite.mkdir()
    (suite / "tc.vada").write_text("tc(X,Y) :- edge(X,Y).\n")
    for i in range(n):
        (suite / f"c{i:02d}.test.yaml").write_text(f"program: ./tc.vada\nexpect:\n  p{i:02d}: [[1, 2]]\n")
    return suite


def test_jobs_overlap_cases_and_keep_their_order(tmp_path: Path, monkeypatch):
    fake = _WorkersPx(failing={"p03"})
    _connect(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["test", str(_many(tmp_path, 8)), "--jobs", "4"])

    assert result.exit_code == 1
    assert fake.max_active > 1
    names = [line.split()[-1] for line in result.output.splitlines() if line.startswith(("PASS  ", "FAIL  "))]
    assert names == [f"c{i:02d}" for i in range(8)]
    assert fake.events == []


def test_replicas_bracket_the_suite_and_default_the_jobs(tmp_path: Path, monkeypatch):
    fake = _WorkersPx()
    _connect(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["test", str(_many(tmp_path, 6)), "--replicas", "2"])

    assert result.exit_code == 0, result.output
    assert fake.events == [("up", 2), ("down", 2)]
    assert 1 < fake.max_active <= 3
    assert "2/2 ready" in result.output
    assert "$1.50/h per worker ($3.00/h for 2)" in result.output


def test_workers_are_removed_when_a_case_fails(tmp_path: Path, monkeypatch):
    fake = _WorkersPx(failing={"p01"})
    _connect(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["test", str(_many(tmp_path, 3)), "--replicas", "1"])

    assert result.exit_code == 1
    assert fake.events == [("up", 1), ("down", 1)]


def test_keep_replicas_leaves_them_running(tmp_path: Path, monkeypatch):
    fake = _WorkersPx()
    _connect(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["test", str(_many(tmp_path, 2)), "--replicas", "1",
                                      "--keep-replicas"])

    assert result.exit_code == 0, result.output
    assert fake.events == [("up", 1)]


def test_auto_picks_one_worker_per_ten_cases_up_to_the_cap(tmp_path: Path, monkeypatch):
    fake = _WorkersPx(cap=2)
    _connect(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["test", str(_many(tmp_path, 35)), "--replicas", "auto"])

    assert result.exit_code == 0, result.output
    assert fake.events == [("up", 2), ("down", 2)]
    assert "--replicas auto: 2 engine worker(s) for 35 case(s)" in result.output


def test_auto_runs_a_small_suite_without_workers(tmp_path: Path, monkeypatch):
    fake = _WorkersPx()
    _connect(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["test", str(_many(tmp_path, 5)), "--replicas", "auto"])

    assert result.exit_code == 0, result.output
    assert fake.events == []
    assert fake.max_active == 1


def test_workers_that_never_get_ready_exit_2(tmp_path: Path, monkeypatch):
    fake = _WorkersPx(never_ready=True)
    _connect(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["test", str(_many(tmp_path, 2)), "--replicas", "2",
                                      "--replicas-timeout", "5"])

    assert result.exit_code == 2
    assert "0 of 2 engine worker(s) ready" in result.output
    assert fake.programs == []
    assert fake.events == [("up", 2), ("down", 2)]


def test_a_refusal_from_the_platform_exits_2(tmp_path: Path, monkeypatch):
    fake = _WorkersPx(refuse="No compute machine is running; start one before adding workers")
    _connect(monkeypatch, fake)

    result = CliRunner().invoke(cli, ["test", str(_many(tmp_path, 2)), "--replicas", "1"])

    assert result.exit_code == 2
    assert "engine workers: No compute machine is running" in result.output
    assert fake.programs == []


def test_replicas_must_be_a_number_or_auto(tmp_path: Path, monkeypatch):
    _connect(monkeypatch, _WorkersPx())

    result = CliRunner().invoke(cli, ["test", str(_many(tmp_path, 2)), "--replicas", "lots"])

    assert result.exit_code == 2
    assert "number or 'auto'" in result.output
