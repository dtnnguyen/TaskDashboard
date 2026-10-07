"""Markdown progress report, e.g. for the GitHub Actions job summary. Standard library only."""

from __future__ import annotations

from datetime import timedelta

from . import history
from .history import Accomplishment
from .plan import Plan


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _pct(value: int | None) -> str:
    return "—" if value is None else f"{value}%"


def _bar(value: int | None, width: int = 10) -> str:
    filled = round((value or 0) * width / 100)
    return "▓" * filled + "░" * (width - filled)


def markdown(plan: Plan, items: list[Accomplishment]) -> str:
    overall = plan.overall
    s = history.stats(items, plan.today)
    lines = [
        f"## 🎯 {_pct(overall['percent'])} of active goals done ({overall['done']}/{overall['total']})",
        "",
        f"**Today:** {s['today']} · **This week:** {s['this_week']} · **Last week:** {s['last_week']}"
        f" · as of {plan.today.isoformat()}",
        "",
        "| Project | Progress | Done | Target | Overdue |",
        "|---|---|---|---|---|",
    ]
    for p in plan.projects:
        overdue = p.overdue(plan.today)
        lines.append(
            f"| {p.emoji} {_cell(p.name)} | `{_bar(p.percent)}` {_pct(p.percent)} | {p.done}/{p.total}"
            f" | {p.target.isoformat() if p.target else ''} | {len(overdue) or ''} |"
        )

    monday = history.week_start(plan.today)
    week = [a for a in items if monday <= a.date <= plan.today]
    lines += ["", "### Done this week", ""]
    if not week:
        lines.append("_Nothing yet._")
    for a in sorted(week, key=lambda a: a.date, reverse=True):
        lines.append(f"- {a.date:%a %b} {a.date.day} · **{_cell(a.project)}** · {_cell(a.goal)}")

    overdue = [(p, g) for p in plan.projects for g in p.overdue(plan.today)]
    if overdue:
        lines += ["", "### Overdue", ""]
        lines += [f"- **{_cell(p.name)}** · {_cell(g.title)}" for p, g in overdue]

    last_week = [a for a in items if monday - timedelta(days=7) <= a.date < monday]
    if last_week:
        lines += ["", f"<details><summary>Done last week ({len(last_week)})</summary>", ""]
        lines += [f"- {a.date:%a %b} {a.date.day} · **{_cell(a.project)}** · {_cell(a.goal)}" for a in last_week]
        lines += ["", "</details>"]
    return "\n".join(lines) + "\n"
