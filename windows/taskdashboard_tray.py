"""Windows tray icon: the overall % drawn into the icon, details on hover and in the menu.

Windows tray icons can't show text next to them, so the number is drawn into a
small progress ring. Left-click opens the dashboard page; right-click shows the menu.
Refreshes every 5 minutes: records new ticks in history.jsonl and rebuilds index.html.

Needs:  py -m pip install -r windows\\requirements.txt
Try it: py windows\\taskdashboard_tray.py      (pythonw.exe runs it without a console window)
Start at login: windows\\install.ps1
"""

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from taskdashboard.menu import SEPARATOR, MenuItem, Snapshot, snapshot  # noqa: E402
from taskdashboard.osutil import open_path  # noqa: E402

REFRESH_SECONDS = 5 * 60
SIZE = 64  # drawn large, Windows scales it down to 16–32 px
BACKGROUND = (38, 38, 40, 255)  # a solid tile reads on both light and dark taskbars
TRACK = (90, 90, 95, 255)
FILL = (79, 185, 138, 255)
WARN = (232, 110, 60, 255)
TEXT = (255, 255, 255, 255)
# Windows names first; the others only help when previewing the icon on macOS/Linux.
FONTS = ["segoeuib.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"]


def _font(size: int):
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)  # Pillow ≥ 10.1
    except TypeError:
        return ImageFont.load_default()


def _centered_text(draw, text: str, size: int, area_bottom: int) -> None:
    font = _font(size)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = (SIZE - (right - left)) / 2 - left
    y = (area_bottom - (bottom - top)) / 2 - top
    draw.text((x, y), text, font=font, fill=TEXT)


def icon_image(snap: Snapshot) -> Image.Image:
    """Dark rounded tile: the % as a big number, a progress bar along the bottom.

    100% shows a check mark, no goals shows '-', an error shows '!' on orange.
    """
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=12, fill=WARN if snap.error else BACKGROUND)

    if snap.error:
        _centered_text(draw, "!", 52, SIZE)
        return img

    bar_top, bar_bottom, margin = SIZE - 15, SIZE - 6, 7
    draw.rounded_rectangle((margin, bar_top, SIZE - 1 - margin, bar_bottom), radius=4, fill=TRACK)
    pct = snap.percent
    if pct:
        right = margin + (SIZE - 1 - 2 * margin) * pct / 100
        draw.rounded_rectangle((margin, bar_top, max(right, margin + 8), bar_bottom), radius=4, fill=FILL)

    if pct == 100:
        draw.line([(16, 26), (27, 37), (48, 14)], fill=FILL, width=8, joint="curve")
    else:
        text = "-" if pct is None else str(pct)  # no "%" sign: it would not fit at 16 px
        _centered_text(draw, text, 40, bar_top)
    return img


def _opener(target):
    # pystray counts parameters, defaults included, and accepts at most (icon, item)
    def action(icon, item):
        open_path(target)

    return action


def to_pystray(items):
    import pystray

    out = []
    for item in items:
        if item is SEPARATOR:
            out.append(pystray.Menu.SEPARATOR)
        elif item.children:
            out.append(pystray.MenuItem(item.label, pystray.Menu(*to_pystray(item.children))))
        elif item.open:
            out.append(pystray.MenuItem(item.label, _opener(item.open), default=item.default))
        else:
            out.append(pystray.MenuItem(item.label, None, enabled=False))
    return out


class Tray:
    def __init__(self):
        import pystray

        self.pystray = pystray
        self.stop = threading.Event()
        self.snap = snapshot()
        self.icon = pystray.Icon("taskdashboard", icon_image(self.snap), self._tooltip(), menu=self._menu())

    def _tooltip(self) -> str:
        return self.snap.tooltip[:127]  # Windows limit for tray tooltips

    def _menu(self):
        # A Menu built from a function is re-evaluated by update_menu(), so it follows self.snap.
        return self.pystray.Menu(lambda: self._items())

    def _items(self):
        pystray = self.pystray
        return [
            *to_pystray(self.snap.items),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Refresh now", lambda *_: self.refresh()),
            pystray.MenuItem("Quit", lambda *_: self.quit()),
        ]

    def refresh(self):
        self.snap = snapshot()
        self.icon.icon = icon_image(self.snap)
        self.icon.title = self._tooltip()
        self.icon.update_menu()

    def _loop(self, icon):
        icon.visible = True
        while not self.stop.wait(REFRESH_SECONDS):
            self.refresh()

    def quit(self):
        self.stop.set()
        self.icon.stop()

    def run(self):
        self.icon.run(setup=self._loop)


if __name__ == "__main__":
    if "--preview" in sys.argv:  # draw the icon to a PNG without starting the tray (for checking)
        out = Path(sys.argv[-1]) if sys.argv[-1].endswith(".png") else ROOT / "tray_preview.png"
        icon_image(snapshot()).save(out)
        print(f"Wrote {out}")
    else:
        Tray().run()
