import sys

from .base import KeySender
from .parse import Chord, ShortcutError, format_shortcut, parse_shortcut

__all__ = ["Chord", "KeySender", "ShortcutError", "create_key_sender", "format_shortcut", "parse_shortcut"]


def create_key_sender(name: str = "auto", layout: str | None = None, variant: str | None = None) -> KeySender:
    if name == "auto":
        name = {"darwin": "quartz", "win32": "sendinput"}.get(sys.platform, "uinput")
    if name == "uinput":
        from .linux_uinput import UInputKeySender

        return UInputKeySender(layout, variant)
    if name == "quartz":
        from .macos_quartz import QuartzKeySender

        return QuartzKeySender()
    if name == "sendinput":
        from .windows_sendinput import WindowsKeySender

        return WindowsKeySender()
    raise ValueError(f"unknown key backend: {name}")
