import logging
import os
import sys
import time

from .base import FocusProvider, FocusUnavailable, WindowInfo

log = logging.getLogger(__name__)

__all__ = ["FocusProvider", "FocusUnavailable", "WindowInfo", "create_focus_provider"]


class _FallbackFocusProvider(FocusProvider):
    """Uses ``primary`` when it answers, otherwise ``fallback``.

    The primary backend is retried periodically, so e.g. enabling the GNOME
    extension takes effect without restarting the daemon.
    """

    RETRY_SECONDS = 10

    def __init__(self, primary_factory, fallback: FocusProvider):
        self._primary_factory = primary_factory
        self._primary = None
        self._fallback = fallback
        self._next_try = 0.0
        self._warned = False

    @property
    def name(self):
        return self._primary.name if self._primary else f"{self._fallback.name} (fallback)"

    def get(self) -> WindowInfo:
        now = time.monotonic()
        if self._primary is None and now >= self._next_try:
            try:
                self._primary = self._primary_factory()
            except Exception as e:  # noqa: BLE001 - any failure means "not available"
                log.debug("primary focus backend unavailable: %s", e)
            self._next_try = now + self.RETRY_SECONDS
        if self._primary is not None:
            try:
                info = self._primary.get()
                if self._warned:
                    log.info("focus backend %s available again", self._primary.name)
                    self._warned = False
                return info
            except FocusUnavailable as e:
                if not self._warned:
                    log.warning("%s; falling back to %s", e, self._fallback.name)
                    self._warned = True
                self._next_try = now + self.RETRY_SECONDS
                self._primary.close()
                self._primary = None
        return self._fallback.get()


def create_focus_provider(name: str = "auto") -> FocusProvider:
    if name == "auto":
        if sys.platform == "win32":
            name = "windows"
        elif sys.platform == "darwin":
            name = "macos"
        elif "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            name = "gnome"
        else:
            name = "x11"

    if name == "gnome":
        from .gnome import GnomeFocusProvider
        from .x11 import X11FocusProvider

        return _FallbackFocusProvider(GnomeFocusProvider, X11FocusProvider())
    if name == "x11":
        from .x11 import X11FocusProvider

        return X11FocusProvider()
    if name == "windows":
        from .windows import WindowsFocusProvider

        return WindowsFocusProvider()
    if name == "macos":
        from .macos import MacFocusProvider

        return MacFocusProvider()
    raise ValueError(f"unknown focus backend: {name}")
