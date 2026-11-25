"""Press duration through the deck controller, with a fake device."""

import threading
import time
from pathlib import Path

import pytest

from dailydeck.config import parse_config

pytest.importorskip("StreamDeck")

from test_hold import RecordingSender  # noqa: E402


class FakeDeck:
    def __init__(self):
        self.callback = None
        self._lock = threading.RLock()

    def __enter__(self):
        self._lock.acquire()

    def __exit__(self, *exc):
        self._lock.release()

    def key_image_format(self):
        return {"size": (72, 72), "format": "JPEG", "flip": (True, True), "rotation": 0}

    def key_layout(self):
        return 3, 5

    def key_count(self):
        return 15

    def deck_type(self):
        return "Fake Deck"

    def get_serial_number(self):
        return "TEST"

    def set_key_callback(self, callback):
        self.callback = callback

    def open(self): pass
    def reset(self): pass
    def close(self): pass
    def connected(self): return True
    def set_brightness(self, value): pass
    def set_key_image(self, key, image): pass


@pytest.fixture
def controller():
    from dailydeck.app import DeckController

    config = parse_config({"settings": {"app_icon": False}, "profiles": [{"name": "Game", "default": True, "buttons": [
        {"label": "Sprint", "keys": "shift", "hold_while_pressed": True},
        {"label": "Charge", "keys": "e", "hold": 1.5},
        {"label": "Jump", "keys": "space"},
    ]}]}, Path("/tmp/c.toml"))
    deck, sender = FakeDeck(), RecordingSender()
    ctl = DeckController(deck, sender, config)
    ctl.show(config.default_profile, ctl.window, force=True)
    yield ctl, deck, sender
    ctl.close()


def wait_for(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_hold_while_pressed_follows_the_deck_key(controller):
    ctl, deck, sender = controller
    deck.callback(deck, 0, True)
    assert sender.down() == {"shift"}
    deck.callback(deck, 0, False)
    assert sender.down() == set()


def test_fixed_hold_does_not_block_other_keys(controller):
    ctl, deck, sender = controller
    deck.callback(deck, 1, True)   # hold "e" for 1.5 s
    deck.callback(deck, 1, False)
    deck.callback(deck, 2, True)   # jump meanwhile
    deck.callback(deck, 2, False)
    assert wait_for(lambda: ("space", False) in [(k, d) for k, d, _ in sender.events], 1.0)
    assert "e" in sender.down()    # still charging
    assert wait_for(lambda: "e" not in sender.down(), 3.0)


def test_pause_releases_held_keys(controller):
    ctl, deck, sender = controller
    deck.callback(deck, 0, True)
    ctl.set_paused(True)
    assert sender.down() == set()
    deck.callback(deck, 0, False)  # late key-up must not do anything odd
    assert sender.down() == set()
