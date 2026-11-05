import fnmatch
import hashlib
import os
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .focus import WindowInfo
from .keys import Chord, ShortcutError, parse_shortcut


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Button:
    label: str = ""
    chords: tuple[Chord, ...] = ()
    color: str | None = None
    text_color: str | None = None
    icon: Path | None = None
    font_size: int | None = None

    @property
    def empty(self) -> bool:
        return not self.chords and not self.label and not self.icon


@dataclass(frozen=True)
class Profile:
    name: str
    match: tuple[str, ...] = ()
    title: re.Pattern | None = None
    default: bool = False
    color: str | None = None
    text_color: str | None = None
    icon: Path | None = None  # overrides the automatically found app icon
    font: str | None = None  # "Family:Style" or file, overrides settings.font
    buttons: tuple[Button, ...] = ()

    def matches(self, window: WindowInfo) -> bool:
        if not self.match and self.title is None:
            return False
        if self.match and not any(
            fnmatch.fnmatchcase(i.lower(), pattern) for i in window.ids for pattern in self.match
        ):
            return False
        return self.title is None or bool(self.title.search(window.title))


@dataclass(frozen=True)
class Settings:
    brightness: int = 60
    show_keys: bool = True
    poll_interval: float = 0.25
    font: str | None = None  # "Family:Style" (e.g. "Ubuntu:Bold") or a font file
    background: str = "#1e1e1e"
    text_color: str = "#ffffff"
    focus_backend: str = "auto"
    key_backend: str = "auto"
    keyboard_layout: str | None = None
    keyboard_variant: str | None = None
    # application icon drawn across the whole deck
    app_icon: bool = True
    app_icon_brightness: float = 0.7  # behind the buttons, 0..1
    app_icon_flash: float = 0.6  # seconds at full brightness after a switch, 0 = off
    button_opacity: float = 0.35  # button colour over the icon, 0..1
    key_spacing: int = 36  # gap between keys in pixels, so the icon looks continuous


@dataclass
class Config:
    path: Path
    settings: Settings
    profiles: list[Profile] = field(default_factory=list)

    def profile_for(self, window: WindowInfo) -> Profile | None:
        for profile in self.profiles:
            if profile.matches(window):
                return profile
        return self.default_profile

    @property
    def default_profile(self) -> Profile | None:
        return next((p for p in self.profiles if p.default), None)


DATA_DIR = Path(__file__).resolve().parent / "data"


def config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "dailydeck"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "dailydeck"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "dailydeck"


# SHA-256 (with \n line ends) of bundled default configs of earlier releases. A user config
# that is still such an untouched copy is replaced by the current default, so new profiles
# arrive on every machine; edited configs are never touched.
PREVIOUS_DEFAULTS = {
    "c19dadc531305b2557a9fb0f4071ffda5a65c5d58c88be2677337bedf0d425c7",  # 0.1.0
}


def _content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def default_config_path() -> Path:
    """The user's config file; created from (or updated to) the bundled default."""
    user = config_dir() / "config.toml"
    bundled = DATA_DIR / "default_config.toml"
    if not user.exists():
        user.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundled, user)
    else:
        try:
            outdated = _content_hash(user) in PREVIOUS_DEFAULTS
        except OSError:
            outdated = False
        if outdated:
            shutil.copy2(user, user.with_name(user.name + ".bak"))
            shutil.copyfile(bundled, user)
    return user


def read_config_data(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e


def load_config(path: Path) -> Config:
    return parse_config(read_config_data(path), path)


def parse_settings(data: dict) -> Settings:
    s = data.get("settings", {})
    kb = data.get("keyboard", {})
    settings = Settings(
        brightness=int(s.get("brightness", Settings.brightness)),
        show_keys=bool(s.get("show_keys", Settings.show_keys)),
        poll_interval=float(s.get("poll_interval", Settings.poll_interval)),
        font=s.get("font"),
        background=s.get("background", Settings.background),
        text_color=s.get("text_color", Settings.text_color),
        focus_backend=s.get("focus_backend", Settings.focus_backend),
        key_backend=s.get("key_backend", Settings.key_backend),
        keyboard_layout=kb.get("layout"),
        keyboard_variant=kb.get("variant"),
        app_icon=bool(s.get("app_icon", Settings.app_icon)),
        app_icon_brightness=float(s.get("app_icon_brightness", Settings.app_icon_brightness)),
        app_icon_flash=float(s.get("app_icon_flash", Settings.app_icon_flash)),
        button_opacity=float(s.get("button_opacity", Settings.button_opacity)),
        key_spacing=int(s.get("key_spacing", Settings.key_spacing)),
    )
    return settings


def parse_config(data: dict, path: Path) -> Config:
    """Validate raw TOML data (as read or as edited by the GUI)."""
    try:
        settings = parse_settings(data)
    except (TypeError, ValueError) as e:
        raise ConfigError(f"[settings]: {e}") from e
    profiles = [load_profile(p, i, path.parent) for i, p in enumerate(data.get("profiles", []))]
    return Config(path=path, settings=settings, profiles=profiles)


def load_profile(data: dict, index: int, base_dir: Path) -> Profile:
    name = data.get("name") or f"profile #{index + 1}"
    match = data.get("match", [])
    if isinstance(match, str):
        match = [match]
    title = data.get("title")
    try:
        title_re = re.compile(title, re.IGNORECASE) if title else None
    except re.error as e:
        raise ConfigError(f"profile {name!r}: invalid title regex: {e}") from e
    buttons = []
    for j, b in enumerate(data.get("buttons", [])):
        try:
            buttons.append(load_button(b, base_dir))
        except ShortcutError as e:
            raise ConfigError(f"profile {name!r}, button {j + 1} ({b.get('label', '')!r}): {e}") from e
    return Profile(
        name=name,
        match=tuple(m.lower() for m in match),
        title=title_re,
        default=bool(data.get("default", False)),
        color=data.get("color"),
        text_color=data.get("text_color"),
        icon=_resolve(base_dir, data.get("icon")),
        font=data.get("font") or None,
        buttons=tuple(buttons),
    )


# per-system variants of a button's "keys"; a button without one uses "keys"
PLATFORMS = {"macos": "darwin", "windows": "win32", "linux": "linux"}
PLATFORM_LABELS = {"macos": "macOS", "windows": "Windows", "linux": "Linux"}
KEY_FIELDS = ("keys", *(f"keys_{p}" for p in PLATFORMS))


def current_platform() -> str:
    """This system as used in ``keys_<platform>``: "macos", "windows" or "linux"."""
    return {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")


def button_chords(data: dict, platform: str | None = None) -> tuple[Chord, ...]:
    """Chords a button sends on ``platform``; every variant is validated, wherever it applies."""
    platform = platform or current_platform()
    chosen: tuple[Chord, ...] = ()
    if keys := data.get("keys"):
        chosen = parse_shortcut(keys, PLATFORMS[platform])
    for name, sys_name in PLATFORMS.items():
        if variant := data.get(f"keys_{name}"):
            try:
                chords = parse_shortcut(variant, sys_name)
            except ShortcutError as e:
                raise ShortcutError(f"keys_{name}: {e}") from e
            if name == platform:
                chosen = chords
    return chosen


def load_button(data: dict, base_dir: Path) -> Button:
    return Button(
        label=data.get("label", ""),
        chords=button_chords(data),
        color=data.get("color"),
        text_color=data.get("text_color"),
        icon=_resolve(base_dir, data.get("icon")),
        font_size=data.get("font_size") or None,
    )


def _resolve(base_dir: Path, path: str | None) -> Path | None:
    return (base_dir / Path(path).expanduser()) if path else None
