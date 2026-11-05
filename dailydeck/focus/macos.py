"""macOS backend (needs ``pyobjc-framework-Cocoa``).

Window titles would require the Accessibility API, so only the frontmost
application is reported.

``frontmostApplication`` is a cached property that AppKit refreshes from
workspace notifications delivered on the main run loop. With ``--tray`` Qt
runs that loop and the daemon thread just reads the value; without Qt the
daemon polls on the main thread, so ``get`` processes pending run loop events
itself – otherwise the value would stay frozen at the start-up application.
"""

import threading

from .base import FocusProvider, WindowInfo


class MacFocusProvider(FocusProvider):
    name = "macos"

    def __init__(self):
        from AppKit import NSWorkspace
        from Foundation import NSDate, NSRunLoop

        self._workspace = NSWorkspace.sharedWorkspace()
        self._run_loop = NSRunLoop.mainRunLoop()
        self._NSDate = NSDate

    def get(self) -> WindowInfo:
        if threading.current_thread() is threading.main_thread():
            self._run_loop.runUntilDate_(self._NSDate.dateWithTimeIntervalSinceNow_(0.01))
        app = self._workspace.frontmostApplication()
        if app is None:
            return WindowInfo()
        ids = tuple(i for i in (app.bundleIdentifier(), app.localizedName()) if i)
        return WindowInfo(
            ids=ids, name=app.localizedName() or "", pid=app.processIdentifier()
        )
