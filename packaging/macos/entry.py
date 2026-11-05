"""Entry point of the macOS app bundle (PyInstaller).

Started from Finder or a LaunchAgent without arguments, so it defaults to the
menu bar app. Logs go to ~/Library/Logs/Daily Deck.log since an app bundle
has no terminal.
"""

import logging
import os
import sys
from pathlib import Path


def main() -> int:
    # use the libhidapi.dylib inside the bundle, not one that may or may not be installed
    bundle_libs = getattr(sys, "_MEIPASS", None)
    if bundle_libs:
        os.environ["DYLD_LIBRARY_PATH"] = bundle_libs  # read by ctypes.util.find_library

    args = [a for a in sys.argv[1:] if not a.startswith("-psn_")]  # Finder's process serial number
    if not args:
        args = ["--tray"]
    sys.argv[1:] = args

    log_file = Path.home() / "Library" / "Logs" / "Daily Deck.log"
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=log_file,
            level=logging.DEBUG if "-v" in args or "--verbose" in args else logging.INFO,
            format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        )
    except OSError:
        pass

    from dailydeck.__main__ import main as dailydeck_main

    return dailydeck_main()


if __name__ == "__main__":
    raise SystemExit(main())
