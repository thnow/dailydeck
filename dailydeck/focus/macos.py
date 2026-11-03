"""macOS backend (needs ``pyobjc-framework-Cocoa``). Not yet tested.

Window titles would require the Accessibility API, so only the frontmost
application is reported.
"""

from .base import FocusProvider, WindowInfo


class MacFocusProvider(FocusProvider):
    name = "macos"

    def __init__(self):
        from AppKit import NSWorkspace

        self._workspace = NSWorkspace.sharedWorkspace()

    def get(self) -> WindowInfo:
        app = self._workspace.frontmostApplication()
        if app is None:
            return WindowInfo()
        ids = tuple(i for i in (app.bundleIdentifier(), app.localizedName()) if i)
        return WindowInfo(
            ids=ids, name=app.localizedName() or "", pid=app.processIdentifier()
        )
