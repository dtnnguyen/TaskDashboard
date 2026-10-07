"""Read PLAN_AND_PROGRESS.md into projects and goals, and write changes back safely.

The Markdown file is the single source of truth. This module uses the standard
library only, so the SwiftBar plugin can import it with the system Python.

Write-back rules:
- only the touched lines change; everything else stays byte-for-byte identical
- writes are atomic (temp file + os.replace)
- a write is refused if the file changed since it was parsed
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

STATUS_BY_EMOJI = {"🟢": "active", "🔁": "habit", "⏸️": "later", "⏸": "later", "✅": "done"}
EMOJI_BY_STATUS = {"active": "🟢", "habit": "🔁", "later": "⏸️", "done": "✅", "unset": "•"}

MILESTONES_HEADING = "## Milestones"
DAILY_LOG_HEADING = "## Daily log"
HABIT_LOG_COLUMN = "C++ problem"  # Daily-log column that counts as "did the habit today"

_TARGET_RE = re.compile(r"\(target:\s*(\d{4}-\d{2}-\d{2})\)")
_GOAL_RE = re.compile(r"^(?P<indent>\s*)[-*] \[(?P<mark>[ xX])\]\s+(?P<text>.*?)\s*$")
# Done date at the end of a checked goal: "text — 2026-10-01", "text - 2026-10-01" or "text 2026-10-01"
_DONE_DATE_RE = re.compile(r"\s+(?:[—–-]\s*)?(\d{4}-\d{2}-\d{2})\s*$")


class ConcurrentEditError(RuntimeError):
    """The plan file changed on disk after it was parsed."""


class NotFoundError(LookupError):
    """A project, goal or section that the caller asked for does not exist."""


def percent(done: int, total: int) -> int | None:
    """Whole-number % complete; None when there is nothing to complete.

    Never shows 100 while a goal is still open (199/200 → 99, not 100).
    """
    if total <= 0:
        return None
    if done >= total:
        return 100
    return min(99, int(done * 100 / total + 0.5))


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


@dataclass
class Goal:
    text: str
    done: bool
    line: int  # 0-based line index in the file
    target: date | None = None
    done_on: date | None = None  # from a trailing " — YYYY-MM-DD", if written

    @property
    def title(self) -> str:
        """The text without its done date; identifies the goal in history.jsonl."""
        return _DONE_DATE_RE.sub("", self.text)

    def overdue(self, today: date) -> bool:
        return not self.done and self.target is not None and self.target < today


@dataclass
class Project:
    name: str
    status: str  # active | habit | later | done | unset
    heading_line: int
    target: date | None = None
    goals: list[Goal] = field(default_factory=list)
    streak: int | None = None  # habits only: consecutive weekdays done
    week_done: int | None = None  # habits only: weekdays done this week (0–5)

    @property
    def slug(self) -> str:
        return slugify(self.name)

    @property
    def emoji(self) -> str:
        return EMOJI_BY_STATUS[self.status]

    @property
    def done(self) -> int:
        return sum(g.done for g in self.goals)

    @property
    def total(self) -> int:
        return len(self.goals)

    @property
    def percent(self) -> int | None:
        return percent(self.done, self.total)

    def overdue(self, today: date) -> list[Goal]:
        return [g for g in self.goals if g.overdue(today)]


@dataclass
class Plan:
    path: Path
    digest: str  # sha256 of the file when parsed; guards against concurrent edits
    lines: list[str]  # with line endings kept
    projects: list[Project]
    milestones: tuple[int, int] | None  # [start, end) line range of "## Milestones"
    today: date

    @property
    def newline(self) -> str:
        return "\r\n" if self.lines and self.lines[0].endswith("\r\n") else "\n"

    @property
    def overall(self) -> dict:
        """Pooled goal counts across 🟢 active projects (not an average of percentages)."""
        active = [p for p in self.projects if p.status == "active"]
        done = sum(p.done for p in active)
        total = sum(p.total for p in active)
        return {"done": done, "total": total, "percent": percent(done, total)}

    def project(self, slug: str) -> Project:
        for p in self.projects:
            if p.slug == slug:
                return p
        raise NotFoundError(f"No project '{slug}'")

    def goal_at(self, line: int) -> tuple[Project, Goal]:
        for p in self.projects:
            for g in p.goals:
                if g.line == line:
                    return p, g
        raise NotFoundError(f"No goal on line {line + 1}")


# ── Parsing ──────────────────────────────────────────────────────────────────


def parse(path: Path | str, today: date | None = None) -> Plan:
    path = Path(path)
    raw = path.read_bytes()
    lines = raw.decode("utf-8").splitlines(keepends=True)
    today = today or date.today()

    milestones = _section(lines, MILESTONES_HEADING)
    projects = _parse_projects(lines, *milestones) if milestones else []

    log = _parse_daily_log(lines)
    for p in projects:
        if p.status == "habit":
            p.week_done, p.streak = _habit_stats(log, today)

    return Plan(
        path=path,
        digest=hashlib.sha256(raw).hexdigest(),
        lines=lines,
        projects=projects,
        milestones=milestones,
        today=today,
    )


def _section(lines: list[str], heading: str) -> tuple[int, int] | None:
    """[start, end) of a level-2 section: from its heading to the next '## ' heading."""
    start = next((i for i, l in enumerate(lines) if l.rstrip() == heading), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start, end


def _parse_date(regex: re.Pattern, text: str) -> date | None:
    m = regex.search(text)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def _parse_projects(lines: list[str], start: int, end: int) -> list[Project]:
    projects: list[Project] = []
    for i in range(start + 1, end):
        line = lines[i].rstrip("\r\n")
        if line.startswith("### "):
            title = line[4:].strip()
            first, _, rest = title.partition(" ")
            status = STATUS_BY_EMOJI.get(first)
            if status is None:
                status, rest = "unset", title
            name = _TARGET_RE.sub("", rest).strip()
            projects.append(Project(name=name, status=status, heading_line=i, target=_parse_date(_TARGET_RE, rest)))
        elif projects and (m := _GOAL_RE.match(line)):
            text = m.group("text")
            projects[-1].goals.append(
                Goal(
                    text=text,
                    done=m.group("mark") != " ",
                    line=i,
                    target=_parse_date(_TARGET_RE, text),
                    done_on=_parse_date(_DONE_DATE_RE, text),
                )
            )
    return projects


def _table_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _parse_daily_log(lines: list[str]) -> dict[date, bool]:
    """date → whether the habit column has an entry that day."""
    section = _section(lines, DAILY_LOG_HEADING)
    if not section:
        return {}
    column = None
    log: dict[date, bool] = {}
    for line in lines[section[0] + 1 : section[1]]:
        if not line.lstrip().startswith("|"):
            continue
        cells = _table_cells(line)
        if column is None:
            if HABIT_LOG_COLUMN in cells:
                column = cells.index(HABIT_LOG_COLUMN)
            continue
        try:
            day = date.fromisoformat(cells[0])
        except ValueError:
            continue  # the |---| separator row, or a malformed date
        log[day] = column < len(cells) and bool(cells[column])
    return log


def _prev_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _habit_stats(log: dict[date, bool], today: date) -> tuple[int, int]:
    """(weekdays done this week, current streak in weekdays).

    Today not being logged yet does not break the streak.
    """
    monday = today - timedelta(days=today.weekday())
    week_done = sum(log.get(monday + timedelta(days=i), False) for i in range(5))

    day = today if log.get(today) else _prev_weekday(today)
    streak = 0
    while log.get(day):
        streak += 1
        day = _prev_weekday(day)
    return week_done, streak


# ── Write-back ───────────────────────────────────────────────────────────────


def _clean(text: str) -> str:
    text = " ".join(text.split())  # no newlines can sneak into the Markdown
    if not text:
        raise ValueError("Text must not be empty")
    return text


def _write(plan: Plan, lines: list[str]) -> Plan:
    current = hashlib.sha256(plan.path.read_bytes()).hexdigest()
    if current != plan.digest:
        raise ConcurrentEditError(f"{plan.path.name} changed since it was read; reload and try again")

    fd, tmp = tempfile.mkstemp(dir=plan.path.parent, prefix=f".{plan.path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.writelines(lines)
        shutil.copymode(plan.path, tmp)
        os.replace(tmp, plan.path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return parse(plan.path, plan.today)


def _insert(plan: Plan, at: int, new: list[str]) -> Plan:
    lines = list(plan.lines)
    if at > 0 and not lines[at - 1].endswith(("\n", "\r")):
        lines[at - 1] += plan.newline  # previous line was the last one, without a newline
    lines[at:at] = new
    return _write(plan, lines)


def add_project(plan: Plan, name: str, status: str = "active", target: date | None = None) -> Plan:
    """Append a '### <emoji> Name (target: …)' section at the end of ## Milestones."""
    if plan.milestones is None:
        raise NotFoundError(f"'{MILESTONES_HEADING}' section not found in {plan.path.name}")
    if status not in EMOJI_BY_STATUS or status == "unset":
        raise ValueError(f"Unknown status '{status}'")
    name = _clean(name)
    if any(p.slug == slugify(name) for p in plan.projects):
        raise ValueError(f"A project named '{name}' already exists")

    heading = f"### {EMOJI_BY_STATUS[status]} {name}"
    if target:
        heading += f" (target: {target.isoformat()})"

    # Insert after the last project's content, before the trailing blank lines / '---'.
    at = plan.milestones[1]
    while at > plan.milestones[0] + 1 and plan.lines[at - 1].strip() in ("", "---"):
        at -= 1
    return _insert(plan, at, [plan.newline, heading + plan.newline])


def add_goal(plan: Plan, slug: str, text: str, target: date | None = None) -> Plan:
    """Insert '- [ ] text' after the project's last checkbox (not after trailing plain bullets)."""
    project = plan.project(slug)
    line = f"- [ ] {_clean(text)}"
    if target:
        line += f" (target: {target.isoformat()})"

    at = project.goals[-1].line + 1 if project.goals else project.heading_line + 1
    return _insert(plan, at, [line + plan.newline])


def _is_last(plan: Plan, project: Project) -> bool:
    return not any(p.heading_line > project.heading_line for p in plan.projects)


def project_lines(plan: Plan, project: Project) -> tuple[int, int]:
    """[start, end) of a project's section: its heading up to the next '### ' heading, or for
    the last project, up to the end of ## Milestones without the trailing blank lines / '---'."""
    if not _is_last(plan, project):
        return project.heading_line, min(p.heading_line for p in plan.projects if p.heading_line > project.heading_line)
    assert plan.milestones is not None  # there is a project, so there is a Milestones section
    end = plan.milestones[1]
    while end > project.heading_line + 1 and plan.lines[end - 1].strip() in ("", "---"):
        end -= 1
    return project.heading_line, end


def remove_projects(plan: Plan, projects: list[Project]) -> Plan:
    """Delete whole project sections. Everything else stays byte-for-byte identical."""
    drop: set[int] = set()
    for p in projects:
        drop.update(range(*project_lines(plan, p)))

    def blank(i: int) -> bool:
        return 0 <= i < len(plan.lines) and plan.lines[i].strip() == ""

    # Where a removed block had a blank line on both sides, keep only one of them.
    for i in sorted(drop):
        if i - 1 not in drop and blank(i - 1):
            end = i
            while end in drop:
                end += 1
            if blank(end):
                drop.add(i - 1)
    return _write(plan, [l for i, l in enumerate(plan.lines) if i not in drop])


def toggle_goal(plan: Plan, line: int) -> Plan:
    """Check or uncheck the goal on a line. Checking appends ' — YYYY-MM-DD'; unchecking removes it."""
    _, goal = plan.goal_at(line)
    original = plan.lines[line]
    body = original.rstrip("\r\n")
    ending = original[len(body):]

    m = _GOAL_RE.match(body)
    assert m  # goal_at() guarantees this line is a checkbox
    text = _DONE_DATE_RE.sub("", m.group("text"))
    if goal.done:
        new = f"{m.group('indent')}- [ ] {text}"
    else:
        new = f"{m.group('indent')}- [x] {text} — {plan.today.isoformat()}"

    lines = list(plan.lines)
    lines[line] = new + ending
    return _write(plan, lines)


# ── Shared summary (web API + menu bar) ──────────────────────────────────────


def summary(plan: Plan) -> dict:
    return {
        "today": plan.today.isoformat(),
        "overall": plan.overall,
        "projects": [
            {
                "name": p.name,
                "slug": p.slug,
                "status": p.status,
                "done": p.done,
                "total": p.total,
                "percent": p.percent,
                "target": p.target.isoformat() if p.target else None,
                "overdue": [g.text for g in p.overdue(plan.today)],
                **({"streak": p.streak, "week_done": p.week_done} if p.status == "habit" else {}),
            }
            for p in plan.projects
        ],
    }
