"""Parsing of shortcut strings such as ``"ctrl+shift+t"`` or ``"ctrl+k ctrl+c"``.

A shortcut is a sequence of chords separated by whitespace. A chord is a set
of modifiers plus one key, joined with ``+``. Keys are either a single
character (resolved through the active keyboard layout) or one of the named
keys in ``NAMED_KEYS``.
"""

from dataclasses import dataclass

MODIFIER_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl", "strg": "ctrl", "ctl": "ctrl",
    "shift": "shift", "umschalt": "shift",
    "alt": "alt", "option": "alt", "opt": "alt",
    "altgr": "altgr",
    "super": "super", "win": "super", "meta": "super", "cmd": "super",
    "command": "super", "logo": "super",
}

MODIFIER_ORDER = ("ctrl", "alt", "altgr", "shift", "super")

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
        mods = [m.capitalize() if m != "altgr" else "AltGr" for m in MODIFIER_ORDER if m in self.modifiers]
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


def parse_chord(text: str) -> Chord:
    if text.endswith("++"):  # "ctrl++" means ctrl and the plus key
        parts = text[:-2].split("+") + ["+"]
    elif text == "+":
        parts = ["+"]
    else:
        parts = text.split("+")
    if any(p == "" for p in parts):
        raise ShortcutError(f"empty key in {text!r}")

    *mod_parts, key_part = parts
    modifiers = set()
    for part in mod_parts:
        mod = MODIFIER_ALIASES.get(part.lower())
        if mod is None:
            raise ShortcutError(f"unknown modifier {part!r} in {text!r}")
        modifiers.add(mod)

    lower = key_part.lower()
    if len(key_part) == 1:
        # letters are case-insensitive, Shift must be given explicitly
        return Chord(frozenset(modifiers), lower if key_part.isalpha() else key_part, True)
    if lower in CHAR_ALIASES:
        return Chord(frozenset(modifiers), CHAR_ALIASES[lower], True)
    if lower in NAMED_KEYS:
        return Chord(frozenset(modifiers), NAMED_KEYS[lower], False)
    if lower in MODIFIER_ALIASES:
        # modifiers only, e.g. "super" to open the GNOME overview
        return Chord(frozenset(modifiers | {MODIFIER_ALIASES[lower]}), "", False)
    raise ShortcutError(f"unknown key {key_part!r} in {text!r}")


def parse_shortcut(text: str) -> tuple[Chord, ...]:
    chords = tuple(parse_chord(part) for part in text.split())
    if not chords:
        raise ShortcutError("empty shortcut")
    return chords


def format_shortcut(chords: tuple[Chord, ...]) -> str:
    return " ".join(str(c) for c in chords)
