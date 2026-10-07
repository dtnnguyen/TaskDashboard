"""Paths and URLs. Standard library only.

Personal data lives in a data folder (the plan, history.jsonl and the generated
index.html), so the code can be shared without it. Each path is chosen in this order:

1. Environment variable: TASKDASHBOARD_DATA for the folder, or TASKDASHBOARD_PLAN /
   _HISTORY / _HTML for single files.
2. The user config file (see config_file()), written by `taskdashboard config --data DIR`
   or `--plan FILE` and by the installers' --data option. Unlike environment variables, it
   also reaches the menu bar / tray icon, which the desktop starts without your shell's settings.
3. data/ inside this project.

history.jsonl and index.html default to the plan's folder, wherever the plan is.

The command line's --plan flag overrides all of these for one command (see cli.py).
"""

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # TaskDashboard/

SECTION = "taskdashboard"
KEYS = ("data", "plan", "history", "html")
PLAN_NAME = "PLAN_AND_PROGRESS.md"
HISTORY_NAME = "history.jsonl"
HTML_NAME = "index.html"


def config_file() -> Path:
    """The per-user config file. TASKDASHBOARD_CONFIG points somewhere else (tests use it).

    macOS:   ~/.config/taskdashboard/config.ini
    Linux:   $XDG_CONFIG_HOME/taskdashboard/config.ini (default ~/.config/...)
    Windows: %APPDATA%\\taskdashboard\\config.ini

    macOS ignores XDG_CONFIG_HOME on purpose: SwiftBar starts the plugin without your
    shell's variables, so honouring it would split the installer and the icon.
    """
    if os.environ.get("TASKDASHBOARD_CONFIG"):
        return Path(os.environ["TASKDASHBOARD_CONFIG"]).expanduser()
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        base = Path(os.environ["APPDATA"])
    elif sys.platform.startswith("linux") and os.environ.get("XDG_CONFIG_HOME"):
        base = Path(os.environ["XDG_CONFIG_HOME"])
    else:
        base = Path.home() / ".config"
    return base / "taskdashboard" / "config.ini"


def settings() -> dict[str, Path]:
    """Paths set in the config file. A missing file means none; a broken one raises ValueError.

    Relative paths are taken relative to the config file's folder, and ~ is expanded.
    """
    path = config_file()
    if not path.exists():
        return {}
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as e:
        raise ValueError(f"cannot read config file {path}: {str(e).splitlines()[0]}") from e
    if not parser.has_section(SECTION):
        return {}
    unknown = sorted(set(parser[SECTION]) - set(KEYS))
    if unknown:
        raise ValueError(f"unknown setting(s) {', '.join(unknown)} in {path} (expected: {', '.join(KEYS)})")
    return {key: (path.parent / Path(value.strip()).expanduser()).resolve()
            for key, value in parser[SECTION].items() if value.strip()}


def _pick(env: str, key: str, default: Path) -> Path:
    if os.environ.get(env):
        return Path(os.environ[env]).expanduser()
    return settings().get(key, default)


def data_dir() -> Path:
    return _pick("TASKDASHBOARD_DATA", "data", PROJECT_ROOT / "data")


def plan_path() -> Path:
    return _pick("TASKDASHBOARD_PLAN", "plan", data_dir() / PLAN_NAME)


# history.jsonl and index.html sit next to the plan unless set on their own, so moving the
# plan (by folder, by file, by variable or in the config file) always takes its history along.
def history_path() -> Path:
    return _pick("TASKDASHBOARD_HISTORY", "history", plan_path().parent / HISTORY_NAME)


def html_path() -> Path:
    return _pick("TASKDASHBOARD_HTML", "html", plan_path().parent / HTML_NAME)


def save_plan_location(plan: Path) -> Path:
    """Point the config file at a plan, with history.jsonl and index.html beside it. Returns the file.

    Writes `data = <the plan's folder>`, plus `plan = <file>` only when the file isn't named
    PLAN_AND_PROGRESS.md. Any plan / history / html entries are dropped, so nothing is left
    pointing at the old place.
    """
    plan = Path(plan).expanduser().resolve()
    path = config_file()
    parser = configparser.ConfigParser(interpolation=None)
    if path.exists():
        try:
            parser.read(path, encoding="utf-8")
        except configparser.Error as e:  # don't overwrite a file the user may want to fix
            raise ValueError(f"cannot update config file {path}: {str(e).splitlines()[0]} "
                             f"Fix or delete it, then try again.") from e
    if not parser.has_section(SECTION):
        parser.add_section(SECTION)
    for key in ("plan", "history", "html"):
        parser.remove_option(SECTION, key)
    parser[SECTION]["data"] = str(plan.parent)
    if plan.name != PLAN_NAME:
        parser[SECTION]["plan"] = str(plan)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# TaskDashboard settings. Paths may use ~; relative paths are relative to this file.\n")
        f.write("# Keys: data (folder for the plan; history.jsonl and index.html go next to the plan),\n")
        f.write("# plan (a plan file with another name), history / html (only to put those elsewhere).\n")
        parser.write(f)
    return path


def save_data_dir(folder: Path) -> Path:
    """Use <folder>/PLAN_AND_PROGRESS.md, with its history and page beside it. Returns the file."""
    return save_plan_location(Path(folder).expanduser() / PLAN_NAME)
