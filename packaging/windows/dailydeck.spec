# PyInstaller spec for the Windows build; run through scripts/build-windows.ps1, which sets
# DAILYDECK_VERSION, DAILYDECK_HIDAPI, DAILYDECK_ICO and DAILYDECK_VERSION_FILE.
#
# One folder, two programs sharing it:
#   Daily Deck.exe  no console: tray app (default) and editor (--gui)
#   dailydeck.exe   console: command line (--print-focus, --dry-run, -v …)
import os

from PyInstaller.utils.hooks import collect_data_files

here = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821 - defined by PyInstaller

datas = [(src, dst) for src, dst in collect_data_files("dailydeck")
         if "gnome-extension" not in src and not src.endswith((".pot", ".dll"))]

a = Analysis(  # noqa: F821
    [os.path.join(here, "entry.py")],
    # dailydeck/__init__.py puts this directory on PATH for python-elgato-streamdeck
    binaries=[(os.environ["DAILYDECK_HIDAPI"], "dailydeck/data/win32")],
    datas=datas,
    hiddenimports=["dailydeck.focus.windows", "dailydeck.keys.windows_sendinput", "dailydeck.tray",
                   "dailydeck.gui"],
    excludes=["tkinter", "evdev", "jeepney", "pytest", "ruff", "pynput", "PySide6.QtNetwork",
              # backends of the other systems
              "dailydeck.focus.macos", "dailydeck.focus.gnome", "dailydeck.focus.x11",
              "dailydeck.keys.macos_quartz", "dailydeck.keys.linux_uinput", "dailydeck.keys.xkb"],
)
# not needed by a widgets-only app: software OpenGL fallback, Qt networking, AVIF images
UNUSED = ("opengl32sw.dll", "qt6network.dll", "_avif.")
a.binaries = [b for b in a.binaries if not any(u in b[0].lower() for u in UNUSED)]
pyz = PYZ(a.pure)  # noqa: F821


def program(name: str, console: bool):
    return EXE(  # noqa: F821
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=console,
        icon=os.environ["DAILYDECK_ICO"],
        version=os.environ["DAILYDECK_VERSION_FILE"],
    )


coll = COLLECT(  # noqa: F821
    program("Daily Deck", console=False),
    program("dailydeck", console=True),
    a.binaries,
    a.datas,
    name="Daily Deck",
)
