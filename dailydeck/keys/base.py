import threading
import time
from collections import Counter

from .parse import Chord

KEY_DELAY = 0.012  # pause between single key events
MAX_HOLD = 60.0  # upper limit for a fixed press duration (seconds)


class KeySender:
    """Sends shortcuts. Backends implement ``resolve`` and ``_emit``; optionally
    ``_sequence`` (resolve several chords at once) and ``_ready`` (precondition).

    Keys are reference counted: when two deck buttons hold the same key
    (e.g. Shift) at the same time, it is only released when both let go.
    All methods are thread safe, so several buttons can be active at once.
    """

    name = "base"

    def __init__(self):
        self._lock = threading.Lock()
        self._down: Counter = Counter()

    # --- backend interface ----------------------------------------------------

    def resolve(self, chord: Chord) -> list:
        """Backend keys of one chord in press order (modifiers first)."""
        raise NotImplementedError

    def _emit(self, key, down: bool) -> None:
        """One key event. Keys must be hashable; ``self._down`` already reflects the event."""
        raise NotImplementedError

    def _sequence(self, chords: tuple[Chord, ...]) -> list[list]:
        """Backend keys for each chord."""
        return [self.resolve(chord) for chord in chords]

    def _ready(self) -> bool:
        """False: send nothing (e.g. missing permission)."""
        return True

    # --- public API ---------------------------------------------------------------

    def send(self, chords: tuple[Chord, ...], hold: float = 0.0) -> None:
        """Press and release each chord in turn; ``hold`` = seconds each chord stays down."""
        if not self._ready():
            return
        sequences = self._sequence(chords)
        hold = min(max(hold, 0.0), MAX_HOLD)
        for keys in sequences:
            self._press_keys(keys)
            if hold:
                time.sleep(hold)
            self._release_keys(keys)

    def press(self, chords: tuple[Chord, ...]) -> list:
        """Tap all chords but the last, keep the last one down. Returns what ``release`` needs."""
        if not self._ready():
            return []
        sequences = self._sequence(chords)
        for keys in sequences[:-1]:
            self._press_keys(keys)
            self._release_keys(keys)
        if not sequences:
            return []
        self._press_keys(sequences[-1])
        return sequences[-1]

    def release(self, held: list) -> None:
        self._release_keys(held)

    def release_all(self) -> None:
        """Let go of everything still held (profile switch, pause, shutdown)."""
        with self._lock:
            keys = list(self._down)
            self._down.clear()
            for key in reversed(keys):
                self._emit(key, False)

    def describe(self, chords: tuple[Chord, ...]) -> str:
        """Human readable description of what ``send`` would do (dry run)."""
        return " ".join(str(c) for c in chords)

    def close(self) -> None:
        pass

    # --- helpers --------------------------------------------------------------------

    def _press_keys(self, keys: list) -> None:
        for key in keys:
            with self._lock:
                self._down[key] += 1
                if self._down[key] == 1:
                    self._emit(key, True)
            time.sleep(KEY_DELAY)

    def _release_keys(self, keys: list) -> None:
        for key in reversed(keys):
            with self._lock:
                if self._down[key] <= 0:
                    continue  # already released (release_all)
                self._down[key] -= 1
                if self._down[key] == 0:
                    del self._down[key]
                    self._emit(key, False)
            time.sleep(KEY_DELAY)


class NullKeySender(KeySender):
    """Sends nothing (used for previews)."""

    name = "null"

    def resolve(self, chord: Chord) -> list:
        return []

    def _emit(self, key, down: bool) -> None:
        pass
