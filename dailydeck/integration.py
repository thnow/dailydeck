"""Desktop integration checks run by the tray app at startup (GNOME).

- The focus extension (``dailydeck-focus@thnow.github.io``) is shipped system-wide
  by the .deb; for pip/source installs it is copied to the user's extension
  directory. Either way it has to be enabled per user, and GNOME on Wayland
  loads new extensions only after logging in again.
- The tray icon needs an AppIndicator extension on GNOME.
"""

import ast
import logging
import os
import shutil
import subprocess
from pathlib import Path

from .config import DATA_DIR

log = logging.getLogger(__name__)

FOCUS_EXTENSION = "dailydeck-focus@thnow.github.io"
APPINDICATOR_EXTENSIONS = ("ubuntu-appindicators@ubuntu.com", "appindicatorsupport@rgcjonas.gmail.com")


def is_gnome() -> bool:
    return "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def _run(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("%s failed: %s", args[0], e)
        return None


def _extension_dirs() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    system = [Path(d) for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    return [d / "gnome-shell" / "extensions" for d in [home, *system]]


def extension_installed(uuid: str) -> bool:
    return any((d / uuid / "metadata.json").exists() for d in _extension_dirs())


def extension_state(uuid: str) -> str | None:
    """GNOME's state ("ACTIVE", "INACTIVE", ...) or None if the running shell does not know it."""
    result = _run("gnome-extensions", "info", uuid)
    if result is None or result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        key, _, value = line.strip().partition(":")
        if key == "State":
            return value.strip().upper()
    return None


def _gsettings_list(key: str) -> list[str]:
    result = _run("gsettings", "get", "org.gnome.shell", key)
    if result is None or result.returncode != 0:
        return []
    try:
        return list(ast.literal_eval(result.stdout.strip().removeprefix("@as ")))
    except (ValueError, SyntaxError):
        return []


def _gsettings_set_list(key: str, values: list[str]) -> None:
    _run("gsettings", "set", "org.gnome.shell", key, str(values))


def enable_extension(uuid: str) -> None:
    """Enable now if the shell knows the extension, otherwise from the next login."""
    disabled = _gsettings_list("disabled-extensions")
    if uuid in disabled:
        _gsettings_set_list("disabled-extensions", [u for u in disabled if u != uuid])
    result = _run("gnome-extensions", "enable", uuid)
    if result is None or result.returncode != 0:
        enabled = _gsettings_list("enabled-extensions")
        if uuid not in enabled:
            _gsettings_set_list("enabled-extensions", enabled + [uuid])


def _install_user_copy() -> bool:
    """Copy the bundled extension to the user's directory (pip/source installs).
    Returns True if files changed."""
    src = DATA_DIR / "gnome-extension" / FOCUS_EXTENSION
    dst = _extension_dirs()[0] / FOCUS_EXTENSION
    changed = False
    dst.mkdir(parents=True, exist_ok=True)
    for file in src.iterdir():
        target = dst / file.name
        if not target.exists() or target.read_bytes() != file.read_bytes():
            shutil.copy2(file, target)
            changed = True
    return changed


def ensure_focus_extension() -> str | None:
    """Make sure the focus extension is installed and enabled.

    Returns a message for the user, or None if everything is fine already.
    """
    if not is_gnome():
        return None
    system_wide = any((d / FOCUS_EXTENSION).exists() for d in _extension_dirs()[1:])
    updated = False
    if not system_wide:
        try:
            updated = _install_user_copy()
        except OSError as e:
            return f"Die GNOME-Erweiterung zur Fenstererkennung konnte nicht installiert werden: {e}"
    state = extension_state(FOCUS_EXTENSION)
    if state == "ACTIVE" and not updated:
        return None
    enable_extension(FOCUS_EXTENSION)
    if extension_state(FOCUS_EXTENSION) == "ACTIVE" and not updated:
        return None
    return ("Die Fenstererkennung für GNOME wurde eingerichtet. Sie ist nach dem nächsten Ab- und "
            "Anmelden aktiv – bis dahin zeigt das Deck nur das Standardprofil.")


def appindicator_extension() -> tuple[str | None, bool]:
    """(uuid of an installed AppIndicator extension or None, is it active)."""
    for uuid in APPINDICATOR_EXTENSIONS:
        if extension_installed(uuid):
            return uuid, extension_state(uuid) == "ACTIVE"
    return None, False
