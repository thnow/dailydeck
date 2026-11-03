# Starts the Daily Deck tray app; used for autostart on all platforms
# (.pyw: no console window on Windows).
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dailydeck.tray import main  # noqa: E402

raise SystemExit(main())
