"""Built-in key symbols: ``icon = "symbol:play"`` instead of an image file.

The symbols are white PNGs from Lucide (https://lucide.dev, ISC license, see
``data/symbols/LICENSE``), rendered by ``scripts/build-symbols.py``. They are
drawn in the key's text colour.
"""

from pathlib import Path

from PIL import Image

from .i18n import N_

PREFIX = "symbol:"
SYMBOLS_DIR = Path(__file__).resolve().parent / "data" / "symbols"

# category (translatable) -> Lucide icon names, in the order shown in the editor
CATEGORIES: dict[str, tuple[str, ...]] = {
    N_("Media"): (
        "play", "pause", "square", "circle-dot", "skip-back", "skip-forward", "rewind", "fast-forward",
        "repeat", "shuffle", "volume-2", "volume-1", "volume-x", "mic", "mic-off", "video", "video-off",
        "camera", "headphones", "music", "radio", "cast", "monitor-play", "list-music",
    ),
    N_("Editing"): (
        "copy", "clipboard-paste", "scissors", "undo-2", "redo-2", "save", "search", "replace", "trash-2",
        "pencil", "plus", "minus", "x", "check", "type", "bold", "italic", "underline", "strikethrough",
        "list", "list-ordered", "indent-increase", "indent-decrease", "text-select", "message-square-quote",
    ),
    N_("Files"): (
        "file", "file-plus", "file-text", "files", "folder", "folder-open", "folder-plus", "download",
        "upload", "archive", "printer", "image", "link", "external-link", "share-2", "paperclip",
    ),
    N_("Navigation"): (
        "arrow-left", "arrow-right", "arrow-up", "arrow-down", "chevron-left", "chevron-right",
        "chevrons-left", "chevrons-right", "house", "refresh-cw", "rotate-ccw", "rotate-cw", "zoom-in",
        "zoom-out", "maximize-2", "minimize-2", "fullscreen", "panel-left", "panel-right", "panel-bottom",
        "layout-grid", "columns-2", "app-window", "monitor", "history", "move", "map", "car",
    ),
    N_("Development"): (
        "terminal", "square-terminal", "code", "braces", "bug", "bug-play", "git-branch",
        "git-commit-horizontal", "git-pull-request", "git-merge", "git-compare", "circle-play",
        "step-forward", "database", "server", "package", "cpu", "rocket", "flask-conical", "wrench",
        "hammer", "puzzle",
    ),
    N_("Communication"): (
        "mail", "send", "inbox", "reply", "reply-all", "forward", "message-square", "phone", "phone-off",
        "bell", "bell-off", "at-sign", "users", "user", "calendar", "clock", "timer", "alarm-clock",
    ),
    N_("System"): (
        "settings", "power", "lock", "lock-open", "eye", "eye-off", "sun", "moon", "sun-moon", "wifi",
        "battery-full", "keyboard", "mouse-pointer-2", "log-out", "cloud", "globe",
        "screen-share", "app-window-mac", "info", "circle-help", "triangle-alert", "circle-check",
        "circle-x", "ban", "scan",
    ),
    N_("Other"): (
        "star", "heart", "bookmark", "flag", "tag", "pin", "zap", "lightbulb", "coffee", "layers",
        "sparkles", "smile", "thumbs-up", "thumbs-down", "hash", "gamepad-2", "palette", "brush",
        "shopping-cart", "map-pin", "trophy", "gift", "hand", "circle",
    ),
}


def all_names() -> list[str]:
    return [name for names in CATEGORIES.values() for name in names]


def is_symbol(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def symbol_path(value: str) -> Path:
    """``"symbol:play"`` -> the bundled PNG (which may not exist for unknown names)."""
    name = value.removeprefix(PREFIX).strip().lower()
    return SYMBOLS_DIR / f"{Path(name).name}.png"


def is_symbol_file(path: Path) -> bool:
    return path.parent == SYMBOLS_DIR


def tinted(image: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """The white symbol ``image`` drawn in ``color``."""
    out = Image.new("RGBA", image.size, (*color, 255))
    out.putalpha(image.getchannel("A"))
    return out
