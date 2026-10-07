"""Run with:  python3 -m unittest discover -s tests"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from taskdashboard import history  # noqa: E402
from taskdashboard.archive import ARCHIVE_NAME, HISTORY_ARCHIVE_NAME, archive, finished  # noqa: E402
from taskdashboard.cli import main  # noqa: E402
from taskdashboard.plan import ConcurrentEditError, parse  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "plan_sample.md"
TODAY = date(2026, 10, 2)

# Appended to the sample plan's Milestones: one ✅ done project, one with every goal ticked.
EXTRA = """### ✅ Finished thing
- [x] Did it — 2026-09-20

### 🟢 Gamma
- [x] One — 2026-09-28
- [x] Two — 2026-09-29

"""


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.path = self.tmp / "PLAN_AND_PROGRESS.md"
        text = FIXTURE.read_text(encoding="utf-8")
        marker = "### ⏸️ Later thing (later)"
        self.path.write_text(text.replace(marker, EXTRA + marker), encoding="utf-8")
        self.history = self.tmp / "history.jsonl"
        history.sync(parse(self.path, TODAY), self.history, now=None)
        self.plan = parse(self.path, TODAY)

    def names(self):
        return [p.name for p in parse(self.path, TODAY).projects]

    def events(self, path):
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    def run_cli(self, *cmd):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["--plan", str(self.path), "--history", str(self.history), *cmd])
        return code, out.getvalue(), err.getvalue()

    def test_finished_picks_done_and_fully_ticked_but_not_habits(self):
        self.assertEqual([p.name for p in finished(self.plan)], ["Finished thing", "Gamma"])

    def test_archive_moves_section_and_history(self):
        gamma = self.plan.project("gamma")
        before = [e for e in self.events(self.history) if e["project"] == "Gamma"]
        self.assertEqual(len(before), 2)

        plan, moved = archive(self.plan, [gamma], self.history)

        self.assertEqual(moved, 2)
        self.assertNotIn("Gamma", [p.name for p in plan.projects])
        self.assertIn("Finished thing", self.names())  # the others are untouched
        self.assertFalse([e for e in self.events(self.history) if e["project"] == "Gamma"])
        self.assertEqual(self.events(self.tmp / HISTORY_ARCHIVE_NAME), before)
        md = (self.tmp / ARCHIVE_NAME).read_text(encoding="utf-8")
        self.assertIn("## Archived 2026-10-02", md)
        self.assertIn("### 🟢 Gamma\n- [x] One — 2026-09-28\n- [x] Two — 2026-09-29\n", md)

    def test_other_lines_stay_identical(self):
        before = self.path.read_text(encoding="utf-8")
        archive(self.plan, [self.plan.project("gamma")], self.history)
        after = self.path.read_text(encoding="utf-8")
        self.assertEqual(after, before.replace("### 🟢 Gamma\n- [x] One — 2026-09-28\n- [x] Two — 2026-09-29\n\n", ""))

    def test_last_projects_leave_one_blank_line_before_rule(self):
        later = self.plan.project("later-thing-later")
        gamma = self.plan.project("gamma")
        archive(self.plan, [later, gamma], self.history)
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("\n\n\n", text)
        self.assertIn("- [x] Did it — 2026-09-20\n\n---\n", text)

    def test_second_archive_appends_to_archive_md(self):
        archive(self.plan, [self.plan.project("gamma")], self.history)
        plan = parse(self.path, TODAY)
        archive(plan, [plan.project("finished-thing")], self.history)
        md = (self.tmp / ARCHIVE_NAME).read_text(encoding="utf-8")
        self.assertEqual(md.count("# Archived projects"), 1)
        self.assertIn("Gamma", md)
        self.assertIn("Finished thing", md)

    def test_changed_plan_is_refused_before_anything_is_written(self):
        with self.path.open("a", encoding="utf-8") as f:
            f.write("\nedited elsewhere\n")
        with self.assertRaises(ConcurrentEditError):
            archive(self.plan, [self.plan.project("gamma")], self.history)
        self.assertFalse((self.tmp / ARCHIVE_NAME).exists())

    def test_broken_history_lines_are_kept(self):
        with self.history.open("a", encoding="utf-8") as f:
            f.write("not json\n")
        archive(self.plan, [self.plan.project("gamma")], self.history)
        self.assertIn("not json\n", self.history.read_text(encoding="utf-8"))

    # ── command line ──

    def test_cli_done_with_yes(self):
        code, out, _ = self.run_cli("archive", "--done", "--yes")
        self.assertEqual(code, 0)
        self.assertIn("Archived 2 project(s)", out)
        self.assertNotIn("Gamma", self.names())
        self.assertNotIn("Finished thing", self.names())
        self.assertIn("Alpha", self.names())
        self.assertTrue((self.tmp / "index.html").exists())

    def test_cli_alias_and_slug(self):
        code, _, _ = self.run_cli("remove-project", "beta", "--yes")
        self.assertEqual(code, 0)
        self.assertNotIn("Beta", self.names())

    def test_cli_dry_run_changes_nothing(self):
        before = self.path.read_bytes()
        code, out, _ = self.run_cli("archive", "--done", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Would archive 2 project(s)", out)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse((self.tmp / ARCHIVE_NAME).exists())

    def test_cli_refuses_without_a_terminal_or_yes(self):
        before = self.path.read_bytes()
        code, _, err = self.run_cli("archive", "gamma")
        self.assertEqual(code, 1)
        self.assertIn("--yes", err)
        self.assertEqual(self.path.read_bytes(), before)

    def test_cli_needs_a_slug_or_done(self):
        code, _, err = self.run_cli("archive")
        self.assertEqual(code, 1)
        self.assertIn("--done", err)

    def test_cli_unknown_slug_writes_nothing(self):
        code, _, _ = self.run_cli("archive", "nope", "--yes")
        self.assertEqual(code, 1)
        self.assertFalse((self.tmp / ARCHIVE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
