"""`px status` — show each ontology's current/latest run status (optionally live)."""

from __future__ import annotations

import sys
import time

import click

from ..sdk import SdkError, connected_sdk

# Sort order: running first, then failures, then success, then idle.
_ORDER = {"running": 0, "error": 1, "cancelled": 2, "interrupted": 2, "success": 3, "idle": 4}
_SYM = {"running": "▶", "success": "✓", "error": "✗", "cancelled": "⊘",
        "interrupted": "⊘", "idle": "·"}
_FG = {"running": "yellow", "success": "green", "error": "red",
       "cancelled": "magenta", "interrupted": "magenta", "idle": None}


@click.command()
@click.option("--watch", "-w", is_flag=True, help="Refresh continuously until Ctrl-C.")
@click.option("--interval", "-i", default=3.0, show_default=True,
              help="Seconds between refreshes with --watch.")
@click.option("--scope", default="user", show_default=True,
              help="Comma-separated scopes to include, e.g. 'user,organization'.")
def status(watch: bool, interval: float, scope: str) -> None:
    """Show each ontology's current/latest run status.

    One row per ontology: running / success / error / cancelled / interrupted /
    idle, plus the concept currently executing and its progress. The engine is
    globally serialized, so at most one ontology is ever ``running``. With
    --watch the table refreshes in place and announces when a run starts.
    """
    scopes = [s.strip() for s in scope.split(",") if s.strip()] or ["user"]
    try:
        px, url, _ = connected_sdk(require_token=True)
    except SdkError as exc:
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)

    if not watch:
        _render(_fetch(px, scopes), {}, url)
        return
    prev: dict = {}
    try:
        while True:
            click.clear()
            prev = _render(_fetch(px, scopes), prev, url)
            time.sleep(interval)
    except KeyboardInterrupt:
        click.echo("\nstopped.")


def _fetch(px, scopes):
    """Join the ontology list with the latest run per ontology into rows."""
    try:
        onts = px.list_ontologies(scopes) or []
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style("FAIL", fg="red", bold=True) + f": {exc}", err=True)
        sys.exit(1)
    statuses: dict = {}
    for sc in scopes:
        try:
            statuses.update(px.get_execution_statuses(sc) or {})
        except Exception:  # noqa: BLE001 - a scope may be unavailable; others still render
            pass

    rows = []
    for o in onts:
        oid = o.get("id")
        snap = statuses.get(oid) or {}
        state = snap.get("status", "idle")
        per = snap.get("statuses") or {}
        done = sum(1 for s in per.values() if isinstance(s, dict) and s.get("status") == "success")
        total = snap.get("total")
        progress = f"{done}/{total}" if (state == "running" and total) else ""
        current = next((n for n, s in per.items()
                        if isinstance(s, dict) and s.get("status") == "running"), "")
        current = current or (snap.get("target_concept") or "")
        rows.append({"name": o.get("name") or oid, "id": oid, "status": state,
                     "current": current, "progress": progress})
    rows.sort(key=lambda r: (_ORDER.get(r["status"], 5), r["name"].lower()))
    return rows


def _render(rows, prev_status, url) -> dict:
    n_run = sum(1 for r in rows if r["status"] == "running")
    n_err = sum(1 for r in rows if r["status"] == "error")
    click.echo(f"Ontology status — {url}")
    click.echo(
        f"{time.strftime('%H:%M:%S')}   {len(rows)} ontolog{'y' if len(rows) == 1 else 'ies'}"
        f"   {n_run} running   {n_err} error\n"
    )
    for r in rows:  # announce idle/other -> running transitions
        if r["status"] == "running" and prev_status.get(r["id"]) != "running":
            click.echo(click.style(f"▶ {r['name']} started running", fg="yellow", bold=True) + "\n")

    name_w = min(40, max(20, *(len(r["name"]) for r in rows))) if rows else 20
    click.echo(f"  {'STATUS':<12} {'ONTOLOGY':<{name_w}} {'CONCEPT':<26} PROGRESS")
    click.echo(f"  {'-'*12} {'-'*name_w} {'-'*26} {'-'*8}")
    for r in rows:
        label = f"{_SYM.get(r['status'], '?')} {r['status']}"
        click.echo(
            "  " + click.style(f"{label:<12}", fg=_FG.get(r["status"]),
                               bold=(r["status"] == "running"))
            + f" {r['name'][:name_w]:<{name_w}} {r['current'][:26]:<26} {r['progress']}"
        )
    return {r["id"]: r["status"] for r in rows}
