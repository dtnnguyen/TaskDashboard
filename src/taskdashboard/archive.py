"""Move finished projects out of the plan and history.jsonl into archive files beside them.

    ARCHIVE.md               the projects' Markdown sections, under "## Archived YYYY-MM-DD"
    history.archive.jsonl    their history lines, unchanged

The dashboard stops showing an archived project, and the plan and history stay small. Nothing
is lost: to restore a project, paste its section back under ## Milestones and append its lines
from history.archive.jsonl to history.jsonl (restore both, or ticks without a date in the plan
are recorded again as done on the day of the restore).

This is the one place history.jsonl is rewritten rather than appended to. It happens under the
same lock as history.sync(), and atomically. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

from .osutil import file_lock
from .plan import ConcurrentEditError, Plan, Project, project_lines, remove_projects

ARCHIVE_NAME = "ARCHIVE.md"
HISTORY_ARCHIVE_NAME = "history.archive.jsonl"


def finished(plan: Plan) -> list[Project]:
    """Projects marked ✅ done, and non-habit projects whose goals are all ticked."""
    return [
        p for p in plan.projects
        if p.status == "done" or (p.status != "habit" and p.total > 0 and p.done == p.total)
    ]


def _event_project(line: str) -> str | None:
    try:
        return json.loads(line).get("project")
    except (json.JSONDecodeError, AttributeError):
        return None  # a hand-edited or broken line: never moved, never dropped


def history_lines(history_file: Path, projects: list[Project]) -> int:
    """How many history lines belong to these projects."""
    if not history_file.exists():
        return 0
    names = {p.name for p in projects}
    with history_file.open(encoding="utf-8", newline="") as f:
        return sum(_event_project(l) in names for l in f if l.strip())


def _replace(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", newline="") as f:
        f.write(text)


def archive(plan: Plan, projects: list[Project], history_file: Path, today: date | None = None) -> tuple[Plan, int]:
    """Archive the projects. Returns the updated plan and how many history lines moved.

    Order: copy to the archives first, then remove from the plan, then from history.jsonl,
    so an interruption can leave a project in two places but never in none.
    """
    today = today or plan.today
    if hashlib.sha256(plan.path.read_bytes()).hexdigest() != plan.digest:
        raise ConcurrentEditError(f"{plan.path.name} changed since it was read; reload and try again")
    nl = plan.newline

    # 1. Plan sections -> ARCHIVE.md
    archive_md = plan.path.parent / ARCHIVE_NAME
    text = "" if archive_md.exists() else (
        f"# Archived projects{nl}{nl}"
        f"Moved out of {plan.path.name} by `td archive`. Their history is in {HISTORY_ARCHIVE_NAME}.{nl}"
    )
    text += f"{nl}## Archived {today.isoformat()}{nl}{nl}"
    for p in sorted(projects, key=lambda p: p.heading_line):
        start, end = project_lines(plan, p)
        section = "".join(plan.lines[start:end]).rstrip("\r\n")
        text += section + nl + nl
    _append(archive_md, text)

    # 2. Remove the sections from the plan
    plan = remove_projects(plan, projects)

    # 3. History lines -> history.archive.jsonl, then rewrite history.jsonl without them
    moved = 0
    if history_file.exists():
        names = {p.name for p in projects}
        with file_lock(history_file):
            with history_file.open(encoding="utf-8", newline="") as f:
                lines = f.readlines()
            keep = [l for l in lines if _event_project(l) not in names]
            gone = [l for l in lines if _event_project(l) in names]
            if gone:
                if not gone[-1].endswith("\n"):
                    gone[-1] += "\n"
                _append(history_file.parent / HISTORY_ARCHIVE_NAME, "".join(gone))
                _replace(history_file, "".join(keep))
            moved = len(gone)
    return plan, moved
