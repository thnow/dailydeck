"""Windows backend (Win32 API via ctypes): exe name and title of the foreground window."""

import ctypes
import os
from ctypes import wintypes

from .base import FocusProvider, WindowInfo

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# hosts the windows of UWP / Store apps; the app itself owns a child window
FRAME_HOST = "applicationframehost.exe"

_ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class WindowsFocusProvider(FocusProvider):
    name = "windows"

    def __init__(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.EnumChildWindows.argtypes = [wintypes.HWND, _ENUM_PROC, wintypes.LPARAM]
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                        ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._user32 = user32
        self._kernel32 = kernel32

    def get(self) -> WindowInfo:
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return WindowInfo()
        length = self._user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = self._pid(hwnd)
        exe = self._exe_name(pid)
        if exe == FRAME_HOST:
            pid, exe = self._uwp_app(hwnd, pid) or (pid, exe)
        ids = (exe, exe.removesuffix(".exe")) if exe else ()
        return WindowInfo(ids=ids, title=buf.value, name=ids[-1] if ids else "", pid=pid)

    def _pid(self, hwnd) -> int:
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def _uwp_app(self, hwnd, host_pid: int) -> tuple[int, str] | None:
        """(pid, exe) of the app inside an ApplicationFrameHost window."""
        found: list[int] = []

        def visit(child, _lparam):
            pid = self._pid(child)
            if pid != host_pid:
                found.append(pid)
                return False
            return True

        self._user32.EnumChildWindows(hwnd, _ENUM_PROC(visit), 0)
        if found and (exe := self._exe_name(found[0])):
            return found[0], exe
        return None

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
