"""Windows / macOS / X11 backend using ``pynput``.

On macOS the process needs the Accessibility permission; without it the
system drops synthetic key events silently, so it is checked explicitly.
"""

import logging
import sys
import time

from pynput.keyboard import Controller, Key, KeyCode

from .base import KeySender
from .parse import Chord

MODIFIER_KEYS = {
    "ctrl": Key.ctrl,
    "shift": Key.shift,
    "alt": Key.alt,
    "altgr": getattr(Key, "alt_gr", Key.alt),
    "super": Key.cmd,
}

NAMED_KEYS = {
    "enter": Key.enter, "escape": Key.esc, "tab": Key.tab, "space": Key.space,
    "backspace": Key.backspace, "delete": Key.delete, "home": Key.home,
    "end": Key.end, "pageup": Key.page_up, "pagedown": Key.page_down,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "capslock": Key.caps_lock,
    "volumeup": Key.media_volume_up, "volumedown": Key.media_volume_down,
    "mute": Key.media_volume_mute, "playpause": Key.media_play_pause,
    "nexttrack": Key.media_next, "prevtrack": Key.media_previous,
    **{f"f{i}": getattr(Key, f"f{i}") for i in range(1, 21) if hasattr(Key, f"f{i}")},
}
for _name, _attr in (("insert", "insert"), ("print", "print_screen"), ("menu", "menu"), ("pause", "pause")):
    if hasattr(Key, _attr):
        NAMED_KEYS[_name] = getattr(Key, _attr)

KEY_DELAY = 0.012

log = logging.getLogger(__name__)

ACCESSIBILITY_HINT = (
    "Daily Deck darf keine Tastendrücke senden. Freigabe erteilen unter Systemeinstellungen → "
    "Datenschutz & Sicherheit → Bedienungshilfen (für die App bzw. das Terminal, aus dem sie läuft)."
)


def accessibility_trusted(prompt: bool = False) -> bool:
    """Whether macOS lets this process send key events (always True elsewhere).

    With ``prompt`` macOS shows its dialog that leads to the settings pane.
    """
    if sys.platform != "darwin":
        return True
    from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))


class PynputKeySender(KeySender):
    name = "pynput"

    def __init__(self):
        self._kb = Controller()
        self._trusted = accessibility_trusted(prompt=True)
        if not self._trusted:
            log.warning(ACCESSIBILITY_HINT)

    def resolve(self, chord: Chord) -> list:
        # "cmd" is the natural primary modifier on macOS, "super" elsewhere
        keys = [MODIFIER_KEYS[m] for m in ("ctrl", "alt", "altgr", "shift", "super") if m in chord.modifiers]
        if not chord.key:
            pass
        elif chord.is_char:
            keys.append(KeyCode.from_char(chord.key))
        elif chord.key in NAMED_KEYS:
            keys.append(NAMED_KEYS[chord.key])
        else:
            raise ValueError(f"key {chord.key!r} not supported on {sys.platform}")
        return keys

    def send(self, chords: tuple[Chord, ...]) -> None:
        if not self._trusted:
            # the permission can be granted while running; re-check without prompting again
            self._trusted = accessibility_trusted()
            if not self._trusted:
                log.warning(ACCESSIBILITY_HINT)
                return
        for chord in chords:
            keys = self.resolve(chord)
            for k in keys:
                self._kb.press(k)
                time.sleep(KEY_DELAY)
            for k in reversed(keys):
                self._kb.release(k)
                time.sleep(KEY_DELAY)
