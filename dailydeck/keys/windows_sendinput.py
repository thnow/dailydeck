"""Windows backend using ``SendInput`` with virtual key and scan codes.

Characters are resolved through the keyboard layout of the focused window
(``VkKeyScanExW``), including the modifiers the layout needs: on a German
layout ``/`` is Shift+7 and ``[`` is AltGr+8, so ``ctrl+/`` is sent as
Ctrl+Shift+7. AltGr is sent like a real keyboard does: left Ctrl plus right Alt.

Windows does not let a normal process send input to an elevated window (UIPI);
for those, run Daily Deck as administrator too.
"""

import ctypes
import logging
import time
from ctypes import wintypes

from .base import KeySender
from .parse import Chord

log = logging.getLogger(__name__)

KEY_DELAY = 0.012

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MAPVK_VK_TO_VSC_EX = 4

# modifier -> [(virtual key, scan code, extended)], pressed in this order
MODIFIERS = {
    "ctrl": [(0xA2, 0x1D, False)],                       # VK_LCONTROL
    "alt": [(0xA4, 0x38, False)],                        # VK_LMENU
    "altgr": [(0xA2, 0x1D, False), (0xA5, 0x38, True)],  # LCtrl + VK_RMENU, as the keyboard driver does
    "shift": [(0xA0, 0x2A, False)],                      # VK_LSHIFT
    "super": [(0x5B, 0x5B, True)],                       # VK_LWIN
}
ORDER = ("ctrl", "alt", "altgr", "shift", "super")

# keys that sit on the extended (E0) scan code block
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D,
             0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}

NAMED_KEYS = {
    "enter": 0x0D, "tab": 0x09, "space": 0x20, "backspace": 0x08, "escape": 0x1B,
    "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "print": 0x2C, "menu": 0x5D, "capslock": 0x14, "pause": 0x13,
    "volumeup": 0xAF, "volumedown": 0xAE, "mute": 0xAD,
    "playpause": 0xB3, "nexttrack": 0xB0, "prevtrack": 0xB1,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},  # VK_F1 = 0x70
}

# VkKeyScanExW shift state bits
_SHIFT, _CTRL, _ALT = 0x01, 0x02, 0x04


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):  # only for the size of the union
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _extra_modifiers(state: int) -> tuple[str, ...]:
    """Modifiers a layout needs for a character, from VkKeyScanExW's shift state."""
    mods = []
    if state & _CTRL and state & _ALT:
        mods.append("altgr")
    elif state & _CTRL:
        mods.append("ctrl")
    elif state & _ALT:
        mods.append("alt")
    if state & _SHIFT:
        mods.append("shift")
    return tuple(mods)


class WindowsKeySender(KeySender):
    name = "sendinput"

    def __init__(self):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
        user32.GetKeyboardLayout.restype = ctypes.c_void_p
        user32.VkKeyScanExW.argtypes = [wintypes.WCHAR, ctypes.c_void_p]
        user32.VkKeyScanExW.restype = ctypes.c_short
        user32.MapVirtualKeyExW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
        user32.MapVirtualKeyExW.restype = wintypes.UINT
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        self._user32 = user32

    def _layout(self) -> int:
        """Keyboard layout (HKL) of the focused window – each thread can have its own."""
        hwnd = self._user32.GetForegroundWindow()
        thread = self._user32.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
        return self._user32.GetKeyboardLayout(thread) or 0

    def resolve(self, chord: Chord, hkl: int) -> list[tuple[int, int, bool]]:
        """Keys to press in order, as (virtual key, scan code, extended), released in reverse."""
        mods = set(chord.modifiers)
        vk = None
        if chord.key and chord.is_char:
            res = self._user32.VkKeyScanExW(chord.key, hkl)
            if res == -1 and chord.key.isalpha():
                res = self._user32.VkKeyScanExW(chord.key.lower(), hkl)
            if res == -1:
                raise ValueError(f"character {chord.key!r} cannot be typed on keyboard layout {hkl & 0xFFFFFFFF:08x}")
            vk = res & 0xFF
            extra = _extra_modifiers((res >> 8) & 0xFF)
            if "altgr" in mods or "altgr" in extra:  # AltGr already holds Ctrl+Alt
                mods.discard("ctrl")
                mods.discard("alt")
            mods.update(extra)
        elif chord.key:
            if chord.key not in NAMED_KEYS:
                raise ValueError(f"key {chord.key!r} not available on Windows")
            vk = NAMED_KEYS[chord.key]
        keys: list[tuple[int, int, bool]] = []
        for m in ORDER:
            if m in mods:
                keys += [k for k in MODIFIERS[m] if k not in keys]
        if vk is not None:
            scan = self._user32.MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC_EX, hkl)
            keys.append((vk, scan & 0xFF, vk in _EXTENDED or (scan >> 8) in (0xE0, 0xE1)))
        return keys

    def describe(self, chords: tuple[Chord, ...]) -> str:
        hkl = self._layout()
        parts = []
        for chord in chords:
            parts.append("+".join(f"vk{vk:#04x}" for vk, _scan, _ext in self.resolve(chord, hkl)))
        return " ".join(parts) + f"  [layout {hkl & 0xFFFFFFFF:08x}]"

    def send(self, chords: tuple[Chord, ...]) -> None:
        hkl = self._layout()
        for chord in chords:
            keys = self.resolve(chord, hkl)
            for key in keys:
                self._send(*key, down=True)
            for key in reversed(keys):
                self._send(*key, down=False)

    def _send(self, vk: int, scan: int, extended: bool, down: bool) -> None:
        flags = (KEYEVENTF_EXTENDEDKEY if extended else 0) | (0 if down else KEYEVENTF_KEYUP)
        event = INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)))
        if self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
            log.warning("SendInput failed (error %d)", ctypes.get_last_error())
        time.sleep(KEY_DELAY)
