"""Moving the configuration into a synchronised folder and back.

The folder is synchronised by something else (Nextcloud, Syncthing, OneDrive,
a Git repository, ...); Daily Deck only reads and writes ``config.toml`` and
``icons/`` there. See ``config.py`` for local.toml and the local settings.
"""

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from . import config
from .config import (
    CONFIG_FILE,
    ConfigError,
    load_config,
    read_config_data,
    read_local,
    split_local,
    write_local,
)
from .i18n import _
from .profile_io import save_config


@dataclass(frozen=True)
class Existing:
    """A config already in the folder (e.g. from another computer)."""

    path: Path
    profiles: int
    modified: float


def existing_config(folder: Path) -> Existing | None:
    path = folder / CONFIG_FILE
    if not path.is_file():
        return None
    try:
        profiles = len(load_config(path).profiles)
    except ConfigError:
        profiles = -1
    return Existing(path, profiles, path.stat().st_mtime)


def _copy_icons(src_dir: Path, dst_dir: Path) -> None:
    src = src_dir / "icons"
    if src.is_dir() and src.resolve() != (dst_dir / "icons").resolve():
        shutil.copytree(src, dst_dir / "icons", dirs_exist_ok=True)


def connect(folder: Path, current: Path, adopt: bool) -> Path:
    """Use ``folder`` for the configuration; returns the new config path.

    ``adopt``: use the config already there (from another computer) and keep
    only this computer's local settings. Otherwise the current configuration
    and its images are copied there.
    """
    folder = folder.expanduser().resolve()
    target = folder / CONFIG_FILE
    if target.resolve() == current.resolve():
        return target
    if not folder.is_dir():
        raise ConfigError(_("Folder not found: {folder}").format(folder=folder))
    data = read_config_data(current)
    shared, local_settings = split_local(data)
    if adopt and not target.is_file():
        raise ConfigError(_("There is no configuration in {folder}.").format(folder=folder))
    if not adopt:
        _copy_icons(current.parent, folder)
    local = read_local()
    local["sync_dir"] = str(folder)
    local["settings"] = local_settings
    write_local(local)
    if not adopt:
        try:
            save_config(data, target)  # splits off the local settings again
        except BaseException:
            local.pop("sync_dir")
            write_local(local)
            raise
    return target


def disconnect(current: Path) -> Path:
    """Stop using the sync folder: copy the configuration back to this computer."""
    target = config.config_dir() / CONFIG_FILE
    data = read_config_data(current)  # shared config + this computer's settings
    _copy_icons(current.parent, target.parent)
    local = read_local()
    local.pop("sync_dir", None)
    local.pop("settings", None)
    write_local(local)
    save_config(data, target)
    return target


def format_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))
