from .parse import Chord


class KeySender:
    name = "base"

    def send(self, chords: tuple[Chord, ...]) -> None:
        raise NotImplementedError

    def describe(self, chords: tuple[Chord, ...]) -> str:
        """Human readable description of what ``send`` would do (dry run)."""
        return " ".join(str(c) for c in chords)

    def close(self) -> None:
        pass


class NullKeySender(KeySender):
    """Sends nothing (used for previews)."""

    name = "null"

    def send(self, chords: tuple[Chord, ...]) -> None:
        pass
