"""The few things that differ between macOS, Linux and Windows. Standard library only."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Exclusive lock across processes (menu bar app, CLI), held for the `with` block.

    Locks a hidden sidecar file next to `path`, so the data file itself never
    carries a Windows mandatory lock that could block git or an editor.
    """
    lock_path = path.parent / f".{path.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as f:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)  # retries for ~10 s, then raises OSError
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def open_path(target: Path | str) -> None:
    """Open a file or URL with the default app, without waiting for it."""
    target = str(target)
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]  # Windows only
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


def file_url(path: Path, fragment: str = "") -> str:
    """file:// URL that works on every OS (drive letters, spaces)."""
    url = Path(path).resolve().as_uri()
    return f"{url}#{fragment}" if fragment else url
