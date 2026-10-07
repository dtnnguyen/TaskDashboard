#!/usr/bin/env python3
"""Build one release archive per platform into dist/.

    python3 scripts/package.py                   # all platforms
    python3 scripts/package.py --check-tag v0.2.0  # also fail unless the tag matches the version

Only files on an explicit list go in, so personal data (data/, history.jsonl, your plan,
the generated index.html) can never be shipped. Each archive is also checked after it is
built. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
import tarfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

COMMON = [
    "README.md",
    "architecture.md",
    "pyproject.toml",
    "assets/taskdashboard.svg",
    "examples/PLAN_AND_PROGRESS.example.md",
    "examples/history.example.jsonl",
    "src/taskdashboard/*.py",
]
OPTIONAL = ["LICENSE"]  # included when present
PLATFORMS = {
    "macos": {"files": ["macos/*", "td"], "format": "zip"},
    "linux": {"files": ["linux/*", "td"], "format": "tar.gz"},
    "windows": {"files": ["windows/*", "td.cmd"], "format": "zip"},
}
EXECUTABLE = {"td", "macos/install.sh", "macos/taskdashboard.5m.py", "linux/install.sh", "linux/taskdashboard_indicator.py"}
FORBIDDEN = re.compile(r"(^|/)(data/|history\.jsonl$|index\.html$|PLAN_AND_PROGRESS\.md$|\.)")

INSTALL = {
    "macos": """TaskDashboard {version} for macOS

1. Install SwiftBar:   brew install --cask swiftbar
2. In Terminal, in this folder:
       bash macos/install.sh --data ~/Documents/TaskDashboard
   It creates PLAN_AND_PROGRESS.md in that folder from an example and puts 🎯 in
   the menu bar. Keeping your data outside this folder means a newer release can
   replace this folder without losing anything. (Without --data it uses data/ here.)
3. Edit the plan (menu bar → Edit plan) to add your own projects.

See where your files are:  ./td config      (move them: ./td config --data DIR --move)
Uninstall: bash macos/install.sh --remove (your data folder is kept). More in README.md.
""",
    "linux": """TaskDashboard {version} for Ubuntu

1. sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1
2. In this folder:
       bash linux/install.sh --data ~/Documents/TaskDashboard
   It creates PLAN_AND_PROGRESS.md in that folder from an example, adds the icon to
   the top bar and starts it at every login. Keeping your data outside this folder
   means a newer release can replace this folder without losing anything.
   (Without --data it uses data/ here.)
3. Edit the plan (top bar → Edit plan) to add your own projects.

See where your files are:  ./td config      (move them: ./td config --data DIR --move)
Uninstall: bash linux/install.sh --remove (your data folder is kept). More in README.md.
""",
    "windows": """TaskDashboard {version} for Windows

1. Install Python 3:   winget install Python.Python.3.13
2. In PowerShell, in this folder:
       powershell -ExecutionPolicy Bypass -File windows\\install.ps1 -Data "$HOME\\Documents\\TaskDashboard"
   It creates PLAN_AND_PROGRESS.md in that folder from an example, adds the tray icon
   and starts it at every login. Keeping your data outside this folder means a newer
   release can replace this folder without losing anything. (Without -Data it uses
   data\\ here.)
3. Edit the plan (tray icon → Edit plan) to add your own projects.

See where your files are:  .\\td config      (move them: .\\td config --data DIR --move)
Uninstall: powershell -ExecutionPolicy Bypass -File windows\\install.ps1 -Remove
(your data folder is kept). More in README.md.
""",
}


def version() -> str:
    init = (ROOT / "src/taskdashboard/__init__.py").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    v1 = re.search(r'__version__ = "([^"]+)"', init).group(1)
    v2 = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    if v1 != v2:
        sys.exit(f"Version mismatch: __init__.py has {v1}, pyproject.toml has {v2}")
    return v1


def collect(platform: str) -> list[str]:
    files: set[str] = set()
    for pattern in COMMON + PLATFORMS[platform]["files"]:
        matches = [p for p in ROOT.glob(pattern) if p.is_file() and "__pycache__" not in p.parts]
        if not matches:
            sys.exit(f"Nothing matches {pattern}")
        files.update(p.relative_to(ROOT).as_posix() for p in matches)
    files.update(f for f in OPTIONAL if (ROOT / f).is_file())
    return sorted(files)


def check(names: list[str]) -> None:
    """Refuse personal data and hidden files (lock files, .DS_Store) in an archive."""
    bad = [n for n in names if FORBIDDEN.search(n.split("/", 1)[1])]
    if bad:
        sys.exit(f"Refusing to package: {bad}")


def build(platform: str, ver: str, out: Path) -> Path:
    prefix = f"taskdashboard-{ver}-{platform}"
    files = collect(platform)
    entries = [(f"{prefix}/{f}", (ROOT / f).read_bytes(), 0o755 if f in EXECUTABLE else 0o644) for f in files]
    entries.append((f"{prefix}/INSTALL.txt", INSTALL[platform].format(version=ver).encode(), 0o644))
    check([name for name, _, _ in entries])

    out.mkdir(parents=True, exist_ok=True)
    mtime = time.time()
    if PLATFORMS[platform]["format"] == "zip":
        path = out / f"{prefix}.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data, mode in entries:
                info = zipfile.ZipInfo(name, time.localtime(mtime)[:6])
                info.create_system = 3  # Unix, so macOS keeps the executable bits
                info.external_attr = (0o100000 | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, data)
    else:
        path = out / f"{prefix}.tar.gz"
        with tarfile.open(path, "w:gz") as t:
            for name, data, mode in entries:
                info = tarfile.TarInfo(name)
                info.size, info.mode, info.mtime = len(data), mode, int(mtime)
                t.addfile(info, io.BytesIO(data))
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--platform", choices=[*PLATFORMS, "all"], default="all")
    parser.add_argument("--check-tag", help="git tag being released, e.g. v0.2.0")
    args = parser.parse_args(argv)

    ver = version()
    if args.check_tag and args.check_tag.lstrip("v") != ver:
        sys.exit(f"Tag {args.check_tag} does not match version {ver} (src/taskdashboard/__init__.py)")

    platforms = list(PLATFORMS) if args.platform == "all" else [args.platform]
    paths = [build(p, ver, args.out) for p in platforms]
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in paths)
    (args.out / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    for p in paths:
        print(f"{p}  ({p.stat().st_size // 1024} KB)")
    print(args.out / "SHA256SUMS.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
