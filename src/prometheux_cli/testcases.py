"""Test cases for `px test`: loading `*.test.yaml` files and running them.

A case names one program, or one question for the natural-language
translator, and the rows each output predicate must produce. Paths in a case
are relative to the case file:

    program: ./tc.vada          # or  question: "Transitive closure of edge. Output as tc."
    mode: exact                 # or  contains
    header: false               # expected CSVs start with a header line
    params: {}
    expect:
      tc: ./tc.csv              # a CSV path, or the rows inline: [[1, 2], [2, 3]]

A question case may give `expect` as a single CSV or list of rows; it is then
checked against `expect_predicate`, or the generated program's last @output.
The comparison itself lives in prometheux_chain (`check_program`,
`check_question`); this module only reads cases and reports on them.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

CASE_SUFFIX = ".test.yaml"
MODES = ("exact", "contains")


class CaseError(Exception):
    """A case file that cannot be run as written."""


@dataclass
class TestCase:
    __test__ = False  # not a pytest class, whatever the name suggests

    name: str
    program: Optional[str] = None
    question: Optional[str] = None
    context: Optional[str] = None
    expect: Any = None
    expect_predicate: Optional[str] = None
    mode: str = "exact"
    header: bool = False
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseResult:
    case: TestCase
    report: Any  # prometheux_chain.CheckReport

    @property
    def ok(self) -> bool:
        return bool(self.report.ok)


def find_cases(root: Path) -> List[Path]:
    """Every case file under ROOT, in a stable order."""
    return sorted(p for p in root.rglob(f"*{CASE_SUFFIX}") if p.is_file())


def load_case(path: Path) -> TestCase:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise CaseError(f"{path}: cannot read: {exc}") from exc
    if not isinstance(raw, dict):
        raise CaseError(f"{path}: expected a mapping at the top level")

    base = path.parent
    name = path.name[: -len(CASE_SUFFIX)] if path.name.endswith(CASE_SUFFIX) else path.stem
    has_program, has_question = "program" in raw, "question" in raw
    if has_program == has_question:
        raise CaseError(f"{path}: give exactly one of 'program' or 'question'")

    mode = raw.get("mode", "exact")
    if mode not in MODES:
        raise CaseError(f"{path}: mode must be one of {', '.join(MODES)}, got {mode!r}")
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        raise CaseError(f"{path}: 'params' must be a mapping")

    case = TestCase(
        name=name,
        question=raw.get("question"),
        context=raw.get("context"),
        expect_predicate=raw.get("expect_predicate"),
        mode=mode,
        header=bool(raw.get("header", False)),
        params=params,
    )
    if has_program:
        case.program = _read_program(base / str(raw["program"]), path)
    case.expect = _resolve_expect(raw.get("expect"), base, path, single_allowed=has_question)
    return case


def program_case(program_path: Path, expect: Dict[str, str], *, mode: str,
                 header: bool, params: Dict[str, Any]) -> TestCase:
    """A case for a single program given on the command line."""
    return TestCase(name=str(program_path), program=_read_program(program_path, program_path),
                    expect=expect or None, mode=mode, header=header, params=params)


def run_case(px, case: TestCase):
    if case.question is not None:
        report = px.check_question(case.question, expect=case.expect, mode=case.mode,
                                   expect_predicate=case.expect_predicate, context=case.context,
                                   params=case.params or None, header=case.header)
    else:
        report = px.check_program(case.program, expect=case.expect, mode=case.mode,
                                  params=case.params or None, header=case.header)
    return CaseResult(case=case, report=report)


def results_json(results: List[CaseResult]) -> str:
    return json.dumps(
        [{"name": r.case.name, "ok": r.ok, "report": r.report.to_dict()} for r in results],
        indent=2, default=str,
    )


def write_junit(results: List[CaseResult], path: Path) -> None:
    """A JUnit XML report, the format CI systems read test results from."""
    failures = sum(1 for r in results if not r.ok)
    suite = ET.Element("testsuite", name="px test", tests=str(len(results)),
                       failures=str(failures), errors="0")
    for result in results:
        testcase = ET.SubElement(suite, "testcase", classname="px.test", name=result.case.name)
        if not result.ok:
            summary = result.report.summary()
            failure = ET.SubElement(testcase, "failure", message=summary.splitlines()[0])
            failure.text = summary
        if result.report.program and result.case.question is not None:
            ET.SubElement(testcase, "system-out").text = result.report.program
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _read_program(path: Path, origin: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CaseError(f"{origin}: cannot read program {path}: {exc}") from exc


def _resolve_expect(expect, base: Path, origin: Path, *, single_allowed: bool):
    if expect is None:
        return None
    if isinstance(expect, dict):
        return {str(pred): _resolve_rows(rows, base) for pred, rows in expect.items()}
    if not single_allowed:
        raise CaseError(f"{origin}: 'expect' must map each predicate to a CSV or rows")
    return _resolve_rows(expect, base)


def _resolve_rows(rows, base: Path):
    """A CSV path made relative to the case file; inline rows pass through."""
    if isinstance(rows, str):
        return str(base / rows)
    return rows
