import pytest

from dailydeck.keys.parse import parse_shortcut

xkb = pytest.importorskip("dailydeck.keys.xkb")

KEY_Y, KEY_Z, KEY_7, KEY_Q, KEY_RIGHTBRACE = 21, 44, 8, 16, 27  # evdev codes


@pytest.fixture(scope="module")
def de():
    try:
        return xkb.XkbKeymap("de", "nodeadkeys")
    except (OSError, ValueError) as e:
        pytest.skip(f"libxkbcommon/xkb-data not available: {e}")


def lookup(keymap, char):
    return keymap.lookup(keymap.keysym_for_char(char))


def test_german_layout_swaps_y_and_z(de):
    assert lookup(de, "z") == (KEY_Y, frozenset())
    assert lookup(de, "y") == (KEY_Z, frozenset())


def test_shift_and_altgr_levels(de):
    assert lookup(de, "/") == (KEY_7, frozenset({"shift"}))
    assert lookup(de, "@") == (KEY_Q, frozenset({"altgr"}))
    assert lookup(de, "+") == (KEY_RIGHTBRACE, frozenset())


def test_named_keys(de):
    assert de.lookup(de.keysym_for_name("F5")) is not None
    assert parse_shortcut("F5")[0].key == "f5"
