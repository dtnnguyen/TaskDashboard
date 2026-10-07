"""Cross-platform helpers, the shared tray menu, and the tray apps.

Run with:  python3 -m unittest discover -s tests
The Windows icon test runs only where Pillow is installed; the Linux indicator is
syntax-checked only, because GTK/AppIndicator exist only on Linux.
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from taskdashboard import history, menu, osutil  # noqa: E402
from taskdashboard.plan import parse  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "plan_sample.md"


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)


class FileLockTest(TempDirTest):
    @unittest.skipIf(os.name == "nt", "POSIX lock")
    def test_second_holder_waits(self):
        target = self.tmp / "history.jsonl"
        order = []

        def other():
            with osutil.file_lock(target):
                order.append("other")

        with osutil.file_lock(target):
            t = threading.Thread(target=other)
            t.start()
            time.sleep(0.2)
            order.append("first")  # 'other' must still be waiting
        t.join(2)
        self.assertEqual(order, ["first", "other"])
        self.assertTrue((self.tmp / ".history.jsonl.lock").exists())
        self.assertFalse(target.exists())  # the data file itself is never locked or created

    def test_windows_branch_uses_msvcrt(self):
        calls = []
        fake_msvcrt = SimpleNamespace(
            LK_LOCK=1, LK_UNLCK=0, locking=lambda fd, mode, n: calls.append((mode, n))
        )
        with mock.patch.object(osutil, "os", SimpleNamespace(name="nt")), \
                mock.patch.dict(sys.modules, {"msvcrt": fake_msvcrt}):
            with osutil.file_lock(self.tmp / "history.jsonl"):
                calls.append("inside")
        self.assertEqual(calls, [(1, 1), "inside", (0, 1)])


class OpenPathTest(unittest.TestCase):
    def test_per_platform(self):
        for platform, expected in (("darwin", ["open", "x.html"]), ("linux", ["xdg-open", "x.html"])):
            with mock.patch.object(osutil.sys, "platform", platform), \
                    mock.patch.object(osutil.subprocess, "Popen") as popen:
                osutil.open_path("x.html")
                popen.assert_called_once_with(expected)

    def test_windows_startfile(self):
        fake_os = SimpleNamespace(startfile=mock.Mock())
        with mock.patch.object(osutil.sys, "platform", "win32"), mock.patch.object(osutil, "os", fake_os):
            osutil.open_path(Path("x.html"))
        fake_os.startfile.assert_called_once_with("x.html")

    def test_file_url(self):
        url = osutil.file_url(Path("/tmp/my page.html"), "timeline")
        self.assertTrue(url.startswith("file:///"))
        self.assertTrue(url.endswith("my%20page.html#timeline"))


class LineEndingTest(TempDirTest):
    def test_history_and_page_use_lf(self):
        from taskdashboard.build import refresh

        plan_path = self.tmp / "plan.md"
        shutil.copy(FIXTURE, plan_path)
        refresh(parse(plan_path, date(2026, 10, 2)), self.tmp / "index.html", self.tmp / "history.jsonl")
        self.assertNotIn(b"\r", (self.tmp / "history.jsonl").read_bytes())
        self.assertNotIn(b"\r", (self.tmp / "index.html").read_bytes())


class MenuTest(TempDirTest):
    def setUp(self):
        super().setUp()
        self.plan_path = self.tmp / "plan.md"
        shutil.copy(FIXTURE, self.plan_path)
        env = {
            "TASKDASHBOARD_PLAN": str(self.plan_path),
            "TASKDASHBOARD_HISTORY": str(self.tmp / "history.jsonl"),
            "TASKDASHBOARD_HTML": str(self.tmp / "index.html"),
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_snapshot(self):
        snap = menu.snapshot()
        self.assertIsNone(snap.error)
        labels = [i.label for i in snap.items]
        self.assertTrue(any(l.startswith("🟢 Alpha") and "50% (2/4)" in l for l in labels))
        self.assertTrue(any("Overdue: Third step" in l for l in labels))
        self.assertIn("TaskDashboard:", snap.tooltip)
        defaults = [i for i in snap.items if i.default]
        self.assertEqual([i.label for i in defaults], ["Open dashboard page"])
        self.assertTrue((self.tmp / "index.html").exists())  # snapshot also rebuilds the page
        self.assertTrue((self.tmp / "history.jsonl").exists())  # ...and records ticks

    def test_goal_labels_are_plain(self):
        alpha = next(i for i in menu.snapshot().items if i.label.startswith("🟢 Alpha"))
        fourth = next(c.label for c in alpha.children if "Fourth" in c.label)
        self.assertNotIn("`", fourth)
        self.assertNotIn("**", fourth)

    def test_broken_plan_shows_error_instead_of_crashing(self):
        self.plan_path.unlink()
        snap = menu.snapshot()
        self.assertEqual(snap.label, "⚠")
        self.assertIsNotNone(snap.error)
        self.assertTrue(snap.items[0].label.startswith("Error:"))

    def test_long_labels_truncated(self):
        self.assertEqual(len(menu.plain("x" * 200)), menu.MAX_LABEL)


class TrayScriptsTest(unittest.TestCase):
    def test_scripts_compile(self):
        for script in ("linux/taskdashboard_indicator.py", "windows/taskdashboard_tray.py", "macos/taskdashboard.5m.py"):
            path = ROOT / script
            compile(path.read_text(encoding="utf-8"), str(path), "exec")  # SyntaxError fails the test


class SwiftBarPluginTest(MenuTest):
    def test_every_menu_line_has_an_action(self):
        """macOS greys out menu items with no action, so every line needs href/bash/refresh."""
        import subprocess

        out = subprocess.run(
            [sys.executable, str(ROOT / "macos" / "taskdashboard.5m.py")],
            capture_output=True, text=True, encoding="utf-8", check=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},  # Windows pipes default to cp1252
        ).stdout.splitlines()
        self.assertTrue(out[0].startswith("🎯 40%"))
        items = [l for l in out[1:] if l.strip() != "---"]
        self.assertTrue(items)
        for line in items:
            self.assertRegex(line, r"\| .*(href=|bash=|refresh=)", line)
        self.assertTrue(any("#project-alpha" in l for l in out))


class LinuxIndicatorTest(MenuTest):
    """Runs the Ubuntu indicator against stand-in gi/GTK modules (the real ones exist only on Linux)."""

    def test_builds_label_and_menu(self):
        gtk = mock.MagicMock()
        appindicator = mock.MagicMock()
        glib = mock.MagicMock()
        repository = SimpleNamespace(AyatanaAppIndicator3=appindicator, Gtk=gtk, GLib=glib)
        fake_gi = SimpleNamespace(require_version=lambda *a: None, repository=repository)
        modules = {
            "gi": fake_gi,
            "gi.repository": repository,
            "gi.repository.AyatanaAppIndicator3": appindicator,
        }
        sys.modules.pop("taskdashboard_indicator", None)
        sys.path.insert(0, str(ROOT / "linux"))
        try:
            with mock.patch.dict(sys.modules, modules):
                import taskdashboard_indicator as linux

                linux.Indicator()
        finally:
            sys.path.remove(str(ROOT / "linux"))
            sys.modules.pop("taskdashboard_indicator", None)

        ind = appindicator.Indicator.new.return_value
        ind.set_label.assert_called_with("40%", "100%")
        ind.set_menu.assert_called_once()
        glib.timeout_add_seconds.assert_called_once()
        labels = [c.kwargs.get("label") for c in gtk.MenuItem.call_args_list]
        self.assertIn("Open dashboard page", labels)
        self.assertIn("Quit", labels)
        self.assertTrue(any(l and l.startswith("🟢 Alpha") for l in labels))


try:
    import PIL  # noqa: F401

    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


@unittest.skipUnless(HAVE_PIL, "Pillow not installed (only needed for the Windows tray)")
class WindowsIconTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "windows"))
        import taskdashboard_tray

        self.tray = taskdashboard_tray

    def test_icon_variants(self):
        for snap in (
            menu.Snapshot(percent=13, label="13%", tooltip="", items=[]),
            menu.Snapshot(percent=100, label="100%", tooltip="", items=[]),
            menu.Snapshot(percent=None, label="—", tooltip="", items=[]),
            menu.Snapshot(percent=None, label="⚠", tooltip="", items=[], error="boom"),
        ):
            img = self.tray.icon_image(snap)
            self.assertEqual(img.size, (64, 64))
            self.assertEqual(img.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
