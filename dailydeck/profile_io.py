"""Saving the config and exchanging single profiles as ``.dailydeck`` files.

A ``.dailydeck`` is a zip archive with

    profile.toml   format = "dailydeck-profile", version = 1, [profile] ...
    icons/...      images referenced by the profile (paths rewritten)
"""

import copy
import io
import os
import re
import shutil
import tempfile
import tomllib
import zipfile
from pathlib import Path

import tomli_w
from PIL import Image

from .config import ConfigError, load_profile, parse_config
from .i18n import _

PROFILE_SUFFIX = ".dailydeck"
FORMAT_NAME = "dailydeck-profile"
FORMAT_VERSION = 1
ICON_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".icns", ".svg"}
MAX_ICON_BYTES = 5 * 1024 * 1024
MAX_PROFILE_BYTES = 1024 * 1024

CONFIG_HEADER = """\
# dailydeck – Konfiguration
# Bearbeitbar mit dem Editor (python -m dailydeck --gui) oder von Hand.
# Das Format ist im config.toml des Projekts ausführlich kommentiert.

"""


def clean_profile(profile: dict) -> dict:
    """Drop empty values and trailing empty buttons (TOML has no null)."""
    out = {k: v for k, v in profile.items() if k != "buttons" and v not in (None, "", [], False)}
    buttons = [{k: v for k, v in b.items() if v not in (None, "", 0)} for b in profile.get("buttons", [])]
    while buttons and not buttons[-1]:
        buttons.pop()
    if buttons:
        out["buttons"] = buttons
    return out


def clean_config(data: dict) -> dict:
    out = {k: copy.deepcopy(v) for k, v in data.items() if k != "profiles"}
    out["profiles"] = [clean_profile(p) for p in data.get("profiles", [])]
    return out


def save_config(data: dict, path: Path) -> None:
    """Validate and atomically write ``data``; keeps one ``.bak`` of the old file."""
    data = clean_config(data)
    parse_config(data, path)  # raises ConfigError
    text = CONFIG_HEADER + tomli_w.dumps(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".bak")
    if path.exists() and not backup.exists():
        shutil.copy2(path, backup)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _slug(name: str) -> str:
    return re.sub(r"[^\w-]+", "-", name, flags=re.UNICODE).strip("-").lower() or "profil"


def _resolve(config_dir: Path, rel: str) -> Path:
    return config_dir / Path(rel).expanduser()


def export_profile(profile: dict, config_dir: Path, target: Path) -> None:
    profile = clean_profile(copy.deepcopy(profile))
    icons: dict[str, Path] = {}

    def pack(rel: str | None) -> str | None:
        if not rel:
            return None
        src = _resolve(config_dir, rel)
        if not src.is_file():
            return None
        for name, existing in icons.items():
            if existing == src:
                return name
        safe = re.sub(r"[^\w.-]+", "_", src.name)
        name = f"icons/{len(icons) + 1}_{safe}"
        icons[name] = src
        return name

    if icon := pack(profile.get("icon")):
        profile["icon"] = icon
    else:
        profile.pop("icon", None)
    for button in profile.get("buttons", []):
        if icon := pack(button.get("icon")):
            button["icon"] = icon
        else:
            button.pop("icon", None)

    doc = {"format": FORMAT_NAME, "version": FORMAT_VERSION, "profile": profile}
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("profile.toml", tomli_w.dumps(doc))
        for name, src in icons.items():
            zf.write(src, name)


def import_profile(source: Path, config_dir: Path) -> dict:
    """Read a ``.dailydeck``; icons are copied to ``config_dir/icons/<name>/``."""
    try:
        with zipfile.ZipFile(source) as zf:
            info = zf.getinfo("profile.toml")
            if info.file_size > MAX_PROFILE_BYTES:
                raise ConfigError(_("profile.toml is too large"))
            doc = tomllib.loads(zf.read(info).decode("utf-8"))
            if doc.get("format") != FORMAT_NAME:
                raise ConfigError(_("not a Daily Deck profile file"))
            if int(doc.get("version", 0)) > FORMAT_VERSION:
                raise ConfigError(_("the profile comes from a newer version"))
            profile = doc.get("profile")
            if not isinstance(profile, dict):
                raise ConfigError(_("profile data missing"))
            profile = clean_profile(profile)

            target_dir = config_dir / "icons" / _slug(profile.get("name", ""))
            n = 1
            while target_dir.exists():
                n += 1
                target_dir = config_dir / "icons" / f"{_slug(profile.get('name', ''))}-{n}"
            extracted: dict[str, str] = {}

            def unpack(name: str | None) -> str | None:
                if not name:
                    return None
                if name in extracted:
                    return extracted[name]
                try:
                    member = zf.getinfo(name)
                except KeyError:
                    return None
                safe = re.sub(r"[^\w.-]+", "_", Path(name).name)
                if not name.startswith("icons/") or Path(safe).suffix.lower() not in ICON_SUFFIXES:
                    return None
                if member.file_size > MAX_ICON_BYTES:
                    return None
                payload = zf.read(member)
                if not _looks_like_image(payload, Path(safe).suffix.lower()):
                    return None
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / safe).write_bytes(payload)
                rel = str((target_dir / safe).relative_to(config_dir))
                extracted[name] = rel
                return rel

            for holder in [profile, *profile.get("buttons", [])]:
                if "icon" in holder:
                    if rel := unpack(holder["icon"]):
                        holder["icon"] = rel
                    else:
                        del holder["icon"]
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError) as e:
        raise ConfigError(_("{file}: invalid profile file ({error})").format(file=source.name, error=e)) from e

    load_profile(profile, 0, config_dir)  # validate shortcuts etc.
    return profile


def _looks_like_image(payload: bytes, suffix: str) -> bool:
    if suffix == ".svg":
        head = payload[:2048].lstrip().lower()
        return head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head
    try:
        with Image.open(io.BytesIO(payload)) as img:
            img.verify()
        return True
    except Exception:  # noqa: BLE001
        return False
