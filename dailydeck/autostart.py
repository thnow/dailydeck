"""Start the tray app at login.

Linux:   ~/.config/autostart/io.github.thnow.dailydeck.desktop (XDG autostart)
Windows: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
macOS:   ~/Library/LaunchAgents/io.github.thnow.dailydeck.plist
"""

import os
import plistlib
import shlex
import shutil
import sys
from pathlib import Path

APP_ID = "dailydeck"


def _python() -> str:
    exe = Path(sys.executable)
    if sys.platform == "win32" and exe.name.lower() == "python.exe":
        pythonw = exe.with_name("pythonw.exe")  # no console window
        if pythonw.exists():
            return str(pythonw)
    return str(exe)


def command() -> list[str]:
    """How to start the tray app, for this kind of installation."""
    if getattr(sys, "frozen", False):  # PyInstaller build (macOS app, Windows installer)
        return [sys.executable, "--tray"]
    # deb / pip; not on Windows, where pip's dailydeck.exe would open a console window
    if sys.platform != "win32" and (exe := shutil.which("dailydeck")):
        return [exe, "--tray"]
    return [_python(), "-m", "dailydeck", "--tray"]  # source checkout (pip install -e) / Windows venv


def _desktop_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / f"{APP_ID}.desktop"


def _plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / "io.github.thnow.dailydeck.plist"


def is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
                winreg.QueryValueEx(key, APP_ID)
            return True
        except OSError:
            return False
    if sys.platform == "darwin":
        return _plist().exists()
    return _desktop_file().exists()


def set_enabled(enabled: bool) -> None:
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, " ".join(f'"{a}"' for a in command()))
            else:
                try:
                    winreg.DeleteValue(key, APP_ID)
                except FileNotFoundError:
                    pass
        return
    if sys.platform == "darwin":
        path = _plist()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                plistlib.dump({
                    "Label": "io.github.thnow.dailydeck",
                    "ProgramArguments": command(),
                    "RunAtLoad": True,
                    "ProcessType": "Interactive",
                }, f)
        else:
            path.unlink(missing_ok=True)
        return
    path = _desktop_file()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Daily Deck\n"
            "Comment=Stream Deck zeigt die Tastenkürzel des aktiven Fensters (Daily Deck)\n"
            f"Exec={shlex.join(command())}\n"
            "Icon=io.github.thnow.dailydeck\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    else:
        path.unlink(missing_ok=True)
