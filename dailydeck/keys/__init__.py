import sys

from .base import KeySender
from .parse import Chord, ShortcutError, format_shortcut, parse_shortcut

__all__ = ["Chord", "KeySender", "ShortcutError", "create_key_sender", "format_shortcut", "parse_shortcut"]


def create_key_sender(name: str = "auto", layout: str | None = None, variant: str | None = None) -> KeySender:
    if name == "auto":
        name = "uinput" if sys.platform.startswith("linux") else "pynput"
    if name == "uinput":
        from .linux_uinput import UInputKeySender

        return UInputKeySender(layout, variant)
    if name == "pynput":
        from .pynput_sender import PynputKeySender

        return PynputKeySender()
    raise ValueError(f"unknown key backend: {name}")
