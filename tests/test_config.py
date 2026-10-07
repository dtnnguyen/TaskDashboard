"""The user config file, the `config` command and the installers' --data option.

Run with:  python3 -m unittest discover -s tests
"""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from taskdashboard import cli, config, menu  # noqa: E402

PATH_VARS = ("TASKDASHBOARD_DATA", "TASKDASHBOARD_PLAN", "TASKDASHBOARD_HISTORY", "TASKDASHBOARD_HTML")


class ConfigTest(unittest.TestCase):
    """Every test gets its own config file location and no TASKDASHBOARD_* variables,
    so a real ~/.config/taskdashboard/config.ini on the machine can't change the result."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.cfg = self.tmp / "cfg" / "config.ini"
        env = {k: v for k, v in os.environ.items() if k not in PATH_VARS}
        env["TASKDASHBOARD_CONFIG"] = str(self.cfg)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def write_cfg(self, text):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(text, encoding="utf-8")

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()


class PathOrderTest(ConfigTest):
    def test_default_without_a_config_file(self):
        self.assertEqual(config.settings(), {})
        self.assertEqual(config.data_dir(), config.PROJECT_ROOT / "data")
        self.assertEqual(config.plan_path(), config.PROJECT_ROOT / "data" / "PLAN_AND_PROGRESS.md")

    def test_data_folder_from_the_file_moves_every_file(self):
        self.write_cfg(f"[taskdashboard]\ndata = {self.tmp / 'mine'}\n")
        mine = self.tmp / "mine"
        self.assertEqual(config.data_dir(), mine)
        self.assertEqual(config.plan_path(), mine / "PLAN_AND_PROGRESS.md")
        self.assertEqual(config.history_path(), mine / "history.jsonl")
        self.assertEqual(config.html_path(), mine / "index.html")

    def test_history_and_page_follow_the_plan(self):
        self.write_cfg(f"[taskdashboard]\ndata = {self.tmp / 'mine'}\nplan = {self.tmp / 'other' / 'p.md'}\n")
        self.assertEqual(config.plan_path(), self.tmp / "other" / "p.md")
        self.assertEqual(config.history_path(), self.tmp / "other" / "history.jsonl")
        self.assertEqual(config.html_path(), self.tmp / "other" / "index.html")
        with mock.patch.dict(os.environ, {"TASKDASHBOARD_PLAN": str(self.tmp / "env" / "p.md")}):
            self.assertEqual(config.history_path(), self.tmp / "env" / "history.jsonl")

    def test_history_can_still_be_set_on_its_own(self):
        self.write_cfg(f"[taskdashboard]\nplan = {self.tmp / 'p.md'}\nhistory = {self.tmp / 'h' / 'h.jsonl'}\n")
        self.assertEqual(config.history_path(), self.tmp / "h" / "h.jsonl")
        self.assertEqual(config.html_path(), self.tmp / "index.html")

    def test_environment_variable_beats_the_file(self):
        self.write_cfg(f"[taskdashboard]\ndata = {self.tmp / 'from-file'}\n")
        with mock.patch.dict(os.environ, {"TASKDASHBOARD_DATA": str(self.tmp / "from-env")}):
            self.assertEqual(config.data_dir(), self.tmp / "from-env")
        with mock.patch.dict(os.environ, {"TASKDASHBOARD_PLAN": str(self.tmp / "p.md")}):
            self.assertEqual(config.plan_path(), self.tmp / "p.md")

    def test_tilde_and_relative_paths(self):
        self.write_cfg("[taskdashboard]\ndata = ~/td-somewhere\n")
        self.assertEqual(config.data_dir(), Path.home() / "td-somewhere")
        self.write_cfg("[taskdashboard]\ndata = ../mine\n")  # relative to the config file's folder
        self.assertEqual(config.data_dir(), self.tmp / "mine")

    def test_empty_value_and_missing_section_mean_default(self):
        self.write_cfg("[taskdashboard]\ndata =\n")
        self.assertEqual(config.data_dir(), config.PROJECT_ROOT / "data")
        self.write_cfg("[other]\nkey = value\n")
        self.assertEqual(config.settings(), {})

    def test_broken_file_raises_value_error(self):
        self.write_cfg("no section header\n")
        with self.assertRaisesRegex(ValueError, "cannot read config file"):
            config.plan_path()
        self.write_cfg("[taskdashboard]\ndat = /typo\n")
        with self.assertRaisesRegex(ValueError, "unknown setting.*dat"):
            config.data_dir()


class SaveTest(ConfigTest):
    def test_save_creates_the_file_with_an_absolute_path(self):
        written = config.save_data_dir(self.tmp / "a" / ".." / "mine")
        self.assertEqual(written, self.cfg)
        self.assertEqual(config.settings(), {"data": self.tmp / "mine"})
        self.assertIn("[taskdashboard]", self.cfg.read_text(encoding="utf-8"))

    def test_new_data_folder_drops_old_file_settings(self):
        # Nothing may be left pointing at the old place.
        self.write_cfg(f"[taskdashboard]\nplan = {self.tmp / 'p.md'}\nhistory = {self.tmp / 'h.jsonl'}\n")
        config.save_data_dir(self.tmp / "mine")
        self.assertEqual(config.settings(), {"data": self.tmp / "mine"})

    def test_plan_with_the_default_name_is_just_a_folder(self):
        config.save_plan_location(self.tmp / "mine" / "PLAN_AND_PROGRESS.md")
        self.assertEqual(config.settings(), {"data": self.tmp / "mine"})

    def test_plan_with_another_name(self):
        config.save_plan_location(self.tmp / "mine" / "goals.md")
        self.assertEqual(config.settings(), {"data": self.tmp / "mine", "plan": self.tmp / "mine" / "goals.md"})
        self.assertEqual(config.plan_path(), self.tmp / "mine" / "goals.md")
        self.assertEqual(config.history_path(), self.tmp / "mine" / "history.jsonl")

    def test_save_refuses_to_overwrite_a_broken_file(self):
        self.write_cfg("garbage\n")
        with self.assertRaisesRegex(ValueError, "Fix or delete it"):
            config.save_data_dir(self.tmp / "mine")
        self.assertEqual(self.cfg.read_text(encoding="utf-8"), "garbage\n")


class ConfigFileLocationTest(unittest.TestCase):
    # Kept when the environment is cleared: Path.home() needs HOME, or USERPROFILE on Windows.
    HOME_VARS = ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")

    def location(self, platform, env):
        keep = {k: os.environ[k] for k in self.HOME_VARS if k in os.environ}
        with mock.patch.object(sys, "platform", platform), mock.patch.dict(os.environ, {**keep, **env}, clear=True):
            return config.config_file()

    def test_per_platform(self):
        home = Path.home()
        self.assertEqual(self.location("darwin", {}), home / ".config" / "taskdashboard" / "config.ini")
        self.assertEqual(self.location("linux", {"XDG_CONFIG_HOME": "/xdg"}), Path("/xdg/taskdashboard/config.ini"))
        self.assertEqual(self.location("linux", {}), home / ".config" / "taskdashboard" / "config.ini")
        self.assertEqual(self.location("win32", {"APPDATA": "/appdata"}), Path("/appdata/taskdashboard/config.ini"))

    def test_macos_ignores_xdg(self):
        # SwiftBar starts the plugin without the shell's variables; the installer must agree with it.
        self.assertEqual(self.location("darwin", {"XDG_CONFIG_HOME": "/xdg"}),
                         Path.home() / ".config" / "taskdashboard" / "config.ini")

    def test_override_wins(self):
        self.assertEqual(self.location("linux", {"TASKDASHBOARD_CONFIG": "/x/c.ini", "XDG_CONFIG_HOME": "/xdg"}),
                         Path("/x/c.ini"))


class ConfigCommandTest(ConfigTest):
    def test_shows_paths_and_where_they_come_from(self):
        code, out, _ = self.run_cli("config")
        self.assertEqual(code, 0)
        self.assertIn("(not created)", out)
        self.assertIn("(default)", out)

    def test_data_option_then_init_creates_the_plan_there(self):
        mine = self.tmp / "mine"
        code, out, _ = self.run_cli("config", "--data", str(mine))
        self.assertEqual(code, 0)
        self.assertIn("(from config file)", out)
        code, out, _ = self.run_cli("init")
        self.assertEqual(code, 0)
        self.assertTrue((mine / "PLAN_AND_PROGRESS.md").exists())
        self.assertEqual(self.run_cli("build")[0], 0)
        self.assertTrue((mine / "index.html").exists())
        self.assertTrue((mine / "history.jsonl").exists())

    def test_warns_when_an_environment_variable_still_wins(self):
        with mock.patch.dict(os.environ, {"TASKDASHBOARD_DATA": str(self.tmp / "env")}):
            _, out, _ = self.run_cli("config", "--data", str(self.tmp / "mine"))
        self.assertIn("takes priority over the config file", out)

    def test_broken_file_is_a_clean_error(self):
        self.write_cfg("garbage\n")
        for args in (("build",), ("init",), ("config",), ("config", "--data", str(self.tmp))):
            code, out, err = self.run_cli(*args)
            self.assertEqual(code, 1, args)
            self.assertTrue(err.startswith("error: "), (args, err))
            self.assertNotIn("Traceback", err)


class MoveTest(ConfigTest):
    def setUp(self):
        super().setUp()
        self.old = self.tmp / "old"
        config.save_data_dir(self.old)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["init"])
            cli.main(["build"])  # creates history.jsonl and index.html beside the plan
        self.plan_text = (self.old / "PLAN_AND_PROGRESS.md").read_text(encoding="utf-8")

    def test_move_to_a_folder_takes_plan_and_history(self):
        new = self.tmp / "new"
        code, out, err = self.run_cli("config", "--data", str(new), "--move")
        self.assertEqual(code, 0, err)
        self.assertEqual((new / "PLAN_AND_PROGRESS.md").read_text(encoding="utf-8"), self.plan_text)
        self.assertTrue((new / "history.jsonl").exists())
        for name in ("PLAN_AND_PROGRESS.md", "history.jsonl", "index.html"):
            self.assertFalse((self.old / name).exists(), name)
        self.assertEqual(config.plan_path(), new / "PLAN_AND_PROGRESS.md")
        self.assertEqual(config.history_path(), new / "history.jsonl")

    def test_move_to_a_renamed_plan_keeps_history_beside_it(self):
        target = self.tmp / "dropbox" / "goals.md"
        code, _, err = self.run_cli("config", "--plan", str(target), "--move")
        self.assertEqual(code, 0, err)
        self.assertEqual(target.read_text(encoding="utf-8"), self.plan_text)
        self.assertTrue((target.parent / "history.jsonl").exists())
        self.assertEqual(config.history_path(), target.parent / "history.jsonl")
        self.assertEqual(self.run_cli("build")[0], 0)  # and everything still works from there

    def test_never_overwrites(self):
        new = self.tmp / "new"
        new.mkdir()
        (new / "history.jsonl").write_text("keep me\n", encoding="utf-8")
        code, _, err = self.run_cli("config", "--data", str(new), "--move")
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual((new / "history.jsonl").read_text(encoding="utf-8"), "keep me\n")
        self.assertTrue((self.old / "PLAN_AND_PROGRESS.md").exists())   # original untouched
        self.assertEqual(config.data_dir(), self.old)                    # config unchanged

    def test_refused_while_an_environment_variable_points_elsewhere(self):
        with mock.patch.dict(os.environ, {"TASKDASHBOARD_DATA": str(self.old)}):
            code, _, err = self.run_cli("config", "--data", str(self.tmp / "new"), "--move")
        self.assertEqual(code, 1)
        self.assertIn("Unset it", err)
        self.assertTrue((self.old / "PLAN_AND_PROGRESS.md").exists())

    def test_nothing_to_move(self):
        (self.old / "PLAN_AND_PROGRESS.md").unlink()
        code, _, err = self.run_cli("config", "--data", str(self.tmp / "new"), "--move")
        self.assertEqual(code, 1)
        self.assertIn("nothing to move", err)

    def test_moving_to_where_it_already_is_does_nothing(self):
        code, _, err = self.run_cli("config", "--data", str(self.old), "--move")
        self.assertEqual(code, 0, err)
        self.assertEqual((self.old / "PLAN_AND_PROGRESS.md").read_text(encoding="utf-8"), self.plan_text)

    def test_without_move_files_stay_and_init_is_suggested(self):
        code, out, _ = self.run_cli("config", "--data", str(self.tmp / "new"))
        self.assertEqual(code, 0)
        self.assertIn("run `init`", out)
        self.assertTrue((self.old / "PLAN_AND_PROGRESS.md").exists())

    def test_move_needs_a_destination(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["config", "--move"])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["config", "--data", "a", "--plan", "b"])


class MenuTest(ConfigTest):
    def test_broken_config_shows_an_error_and_edit_opens_the_config_file(self):
        self.write_cfg("garbage\n")
        snap = menu.snapshot()
        self.assertEqual(snap.label, "⚠")
        self.assertIn("config file", snap.items[0].label)
        self.assertEqual(snap.items[-1].open, str(self.cfg))

    def test_menu_follows_the_configured_folder(self):
        mine = self.tmp / "mine"
        config.save_data_dir(mine)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["init"])
        snap = menu.snapshot()
        self.assertIsNone(snap.error)
        edit = [i for i in snap.items if i.label.startswith("Edit")]
        self.assertEqual(edit[0].open, str(mine / "PLAN_AND_PROGRESS.md"))


@unittest.skipUnless(shutil.which("bash") and sys.platform != "win32", "needs bash")
class InstallerOptionsTest(unittest.TestCase):
    """Only the option checks, which exit before the installer changes anything."""

    def run_installer(self, script, *args):
        return subprocess.run(["bash", str(ROOT / script), *args], capture_output=True, text=True)

    def test_bad_options_are_refused_before_installing(self):
        for script in ("macos/install.sh", "linux/install.sh"):
            r = self.run_installer(script, "--bogus")
            self.assertEqual(r.returncode, 1, script)
            self.assertIn("Unknown option: --bogus", r.stdout)
            r = self.run_installer(script, "--data")
            self.assertEqual(r.returncode, 1, script)
            self.assertIn("--data needs a folder", r.stdout)

    def test_installers_document_the_data_option(self):
        for script in ("macos/install.sh", "linux/install.sh"):
            self.assertIn("taskdashboard config --data", (ROOT / script).read_text(encoding="utf-8"))
        self.assertIn("[string]$Data", (ROOT / "windows/install.ps1").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
