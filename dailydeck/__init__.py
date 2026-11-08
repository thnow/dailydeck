"""Daily Deck: the Stream Deck shows the keyboard shortcuts of the focused window."""

import os
import sys

__version__ = "0.2.0"

if sys.platform == "win32":
    # python-elgato-streamdeck finds hidapi.dll via ctypes.util.find_library, which searches PATH.
    # The DLL is not part of the repository; scripts/fetch-hidapi.ps1 puts it here.
    _HIDAPI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "win32")
    if os.path.isfile(os.path.join(_HIDAPI_DIR, "hidapi.dll")):
        os.environ["PATH"] = _HIDAPI_DIR + os.pathsep + os.environ.get("PATH", "")
