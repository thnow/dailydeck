"""Parsing of shortcut strings such as ``"ctrl+shift+t"`` or ``"ctrl+k ctrl+c"``.

A shortcut is a sequence of chords separated by whitespace. A chord is a set
of modifiers plus one key, joined with ``+``. Keys are either a single
character (resolved through the active keyboard layout) or one of the named
keys in ``NAMED_KEYS``.
"""

import sys
from dataclasses import dataclass

from ..i18n import _

MODIFIER_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl", "strg": "ctrl", "ctl": "ctrl",
    "shift": "shift", "umschalt": "shift",
    "alt": "alt", "option": "alt", "opt": "alt",
    "altgr": "altgr",
    "super": "super", "win": "super", "meta": "super", "cmd": "super",
    "command": "super", "logo": "super",
}

# "primary" is the platform's main shortcut modifier: Cmd on macOS, Ctrl elsewhere.
# It is resolved while parsing, so one profile gives Cmd+C on a Mac and Ctrl+C elsewhere.
PRIMARY_ALIASES = ("primary", "mod")


def primary_modifier(platform: str | None = None) -> str:
    return "super" if (platform or sys.platform) == "darwin" else "ctrl"


MODIFIER_ORDER = ("ctrl", "alt", "altgr", "shift", "super")

MODIFIER_DISPLAY = {"ctrl": "Ctrl", "alt": "Alt", "altgr": "AltGr", "shift": "Shift",
                    "super": {"darwin": "Cmd", "win32": "Win"}.get(sys.platform, "Super")}

# canonical name -> aliases
_NAMED = {
    "enter": ("return",),
    "escape": ("esc",),
    "tab": (),
    "space": ("leertaste",),
    "backspace": ("bksp",),
    "delete": ("del", "entf"),
    "insert": ("ins", "einfg"),
    "home": ("pos1",),
    "end": ("ende",),
    "pageup": ("pgup", "prior", "bildauf"),
    "pagedown": ("pgdn", "next", "bildab"),
    "up": ("arrowup",),
    "down": ("arrowdown",),
    "left": ("arrowleft",),
    "right": ("arrowright",),
    "print": ("printscreen", "druck"),
    "menu": ("contextmenu",),
    "capslock": (),
    "pause": (),
    "volumeup": (),
    "volumedown": (),
    "mute": (),
    "playpause": ("play",),
    "nexttrack": (),
    "prevtrack": (),
    **{f"f{i}": () for i in range(1, 25)},
}
NAMED_KEYS = {alias: canon for canon, aliases in _NAMED.items() for alias in (canon, *aliases)}

# names that are just a spelled out character
CHAR_ALIASES = {
    "plus": "+", "minus": "-", "comma": ",", "period": ".", "dot": ".",
    "slash": "/", "backslash": "\\", "equal": "=", "equals": "=",
    "semicolon": ";", "colon": ":", "hash": "#", "less": "<", "greater": ">",
    "apostrophe": "'", "quote": "'", "grave": "`", "bracketleft": "[",
    "bracketright": "]", "braceleft": "{", "braceright": "}",
}


DISPLAY_NAMES = {
    "escape": "Esc", "pageup": "PgUp", "pagedown": "PgDn", "backspace": "⌫",
    "delete": "Del", "insert": "Ins", "up": "↑", "down": "↓", "left": "←",
    "right": "→", "enter": "↵", "volumeup": "Vol+", "volumedown": "Vol-",
    "playpause": "Play", "nexttrack": "Next", "prevtrack": "Prev",
}


@dataclass(frozen=True)
class Chord:
    modifiers: frozenset[str]
    key: str  # a NAMED_KEYS canonical name, a single character, or "" (modifiers only)
    is_char: bool

    def __str__(self) -> str:
        mods = [MODIFIER_DISPLAY[m] for m in MODIFIER_ORDER if m in self.modifiers]
        if not self.key:
            return "+".join(mods)
        if self.is_char:
            key = {" ": "Space"}.get(self.key, self.key.upper())
        else:
            key = DISPLAY_NAMES.get(self.key) or (
                self.key.upper() if self.key.startswith("f") and self.key[1:].isdigit() else self.key.capitalize()
            )
        return "+".join([*mods, key])


class ShortcutError(ValueError):
    pass


def _modifier(name: str, platform: str | None) -> str | None:
    name = name.lower()
    if name in PRIMARY_ALIASES:
        return primary_modifier(platform)
    return MODIFIER_ALIASES.get(name)


def parse_chord(text: str, platform: str | None = None) -> Chord:
    if text.endswith("++"):  # "ctrl++" means ctrl and the plus key
        parts = text[:-2].split("+") + ["+"]
    elif text == "+":
        parts = ["+"]
    else:
        parts = text.split("+")
    if any(p == "" for p in parts):
        raise ShortcutError(_("empty key in “{shortcut}”").format(shortcut=text))

    *mod_parts, key_part = parts
    modifiers = set()
    for part in mod_parts:
        mod = _modifier(part, platform)
        if mod is None:
            raise ShortcutError(_("unknown modifier “{modifier}” in “{shortcut}”").format(modifier=part, shortcut=text))
        modifiers.add(mod)

    lower = key_part.lower()
    if len(key_part) == 1:
        # letters are case-insensitive, Shift must be given explicitly
        return Chord(frozenset(modifiers), lower if key_part.isalpha() else key_part, True)
    if lower in CHAR_ALIASES:
        return Chord(frozenset(modifiers), CHAR_ALIASES[lower], True)
    if lower in NAMED_KEYS:
        return Chord(frozenset(modifiers), NAMED_KEYS[lower], False)
    if (mod := _modifier(lower, platform)) is not None:
        # modifiers only, e.g. "super" to open the GNOME overview
        return Chord(frozenset(modifiers | {mod}), "", False)
    raise ShortcutError(_("unknown key “{key}” in “{shortcut}”").format(key=key_part, shortcut=text))


def parse_shortcut(text: str, platform: str | None = None) -> tuple[Chord, ...]:
    """``platform`` (a ``sys.platform`` value) decides what ``primary`` means; default: this system."""
    chords = tuple(parse_chord(part, platform) for part in text.split())
    if not chords:
        raise ShortcutError(_("empty shortcut"))
    return chords


def format_shortcut(chords: tuple[Chord, ...]) -> str:
    return " ".join(str(c) for c in chords)
