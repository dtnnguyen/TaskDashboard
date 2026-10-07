"""What the tray icon shows, independent of the toolkit that draws it.

The Ubuntu (AppIndicator) and Windows (pystray) apps both call snapshot() and turn
the result into their own menus, so they always show the same thing.
Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config, history
from .build import refresh
from .osutil import file_url
from .plan import Plan, parse

MAX_LABEL = 80


@dataclass
class MenuItem:
    label: str
    open: str | None = None  # file path or URL to open when clicked; None = not clickable
    children: list[MenuItem] = field(default_factory=list)
    default: bool = False  # Windows: what a left-click on the icon does


SEPARATOR = MenuItem("-")


@dataclass
class Snapshot:
    percent: int | None  # overall % of active projects; None when nothing to show
    label: str  # short text next to the icon: "13%"
    tooltip: str  # hover text
    items: list[MenuItem]
    error: str | None = None


def plain(text: str) -> str:
    """Menus are plain text: drop Markdown marks, keep it short."""
    text = text.replace("**", "").replace("`", "")
    return text if len(text) <= MAX_LABEL else text[: MAX_LABEL - 1] + "…"


def bar(pct: int | None, width: int = 10) -> str:
    filled = round((pct or 0) * width / 100)
    return "▓" * filled + "░" * (width - filled)


def _build(plan: Plan, items: list[history.Accomplishment], html: Path) -> Snapshot:
    overall = plan.overall
    pct = overall["percent"]
    label = "—" if pct is None else f"{pct}%"
    s = history.stats(items, plan.today)
    page = str(html)

    today_items = [
        MenuItem(f"✓ {plain(a.goal)}  ({plain(a.project)})", open=page)
        for a in history.by_day(items).get(plan.today, [])
    ] or [MenuItem("Nothing yet today")]

    menu = [
        MenuItem(f"Active projects: {label} ({overall['done']}/{overall['total']} goals)"),
        MenuItem(f"Today: {s['today']} done", children=today_items),
        MenuItem(f"This week: {s['this_week']} done · last week: {s['last_week']}", open=file_url(html, "timeline")),
        SEPARATOR,
    ]
    for p in plan.projects:
        pct_txt = "—" if p.percent is None else f"{p.percent}%"
        extra = f" · streak {p.streak}" if p.status == "habit" and p.streak is not None else ""
        goals = [
            MenuItem(f"{'✓' if g.done else '⚠' if g.overdue(plan.today) else '○'} {plain(g.title)}", open=str(plan.path))
            for g in p.goals
        ] or [MenuItem("No goals yet")]
        menu.append(MenuItem(f"{p.emoji} {p.name}   {bar(p.percent)} {pct_txt} ({p.done}/{p.total}){extra}", children=goals))
        for g in p.overdue(plan.today):
            menu.append(MenuItem(f"      ⚠ Overdue: {plain(g.title)}", open=str(plan.path)))

    menu += [
        SEPARATOR,
        MenuItem("Open dashboard page", open=page, default=True),
        MenuItem("Edit plan", open=str(plan.path)),
    ]
    tooltip = f"TaskDashboard: {label} · {s['today']} today · {s['this_week']} this week"
    return Snapshot(percent=pct, label=label, tooltip=tooltip, items=menu)



def _edit_target() -> Path:
    """What "Edit plan" opens after an error: the plan, or the config file if that is what's broken."""
    try:
        return config.plan_path()
    except ValueError:
        return config.config_file()

def snapshot() -> Snapshot:
    """Read the plan, record new ticks in history.jsonl, rebuild index.html, describe the menu.

    Never raises: a broken plan shows as a warning in the menu instead of killing the app.
    """
    try:
        plan = parse(config.plan_path())
        html = config.html_path()
        items = refresh(plan, html, config.history_path())
        return _build(plan, items, html)
    except Exception as e:  # noqa: BLE001
        return Snapshot(
            percent=None,
            label="⚠",
            tooltip=f"TaskDashboard error: {e}",
            items=[MenuItem(f"Error: {plain(str(e))}"), SEPARATOR, MenuItem("Edit plan", open=str(_edit_target()))],
            error=str(e),
        )
