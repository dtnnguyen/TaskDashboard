# TaskDashboard: Implementation Suggestions

> Review of `Goals.md` · 2026-10-03

---

## 1. Key observation: the data already exists

`PersonalProjects/PLAN_AND_PROGRESS.md` already tracks projects and goals the way this dashboard needs:

- each project is a `### <status emoji> <Name> (target: YYYY-MM-DD)` heading
- each goal is a checkbox line: `- [ ]` / `- [x]`, often with `(target: YYYY-MM-DD)`
- status emojis are used consistently: 🟢 active · 🔁 habit · ⏸️ later

**Suggestion:** make that Markdown file the **single source of truth**, so the dashboard reads and writes it and never keeps its own database.

- No double entry: you keep editing the plan in your editor (or with Claude) and the dashboard updates automatically.
- "Add project" and "add goal" just append lines to the Markdown file.
- No migration and no lock-in. If the dashboard breaks, the plan still works on its own.

### Percentage of completion

Every project shows a **percentage**, calculated by the parser in `plan.py` so the menu bar, the web page and the API always show the same number.

| Level | Formula | Example (today's plan) |
|---|---|---|
| **Project** | `round(100 × checked / total)` over that section's checkboxes | Xanadu: 1 of 14 → **7%** |
| **Overall** (menu bar) | Checked ÷ total across all **🟢 active** projects combined | (0 + 1) / (12 + 14) → **4%** |
| **Habit (🔁)** | Weekdays done this week ÷ 5, from the *Daily log* | 3 of 5 weekdays → **60%** |

Rules:
- Non-checkbox bullets (like "Topics to rotate…") are ignored.
- **⏸️ later** projects show their own % but are **left out of the overall %**, so parked work doesn't drag the number down.
- **No goals yet** → show `—` instead of 0%, so you can tell an empty project from one that hasn't started.
- Show **0–99%** until every box is checked. Rounding should never display 100% when one goal is still open, so round down when it's above 99. At 100%, suggest switching the project to ✅ done.
- Combine the overall % from goal counts, not by averaging project percentages. That way a 3-goal project doesn't count as much as a 14-goal one.
- Optional later: weights per goal (`- [ ] … (weight: 3)`) if some goals are much bigger than others. Leave this out of the first version.

---

## 2. Recommended architecture

```
                 PLAN_AND_PROGRESS.md   (source of truth)
                          ▲
                          │ parse / append
                ┌─────────┴─────────┐
                │  core: plan.py     │  parse → {projects, goals, progress}
                └───┬───────────┬───┘
                    │           │
        menu bar ◄──┘           └──► web server (FastAPI) ──► browser / phone
     (SwiftBar plugin,                    │
      later SwiftUI)                 remote via Tailscale
```

One small Python parser module, used by two front ends. Python 3 is already installed (`/opt/homebrew/bin/python3`) and matches `captions2doc/`.

---

## 3. Phased plan

### Phase 1: Menu bar icon (about one evening)

Use **[SwiftBar](https://github.com/swiftbar/SwiftBar)** (`brew install swiftbar`). A SwiftBar plugin is any script whose stdout becomes a menu bar item and dropdown, so no Xcode or Swift is needed.

- `plugins/goals.5m.py` → re-runs every 5 minutes (it can also refresh on file change)
- Menu bar text: `🎯 4%` (overall % of active projects). Alternative: `🎯 4% · 1/26`, or the next due goal
- Dropdown, one block per project, **percentage first**:
  ```
  🟢 MySatKit: Nordspace slice   ▓▓░░░░░░░░  17%  (2/12) · due 10-14
     ⚠ Overdue: Push QuantumSim to GitHub (10-04)
  🟢 Xanadu                       ▓░░░░░░░░░   7%  (1/14)
  🔁 C++ practice                 ▓▓▓▓▓▓░░░░  60%  this week · streak 2 days
  ⏸️ Agentic AI                   ░░░░░░░░░░   0%  (0/4)
  ---
  Open plan in editor | bash=open param1=.../PLAN_AND_PROGRESS.md
  Open web dashboard  | href=http://localhost:8000
  ```
- Clicking a goal can toggle its checkbox (SwiftBar supports `bash=` actions per line).

This covers the "icon at the top of the MacBook" requirement almost right away.

### Phase 2: Web dashboard plus configuration (1–2 weekends)

**FastAPI + Jinja templates + htmx** (or plain HTML forms). This means no JS build step and one process.

| Route | Purpose |
|---|---|
| `GET /` | Overall % at the top. Then a card per project: a large **% complete**, progress bar, `done/total`, target date, overdue goals |
| `GET /project/{slug}` | Full goal list with checkboxes |
| `POST /projects` | **Add new project** → appends a `### 🟢 Name (target: …)` section |
| `POST /project/{slug}/goals` | **Add goal to new or existing project** → inserts `- [ ] …` at the end of that section's checklist |
| `POST /goal/toggle` | Check or uncheck a goal |
| `GET /api/summary` | JSON, used by the menu bar (and later by a native app). Includes `percent` per project and overall (see below) |

`/api/summary` example:

```json
{
  "overall": { "done": 1, "total": 26, "percent": 4 },
  "projects": [
    { "name": "Xanadu", "status": "active", "done": 1, "total": 14, "percent": 7,
      "target": null, "overdue": ["Push QuantumSim to GitHub"] },
    { "name": "C++ practice", "status": "habit", "percent": 60, "streak": 2 }
  ]
}
```

After toggling a goal, the page updates that project's % and the overall % (an htmx swap of the card), so you don't need a full reload.

**Remote viewing:** install **Tailscale** on the Mac and on your phone or laptop, then open `http://<mac-name>:8000` from anywhere.
- It's private by default, so you don't need to write login or auth code.
- Trade-off: the Mac has to be awake. Run the server as a `launchd` agent so it starts at login. If you need access while the Mac sleeps, see Option C below.

### Phase 3 (optional): Native SwiftUI menu bar app

Replace SwiftBar with a SwiftUI `MenuBarExtra` app (macOS 13+) that calls `/api/summary`. Do this only if you want a richer popover (charts, inline add-goal form) or the practice. SwiftBar is enough for daily use.

---

## 4. Write-back rules (to avoid corrupting the plan)

Writing to a hand-edited Markdown file is the riskiest part. Keep it safe:

1. **Never re-serialize the whole file.** Only insert or modify specific lines and leave everything else byte-for-byte unchanged.
2. **Insert new goals after the last `- [ ]`/`- [x]` line** of the section, not at the very end, because the C++ section has trailing plain bullets.
3. **Atomic writes:** write to a temp file, then `os.replace()`.
4. **Detect concurrent edits:** keep the file's mtime/hash at read time and refuse the write (re-read and retry) if it changed.
5. **Put `PersonalProjects/` under git** (it isn't a repo yet). Every dashboard change gets an undo button, and git history gives you **progress-over-time charts** for free (see section 6).

---

## 5. Parsing conventions to formalize

Write these into the top of `PLAN_AND_PROGRESS.md` (or a short `TaskDashboard/FORMAT.md`) so you and the parser agree:

| Element | Pattern | Example |
|---|---|---|
| Project | `### <emoji> <name> [(target: YYYY-MM-DD)]` under `## Milestones` | `### 🟢 Xanadu` |
| Status | 🟢 active · 🔁 habit · ⏸️ later · ✅ done (new) | |
| Goal | `- [ ] text [(target: YYYY-MM-DD)]` | |
| Done date | `- [x] text — YYYY-MM-DD` (already used) | `- [x] QuantumSim/ project created … — 2026-10-01` |

Scope the parser to the `## Milestones` section so that tables, the daily log and the weekly template are never mistaken for goals.

Optional: support a `projects/*.md` glob as well, so a project can keep its goals in its own folder (e.g. `MySatKit/docs/Space_Career_Plan.md`) and still show up.

---

## 6. Features worth adding (not in Goals.md yet)

The parsing work above makes these cheap:

- **Overdue / due-soon highlighting** using the `(target: …)` dates. This is the most useful signal in the menu bar.
- **Habit projects (🔁):** a checkbox % doesn't fit "C++ practice", because it never finishes. Use the **weekly %** from section 1 plus a **streak**, both from the *Daily log* table's "C++ problem" column. This matches your rule "never miss two days in a row".
- **"Today's main task"** pulled from the newest *Daily log* row's "Tomorrow's main task" column, shown first in the dropdown.
- **2-active-project rule:** warn when more than two projects are 🟢, which enforces your own rule.
- **Progress history:** a nightly snapshot (`date, project, done, total, percent` → CSV) or `git log` replay, plotted as a **% over time** chart. You could also show "+12% this week" next to each project.
- **Weekly review helper:** a page listing what got checked off this week, ready to paste into the Sunday template.

---

## 7. Gaps in Goals.md to decide on

| Question | Suggested answer |
|---|---|
| How is "progress" / % measured? | Checkbox ratio by default, weekly % plus a streak for 🔁 habits, overall % over active projects only (section 1). Only add numeric goals (e.g. "20 problems") or weights if you really need them. |
| Can goals be **edited, completed, deleted, archived**? Goals.md only lists *add*. | At least add **complete (toggle)**. Do editing and deleting in the Markdown file itself. |
| Is remote access **read-only or editable**? | Editable over Tailscale is fine because the network is private. |
| Should it work while the Mac is asleep? | If yes → Option C below. |
| Mac app **or** webpage? | **Both**, through the shared core: a menu bar plugin plus a web page. |

---

## 8. Alternatives considered

| Option | Pros | Cons | When to pick |
|---|---|---|---|
| **A. Markdown + SwiftBar + FastAPI (recommended)** | Reuses your existing plan; fast to build; no DB | Mac must be awake for remote | Default |
| **B. Native SwiftUI app + SwiftData/CloudKit** | Polished; iCloud sync to iPhone | Separate data from your Markdown plan; needs Xcode/Swift; no web view | You want a real Mac/iOS app |
| **C. Hosted web app (e.g. Supabase + Vercel, or a Raspberry Pi at home)** | Always reachable | Needs auth; data leaves the Markdown file, or you need a sync job (git push → host parses) | You check goals often while the Mac is off |

A middle path for C: push `PersonalProjects` to a **private** GitHub repo and have a host such as a Pi or a free-tier VM parse it on each push. The Markdown file stays the source of truth.

---

## 9. Suggested folder layout

```
TaskDashboard/
├── Goals.md
├── Implementation_Suggestions.md
├── README.md
├── pyproject.toml
├── src/taskdashboard/
│   ├── plan.py          # parse + safe write-back (the core)
│   ├── server.py        # FastAPI app
│   └── templates/       # Jinja + htmx pages
├── swiftbar/
│   └── goals.5m.py      # menu bar plugin (imports plan.py or calls /api/summary)
├── launchd/
│   └── com.trang.taskdashboard.plist
└── tests/
    ├── fixtures/PLAN_AND_PROGRESS.sample.md
    └── test_plan.py     # parse counts, %, insert keeps file otherwise identical
```

**Most important test:** "add a goal, then diff the file → exactly one line added, in the right section."

**Percentage tests:** 0 goals → `—`; 13/14 → 92%; 199/200 → 99% (not 100%); all checked → 100%; ⏸️ projects excluded from overall; adding a goal lowers the %, ticking one raises it.

---

## 10. First steps

1. `git init` in `PersonalProjects/` and commit.
2. Write `plan.py` with `parse(path) -> list[Project]` plus tests against a copy of the current plan.
3. Write the SwiftBar plugin and confirm the 🎯 icon shows the correct overall % and per-project %.
4. Add FastAPI with read-only pages, then the add/toggle forms.
5. Set up Tailscale and the launchd agent → check the dashboard from your phone.

