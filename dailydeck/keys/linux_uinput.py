"""Linux backend: a virtual keyboard via /dev/uinput.

Works on Wayland and X11 alike, because the compositor sees it as a normal
keyboard. Needs write access to /dev/uinput (see README).
"""

import logging
import time

from evdev import UInput, ecodes

from .base import KeySender
from .parse import Chord
from .xkb import XkbKeymap, detect_layout

log = logging.getLogger(__name__)

MODIFIER_CODES = {
    "ctrl": ecodes.KEY_LEFTCTRL,
    "shift": ecodes.KEY_LEFTSHIFT,
    "alt": ecodes.KEY_LEFTALT,
    "altgr": ecodes.KEY_RIGHTALT,
    "super": ecodes.KEY_LEFTMETA,
}

# canonical named key -> X keysym name (looked up in the layout)
KEYSYM_NAMES = {
    "enter": "Return", "escape": "Escape", "tab": "Tab", "space": "space",
    "backspace": "BackSpace", "delete": "Delete", "insert": "Insert",
    "home": "Home", "end": "End", "pageup": "Prior", "pagedown": "Next",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "print": "Print", "menu": "Menu", "capslock": "Caps_Lock", "pause": "Pause",
    "volumeup": "XF86AudioRaiseVolume", "volumedown": "XF86AudioLowerVolume",
    "mute": "XF86AudioMute", "playpause": "XF86AudioPlay",
    "nexttrack": "XF86AudioNext", "prevtrack": "XF86AudioPrev",
    **{f"f{i}": f"F{i}" for i in range(1, 25)},
}

# used when the keysym is missing from the layout
FALLBACK_CODES = {
    "enter": ecodes.KEY_ENTER, "escape": ecodes.KEY_ESC, "tab": ecodes.KEY_TAB,
    "space": ecodes.KEY_SPACE, "backspace": ecodes.KEY_BACKSPACE,
    "delete": ecodes.KEY_DELETE, "insert": ecodes.KEY_INSERT,
    "home": ecodes.KEY_HOME, "end": ecodes.KEY_END,
    "pageup": ecodes.KEY_PAGEUP, "pagedown": ecodes.KEY_PAGEDOWN,
    "up": ecodes.KEY_UP, "down": ecodes.KEY_DOWN, "left": ecodes.KEY_LEFT,
    "right": ecodes.KEY_RIGHT, "print": ecodes.KEY_SYSRQ, "menu": ecodes.KEY_COMPOSE,
    "capslock": ecodes.KEY_CAPSLOCK, "pause": ecodes.KEY_PAUSE,
    "volumeup": ecodes.KEY_VOLUMEUP, "volumedown": ecodes.KEY_VOLUMEDOWN,
    "mute": ecodes.KEY_MUTE, "playpause": ecodes.KEY_PLAYPAUSE,
    "nexttrack": ecodes.KEY_NEXTSONG, "prevtrack": ecodes.KEY_PREVIOUSSONG,
    **{f"f{i}": getattr(ecodes, f"KEY_F{i}") for i in range(1, 25)},
}

KEY_DELAY = 0.012


class UInputKeySender(KeySender):
    name = "uinput"

    def __init__(self, layout: str | None = None, variant: str | None = None):
        if not layout:
            layout, detected_variant = detect_layout()
            variant = detected_variant if variant is None else variant
        self.keymap = XkbKeymap(layout, variant or "")
        log.info("keyboard layout: %s%s", layout, f" ({variant})" if variant else "")
        keys = sorted(set(range(ecodes.KEY_ESC, ecodes.KEY_MICMUTE + 1)) & set(ecodes.KEY))
        self._ui = UInput({ecodes.EV_KEY: keys}, name="dailydeck virtual keyboard")

    def resolve(self, chord: Chord) -> list[int]:
        """Return evdev codes to press in order (modifiers first)."""
        if not chord.key:
            return [MODIFIER_CODES[m] for m in ("ctrl", "alt", "altgr", "shift", "super") if m in chord.modifiers]
        if chord.is_char:
            keysym = self.keymap.keysym_for_char(chord.key)
        else:
            keysym = self.keymap.keysym_for_name(KEYSYM_NAMES[chord.key])
        found = self.keymap.lookup(keysym) if keysym else None
        if found:
            code, layout_mods = found
        elif not chord.is_char:
            code, layout_mods = FALLBACK_CODES[chord.key], frozenset()
        else:
            raise ValueError(f"character {chord.key!r} not available in layout {self.keymap.layout!r}")
        mods = chord.modifiers | layout_mods
        return [MODIFIER_CODES[m] for m in ("ctrl", "alt", "altgr", "shift", "super") if m in mods] + [code]

    def describe(self, chords: tuple[Chord, ...]) -> str:
        return "  ".join(
            "+".join(ecodes.KEY[c] if isinstance(ecodes.KEY[c], str) else ecodes.KEY[c][-1] for c in self.resolve(ch))
            for ch in chords
        )

    def send(self, chords: tuple[Chord, ...]) -> None:
        sequences = [self.resolve(ch) for ch in chords]
        for codes in sequences:
            for code in codes:
                self._ui.write(ecodes.EV_KEY, code, 1)
                self._ui.syn()
                time.sleep(KEY_DELAY)
            for code in reversed(codes):
                self._ui.write(ecodes.EV_KEY, code, 0)
                self._ui.syn()
                time.sleep(KEY_DELAY)

    def close(self) -> None:
        self._ui.close()
