"""Windows backend (Win32 API via ctypes). Not yet tested on real hardware."""

import ctypes
import os
from ctypes import wintypes

from .base import FocusProvider, WindowInfo

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class WindowsFocusProvider(FocusProvider):
    name = "windows"

    def __init__(self):
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    def get(self) -> WindowInfo:
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return WindowInfo()
        length = self._user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = self._exe_name(pid.value)
        ids = (exe, exe.removesuffix(".exe")) if exe else ()
        return WindowInfo(ids=ids, title=buf.value, name=ids[-1] if ids else "", pid=pid.value)

    def _exe_name(self, pid: int) -> str:
        handle = self._kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if self._kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
            return ""
        finally:
            self._kernel32.CloseHandle(handle)
