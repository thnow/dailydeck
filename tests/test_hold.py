"""Press duration: fixed holds, hold-while-pressed, overlapping keys."""

import time
from pathlib import Path

import pytest

from dailydeck import i18n
from dailydeck.config import Button, ConfigError, parse_config
from dailydeck.keys import parse_shortcut
from dailydeck.keys.base import KeySender
from dailydeck.layout import button_badge


class RecordingSender(KeySender):
    """Keys are their names, e.g. ["ctrl", "t"]; records (key, down, time)."""

    def __init__(self):
        super().__init__()
        self.events = []

    def resolve(self, chord):
        return sorted(chord.modifiers) + ([chord.key] if chord.key else [])

    def _emit(self, key, down):
        self.events.append((key, down, time.monotonic()))

    def down(self):
        state = {}
        for key, down, _ in self.events:
            state[key] = down
        return {k for k, v in state.items() if v}


def test_tap_order():
    s = RecordingSender()
    s.send(parse_shortcut("ctrl+t"))
    assert [(k, d) for k, d, _ in s.events] == [("ctrl", True), ("t", True), ("t", False), ("ctrl", False)]


def test_fixed_hold_duration():
    s = RecordingSender()
    s.send(parse_shortcut("w"), hold=0.2)
    (_, _, t_down), (_, _, t_up) = s.events
    assert t_up - t_down >= 0.2


def test_press_and_release():
    s = RecordingSender()
    held = s.press(parse_shortcut("shift+w"))
    assert s.down() == {"shift", "w"}
    s.release(held)
    assert s.down() == set()


def test_shared_modifier_stays_down_until_both_released():
    s = RecordingSender()
    a = s.press(parse_shortcut("shift+a"))
    b = s.press(parse_shortcut("shift+b"))
    s.release(a)
    assert s.down() == {"shift", "b"}
    s.release(b)
    assert s.down() == set()


def test_release_all_then_late_release_is_harmless():
    s = RecordingSender()
    held = s.press(parse_shortcut("ctrl+w"))
    s.release_all()
    assert s.down() == set()
    count = len(s.events)
    s.release(held)
    assert len(s.events) == count  # nothing released twice


def test_sequence_taps_all_but_last():
    s = RecordingSender()
    s.press(parse_shortcut("ctrl+k z"))
    assert s.down() == {"z"}


def config_with(button):
    return parse_config({"profiles": [{"name": "Game", "buttons": [button]}]}, Path("/tmp/c.toml"))


@pytest.mark.parametrize("hold", [-1, "long", True, 999])
def test_invalid_hold_rejected(hold):
    with pytest.raises(ConfigError, match="hold"):
        config_with({"label": "W", "keys": "w", "hold": hold})


def test_hold_values_loaded():
    b = config_with({"label": "W", "keys": "w", "hold": 1.5}).profiles[0].buttons[0]
    assert b.hold == 1.5 and not b.hold_while_pressed
    b = config_with({"label": "W", "keys": "w", "hold_while_pressed": True}).profiles[0].buttons[0]
    assert b.hold_while_pressed


@pytest.mark.parametrize(("lang", "fixed", "held"), [("en", "0.8 s", "hold"), ("de", "0,8 s", "halten")])
def test_badge_shows_press_mode(lang, fixed, held):
    chords = parse_shortcut("w")
    i18n.setup(lang)
    try:
        assert button_badge(Button(chords=chords)) == ""
        assert button_badge(Button(chords=chords, hold=0.8)) == fixed
        assert button_badge(Button(chords=chords, hold_while_pressed=True)) == held
    finally:
        i18n.setup("en")
