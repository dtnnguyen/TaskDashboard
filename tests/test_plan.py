"""Run with:  python3 -m unittest discover -s tests"""

import contextlib
import difflib
import io
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from taskdashboard.build import render, write_html  # noqa: E402
from taskdashboard.cli import main  # noqa: E402
from taskdashboard.plan import (  # noqa: E402
    ConcurrentEditError,
    NotFoundError,
    add_goal,
    add_project,
    parse,
    percent,
    summary,
    toggle_goal,
)

FIXTURE = ROOT / "tests" / "fixtures" / "plan_sample.md"
TODAY = date(2026, 10, 2)  # a Friday


class TempPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "plan.md"
        shutil.copy(FIXTURE, self.path)
        self.plan = parse(self.path, TODAY)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def diff(self, before: str) -> list[str]:
        """Changed lines only, as '+line' / '-line'."""
        after = self.path.read_text(encoding="utf-8")
        return [
            l.rstrip("\n")
            for l in difflib.unified_diff(before.splitlines(True), after.splitlines(True), n=0)
            if l[:1] in "+-" and not l.startswith(("+++", "---"))
        ]


class PercentTest(unittest.TestCase):
    def test_edge_cases(self):
        self.assertIsNone(percent(0, 0))
        self.assertEqual(percent(0, 5), 0)
        self.assertEqual(percent(1, 14), 7)
        self.assertEqual(percent(13, 14), 93)
        self.assertEqual(percent(199, 200), 99)  # never 100% with a goal still open
        self.assertEqual(percent(5, 5), 100)


class ParseTest(TempPlanTest):
    def test_projects_and_statuses(self):
        self.assertEqual(
            [(p.name, p.status) for p in self.plan.projects],
            [
                ("Alpha", "active"),
                ("Beta", "active"),
                ("Habit practice (daily)", "habit"),
                ("No Emoji Project", "unset"),
                ("Later thing (later)", "later"),
            ],
        )

    def test_counts_and_percent(self):
        alpha = self.plan.project("alpha")
        self.assertEqual((alpha.done, alpha.total, alpha.percent), (2, 4, 50))  # [X] and [x] both count
        self.assertEqual(alpha.target, date(2026, 10, 14))

    def test_plain_bullets_and_other_sections_ignored(self):
        habit = self.plan.project("habit-practice-daily")
        self.assertEqual(habit.total, 2)  # "Topics to rotate" is not a goal
        texts = [g.text for p in self.plan.projects for g in p.goals]
        self.assertNotIn("not a goal, outside Milestones", texts)

    def test_overall_uses_active_projects_only(self):
        # Alpha 2/4 + Beta 0/1; habit, unset and later projects are left out
        self.assertEqual(self.plan.overall, {"done": 2, "total": 5, "percent": 40})

    def test_overdue(self):
        self.assertEqual([g.text for g in self.plan.project("alpha").overdue(TODAY)], ["Third step (target: 2026-10-01)"])

    def test_habit_week_and_streak(self):
        habit = self.plan.project("habit-practice-daily")
        self.assertEqual(habit.week_done, 3)  # Tue 29, Wed 30, Fri 2
        self.assertEqual(habit.streak, 1)  # Thu 1 is empty

    def test_summary_shape(self):
        s = summary(self.plan)
        self.assertEqual(s["overall"]["percent"], 40)
        self.assertEqual(s["projects"][0]["percent"], 50)
        self.assertIn("streak", s["projects"][2])


class WriteBackTest(TempPlanTest):
    def test_add_goal_adds_exactly_one_line_after_last_checkbox(self):
        before = self.path.read_text(encoding="utf-8")
        plan = add_goal(self.plan, "habit-practice-daily", "Topic three", date(2026, 11, 1))
        self.assertEqual(self.diff(before), ["+- [ ] Topic three (target: 2026-11-01)"])
        lines = self.path.read_text(encoding="utf-8").splitlines()
        i = lines.index("- [ ] Topic three (target: 2026-11-01)")
        self.assertEqual(lines[i - 1], "- [ ] Topic two")  # before the plain "Topics to rotate" bullet
        self.assertEqual(plan.project("habit-practice-daily").total, 3)

    def test_adding_a_goal_lowers_percent(self):
        plan = add_goal(self.plan, "alpha", "Fifth step")
        self.assertEqual(plan.project("alpha").percent, 40)

    def test_add_project(self):
        before = self.path.read_text(encoding="utf-8")
        plan = add_project(self.plan, "Gamma", target=date(2026, 12, 31))
        self.assertEqual(sorted(self.diff(before)), ["+", "+### 🟢 Gamma (target: 2026-12-31)"])
        self.assertIn(
            "- [ ] Parked goal\n\n### 🟢 Gamma (target: 2026-12-31)\n\n---\n\n## Daily log",
            self.path.read_text(encoding="utf-8"),
        )
        self.assertIsNone(plan.project("gamma").percent)  # no goals yet → "—"
        plan = add_goal(plan, "gamma", "First gamma goal")
        self.assertEqual(plan.project("gamma").total, 1)

    def test_add_duplicate_project_rejected(self):
        with self.assertRaises(ValueError):
            add_project(self.plan, "alpha")

    def test_toggle_checks_with_date_and_unchecks(self):
        line = self.plan.project("beta").goals[0].line
        before = self.path.read_text(encoding="utf-8")
        plan = toggle_goal(self.plan, line)
        self.assertEqual(self.diff(before), ["-- [ ] Only goal", "+- [x] Only goal — 2026-10-02"])
        plan = toggle_goal(plan, line)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_toggle_non_goal_line_rejected(self):
        with self.assertRaises(NotFoundError):
            toggle_goal(self.plan, 0)

    def test_concurrent_edit_refused(self):
        with self.path.open("a", encoding="utf-8") as f:
            f.write("\nedited elsewhere\n")
        with self.assertRaises(ConcurrentEditError):
            add_goal(self.plan, "alpha", "Lost update")

    def test_empty_text_rejected(self):
        with self.assertRaises(ValueError):
            add_goal(self.plan, "alpha", "   \n ")


class BuildTest(TempPlanTest):
    def test_render_shows_percentages_and_escapes(self):
        page = render(self.plan)
        self.assertIn(">40%<", page)  # overall
        self.assertIn(">50%<", page)  # Alpha
        self.assertIn("<code>code</code>", page)
        self.assertIn("<strong>bold</strong>", page)

    def test_html_is_escaped(self):
        plan = add_goal(self.plan, "alpha", "<script>alert(1)</script>")
        self.assertNotIn("<script>alert", render(plan))

    def test_write_html_only_when_changed(self):
        out = self.tmp / "index.html"
        self.assertTrue(write_html(self.plan, out))
        self.assertFalse(write_html(self.plan, out))


class CliTest(TempPlanTest):
    def args(self, *cmd):
        """Never let a test touch the real history.jsonl or index.html."""
        return ["--plan", str(self.path), "--history", str(self.tmp / "history.jsonl"), *cmd]

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"TASKDASHBOARD_HTML": str(self.tmp / "index.html")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_add_goal_and_build(self):
        out = self.tmp / "index.html"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(self.args("add-goal", "beta", "From CLI")), 0)
            self.assertEqual(main(self.args("summary")), 0)
            self.assertEqual(main(self.args("history")), 0)
        self.assertIn("From CLI", out.read_text(encoding="utf-8"))

    def test_unknown_project_fails_cleanly(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(self.args("add-goal", "nope", "x")), 1)


class RealPlanTest(unittest.TestCase):
    """The real plan parses without errors (read-only)."""

    def test_parses(self):
        real = ROOT / "data" / "PLAN_AND_PROGRESS.md"
        if not real.exists():
            self.skipTest("no PLAN_AND_PROGRESS.md")
        plan = parse(real)
        self.assertTrue(plan.projects)
        render(plan)


if __name__ == "__main__":
    unittest.main()
