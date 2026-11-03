import pytest

from dailydeck.keys import ShortcutError, format_shortcut, parse_shortcut


@pytest.mark.parametrize(
    ("text", "mods", "key", "is_char"),
    [
        ("ctrl+shift+t", {"ctrl", "shift"}, "t", True),
        ("Ctrl+T", {"ctrl"}, "t", True),  # letters are case-insensitive
        ("strg+entf", {"ctrl"}, "delete", False),  # German aliases
        ("ctrl++", {"ctrl"}, "+", True),
        ("ctrl+plus", {"ctrl"}, "+", True),
        ("alt+F4", {"alt"}, "f4", False),
        ("super", {"super"}, "", False),  # modifier only
        ("cmd+c", {"super"}, "c", True),
    ],
)
def test_parse_chord(text, mods, key, is_char):
    (chord,) = parse_shortcut(text)
    assert chord.modifiers == frozenset(mods)
    assert chord.key == key
    assert chord.is_char is is_char


def test_sequence():
    chords = parse_shortcut("ctrl+k z")
    assert len(chords) == 2
    assert format_shortcut(chords) == "Ctrl+K Z"


@pytest.mark.parametrize("text", ["", "ctrl+foo", "hyper+a", "ctrl++a+"])
def test_invalid(text):
    with pytest.raises(ShortcutError):
        parse_shortcut(text)


def test_display_names():
    assert format_shortcut(parse_shortcut("alt+left")) == "Alt+←"
    assert format_shortcut(parse_shortcut("ctrl+pagedown")) == "Ctrl+PgDn"
