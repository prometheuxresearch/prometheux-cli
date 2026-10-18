"""`px test` — unit tests for Vadalog programs, run on the platform engine."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
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
# A worker takes minutes to start, so a small suite is faster without one.
CASES_PER_WORKER = 10


class WorkersUnavailable(Exception):
    """The platform would not run the engine workers asked for."""


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
@click.option("--jobs", "-j", type=click.IntRange(min=1), default=None,
              help="Cases to run at the same time (default 1, or one more than --replicas).")
@click.option("--replicas", default=None, metavar="N|auto",
              help="Run N engine workers beside your machine while the suite runs, removed "
                   f"afterwards. 'auto' picks one per {CASES_PER_WORKER} cases, up to the platform cap.")
@click.option("--replicas-timeout", type=click.IntRange(min=1), default=600, show_default=True,
              help="Seconds to wait for the workers to be ready; a new worker usually needs a new node.")
@click.option("--keep-replicas", is_flag=True,
              help="Leave the workers running after the suite (they go after 10 idle minutes).")
def run_tests(target: Optional[Path], expects, question, context, expect_csv, expect_pred,
              mode, header, params, save_vada, as_json, junit_xml, jobs, replicas,
              replicas_timeout, keep_replicas) -> None:
    """Check that Vadalog programs produce the rows you expect.

    TARGET is a .vada program (with --expect), a *.test.yaml case, or a folder
    of cases. Each program runs on the platform engine and every expected
    predicate is compared with its CSV. Exit code 0 when everything passes,
    1 when a check fails, 2 when the tests could not run.

    A large suite runs faster with --replicas: extra engines beside your running
    compute machine, with cases sent to them in parallel.

    \b
    Examples:
      px test tc.vada --expect tc=tc.csv
      px test --question "Transitive closure of edge(X,Y). Output as tc." --expect-csv tc.csv
      px test tests/ --junit-xml report.xml
      px test tests/ --replicas 2
    """
    try:
        cases = _cases(target, expects, question, context, expect_csv, expect_pred, save_vada,
                       mode, header, _parse_params(params))
        px, _, _ = connected_sdk(require_token=True)
        workers = _resolve_replicas(px, replicas, len(cases))
    except (CaseError, SdkError, click.UsageError, WorkersUnavailable) as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(EXIT_USAGE)
    if replicas == "auto" and not as_json:
        click.echo(f"--replicas auto: {workers} engine worker(s) for {len(cases)} case(s).", err=True)
    jobs = jobs or (workers + 1 if workers else 1)

    single = len(cases) == 1
    results = []

    def report(result):
        results.append(result)
        if not as_json:
            _print_result(result, verbose=single)

    try:
        with _engine_workers(px, workers, replicas_timeout, keep_replicas, quiet=as_json):
            _run_cases(px, cases, jobs, report)
    except (TimeoutError, WorkersUnavailable) as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(EXIT_USAGE)

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


def _resolve_replicas(px, replicas: Optional[str], case_count: int) -> int:
    if replicas is None:
        return 0
    if replicas == "auto":
        try:
            cap = int(px.get_engine_workers().get("max") or 0)
        except Exception as exc:
            raise WorkersUnavailable(f"engine workers: {exc}") from exc
        return min(cap, case_count // CASES_PER_WORKER)
    try:
        count = int(replicas)
    except ValueError:
        raise click.UsageError(f"--replicas must be a number or 'auto', got {replicas!r}")
    if count < 0:
        raise click.UsageError("--replicas cannot be negative")
    return count


@contextmanager
def _engine_workers(px, count: int, timeout: int, keep: bool, *, quiet: bool):
    if not count:
        yield
        return
    if not quiet:
        click.echo(f"Starting {count} engine worker(s); a new one can take a few minutes...", err=True)
    last = {"ready": None}

    def progress(state):
        ready = int(state.get("ready") or 0)
        if not quiet and ready != last["ready"]:
            click.echo(f"  {ready}/{count} ready", err=True)
            last["ready"] = ready

    with ExitStack() as stack:
        try:
            stack.enter_context(px.engine_workers(count, timeout=timeout, keep=keep,
                                                  on_progress=progress))
        except TimeoutError:
            raise
        except Exception as exc:  # refused by the platform: no machine running, over the cap
            raise WorkersUnavailable(f"engine workers: {exc}") from exc
        try:
            yield
        finally:
            if not quiet:
                click.echo("Engine workers kept running (removed after 10 idle minutes)." if keep
                           else "Removing engine workers.", err=True)


def _run_cases(px, cases: List[TestCase], jobs: int, report) -> None:
    """Run the cases, `jobs` at a time, reporting each in case order."""
    if jobs <= 1 or len(cases) <= 1:
        for case in cases:
            report(run_case(px, case))
        return
    pool = ThreadPoolExecutor(max_workers=min(jobs, len(cases)))
    try:
        for result in pool.map(lambda case: run_case(px, case), cases):
            report(result)
    finally:
        # On Ctrl-C, stop queuing cases instead of waiting for the whole suite.
        pool.shutdown(wait=False, cancel_futures=True)


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
