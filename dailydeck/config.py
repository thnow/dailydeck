import fnmatch
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import symbols
from .focus import WindowInfo
from .i18n import _, pgettext
from .keys import Chord, ShortcutError, parse_shortcut

log = logging.getLogger(__name__)


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
    language: str = "auto"  # "auto" = system language, or a code such as "de"


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
    "dafb558315d12afee0edc866d402c51b9aefcdf72619830a837679458530235f",  # 0.2.0
    "3143aef5a3ccb1b9ded324bdacbdbd1c2daaea46487cc48270911429b5ae1e0d",  # 0.3.0, English
    "4bd6efbd22b8a90fb201c92a585a07afa526720ca88be7bb7440c93ea076ed1d",  # 0.3.0, German
}
# From 0.3 on the default is written translated (localized_default_config); when it changes,
# add the hash of its rendering in every language here.
SOFT_HYPHEN = "\u00ad"
_NAME_OR_LABEL = re.compile(r'^(\s*(?:name|label)\s*=\s*)"((?:[^"\\]|\\.)*)"', re.M)


def localized_default_config() -> str:
    """The bundled default config with profile names and labels in the current language."""
    def translate(m: re.Match) -> str:
        value = json.loads(f'"{m.group(2)}"')  # TOML basic strings use JSON's escapes
        text = pgettext("default config", value.replace(SOFT_HYPHEN, "|")).replace("|", SOFT_HYPHEN)
        return m.group(1) + json.dumps(text, ensure_ascii=False)

    return _NAME_OR_LABEL.sub(translate, (DATA_DIR / "default_config.toml").read_text(encoding="utf-8"))


def _content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# ------------------------------------------------------------- sync folder
#
# The configuration can live in a folder synchronised by Nextcloud, Git, ... .
# ``local.toml`` in the local config directory points to it and holds what
# belongs to this computer only: the LOCAL_SETTINGS. When the config is shared,
# these are read from and written to local.toml instead of config.toml.

LOCAL_FILE = "local.toml"
CONFIG_FILE = "config.toml"
LOCAL_SETTINGS = ("brightness", "language", "font", "focus_backend", "key_backend",
                  "keyboard_layout", "keyboard_variant", "poll_interval")
_LOCAL_HEADER = ("# Daily Deck – settings of this computer only (not synchronised)\n"
                 "# sync_dir: folder with the shared config.toml (Nextcloud, Git, ...)\n\n")


def local_path() -> Path:
    return config_dir() / LOCAL_FILE


def read_local() -> dict:
    """Contents of local.toml; empty if missing or unreadable."""
    try:
        with open(local_path(), "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        log.warning("ignoring %s: %s", local_path(), e)
        return {}
    if not isinstance(data.get("settings", {}), dict):
        data.pop("settings")
    return data


def write_local(data: dict) -> None:
    import tempfile

    import tomli_w

    path = local_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in data.items() if v not in (None, {}, "")}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".local-", suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_LOCAL_HEADER + tomli_w.dumps(data))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def sync_dir() -> Path | None:
    """The configured sync folder (whether it is reachable or not)."""
    value = read_local().get("sync_dir")
    return Path(value).expanduser() if isinstance(value, str) and value.strip() else None


def is_shared(path: Path) -> bool:
    """Whether ``path`` is the config in the sync folder (local settings apply)."""
    folder = sync_dir()
    if folder is None:
        return False
    try:
        return path.resolve() == (folder / CONFIG_FILE).resolve()
    except OSError:
        return False


def split_local(data: dict) -> tuple[dict, dict]:
    """(data without local settings, the local settings)."""
    settings = dict(data.get("settings") or {})
    local = {k: settings.pop(k) for k in LOCAL_SETTINGS if k in settings}
    shared = dict(data)
    if settings:
        shared["settings"] = settings
    else:
        shared.pop("settings", None)
    return shared, local


def conflict_files(path: Path) -> list[Path]:
    """Conflict copies of ``path`` left by sync tools (Nextcloud, Syncthing, Dropbox, OneDrive)."""
    stem = path.stem.lower()
    try:
        candidates = list(path.parent.iterdir())
    except OSError:
        return []
    return sorted(
        f for f in candidates
        if f != path and f.suffix.lower() == path.suffix.lower() and f.name.lower().startswith(stem)
        and ("conflict" in f.name.lower() or f.name.lower().startswith(f"{stem}-{_hostname()}"))
    )


def _hostname() -> str:
    import socket

    return socket.gethostname().lower()


def active_config_path() -> Path:
    """Where the config is read from: the sync folder if set up and reachable, else locally.

    Never creates anything in the sync folder – on a new computer the sync
    client may not have downloaded the shared config yet."""
    folder = sync_dir()
    if folder is not None:
        shared = folder / CONFIG_FILE
        if shared.is_file():
            return shared
        log.warning("sync folder %s has no %s (yet); using the local configuration", folder, CONFIG_FILE)
    return config_dir() / CONFIG_FILE


def default_config_path() -> Path:
    """The user's config file; created from (or updated to) the bundled default.

    Call ``setup_language`` first, so a new file gets the user's language."""
    user = active_config_path()
    if not user.exists():
        user.parent.mkdir(parents=True, exist_ok=True)
        user.write_text(localized_default_config(), encoding="utf-8", newline="\n")
    else:
        try:
            outdated = _content_hash(user) in PREVIOUS_DEFAULTS
        except OSError:
            outdated = False
        if outdated:
            shutil.copy2(user, user.with_name(user.name + ".bak"))
            user.write_text(localized_default_config(), encoding="utf-8", newline="\n")
    return user


def setup_language(config_path: Path | None = None) -> str:
    """Activates the language from the config's settings (or the system's)."""
    from . import i18n

    path = config_path or active_config_path()
    preferred = read_local().get("settings", {}).get("language") if is_shared(path) else None
    if isinstance(preferred, str):
        return i18n.setup(preferred)
    return i18n.setup_from_config(path)


def read_config_data(path: Path) -> dict:
    """The config as stored; for the shared config, with this computer's local settings."""
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as e:
        raise ConfigError(_("cannot read {file}: {error}").format(file=path, error=e)) from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    if is_shared(path):
        local = {k: v for k, v in read_local().get("settings", {}).items() if k in LOCAL_SETTINGS}
        if local:
            data["settings"] = {**(data.get("settings") or {}), **local}
    return data


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
        language=str(s.get("language", Settings.language)),
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
        raise ConfigError(_("profile “{name}”: invalid window title expression: {error}").format(
            name=name, error=e)) from e
    buttons = []
    for j, b in enumerate(data.get("buttons", [])):
        try:
            buttons.append(load_button(b, base_dir))
        except ShortcutError as e:
            raise ConfigError(_("profile “{name}”, key {number} (“{label}”): {error}").format(
                name=name, number=j + 1, label=b.get("label", ""), error=e)) from e
    return Profile(
        name=name,
        match=tuple(m.lower() for m in match),
        title=title_re,
        default=bool(data.get("default", False)),
        color=data.get("color"),
        text_color=data.get("text_color"),
        icon=resolve_icon(base_dir, data.get("icon")),
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
        icon=resolve_icon(base_dir, data.get("icon")),
        font_size=data.get("font_size") or None,
    )


def resolve_icon(base_dir: Path, path: str | None) -> Path | None:
    """An ``icon`` value: a built-in ``symbol:name`` or a path relative to the config."""
    if not path:
        return None
    if symbols.is_symbol(path):
        return symbols.symbol_path(path)
    return base_dir / Path(path).expanduser()
