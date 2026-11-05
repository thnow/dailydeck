"""macOS backend posting Quartz key events (needs the Accessibility permission).

Like ``xkb`` on Linux, characters are resolved through the active keyboard
layout: ``@`` on a German layout becomes Option+L. Every event carries the
full modifier flags, which apps such as Finder need to see Cmd+Shift shortcuts.

macOS also localizes menu shortcuts that would need Option on the current
layout: on German layouts Finder's Cmd+[ is shown and matched as Cmd+Ö.
``LOCALIZED`` lists the remappings verified on such layouts.
"""

import ctypes
import logging
import threading
import time

import Quartz as Q
from AppKit import NSEvent
from Foundation import NSOperationQueue

from .base import KeySender
from .parse import Chord
from .pynput_sender import ACCESSIBILITY_HINT, accessibility_trusted

log = logging.getLogger(__name__)

KEY_DELAY = 0.012

# modifier name -> (virtual key code of the left key, event flag)
MODIFIERS = {
    "ctrl": (0x3B, Q.kCGEventFlagMaskControl),
    "alt": (0x3A, Q.kCGEventFlagMaskAlternate),
    "altgr": (0x3D, Q.kCGEventFlagMaskAlternate),  # right Option, the Mac's AltGr
    "shift": (0x38, Q.kCGEventFlagMaskShift),
    "super": (0x37, Q.kCGEventFlagMaskCommand),
}
ORDER = ("ctrl", "alt", "altgr", "shift", "super")

NAMED_KEYS = {
    "enter": 0x24, "tab": 0x30, "space": 0x31, "backspace": 0x33, "escape": 0x35,
    "capslock": 0x39, "home": 0x73, "pageup": 0x74, "delete": 0x75, "end": 0x77,
    "pagedown": 0x79, "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
    "insert": 0x72,  # the Help key on Apple keyboards, Insert on PC keyboards
    **dict(zip((f"f{i}" for i in range(1, 21)),
               (0x7A, 0x78, 0x63, 0x76, 0x60, 0x61, 0x62, 0x64, 0x65, 0x6D,
                0x67, 0x6F, 0x69, 0x6B, 0x71, 0x6A, 0x40, 0x4F, 0x50, 0x5A), strict=True)),
}
# arrows and the navigation block carry these flags when typed on a real keyboard
_FN_KEYS = {0x73, 0x74, 0x75, 0x77, 0x79, 0x7B, 0x7C, 0x7D, 0x7E, 0x72}

# NX_KEYTYPE_* from IOKit/hidsystem/ev_keymap.h, sent as system defined events
MEDIA_KEYS = {"volumeup": 0, "volumedown": 1, "mute": 7, "playpause": 16, "nexttrack": 17, "prevtrack": 18}

_GERMAN = {"[": "ö", "]": "ä", "\\": "#"}
LOCALIZED = {
    "com.apple.keylayout.German": _GERMAN,
    "com.apple.keylayout.German-DIN-2018": _GERMAN,
    "com.apple.keylayout.Austrian": _GERMAN,
}

# numeric keypad: apps tell these apart from the main keys, so they are only a fallback
_KEYPAD = {0x41, 0x43, 0x45, 0x47, 0x4B, 0x4C, 0x4E, 0x51, 0x52, 0x53, 0x54, 0x55, 0x56, 0x57,
           0x58, 0x59, 0x5B, 0x5C}

# UCKeyTranslate modifier states (EventModifiers >> 8)
_SHIFT, _OPTION = 0x02, 0x08
_STATES = ((0, ()), (_SHIFT, ("shift",)), (_OPTION, ("alt",)), (_SHIFT | _OPTION, ("shift", "alt")))


class _Layout:
    """Character -> (key code, extra modifiers) for the active keyboard layout."""

    def __init__(self):
        carbon = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
        cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        carbon.TISCopyCurrentKeyboardLayoutInputSource.restype = ctypes.c_void_p
        carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
        carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        carbon.LMGetKbdType.restype = ctypes.c_uint8
        carbon.UCKeyTranslate.argtypes = [
            ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_uint16),
        ]
        cf.CFDataGetBytePtr.restype = ctypes.c_void_p
        cf.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        self._carbon, self._cf = carbon, cf
        self._k_data = ctypes.c_void_p.in_dll(carbon, "kTISPropertyUnicodeKeyLayoutData")
        self._k_id = ctypes.c_void_p.in_dll(carbon, "kTISPropertyInputSourceID")
        self.layout_id = ""
        self._chars: dict[str, tuple[int, tuple[str, ...]]] = {}
        self._checked = 0.0

    def refresh(self) -> None:
        """Re-read the layout if the user switched it (at most once a second).

        The Text Input Sources API must run on the main thread – off it macOS
        aborts the process as soon as a text field has the focus. From the key
        sender thread the call is handed to the main run loop (Qt's, or the
        daemon's focus polling) and the last known layout is kept on a timeout.
        """
        now = time.monotonic()
        if self._chars and now - self._checked < 1.0:
            return
        self._checked = now
        if threading.current_thread() is threading.main_thread():
            self._refresh()
            return
        done = threading.Event()

        def run():
            try:
                self._refresh()
            finally:
                done.set()

        NSOperationQueue.mainQueue().addOperationWithBlock_(run)
        if not done.wait(0.5 if self._chars else 3.0):
            log.debug("main thread busy; keeping keyboard layout %s", self.layout_id or "(none)")

    def _refresh(self) -> None:
        carbon, cf = self._carbon, self._cf
        source = carbon.TISCopyCurrentKeyboardLayoutInputSource()
        if not source:
            return
        try:
            buf = ctypes.create_string_buffer(256)
            cf.CFStringGetCString(carbon.TISGetInputSourceProperty(source, self._k_id), buf, 256, 0x08000100)
            layout_id = buf.value.decode()
            if layout_id == self.layout_id and self._chars:
                return
            data = carbon.TISGetInputSourceProperty(source, self._k_data)
            if not data:
                return
            self._chars = self._read(cf.CFDataGetBytePtr(data))
            self.layout_id = layout_id
            log.debug("keyboard layout %s", layout_id)
        finally:
            cf.CFRelease(source)

    def _read(self, layout_ptr) -> dict[str, tuple[int, tuple[str, ...]]]:
        kbd_type = self._carbon.LMGetKbdType()
        chars: dict[str, tuple[int, tuple[str, ...]]] = {}
        dead = ctypes.c_uint32()
        length = ctypes.c_ulong()
        out = (ctypes.c_uint16 * 4)()
        main = [c for c in range(128) if c not in _KEYPAD]
        passes = [(state, mods, main) for state, mods in _STATES] + [(0, (), sorted(_KEYPAD))]
        for state, mods, codes in passes:  # fewest modifiers first, keypad last, so they win
            for code in codes:
                dead.value = 0
                self._carbon.UCKeyTranslate(
                    layout_ptr, code, 3, state, kbd_type,  # 3 = kUCKeyActionDisplay
                    1,  # kUCKeyTranslateNoDeadKeysMask
                    ctypes.byref(dead), 4, ctypes.byref(length), out,
                )
                if length.value == 1:
                    char = chr(out[0])
                    if char.isprintable() and char not in chars:
                        chars[char] = (code, mods)
        return chars

    def lookup(self, char: str) -> tuple[int, tuple[str, ...]] | None:
        return self._chars.get(char)


class QuartzKeySender(KeySender):
    name = "quartz"

    def __init__(self):
        self._source = Q.CGEventSourceCreate(Q.kCGEventSourceStateHIDSystemState)
        self._layout = _Layout()
        self._layout.refresh()
        self._trusted = accessibility_trusted(prompt=True)
        if not self._trusted:
            log.warning(ACCESSIBILITY_HINT)

    def resolve(self, chord: Chord) -> tuple[list[str], int | None]:
        """(modifiers to hold, key code) – key code None for modifier-only chords."""
        mods = set(chord.modifiers)
        if not chord.key:
            return [m for m in ORDER if m in mods], None
        if chord.key in MEDIA_KEYS:
            return [m for m in ORDER if m in mods], None
        if not chord.is_char:
            if chord.key not in NAMED_KEYS:
                raise ValueError(f"key {chord.key!r} not available on macOS")
            return [m for m in ORDER if m in mods], NAMED_KEYS[chord.key]
        char = chord.key
        found = self._layout.lookup(char)
        if "super" in mods and (found is None or "alt" in found[1]):
            # macOS shows and matches such menu shortcuts on another key, e.g. Cmd+[ as Cmd+Ö
            local = LOCALIZED.get(self._layout.layout_id, {}).get(char)
            if local and (alt := self._layout.lookup(local)):
                found = alt
        if found is None and char.isalpha():
            found = self._layout.lookup(char.lower())
        if found is None:
            raise ValueError(f"character {char!r} cannot be typed on keyboard layout {self._layout.layout_id}")
        code, extra = found
        if "altgr" in mods:  # same flag as Option; avoid holding both keys
            extra = tuple(m for m in extra if m != "alt")
        return [m for m in ORDER if m in mods or m in extra], code

    def describe(self, chords: tuple[Chord, ...]) -> str:
        self._layout.refresh()
        parts = []
        for chord in chords:
            if chord.key in MEDIA_KEYS:
                parts.append(f"media:{chord.key}")
                continue
            mods, code = self.resolve(chord)
            parts.append("+".join([*mods, *([f"vk{code:#04x}"] if code is not None else [])]))
        return " ".join(parts) + f"  [{self._layout.layout_id}]"

    def send(self, chords: tuple[Chord, ...]) -> None:
        if not self._trusted:
            self._trusted = accessibility_trusted()
            if not self._trusted:
                log.warning(ACCESSIBILITY_HINT)
                return
        self._layout.refresh()
        for chord in chords:
            if chord.key in MEDIA_KEYS:
                self._media(MEDIA_KEYS[chord.key])
                continue
            mods, code = self.resolve(chord)
            flags = 0
            for m in mods:
                key, flag = MODIFIERS[m]
                flags |= flag
                self._post(key, True, flags)
            if code is not None:
                key_flags = flags | (Q.kCGEventFlagMaskSecondaryFn | Q.kCGEventFlagMaskNumericPad
                                     if code in _FN_KEYS else 0)
                self._post(code, True, key_flags)
                self._post(code, False, key_flags)
            for m in reversed(mods):
                key, flag = MODIFIERS[m]
                flags &= ~flag
                self._post(key, False, flags)

    def _post(self, code: int, down: bool, flags: int) -> None:
        event = Q.CGEventCreateKeyboardEvent(self._source, code, down)
        Q.CGEventSetFlags(event, flags)
        Q.CGEventPost(Q.kCGHIDEventTap, event)
        time.sleep(KEY_DELAY)

    def _media(self, key_type: int) -> None:
        make = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_
        for down in (True, False):
            state = 0xA if down else 0xB
            event = make(14, (0, 0), state << 8, 0, 0, None, 8, (key_type << 16) | (state << 8), -1)  # NSSystemDefined
            Q.CGEventPost(Q.kCGHIDEventTap, event.CGEvent())
            time.sleep(KEY_DELAY)
