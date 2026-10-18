"""`px test` — unit tests for Vadalog programs, run on the platform engine."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import click

from ..sdk import SdkError, connected_sdk
from ..testcases import (
    CASE_SUFFIX,
    MODES,
    CaseError,
    TestCase,
    find_cases,
    load_case,
    program_case,
    results_json,
    run_case,
    write_junit,
)

EXIT_FAILED = 1
EXIT_USAGE = 2


@click.command(name="test")
@click.argument("target", required=False, type=click.Path(exists=True, path_type=Path))
@click.option("--expect", "expects", multiple=True, metavar="PRED=CSV",
              help="Rows PRED must produce, as a CSV file (repeatable). For a program TARGET.")
@click.option("--question", "-q", help="Ask the NL translator for the program instead of reading TARGET.")
@click.option("--context", help="Extra context for the translator (with --question).")
@click.option("--expect-csv", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Rows the generated program must produce (with --question).")
@click.option("--expect-pred", help="Predicate --expect-csv applies to (default: the program's last @output).")
@click.option("--mode", type=click.Choice(MODES), default="exact", show_default=True,
              help="exact: same rows and count. contains: every expected row is produced.")
@click.option("--header", is_flag=True, help="Expected CSVs start with a header line to skip.")
@click.option("--param", "params", multiple=True, metavar="KEY=VALUE", help="Program parameter (repeatable).")
@click.option("--save-vada", type=click.Path(dir_okay=False, path_type=Path),
              help="Write the generated program to this file (with --question).")
@click.option("--json", "as_json", is_flag=True, help="Print the reports as JSON.")
@click.option("--junit-xml", type=click.Path(dir_okay=False, path_type=Path),
              help="Also write a JUnit XML report, for CI.")
def run_tests(target: Optional[Path], expects, question, context, expect_csv, expect_pred,
              mode, header, params, save_vada, as_json, junit_xml) -> None:
    """Check that Vadalog programs produce the rows you expect.

    TARGET is a .vada program (with --expect), a *.test.yaml case, or a folder
    of cases. Each program runs on the platform engine and every expected
    predicate is compared with its CSV. Exit code 0 when everything passes,
    1 when a check fails, 2 when the tests could not run.

    \b
    Examples:
      px test tc.vada --expect tc=tc.csv
      px test --question "Transitive closure of edge(X,Y). Output as tc." --expect-csv tc.csv
      px test tests/ --junit-xml report.xml
    """
    try:
        cases = _cases(target, expects, question, context, expect_csv, expect_pred, save_vada,
                       mode, header, _parse_params(params))
        px, _, _ = connected_sdk(require_token=True)
    except (CaseError, SdkError, click.UsageError) as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(EXIT_USAGE)

    single = len(cases) == 1
    results = []
    for case in cases:
        result = run_case(px, case)
        results.append(result)
        if not as_json:
            _print_result(result, verbose=single)

    if save_vada and results[0].report.program:
        save_vada.write_text(results[0].report.program.rstrip() + "\n", encoding="utf-8")
    if junit_xml:
        write_junit(results, junit_xml)

    failed = sum(1 for r in results if not r.ok)
    if as_json:
        click.echo(results_json(results))
    else:
        _print_totals(len(results), failed)
    if failed:
        sys.exit(EXIT_FAILED)


def _cases(target, expects, question, context, expect_csv, expect_pred, save_vada,
           mode, header, params) -> List[TestCase]:
    if question:
        if target is not None:
            raise click.UsageError("give either TARGET or --question, not both")
        return [TestCase(name="question", question=question, context=context,
                         expect=str(expect_csv) if expect_csv else None,
                         expect_predicate=expect_pred, mode=mode, header=header, params=params)]
    if target is None:
        raise click.UsageError("give a program, a case file or a folder of cases, or --question")
    if expect_csv or expect_pred or context or save_vada:
        raise click.UsageError("--expect-csv, --expect-pred, --context and --save-vada go with --question")
    is_case_file = target.name.endswith(CASE_SUFFIX)
    if expects and (target.is_dir() or is_case_file):
        raise click.UsageError("--expect goes with a program; a case file names its own expectations")
    if target.is_dir():
        paths = find_cases(target)
        if not paths:
            raise CaseError(f"no *{CASE_SUFFIX} files under {target}")
        return [load_case(path) for path in paths]
    if is_case_file:
        return [load_case(target)]
    return [program_case(target, _parse_expects(expects), mode=mode, header=header, params=params)]


def _parse_expects(pairs) -> dict:
    out = {}
    for pair in pairs:
        pred, sep, path = pair.partition("=")
        if not sep or not pred.strip() or not path.strip():
            raise click.UsageError(f"--expect must be PRED=CSV, got {pair!r}")
        out[pred.strip()] = path.strip()
    return out


def _parse_params(pairs) -> dict:
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise click.UsageError(f"--param must be KEY=VALUE, got {pair!r}")
        out[key.strip()] = value
    return out


def _print_result(result, *, verbose: bool) -> None:
    report = result.report
    status = click.style("PASS", fg="green", bold=True) if result.ok else click.style("FAIL", fg="red", bold=True)
    click.echo(f"{status}  {result.case.name}")
    if verbose and result.case.question is not None and report.program:
        click.echo(click.style(f"  generated program [{report.model}]:", dim=True))
        for line in report.program.splitlines():
            click.echo(f"    {line}")
    if verbose or not result.ok:
        for line in report.summary().splitlines():
            click.echo(f"  {line}")


def _print_totals(total: int, failed: int) -> None:
    if failed:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {failed} of {total} test(s) failed.")
        return
    click.echo(click.style("PASS", fg="green", bold=True) + f": {total} test(s) passed.")
