"""Run with:  python3 -m unittest discover -s tests"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from taskdashboard import history  # noqa: E402
from taskdashboard.build import render  # noqa: E402
from taskdashboard.plan import parse, toggle_goal  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "plan_sample.md"
FRI = date(2026, 10, 2)
SAT = date(2026, 10, 3)
MON = date(2026, 10, 5)


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "plan.md"
        self.hist = self.tmp / "history.jsonl"
        shutil.copy(FIXTURE, self.path)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def sync(self, today):
        plan = parse(self.path, today)
        return plan, history.sync(plan, self.hist, datetime(today.year, today.month, today.day, 12))

    def done(self):
        return [(a.date, a.goal) for a in history.accomplishments(history.load(self.hist))]

    def tick_in_editor(self, old, new):
        """Simulate editing the Markdown by hand (no done date written)."""
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(text.replace(old, new), encoding="utf-8")

    def test_first_run_baseline_is_not_counted(self):
        _, events = self.sync(FRI)
        kinds = {(e["goal"], e["event"], e["date"]) for e in events}
        self.assertIn(("First step", "baseline", "2026-10-02"), kinds)  # already done, date unknown
        self.assertIn(("Second step", "done", "2026-10-01"), kinds)  # date written in the plan
        self.assertEqual(self.done(), [(date(2026, 10, 1), "Second step")])

    def test_no_changes_no_events(self):
        self.sync(FRI)
        _, events = self.sync(FRI)
        self.assertEqual(events, [])

    def test_tick_in_editor_counts_today(self):
        self.sync(FRI)
        self.tick_in_editor("- [ ] Only goal", "- [x] Only goal")
        self.sync(SAT)
        self.assertIn((SAT, "Only goal"), self.done())

    def test_toggle_command_date_is_used(self):
        plan, _ = self.sync(FRI)
        toggle_goal(plan, plan.project("beta").goals[0].line)  # writes " — 2026-10-02"
        self.sync(MON)  # noticed later, still dated the day it was ticked
        self.assertIn((FRI, "Only goal"), self.done())

    def test_untick_removes_and_retick_counts_again(self):
        self.sync(FRI)
        self.tick_in_editor("- [ ] Only goal", "- [x] Only goal")
        self.sync(FRI)
        self.tick_in_editor("- [x] Only goal", "- [ ] Only goal")
        self.sync(SAT)
        self.assertNotIn("Only goal", [g for _, g in self.done()])
        self.tick_in_editor("- [ ] Only goal", "- [x] Only goal")
        self.sync(MON)
        self.assertIn((MON, "Only goal"), self.done())

    def test_stats_week_boundaries(self):
        self.sync(FRI)  # Second step done Thu 10-01
        self.tick_in_editor("- [ ] Only goal", "- [x] Only goal")
        self.sync(MON)  # new week
        s = history.stats(history.accomplishments(history.load(self.hist)), MON)
        self.assertEqual(s, {"today": 1, "this_week": 1, "last_week": 1})

    def test_date_separators(self):
        self.sync(FRI)
        self.tick_in_editor("- [ ] Only goal", "- [x] Only goal - 2026-09-30")
        self.tick_in_editor("- [ ] Topic two", "- [x] Topic two 2026-09-29")
        self.sync(FRI)
        self.assertIn((date(2026, 9, 30), "Only goal"), self.done())
        self.assertIn((date(2026, 9, 29), "Topic two"), self.done())

    def test_date_added_later_redates_baseline(self):
        self.sync(FRI)  # "First step" is a baseline: done, date unknown
        self.tick_in_editor("- [X] First step", "- [X] First step — 2026-09-28")
        _, events = self.sync(SAT)
        self.assertEqual([(e["goal"], e["event"], e["date"]) for e in events], [("First step", "done", "2026-09-28")])
        self.assertIn((date(2026, 9, 28), "First step"), self.done())
        _, events = self.sync(SAT)
        self.assertEqual(events, [])  # recorded once, not on every refresh

    def test_invalid_date_is_treated_as_undated(self):
        self.sync(FRI)
        self.tick_in_editor("- [ ] Only goal", "- [x] Only goal - 2026-09-31")
        self.sync(SAT)
        self.assertIn((SAT, "Only goal"), self.done())

    def test_bad_lines_are_skipped(self):
        self.sync(FRI)
        with self.hist.open("a", encoding="utf-8") as f:
            f.write("not json\n\n")
        self.assertEqual(len(self.done()), 1)

    def test_history_is_append_only(self):
        self.sync(FRI)
        first = self.hist.read_text(encoding="utf-8")
        self.tick_in_editor("- [ ] Only goal", "- [x] Only goal")
        self.sync(SAT)
        self.assertTrue(self.hist.read_text(encoding="utf-8").startswith(first))
        for line in self.hist.read_text(encoding="utf-8").splitlines():
            self.assertEqual(set(json.loads(line)), {"date", "project", "goal", "event", "recorded"})


class TimelineRenderTest(HistoryTest):
    def test_page_has_timeline_and_tiles(self):
        self.sync(FRI)
        self.tick_in_editor("- [ ] Only goal", "- [x] Only goal")
        plan, _ = self.sync(FRI)
        page = render(plan, history.accomplishments(history.load(self.hist)))
        self.assertIn('id="day-2026-10-02"', page)  # timeline entry, target of the heatmap link
        self.assertIn('href="#day-2026-10-02"', page)  # heatmap cell links to it
        self.assertIn("<b>1</b><span>done today</span>", page)
        self.assertIn("<b>2</b><span>done this week", page)
        self.assertIn("Yesterday", page)  # Thu 10-01

    def test_empty_history_message(self):
        plan = parse(self.path, FRI)
        self.assertIn("Nothing ticked yet", render(plan, []))


if __name__ == "__main__":
    unittest.main()
