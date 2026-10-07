# TaskDashboard architecture

How TaskDashboard is put together, and why it's built this way. For installing and using it, see the [README](README.md).
The original requirements are in [docs/Goals.md](docs/Goals.md), and the first design notes, written before
the code, in [docs/Implementation_Suggestions.md](docs/Implementation_Suggestions.md).

## How it fits together

```
PLAN_AND_PROGRESS.md ──parse──▶ plan.py ──┬──▶ history.py ──▶ history.jsonl (append-only)
   (source of truth)                      │         │
                                          │         ▼
                                          └──▶ build.py ──▶ index.html (self-contained page)
                                                    ▲
         menu bar / top bar / tray icon ────────────┘  every 5 minutes, or "Refresh"
         td commands (add-goal, toggle, …) ─────────┘  after every change to the plan
```

1. **`plan.py`** parses the Markdown plan into projects and goals and calculates the % values. It is also the only code that writes back to the plan.
2. **`history.py`** compares the plan with `history.jsonl` and appends a line for every goal that was ticked or unticked since the last run.
3. **`build.py`** renders `index.html` from the plan and the history.

`build.refresh()` runs steps 2 and 3 together. Each icon calls it every 5 minutes (and from its *Refresh* menu item), and every `td` command that changes the plan calls it too. That's how the page and the history stay current without a server or a file watcher.

## Layout

```
src/taskdashboard/
  plan.py      parse the Markdown, calculate %, safe write-back (the core)
  history.py   history.jsonl: record ticks, daily/weekly accomplishments
  archive.py   move finished projects to ARCHIVE.md and history.archive.jsonl
  build.py     render the self-contained index.html (projects, this week, heatmap, timeline)
  cli.py       build / summary / add-project / add-goal / toggle / history / archive / report / init / config
  report.py    Markdown progress report (the GitHub run summary)
  menu.py      what the Ubuntu and Windows icons show (shared)
  osutil.py    file locking and "open with default app" for macOS, Linux and Windows
  config.py    paths: --plan, then TASKDASHBOARD_* variables, then the config file, then data/
data/                          default home of your plan, history and page (ignored by git)
macos/                         macOS menu bar plugin (SwiftBar) + install.sh
linux/                         Ubuntu top-bar indicator + install.sh
windows/                       Windows tray icon + install.ps1
assets/                        icon (packaged with every release)
docs/                          requirements (Goals.md), early design notes, README screenshots (not packaged)
examples/                      example plan for new installs
scripts/package.py             builds the per-platform release packages
td, td.cmd                     command-line shortcut (macOS/Linux, Windows)
.github/workflows/             Tests and Release workflows
tests/                         unit tests + sample plan
```

## Design trade-offs

TaskDashboard deliberately favours **fast to deploy and simple to update** over a heavier
architecture. It's a one-person tool, so every extra layer would be more to install, more to
break and more to maintain than it's worth.

| Choice | What it buys | What it gives up |
|---|---|---|
| Plain Markdown plan, no database | Edit in any editor; diff, sync and undo it with git | No queries or schema; the parser relies on the [plan format](README.md#plan-format-the-parser-expects) |
| Python standard library only | Nothing to install; the same code runs on macOS, Ubuntu and Windows | No web framework or UI toolkit (the Windows icon still needs pystray + Pillow) |
| One self-contained `index.html` | Double-click to open; no server to run or secure | Read-only, and only on this computer |
| SwiftBar plugin, AppIndicator and tray scripts instead of native apps | A small script per platform, shipped in days | Each platform looks and behaves slightly differently; macOS needs SwiftBar |
| Refresh every 5 minutes instead of watching the file | Simple and reliable; no background file-watcher | Changes can take up to 5 minutes to show (or use *Refresh* in the icon's menu) |
| Append-only `history.jsonl` | Never rewritten by normal use, and merges cleanly across computers | No automatic clean-up; `td archive` trims it on request (see below) |

**Trimming the plan and `history.jsonl`:** `td archive` moves finished projects' sections to
`ARCHIVE.md` and their history lines to `history.archive.jsonl`, so nothing is lost
([how to use it](README.md#archiving-finished-projects)). It's the one place `history.jsonl` is
rewritten: atomically, under the same lock as the refresh. To keep it safe, it copies to the
archives first, then removes from the plan, then from the history, so an interruption can leave
a project in two places but never in none.

Both files are plain text, so you can also edit them by hand. Removing a done goal from the plan
doesn't touch the history: past accomplishments keep showing until their lines are removed. A
history line for a goal that's still ticked in the plan comes back on the next refresh, dated
with the plan's ` — YYYY-MM-DD` if it has one, otherwise today.

These are easy to revisit one at a time if a limit starts to hurt. The next steps below are
the first candidates.

## Next steps

- Remote viewing: publish `index.html` somewhere private, or a small server reachable only
  from your own devices (e.g. FastAPI behind Tailscale)
- Native SwiftUI `MenuBarExtra` app (Phase 3) once the plugin feels limiting
