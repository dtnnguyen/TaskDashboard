"""Render the plan as one self-contained index.html you can double-click.

The data is baked into the page (browsers block a file:// page from reading the
Markdown file), so rebuild after editing the plan; the SwiftBar plugin does it
on every refresh. Standard library only.
"""

from __future__ import annotations

import html
import re
from datetime import date, timedelta
from pathlib import Path

from . import history
from .history import Accomplishment
from .plan import Plan, Project

_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

HEATMAP_WEEKS = 26  # about six months
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _inline(text: str) -> str:
    """Escape, then render the two inline Markdown forms the plan uses: `code` and **bold**."""
    out = html.escape(text)
    out = _CODE_RE.sub(r"<code>\1</code>", out)
    return _BOLD_RE.sub(r"<strong>\1</strong>", out)


def _pct(value: int | None) -> str:
    return "—" if value is None else f"{value}%"


def _bar(value: int | None) -> str:
    width = value or 0
    return f'<div class="bar" role="presentation"><div style="width:{width}%"></div></div>'


def _day_label(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return f"{WEEKDAYS[day.weekday()]} {day:%b} {day.day}"


def _plural(n: int, word: str = "goal") -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# ── Projects ─────────────────────────────────────────────────────────────────


def _project(p: Project, plan: Plan) -> str:
    overdue = p.overdue(plan.today)
    meta = [f"{p.done}/{p.total} goals"]
    if p.target:
        meta.append(f"due {p.target.isoformat()}")
    if p.status == "habit" and p.streak is not None:
        meta.append(f"streak {p.streak} · {p.week_done}/5 this week")
    if overdue:
        meta.append(f'<span class="warn">{len(overdue)} overdue</span>')

    goals = "\n".join(
        f'<li class="{"done" if g.done else ""}{" late" if g.overdue(plan.today) else ""}">'
        f'<span class="box">{"✓" if g.done else ""}</span><span>{_inline(g.text)}</span></li>'
        for g in p.goals
    ) or '<li class="empty">No goals yet</li>'

    return f"""
<details class="card status-{p.status}" id="project-{p.slug}">
  <summary>
    <div class="head">
      <span class="name">{p.emoji} {html.escape(p.name)}</span>
      <span class="pct">{_pct(p.percent)}</span>
    </div>
    {_bar(p.percent)}
    <div class="meta">{" · ".join(meta)}</div>
  </summary>
  <ul class="goals">{goals}</ul>
</details>"""


# ── Accomplishments ──────────────────────────────────────────────────────────


def _level(n: int) -> int:
    return 0 if n == 0 else 1 if n == 1 else 2 if n == 2 else 3 if n <= 4 else 4


def _heatmap(days: dict[date, list[Accomplishment]], today: date) -> str:
    """GitHub-style grid: one column per week, Monday on top. Click a day to jump to it."""
    start = history.week_start(today) - timedelta(weeks=HEATMAP_WEEKS - 1)
    cells = []
    for i in range(HEATMAP_WEEKS * 7):
        day = start + timedelta(days=i)
        if day > today:
            cells.append('<span class="cell future"></span>')
            continue
        n = len(days.get(day, []))
        tip = f"{day:%a %b} {day.day}: {_plural(n)} done"
        tag = f'a href="#day-{day.isoformat()}"' if n else "span"
        cells.append(
            f'<{tag} class="cell l{_level(n)}{" today" if day == today else ""}" '
            f'title="{tip}" aria-label="{tip}"></{tag.split()[0]}>'
        )
    months = []
    for w in range(HEATMAP_WEEKS):
        monday = start + timedelta(weeks=w)
        first = w == 0 or monday.month != (monday - timedelta(weeks=1)).month
        months.append(f"<span>{monday:%b}</span>" if first else "<span></span>")
    return f"""
<div class="heatmap-wrap">
  <div class="months" style="grid-template-columns: repeat({HEATMAP_WEEKS}, var(--cell))">{"".join(months)}</div>
  <div class="heatmap-row">
    <div class="wdays"><span>Mon</span><span></span><span>Wed</span><span></span><span>Fri</span><span></span><span>Sun</span></div>
    <div class="heatmap" style="grid-template-columns: repeat({HEATMAP_WEEKS}, var(--cell))">{"".join(cells)}</div>
  </div>
  <div class="legend">Less <span class="cell l0"></span><span class="cell l1"></span><span class="cell l2"></span><span class="cell l3"></span><span class="cell l4"></span> More</div>
</div>"""


def _this_week(days: dict[date, list[Accomplishment]], today: date) -> str:
    """One bar per weekday, Monday to Sunday."""
    monday = history.week_start(today)
    counts = [len(days.get(monday + timedelta(days=i), [])) for i in range(7)]
    top = max(counts + [1])
    cols = []
    for i, n in enumerate(counts):
        day = monday + timedelta(days=i)
        cls = "future" if day > today else ("today" if day == today else "")
        height = 0 if day > today else max(4, round(n * 100 / top)) if n else 2
        cols.append(
            f'<div class="wk-col {cls}"><span class="wk-n">{"" if day > today else n}</span>'
            f'<div class="wk-track"><div class="wk-bar" style="height:{height}%"></div></div>'
            f'<span class="wk-d">{WEEKDAYS[i]}</span></div>'
        )
    return f'<div class="week-chart">{"".join(cols)}</div>'


def _timeline(days: dict[date, list[Accomplishment]], today: date) -> str:
    """Newest first, grouped by week (Monday–Sunday) with a total per week."""
    if not days:
        return (
            '<p class="empty-note">Nothing ticked yet. Check a goal in the plan '
            "(<code>- [x]</code>) and it shows up here on the next refresh.</p>"
        )
    weeks: dict[date, list[date]] = {}
    for day in sorted(days, reverse=True):
        weeks.setdefault(history.week_start(day), []).append(day)

    out = []
    for monday, week_days in weeks.items():
        total = sum(len(days[d]) for d in week_days)
        label = "This week" if monday == history.week_start(today) else f"Week of {monday:%b} {monday.day}"
        entries = []
        for day in week_days:
            items = "".join(
                f'<li><span class="chip">{html.escape(a.project)}</span><span>{_inline(a.goal)}</span></li>'
                for a in days[day]
            )
            entries.append(
                f'<div class="tl-day" id="day-{day.isoformat()}">'
                f'<div class="tl-date">{_day_label(day, today)}<small>{_plural(len(days[day]))}</small></div>'
                f'<ul class="tl-items">{items}</ul></div>'
            )
        out.append(
            f'<section class="tl-week"><h3>{label}<small>{_plural(total)} done</small></h3>{"".join(entries)}</section>'
        )
    return "\n".join(out)


# ── Page ─────────────────────────────────────────────────────────────────────


def render(plan: Plan, items: list[Accomplishment] | None = None) -> str:
    items = items or []
    overall = plan.overall
    days = history.by_day(items)
    s = history.stats(items, plan.today)
    trend = s["this_week"] - s["last_week"]
    trend_txt = "same as last week" if trend == 0 else f"{trend:+d} vs last week"
    cards = "\n".join(_project(p, plan) for p in plan.projects)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Task Dashboard</title>
<style>
:root {{
  --bg: #f6f5f2; --card: #ffffff; --text: #1d1d1f; --muted: #6e6e73;
  --line: #e3e1dc; --track: #ecebe7; --fill: #2f7d5b; --warn: #b4441f; --code: #f0eee9;
  --l1: #b9dcc9; --l2: #7fbf9e; --l3: #4a9e77; --l4: #2f7d5b;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #161617; --card: #212123; --text: #f2f2f2; --muted: #a1a1a6;
    --line: #333336; --track: #2c2c2f; --fill: #4fb98a; --warn: #ff8a5c; --code: #2c2c2f;
    --l1: #1f4a37; --l2: #2b6b4e; --l3: #3d9168; --l4: #5cc796;
  }}
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{ margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
main {{ max-width: 760px; margin: 0 auto; padding: 32px 16px 48px; }}
h1 {{ font-size: 15px; font-weight: 600; color: var(--muted); margin: 0 0 4px; }}
h2 {{ font-size: 18px; margin: 36px 0 12px; }}
nav {{ display: flex; gap: 16px; margin: 20px 0; font-size: 14px; }}
nav a {{ color: var(--muted); text-decoration: none; }}
nav a:hover {{ color: var(--text); }}
.overall {{ font-size: 48px; font-weight: 700; letter-spacing: -0.02em; line-height: 1.1; }}
.overall small {{ font-size: 15px; font-weight: 400; color: var(--muted); margin-left: 8px; }}
.tiles {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 20px 0 0; }}
.tile {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; }}
.tile b {{ display: block; font-size: 28px; line-height: 1.2; font-variant-numeric: tabular-nums; }}
.tile span {{ color: var(--muted); font-size: 13px; }}
.panel {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; margin-bottom: 12px; }}
.panel-title {{ font-size: 13px; color: var(--muted); margin: 0 0 10px; }}
/* heatmap */
.heatmap-wrap {{ --cell: 18px; overflow-x: auto; }}
.months {{ display: grid; gap: 4px; margin-left: 34px; font-size: 11px; color: var(--muted); white-space: nowrap; }}
.heatmap-row {{ display: flex; gap: 6px; }}
.wdays {{ display: grid; grid-template-rows: repeat(7, var(--cell)); gap: 4px; font-size: 10px; color: var(--muted); width: 28px; flex: none; }}
.wdays span {{ line-height: 1; display: flex; align-items: center; }}
.heatmap {{ display: grid; grid-template-rows: repeat(7, var(--cell)); grid-auto-flow: column; gap: 4px; }}
.cell {{ display: block; width: var(--cell); height: var(--cell); border-radius: 3px; background: var(--track); }}
.cell.l1 {{ background: var(--l1); }} .cell.l2 {{ background: var(--l2); }}
.cell.l3 {{ background: var(--l3); }} .cell.l4 {{ background: var(--l4); }}
.cell.future {{ background: transparent; }}
.cell.today {{ outline: 2px solid var(--text); outline-offset: -1px; }}
a.cell:hover {{ outline: 2px solid var(--muted); }}
.legend {{ display: flex; align-items: center; justify-content: flex-end; gap: 4px; font-size: 11px; color: var(--muted); margin-top: 8px; }}
.legend .cell {{ width: 10px; height: 10px; }}
/* this week */
.week-chart {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; height: 140px; }}
.wk-col {{ display: flex; flex-direction: column; align-items: center; gap: 4px; }}
.wk-n {{ font-size: 13px; font-weight: 600; height: 18px; font-variant-numeric: tabular-nums; }}
.wk-track {{ flex: 1; width: 100%; max-width: 36px; display: flex; align-items: flex-end; }}
.wk-bar {{ width: 100%; background: var(--fill); border-radius: 4px 4px 2px 2px; }}
.wk-d {{ font-size: 12px; color: var(--muted); }}
.wk-col.today .wk-d {{ color: var(--text); font-weight: 700; }}
.wk-col.future .wk-d {{ opacity: .5; }}
/* timeline */
.tl-week {{ margin-bottom: 20px; }}
.tl-week h3 {{ font-size: 15px; margin: 0 0 8px; display: flex; justify-content: space-between; align-items: baseline; }}
.tl-week h3 small, .tl-date small {{ color: var(--muted); font-weight: 400; font-size: 13px; }}
.tl-day {{ display: grid; grid-template-columns: 110px 1fr; gap: 12px; padding: 10px 0; border-top: 1px solid var(--line); scroll-margin-top: 16px; }}
.tl-day:target {{ background: var(--track); border-radius: 8px; padding-left: 8px; }}
.tl-date {{ font-weight: 600; font-size: 14px; display: flex; flex-direction: column; }}
.tl-items {{ list-style: none; margin: 0; padding: 0; }}
.tl-items li {{ display: flex; flex-wrap: wrap; gap: 6px 8px; align-items: baseline; padding: 2px 0; }}
.chip {{ font-size: 11px; background: var(--code); color: var(--muted); border-radius: 999px; padding: 1px 8px; white-space: nowrap; }}
.empty-note {{ color: var(--muted); }}
/* projects */
.card {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; margin-bottom: 12px; }}
.card summary {{ list-style: none; cursor: pointer; padding: 16px; }}
.card summary::-webkit-details-marker {{ display: none; }}
.card.status-later, .card.status-done {{ opacity: .7; }}
.head {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }}
.name {{ font-weight: 600; }}
.pct {{ font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }}
.bar {{ height: 8px; background: var(--track); border-radius: 4px; margin: 8px 0 6px; overflow: hidden; }}
.bar div {{ height: 100%; background: var(--fill); border-radius: 4px; }}
.meta {{ color: var(--muted); font-size: 13px; }}
.warn {{ color: var(--warn); font-weight: 600; }}
.goals {{ list-style: none; margin: 0; padding: 0 16px 16px; border-top: 1px solid var(--line); }}
.goals li {{ display: flex; gap: 10px; padding: 6px 0; }}
.goals li.done span:last-child {{ color: var(--muted); text-decoration: line-through; }}
.goals li.late span:last-child {{ color: var(--warn); }}
.goals li.empty {{ color: var(--muted); }}
.box {{ flex: none; width: 18px; height: 18px; margin-top: 2px; border: 1.5px solid var(--muted);
  border-radius: 4px; font-size: 12px; line-height: 15px; text-align: center; color: var(--fill); }}
li.done .box {{ border-color: var(--fill); }}
code {{ background: var(--code); padding: 1px 4px; border-radius: 4px; font-size: 13px; }}
footer {{ color: var(--muted); font-size: 12px; margin-top: 24px; }}
@media (max-width: 520px) {{
  .tiles {{ grid-template-columns: 1fr 1fr; }}
  .tiles .tile:last-child {{ grid-column: span 2; }}
  .heatmap-wrap {{ --cell: 11px; }}
  .tl-day {{ grid-template-columns: 1fr; gap: 4px; }}
  .tl-date {{ flex-direction: row; gap: 8px; align-items: baseline; }}
}}
</style>
</head>
<body>
<main>
  <header>
    <h1>Active projects · as of {plan.today.isoformat()}</h1>
    <div class="overall">{_pct(overall["percent"])}<small>{overall["done"]}/{overall["total"]} goals done</small></div>
    <div class="tiles">
      <div class="tile"><b>{s["today"]}</b><span>done today</span></div>
      <div class="tile"><b>{s["this_week"]}</b><span>done this week · {trend_txt}</span></div>
      <div class="tile"><b>{s["last_week"]}</b><span>done last week</span></div>
    </div>
  </header>

  <nav><a href="#accomplishments">Accomplishments</a><a href="#projects">Projects</a><a href="#timeline">Timeline</a></nav>

  <h2 id="accomplishments">Accomplishments</h2>
  <div class="panel">
    <p class="panel-title">This week</p>
    {_this_week(days, plan.today)}
  </div>
  <div class="panel">
    <p class="panel-title">Last 6 months · click a day to see what was done</p>
    {_heatmap(days, plan.today)}
  </div>

  <h2 id="projects">Projects</h2>
  {cards}

  <h2 id="timeline">Timeline</h2>
  {_timeline(days, plan.today)}

  <footer>Generated from {html.escape(plan.path.name)} and history.jsonl. Click a project to see its goals.
  Edit the Markdown file to change goals; the menu bar plugin rebuilds this page every 5 minutes.</footer>
</main>
<script>
// Opening the page at #project-<name> (from the menu bar) expands that project.
function openFromHash() {{
  const el = location.hash && document.getElementById(location.hash.slice(1));
  if (el && el.tagName === "DETAILS") el.open = true;
}}
window.addEventListener("hashchange", openFromHash);
openFromHash();
</script>
</body>
</html>
"""


def write_html(plan: Plan, out: Path, items: list[Accomplishment] | None = None) -> bool:
    """Write index.html only if it changed (keeps git status quiet). Returns True if written."""
    content = render(plan, items)
    if out.exists():
        with out.open(encoding="utf-8", newline="") as f:
            if f.read() == content:
                return False
    with out.open("w", encoding="utf-8", newline="") as f:  # LF on every OS
        f.write(content)
    return True


def refresh(plan: Plan, out: Path, history_file: Path) -> list[Accomplishment]:
    """Record newly checked/unchecked goals, then rebuild the page. Returns the accomplishments."""
    history.sync(plan, history_file)
    items = history.accomplishments(history.load(history_file))
    write_html(plan, out, items)
    return items
