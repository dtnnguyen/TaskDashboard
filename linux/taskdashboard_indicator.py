#!/usr/bin/env python3
"""Ubuntu top-bar icon: shows '13%' next to a target icon, with a menu of projects and goals.

Uses AppIndicator, which Ubuntu's built-in "Ubuntu AppIndicators" extension shows in
the top bar. Refreshes every 5 minutes: records new ticks in history.jsonl and
rebuilds index.html, like the macOS SwiftBar plugin.

Needs (Ubuntu Desktop usually has the first one already):
    sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1

Run once to try it:   python3 linux/taskdashboard_indicator.py
Start at login:       linux/install.sh
"""

import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
except (ValueError, ImportError):  # older Ubuntu releases ship the original library
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import GLib, Gtk  # noqa: E402

from taskdashboard.menu import SEPARATOR, MenuItem, snapshot  # noqa: E402
from taskdashboard.osutil import open_path  # noqa: E402

REFRESH_SECONDS = 5 * 60
ICON = ROOT / "assets" / "taskdashboard.svg"


class Indicator:
    def __init__(self):
        self.ind = AppIndicator.Indicator.new(
            "taskdashboard", str(ICON), AppIndicator.IndicatorCategory.APPLICATION_STATUS
        )
        self.ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.ind.set_title("TaskDashboard")
        self.refresh()
        GLib.timeout_add_seconds(REFRESH_SECONDS, self.refresh)

    def refresh(self, *_):
        snap = snapshot()
        self.ind.set_label(snap.label, "100%")  # second argument reserves width so the bar doesn't jump

        menu = Gtk.Menu()
        for item in snap.items:
            menu.append(self._item(item))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(self._action("Refresh now", self.refresh))
        menu.append(self._action("Quit", lambda *_: Gtk.main_quit()))
        menu.show_all()
        self.ind.set_menu(menu)
        return True  # keep the GLib timer running

    def _item(self, item: MenuItem) -> Gtk.MenuItem:
        if item is SEPARATOR:
            return Gtk.SeparatorMenuItem()
        widget = Gtk.MenuItem(label=item.label)
        if item.children:
            sub = Gtk.Menu()
            for child in item.children:
                sub.append(self._item(child))
            widget.set_submenu(sub)
        elif item.open:
            widget.connect("activate", lambda _w, target=item.open: open_path(target))
        return widget

    @staticmethod
    def _action(label, callback) -> Gtk.MenuItem:
        widget = Gtk.MenuItem(label=label)
        widget.connect("activate", callback)
        return widget


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Ctrl+C quits when run from a terminal
    Indicator()
    Gtk.main()


if __name__ == "__main__":
    main()
