# PyInstaller spec for "Daily Deck.app"; run through scripts/build-macos.sh,
# which sets DAILYDECK_VERSION, DAILYDECK_HIDAPI, DAILYDECK_ICNS and DAILYDECK_MACOS_MIN.
import os

from PyInstaller.utils.hooks import collect_data_files

version = os.environ["DAILYDECK_VERSION"]
here = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821 - defined by PyInstaller

datas = [(src, dst) for src, dst in collect_data_files("dailydeck")
         if "gnome-extension" not in src and not src.endswith(".pot")]

a = Analysis(  # noqa: F821
    [os.path.join(here, "entry.py")],
    binaries=[(os.environ["DAILYDECK_HIDAPI"], ".")],
    datas=datas,
    hiddenimports=["dailydeck.focus.macos", "dailydeck.keys.macos_quartz"],
    excludes=["tkinter", "evdev", "jeepney", "pytest", "ruff"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Daily Deck",
    console=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Daily Deck")  # noqa: F821
app = BUNDLE(  # noqa: F821
    coll,
    name="Daily Deck.app",
    icon=os.environ["DAILYDECK_ICNS"],
    bundle_identifier="io.github.thnow.dailydeck",
    version=version,
    info_plist={
        "CFBundleDisplayName": "Daily Deck",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "LSMinimumSystemVersion": os.environ["DAILYDECK_MACOS_MIN"],
        "LSUIElement": True,  # menu bar app: no Dock icon
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "© Thomas Wittmann, GPL-3.0-or-later. Not affiliated with Elgato or Corsair.",
    },
)
