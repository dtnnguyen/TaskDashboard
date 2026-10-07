#!/usr/bin/env python3
# <xbar.title>TaskDashboard</xbar.title>
# <xbar.desc>Goals and % completion from PLAN_AND_PROGRESS.md</xbar.desc>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideDisappear>true</swiftbar.hideDisappear>
"""SwiftBar menu bar plugin: '🎯 4%' in the menu bar, a % per project in the dropdown.

Runs every 5 minutes (the '.5m.' in the file name) and rebuilds index.html each
time. Install with macos/install.sh, which links it into SwiftBar's plugin folder.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # resolve() follows the symlink back here
sys.path.insert(0, str(ROOT / "src"))

from taskdashboard import config  # noqa: E402
from taskdashboard import history  # noqa: E402
from taskdashboard.build import refresh  # noqa: E402
from taskdashboard.osutil import file_url  # noqa: E402
from taskdashboard.plan import parse  # noqa: E402

MONO = "font=Menlo size=12"


def plain(text):
    """Menu items are plain text: drop Markdown marks; '|' would start SwiftBar parameters."""
    return text.replace("**", "").replace("`", "").replace("|", "/")


def bar(pct, width=10):
    filled = round((pct or 0) * width / 100)
    return "▓" * filled + "░" * (width - filled)


def main():
    try:
        plan = parse(config.plan_path())
        html = config.html_path()
        items = refresh(plan, html, config.history_path())  # records new ticks, rebuilds the page
    except Exception as e:  # show the problem in the menu instead of a blank icon
        print("🎯 ⚠")
        print("---")
        print(f"TaskDashboard error: {e} | color=red")
        return

    # Every item gets an action (href): macOS greys out menu items that have none.
    page = file_url(html)
    edit = f"href={file_url(config.plan_path())}"
    overall = plan.overall["percent"]
    print(f"🎯 {'—' if overall is None else f'{overall}%'}")
    print("---")
    print(f"Active: {plan.overall['done']}/{plan.overall['total']} goals | {MONO} href={page}")
    s = history.stats(items, plan.today)
    timeline = f"href={file_url(html, 'timeline')}"
    print(f"Today: {s['today']} done · This week: {s['this_week']} · Last week: {s['last_week']} | {MONO} {timeline}")
    for a in history.by_day(items).get(plan.today, []):
        print(f"--✓ {plain(a.goal)}  ({plain(a.project)}) | length=80 {timeline}")
    print(f"Timeline… | {timeline}")
    print("---")

    width = max((len(p.name) for p in plan.projects), default=0)
    for p in plan.projects:
        pct = "  —" if p.percent is None else f"{p.percent:3d}%"
        extra = f"({p.done}/{p.total})"
        if p.status == "habit" and p.streak is not None:
            extra += f" · streak {p.streak}"
        print(f"{p.emoji} {p.name:<{width}}  {bar(p.percent)} {pct} {extra} | {MONO} href={file_url(html, 'project-' + p.slug)}")
        # Submenu (lines starting with '--'): the project's goals
        for g in p.goals:
            mark = "✓" if g.done else ("⚠" if g.overdue(plan.today) else "○")
            print(f"--{mark} {plain(g.text)} | length=80 {edit}")
        for g in p.overdue(plan.today):
            print(f"   ⚠ Overdue: {plain(g.text)} | color=#d9534f size=12 length=70 {edit}")

    print("---")
    print(f"Open dashboard page | href={page}")
    print(f"Edit plan | {edit}")
    print("Refresh | refresh=true")


main()
