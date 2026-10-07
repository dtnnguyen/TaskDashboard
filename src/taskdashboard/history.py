"""Record when each goal gets checked, so daily and weekly accomplishments can be shown
without committing the plan every day.

history.jsonl holds one event per line and is only ever appended to:

    {"date": "2026-10-03", "project": "Learn Rust", "goal": "Read chapters 1–4",
     "event": "done", "recorded": "2026-10-03T14:05:00"}

sync() compares the plan with the replayed history and appends what changed:
- done      a goal became [x]. Dated with its " — YYYY-MM-DD" if written, otherwise today.
            Also appended when the date written in the plan changes: the plan's date wins
- undone    a goal went back to [ ]. Its last "done" no longer counts
- baseline  first run only: goals already [x] without a date. Recorded so they are not
            mistaken for new ticks, but never counted as an accomplishment

The plan file itself is never written here. Standard library only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .osutil import file_lock
from .plan import Plan

DONE, UNDONE, BASELINE = "done", "undone", "baseline"


@dataclass(frozen=True)
class Accomplishment:
    date: date
    project: str
    goal: str


def _key(project: str, goal: str) -> tuple[str, str]:
    return project, " ".join(goal.split())


def _read(f) -> list[dict]:
    events = []
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a hand-edited or half-written line must not break the dashboard
    return events


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return _read(f)


def _state(events: list[dict]) -> dict[tuple[str, str], dict]:
    """Goal → its last recorded event."""
    return {_key(e["project"], e["goal"]): e for e in events}


def sync(plan: Plan, path: Path, now: datetime | None = None) -> list[dict]:
    """Append events for goals checked/unchecked since the last sync. Returns the new events."""
    now = now or datetime.now()
    recorded = now.isoformat(timespec="seconds")
    today = plan.today.isoformat()

    path.parent.mkdir(parents=True, exist_ok=True)
    # The menu bar app and the CLI may run at the same time. newline="" keeps LF line
    # endings on Windows too, so the file diffs and merges cleanly between machines.
    with file_lock(path), path.open("a+", encoding="utf-8", newline="") as f:
        f.seek(0)
        events = _read(f)
        first_run = not events
        state = _state(events)

        new: list[dict] = []
        for p in plan.projects:
            for g in p.goals:
                last = state.get(_key(p.name, g.title))
                was_done = last is not None and last["event"] != UNDONE
                if g.done and was_done and g.done_on and (last["event"], last["date"]) != (DONE, g.done_on.isoformat()):
                    event, day = DONE, g.done_on.isoformat()  # date written or corrected in the plan
                elif g.done and not was_done:
                    if g.done_on:
                        event, day = DONE, g.done_on.isoformat()
                    elif first_run:
                        event, day = BASELINE, today
                    else:
                        event, day = DONE, today
                elif not g.done and was_done:
                    event, day = UNDONE, today
                else:
                    continue
                new.append({"date": day, "project": p.name, "goal": g.title, "event": event, "recorded": recorded})

        for e in new:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return new


def accomplishments(events: list[dict]) -> list[Accomplishment]:
    """Goals that count as done, each on the day it was done. Oldest first."""
    current: dict[tuple[str, str], Accomplishment] = {}
    for e in events:
        key = _key(e["project"], e["goal"])
        if e["event"] == DONE:
            try:
                day = date.fromisoformat(e["date"])
            except (KeyError, ValueError):
                continue
            current[key] = Accomplishment(day, e["project"], e["goal"])
        else:  # undone, or a baseline that replaces an earlier entry
            current.pop(key, None)
    return sorted(current.values(), key=lambda a: (a.date, a.project, a.goal))


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())  # Monday


def by_day(items: list[Accomplishment]) -> dict[date, list[Accomplishment]]:
    days: dict[date, list[Accomplishment]] = {}
    for a in items:
        days.setdefault(a.date, []).append(a)
    return days


def stats(items: list[Accomplishment], today: date) -> dict:
    monday = week_start(today)
    return {
        "today": sum(a.date == today for a in items),
        "this_week": sum(monday <= a.date <= today for a in items),
        "last_week": sum(monday - timedelta(days=7) <= a.date < monday for a in items),
    }
