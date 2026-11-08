"""Entry point of the Windows build (PyInstaller).

``Daily Deck.exe`` (no console) starts the tray app when run without arguments
and logs to %LOCALAPPDATA%\\Daily Deck\\dailydeck.log. ``dailydeck.exe`` (console)
is the command line tool: ``dailydeck --print-focus``, ``--dry-run`` …
"""

import ctypes
import logging
import os
import sys
from pathlib import Path

APP_ID = "io.github.thnow.dailydeck"  # also the AppUserModelID of the start menu shortcut


def main() -> int:
    console = sys.stdout is not None
    args = sys.argv[1:]
    if not console:
        if not args:
            args = ["--tray"]
            sys.argv[1:] = args
        # taskbar grouping and notifications under "Daily Deck", not "Python"
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
        log_file = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Daily Deck" / "dailydeck.log"
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            logging.basicConfig(
                handlers=[logging.FileHandler(log_file, mode="w", encoding="utf-8")],
                level=logging.DEBUG if "-v" in args or "--verbose" in args else logging.INFO,
                format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            )
        except OSError:
            pass

    from dailydeck.__main__ import main as dailydeck_main

    return dailydeck_main()


if __name__ == "__main__":
    raise SystemExit(main())
