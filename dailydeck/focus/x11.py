"""X11 backend using ``xprop``.

Under a Wayland session this only sees XWayland windows, so it is used as a
fallback there.
"""

import re
import subprocess

from .base import FocusProvider, FocusUnavailable, WindowInfo


def _xprop(*args: str) -> str:
    try:
        return subprocess.run(
            ["xprop", *args], capture_output=True, text=True, timeout=1, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError) as e:
        raise FocusUnavailable(f"xprop failed: {e}") from e


class X11FocusProvider(FocusProvider):
    name = "x11"

    def get(self) -> WindowInfo:
        root = _xprop("-root", "_NET_ACTIVE_WINDOW")
        m = re.search(r"window id # (0x[0-9a-fA-F]+)", root)
        if not m or int(m.group(1), 16) == 0:
            return WindowInfo()
        props = _xprop("-id", m.group(1), "WM_CLASS", "_NET_WM_NAME", "_NET_WM_PID")
        ids = tuple(re.findall(r'"([^"]*)"', _line(props, "WM_CLASS")))
        title_m = re.search(r'=\s*"(.*)"', _line(props, "_NET_WM_NAME"))
        pid_m = re.search(r"=\s*(\d+)", _line(props, "_NET_WM_PID"))
        # WM_CLASS is (instance, class); report class first
        ids = tuple(reversed(ids))
        return WindowInfo(
            ids=ids,
            title=title_m.group(1) if title_m else "",
            name=ids[0] if ids else "",
            pid=int(pid_m.group(1)) if pid_m else 0,
        )


def _line(text: str, prop: str) -> str:
    for line in text.splitlines():
        if line.startswith(prop):
            return line
    return ""
