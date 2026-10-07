"""Report, init, and release packaging.  Run with:  python3 -m unittest discover -s tests"""

import contextlib
import io
import shutil
import sys
import tarfile
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import package  # noqa: E402
from taskdashboard import cli, config, history  # noqa: E402
from taskdashboard.plan import parse  # noqa: E402
from taskdashboard.report import markdown  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "plan_sample.md"
EXAMPLE = ROOT / "examples" / "PLAN_AND_PROGRESS.example.md"
EXAMPLE_HISTORY = ROOT / "examples" / "history.example.jsonl"


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()


class ReportTest(TempDirTest):
    def test_markdown(self):
        path = self.tmp / "plan.md"
        shutil.copy(FIXTURE, path)
        plan = parse(path, date(2026, 10, 2))
        history.sync(plan, self.tmp / "h.jsonl")
        text = markdown(plan, history.accomplishments(history.load(self.tmp / "h.jsonl")))
        self.assertIn("## 🎯 40% of active goals done (2/5)", text)
        self.assertIn("| 🟢 Alpha | `▓▓▓▓▓░░░░░` 50% | 2/4 | 2026-10-14 | 1 |", text)
        self.assertIn("### Done this week", text)
        self.assertIn("Second step", text)
        self.assertIn("### Overdue", text)

    def test_pipes_escaped_in_table(self):
        path = self.tmp / "plan.md"
        path.write_text("## Milestones\n\n### 🟢 A | B\n- [ ] x\n", encoding="utf-8")
        self.assertIn("A \\| B", markdown(parse(path), []))


class CliPathsTest(TempDirTest):
    def test_plan_flag_keeps_outputs_next_to_the_plan(self):
        """Regression: --plan elsewhere must never write into the real data/ folder."""
        plan = self.tmp / "plan.md"
        shutil.copy(FIXTURE, plan)
        forbidden = mock.Mock(side_effect=AssertionError("used the default data/ path"))
        with mock.patch.object(config, "html_path", forbidden), mock.patch.object(config, "history_path", forbidden):
            code, _, err = self.run_cli("--plan", str(plan), "summary")
        self.assertEqual(code, 0, err)
        self.assertTrue((self.tmp / "index.html").exists())
        self.assertTrue((self.tmp / "history.jsonl").exists())


class InitTest(TempDirTest):
    def test_creates_from_example_and_never_overwrites(self):
        plan = self.tmp / "data" / "PLAN_AND_PROGRESS.md"
        code, out, _ = self.run_cli("--plan", str(plan), "init")
        self.assertEqual(code, 0)
        self.assertIn("Created", out)
        self.assertEqual(plan.read_bytes(), EXAMPLE.read_bytes())

        plan.write_text("my own plan\n", encoding="utf-8")
        code, out, _ = self.run_cli("--plan", str(plan), "init")
        self.assertEqual(code, 0)
        self.assertIn("already exists", out)
        self.assertEqual(plan.read_text(encoding="utf-8"), "my own plan\n")

    def test_example_plan_parses(self):
        plan = parse(EXAMPLE)
        self.assertGreaterEqual(len(plan.projects), 3)
        self.assertIsNotNone(plan.overall["percent"])

    def test_example_history_matches_example_plan(self):
        """Running the sample (README: Try the example) must not add lines to the history:
        every ticked goal in the example plan already has its "done" event."""
        hist = self.tmp / "history.jsonl"
        shutil.copyfile(EXAMPLE_HISTORY, hist)
        plan = parse(EXAMPLE)
        self.assertEqual(history.sync(plan, hist), [])
        items = history.accomplishments(history.load(hist))
        self.assertEqual(len(items), sum(p.done for p in plan.projects))


class PackageTest(TempDirTest):
    def build_all(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(package.main(["--out", str(self.tmp)]), 0)
        return {p.name: p for p in self.tmp.iterdir()}

    def names(self, path):
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as z:
                return z.namelist()
        with tarfile.open(path) as t:
            return t.getnames()

    def test_one_package_per_platform_without_personal_data(self):
        built = self.build_all()
        ver = package.version()
        expected = {f"taskdashboard-{ver}-macos.zip", f"taskdashboard-{ver}-linux.tar.gz",
                    f"taskdashboard-{ver}-windows.zip", "SHA256SUMS.txt"}
        self.assertEqual(set(built), expected)
        for name in expected - {"SHA256SUMS.txt"}:
            names = self.names(built[name])
            self.assertTrue(any(n.endswith("/INSTALL.txt") for n in names))
            self.assertTrue(any(n.endswith("examples/PLAN_AND_PROGRESS.example.md") for n in names))
            for n in names:
                self.assertNotIn("/data/", n)
                self.assertFalse(n.endswith(("history.jsonl", "index.html", "/PLAN_AND_PROGRESS.md")), n)
                self.assertNotIn("__pycache__", n)
        self.assertIn(f"taskdashboard-{ver}-windows.zip", built["SHA256SUMS.txt"].read_text(encoding="utf-8"))

    def test_each_package_has_only_its_platform(self):
        built = self.build_all()
        for platform, others in (("macos", ("linux/", "windows/")), ("linux", ("macos/", "windows/")),
                                 ("windows", ("macos/", "linux/"))):
            path = next(p for n, p in built.items() if f"-{platform}." in n)
            names = self.names(path)
            self.assertTrue(any(f"/{platform}/" in n for n in names))
            for other in others:
                self.assertFalse(any(f"/{other}" in n for n in names), (platform, other))

    def test_scripts_are_executable(self):
        built = self.build_all()
        mac = next(p for n, p in built.items() if n.endswith("macos.zip"))
        with zipfile.ZipFile(mac) as z:
            mode = z.getinfo(f"taskdashboard-{package.version()}-macos/macos/install.sh").external_attr >> 16
        self.assertTrue(mode & 0o111)
        linux = next(p for n, p in built.items() if n.endswith(".tar.gz"))
        with tarfile.open(linux) as t:
            info = t.getmember(f"taskdashboard-{package.version()}-linux/linux/install.sh")
        self.assertTrue(info.mode & 0o111)

    def test_forbidden_names_refused(self):
        for bad in ("pkg/data/PLAN_AND_PROGRESS.md", "pkg/history.jsonl", "pkg/index.html", "pkg/.DS_Store"):
            with self.assertRaises(SystemExit):
                package.check([bad])
        package.check(["pkg/examples/PLAN_AND_PROGRESS.example.md"])

    def test_tag_must_match_version(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            package.main(["--out", str(self.tmp), "--check-tag", "v0.0.0-wrong"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(package.main(["--out", str(self.tmp), "--check-tag", f"v{package.version()}"]), 0)


class WorkflowFilesTest(unittest.TestCase):
    def test_workflows_exist(self):
        workflows = ROOT / ".github" / "workflows"
        for name in ("tests.yml", "release.yml"):
            text = (workflows / name).read_text(encoding="utf-8")
            self.assertNotIn("\t", text, f"{name}: YAML must not contain tabs")


if __name__ == "__main__":
    unittest.main()
