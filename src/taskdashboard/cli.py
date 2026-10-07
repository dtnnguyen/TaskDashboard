"""Command line: build the page and add projects/goals without opening an editor.

    python3 -m taskdashboard build [--open]
    python3 -m taskdashboard summary
    python3 -m taskdashboard add-project "Name" [--status active|habit|later] [--target YYYY-MM-DD]
    python3 -m taskdashboard add-goal <project-slug> "Goal text" [--target YYYY-MM-DD]
    python3 -m taskdashboard toggle <line-number>
    python3 -m taskdashboard history [--days N]
    python3 -m taskdashboard archive [<project-slug> ...] [--done] [--dry-run] [--yes]
                                                    # move finished projects to ARCHIVE.md (alias: remove-project)
    python3 -m taskdashboard report                # Markdown summary (GitHub Actions job summary)
    python3 -m taskdashboard init                   # first run: create the plan from the example
    python3 -m taskdashboard config [--data DIR | --plan FILE] [--move]
                                                    # show where your files are, or change it

Every command except init and config first records newly checked goals in history.jsonl and rebuilds index.html.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from . import config
from . import history
from .archive import ARCHIVE_NAME, HISTORY_ARCHIVE_NAME, archive, finished, history_lines
from .build import refresh
from .osutil import open_path
from .plan import ConcurrentEditError, NotFoundError, add_goal, add_project, parse, summary, toggle_goal
from .report import markdown

EXAMPLE_PLAN = config.PROJECT_ROOT / "examples" / "PLAN_AND_PROGRESS.example.md"


def init(plan: Path) -> int:
    """Create the plan from the example if there is none. Never overwrites."""
    if plan.exists():
        print(f"Plan already exists: {plan}")
        return 0
    if not EXAMPLE_PLAN.exists():
        print(f"error: example plan not found: {EXAMPLE_PLAN}", file=sys.stderr)
        return 1
    plan.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXAMPLE_PLAN, plan)
    print(f"Created {plan} from the example. Edit it to add your own projects.")
    return 0


PATH_VARS = ("TASKDASHBOARD_DATA", "TASKDASHBOARD_PLAN", "TASKDASHBOARD_HISTORY", "TASKDASHBOARD_HTML")


def move_files(new_plan: Path) -> list[Path]:
    """Copy the plan and history.jsonl to new_plan's folder. Returns the originals to delete.

    Refuses rather than overwrite anything at the destination. The originals are only deleted
    by the caller, after the copies are checked and the config file is saved.
    """
    old = [config.plan_path(), config.history_path()]
    new = [new_plan, new_plan.parent / config.HISTORY_NAME]
    if old[0].resolve() == new_plan:
        return []
    if not old[0].exists():
        raise ValueError(f"nothing to move: there is no plan at {old[0]}")
    pairs = [(src, dst) for src, dst in zip(old, new) if src.exists()]
    for _, dst in pairs:
        if dst.exists():
            raise ValueError(f"{dst} already exists, so it was not overwritten. "
                             "Move it out of the way, or choose another location.")
    new_plan.parent.mkdir(parents=True, exist_ok=True)
    for src, dst in pairs:
        shutil.copy2(src, dst)
        if dst.stat().st_size != src.stat().st_size:
            raise ValueError(f"copying {src} to {dst} failed; the original was kept")
        print(f"Moved {src} -> {dst}")
    return [src for src, _ in pairs] + [p for p in (config.html_path(),) if p.exists()]


def config_command(data: Path | None, plan: Path | None, move: bool) -> int:
    """Show where each file is and why. With --data / --plan, save the new location first;
    with --move as well, take the current plan and history.jsonl along."""
    new_plan = None
    if data is not None:
        new_plan = (data.expanduser() / config.PLAN_NAME).resolve()
    elif plan is not None:
        new_plan = plan.expanduser().resolve()
    if move and any(os.environ.get(v) for v in PATH_VARS):
        raise ValueError("a TASKDASHBOARD_* environment variable is set, and it would keep pointing at the "
                         "old place. Unset it, then run this again.")
    if new_plan is not None:
        leftovers = move_files(new_plan) if move else []
        saved = config.save_plan_location(new_plan)
        for old in leftovers:  # copies are verified and the config points at them: now remove the originals
            old.unlink()
        print(f"Saved in {saved}: plan {new_plan}, with history.jsonl and index.html beside it")
        if not move and not new_plan.exists():
            print("No plan there yet: run `init` to create one from the example, or use --move next time "
                  "to bring your current plan along.")
    cfg = config.settings()
    print(f"Config file: {config.config_file()}{'' if config.config_file().exists() else '  (not created)'}")
    for label, env, key, path in (("Data folder", "TASKDASHBOARD_DATA", "data", config.data_dir()),
                                  ("Plan", "TASKDASHBOARD_PLAN", "plan", config.plan_path()),
                                  ("History", "TASKDASHBOARD_HISTORY", "history", config.history_path()),
                                  ("Page", "TASKDASHBOARD_HTML", "html", config.html_path())):
        if os.environ.get(env):
            source = f"from ${env}"
        elif key in cfg:
            source = "from config file"
        elif key == "data":
            source = "default"
        else:
            source = "in the data folder" if key == "plan" else "next to the plan"
        print(f"  {label + ':':<13}{path}  ({source})")
    if new_plan is not None and any(os.environ.get(v) for v in PATH_VARS):
        print("Note: an environment variable is set in this shell and takes priority over the config file.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="taskdashboard")
    parser.add_argument("--plan", type=Path,
                        help="plan Markdown file (default: from the config file, else data/PLAN_AND_PROGRESS.md)")
    parser.add_argument("--history", type=Path, help="history.jsonl (default: next to the plan)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="write index.html from the plan")
    b.add_argument("--out", type=Path, help="page to write (default: index.html next to the plan)")
    b.add_argument("--open", action="store_true", help="open the page in the browser")

    sub.add_parser("summary", help="print projects and %% complete as JSON")

    ap = sub.add_parser("add-project", help="add a new project section")
    ap.add_argument("name")
    ap.add_argument("--status", default="active", choices=["active", "habit", "later"])
    ap.add_argument("--target", type=date.fromisoformat)

    ag = sub.add_parser("add-goal", help="add a goal to a project (by slug, see `summary`)")
    ag.add_argument("project")
    ag.add_argument("text")
    ag.add_argument("--target", type=date.fromisoformat)

    t = sub.add_parser("toggle", help="check/uncheck the goal on a line (1-based, as in your editor)")
    t.add_argument("line", type=int)

    h = sub.add_parser("history", help="list accomplishments, newest day first")
    h.add_argument("--days", type=int, default=7, help="how many days back (default 7)")

    ar = sub.add_parser("archive", aliases=["remove-project"],
                        help="move finished projects out of the plan and history.jsonl into archive files")
    ar.add_argument("projects", nargs="*", metavar="slug", help="projects to archive (slugs from `summary`)")
    ar.add_argument("--done", action="store_true",
                    help="also every ✅ done project, and every non-habit project with all goals ticked")
    ar.add_argument("--dry-run", action="store_true", help="show what would be archived, change nothing")
    ar.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")

    sub.add_parser("report", help="print a Markdown progress report")
    sub.add_parser("init", help="create the plan from the example if it doesn't exist")

    c = sub.add_parser("config", help="show where your files are; --data DIR or --plan FILE to change it")
    where = c.add_mutually_exclusive_group()
    where.add_argument("--data", type=Path, metavar="DIR",
                       help="keep PLAN_AND_PROGRESS.md, history.jsonl and index.html in DIR")
    where.add_argument("--plan", type=Path, metavar="FILE", dest="new_plan",
                       help="use this plan file; history.jsonl and index.html go in its folder")
    c.add_argument("--move", action="store_true",
                   help="also move your current plan and history.jsonl there (never overwrites)")

    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:  # e.g. Windows with output redirected to a cp1252 file: print "?" instead of crashing on "✓"
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        if args.cmd == "config":
            if args.move and args.data is None and args.new_plan is None:
                parser.error("--move needs --data DIR or --plan FILE")
            return config_command(args.data, args.new_plan, args.move)
        return _run(args)
    except ValueError as e:  # e.g. a broken config file
        print(f"error: {e}", file=sys.stderr)
        return 1


def _archive_command(plan, args: argparse.Namespace):
    """Archive the chosen projects after showing them. Returns the updated plan, or None when
    nothing was written (a dry run, nothing finished, or not confirmed)."""
    if not args.projects and not args.done:
        raise ValueError("name the projects to archive (slugs from `summary`), or use --done")
    chosen = {p.heading_line: p for p in (finished(plan) if args.done else [])}
    for slug in args.projects:
        p = plan.project(slug)
        chosen[p.heading_line] = p
    projects = sorted(chosen.values(), key=lambda p: p.heading_line)
    if not projects:
        print("No finished projects to archive.")
        return None

    history.sync(plan, args.history)  # record ticks not yet in history.jsonl, so they're archived too
    print(f"{'Would archive' if args.dry_run else 'Will archive'} {len(projects)} project(s):")
    for p in projects:
        print(f"  {p.emoji} {p.name}  ({p.done}/{p.total} goals)")
    print(f"  sections        -> {args.plan.parent / ARCHIVE_NAME}")
    print(f"  {history_lines(args.history, projects)} history line(s) -> {args.history.parent / HISTORY_ARCHIVE_NAME}")
    if args.dry_run:
        return None
    if not args.yes:
        if not sys.stdin.isatty():
            raise ValueError("no terminal to confirm in: add --yes")
        if input("Archive them? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing changed.")
            return None

    plan, moved = archive(plan, projects, args.history)
    print(f"Archived {len(projects)} project(s) and {moved} history line(s).")
    for p in projects:
        mention = next((i for i, line in enumerate(plan.lines, 1) if p.name in line), None)
        if mention:
            print(f"Note: '{p.name}' is still mentioned on line {mention} of {plan.path.name} "
                  "(a status table, say); edit it by hand if you like.")
    return plan


def _run(args: argparse.Namespace) -> int:
    # With --plan, history.jsonl and index.html default to the plan's folder, so a plan
    # elsewhere (a demo, a test) never writes into your real data/ folder.
    if args.plan:
        args.history = args.history or args.plan.parent / "history.jsonl"
        html = args.plan.parent / "index.html"
    else:
        args.plan, args.history, html = config.plan_path(), args.history or config.history_path(), config.html_path()
    if args.cmd == "build" and args.out:
        html = args.out
    if args.cmd == "init":
        return init(args.plan)
    try:
        plan = parse(args.plan)
        out = html
        if args.cmd == "add-project":
            plan = add_project(plan, args.name, args.status, args.target)
            print(f"Added project '{args.name}'")
        elif args.cmd == "add-goal":
            plan = add_goal(plan, args.project, args.text, args.target)
            print(f"Added goal to '{args.project}'")
        elif args.cmd == "toggle":
            plan = toggle_goal(plan, args.line - 1)
            print(f"Toggled line {args.line}")
        elif args.cmd in ("archive", "remove-project"):
            plan = _archive_command(plan, args)
            if plan is None:  # dry run, nothing to do, or not confirmed: nothing was written
                return 0

        items = refresh(plan, out, args.history)  # record new ticks, keep the page in step

        if args.cmd == "build":
            print(f"Built: {out}")
            if args.open:
                open_path(out)
        elif args.cmd == "summary":
            data = summary(plan)
            data["accomplishments"] = history.stats(items, plan.today)
            print(json.dumps(data, indent=2, ensure_ascii=False))
        elif args.cmd == "history":
            since = plan.today - timedelta(days=args.days - 1)
            days = history.by_day([a for a in items if a.date >= since])
            if not days:
                print(f"Nothing done in the last {args.days} days.")
            for day in sorted(days, reverse=True):
                print(f"{day:%a %Y-%m-%d}  ({len(days[day])})")
                for a in days[day]:
                    print(f"  ✓ [{a.project}] {a.goal}")
        elif args.cmd == "report":
            print(markdown(plan, items), end="")
    except (ConcurrentEditError, NotFoundError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
