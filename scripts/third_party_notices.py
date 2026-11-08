#!/usr/bin/env python3
"""Write THIRD-PARTY-NOTICES.txt for a binary build (Windows installer, macOS app).

    <build venv>/python scripts/third_party_notices.py OUTPUT

Run it with the Python of the build environment: it lists every package installed
there (except the build tools), with their license texts, plus Python itself,
hidapi and the LGPL for Qt. Wheel, sdist and the .deb do not need this – they
bundle no third-party code.
"""

import platform
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LICENSES = ROOT / "packaging" / "licenses"
sys.path.insert(0, str(ROOT))
from dailydeck import __version__  # noqa: E402

# in the build venv, but not in the app
BUILD_TOOLS = {"pip", "setuptools", "wheel", "packaging", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph",
               "pefile", "pywin32-ctypes", "macholib", "dailydeck"}

# packages whose wheels carry no license file: name prefix -> text in packaging/licenses/
FALLBACK_LICENSES = {
    "pyobjc": "pyobjc-License.txt",  # MIT, from pyobjc-core/License.txt in the PyObjC repository
}

THANKS = """\
Thank you
=========

Daily Deck stands on the work of many people who share their code freely:
Qt and Qt for Python, which draw the editor and the tray; Pillow, which paints
every key; python-elgato-streamdeck and hidapi, which talk to the device;
Lucide and Feather, whose symbols are on the keys; Python itself; and the
people behind PyInstaller, Inno Setup, PyObjC and all the smaller pieces
listed below. Thank you for your work and for making it available to all of
us – this little tool would not exist without you.

    Thomas Wittmann, author of Daily Deck
"""

HIDAPI = """\
hidapi 0.15.0 (https://github.com/libusb/hidapi)
Bundled as hidapi.dll (Windows) or libhidapi.dylib (macOS), used under the
BSD-style license, one of the three licenses hidapi offers.
"""

QT = """\
Qt 6 (https://www.qt.io) is used through PySide6 and shiboken6 under the GNU
Lesser General Public License version 3, whose text follows below (it refers
to the GNU General Public License version 3, the license of Daily Deck itself,
in LICENSE.txt). The Qt libraries are included as separate files and can be
replaced by other builds of the same version. Their source code is available
from https://download.qt.io/official_releases/qt/ and
https://download.qt.io/official_releases/QtForPython/. Third-party components
inside Qt and their licenses are listed at
https://doc.qt.io/qt-6/licenses-used-in-qt.html.
"""


def rule(title: str) -> str:
    return f"\n{'=' * 78}\n{title}\n{'=' * 78}\n\n"


def license_files(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """(file name, text) of the license files a package ships in its metadata."""
    files = []
    for file in dist.files or []:
        name = file.name.lower()
        in_metadata = ".dist-info" in str(file.parent) or ".egg-info" in str(file.parent)
        if "commercial" in name:  # Qt's commercial terms; Daily Deck uses Qt under the LGPL
            continue
        if in_metadata and name.startswith(("license", "licence", "copying", "notice", "authors")):
            try:
                text = Path(file.locate()).read_text(encoding="utf-8", errors="replace")
                files.append((str(file).split("/", 1)[-1], text))
            except OSError:
                continue
    return files


def project_url(meta) -> str | None:
    """The project's home or source page (not its changelog or docs)."""
    urls = {}
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls[label.strip().lower().replace(" ", "")] = url.strip()
    for label in ("homepage", "home", "source", "sourcecode", "repository", "github"):
        if label in urls:
            return urls[label]
    return meta.get("Home-page") or next(iter(urls.values()), None)


def python_license() -> str:
    for candidate in (Path(sys.base_prefix) / "LICENSE.txt",
                      Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
                      Path(sys.base_prefix) / "LICENSE"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    raise SystemExit("license of the Python build not found")


def main(output: Path) -> int:
    packages = sorted(
        (d for d in metadata.distributions() if d.metadata["Name"].lower().replace("_", "-") not in BUILD_TOOLS),
        key=lambda d: d.metadata["Name"].lower(),
    )
    parts = [
        f"Daily Deck {__version__} – third-party notices\n\n"
        "Daily Deck is free software under the GNU General Public License version 3\n"
        "or later (LICENSE.txt). This build includes the software listed below, each\n"
        "under its own license.\n\n",
        THANKS,
        rule("Contents"),
        f"Python {platform.python_version()}\n",
        "hidapi 0.15.0\n",
    ]
    parts += [f"{d.metadata['Name']} {d.version}\n" for d in packages]
    parts.append("Lucide and Feather (key symbols)\n")

    parts += [rule(f"Python {platform.python_version()} (https://www.python.org)"), python_license()]
    parts += [rule("hidapi 0.15.0"), HIDAPI, "\n",
              (LICENSES / "hidapi-LICENSE.txt").read_text(encoding="utf-8"), "\n",
              (LICENSES / "hidapi-LICENSE-bsd.txt").read_text(encoding="utf-8")]

    missing = []
    for dist in packages:
        meta = dist.metadata
        name = meta["Name"]
        license_name = meta.get("License-Expression") or meta.get("License") or ""
        header = f"{name} {dist.version}"
        if url := project_url(meta):
            header += f" ({url})"
        parts.append(rule(header))
        if license_name and len(license_name) < 200:
            parts.append(f"License: {license_name}\n\n")
        texts = license_files(dist)
        if not texts:
            fallback = next((f for prefix, f in FALLBACK_LICENSES.items() if name.lower().startswith(prefix)), None)
            if fallback:
                texts = [(f"{fallback} (from the project's repository)",
                          (LICENSES / fallback).read_text(encoding="utf-8"))]
        for file_name, text in texts:
            parts += [f"--- {file_name}\n\n", text.strip(), "\n\n"]
        if name.lower().replace("_", "-") in ("pyside6-essentials", "pyside6", "shiboken6"):
            parts.append(QT)
        elif not texts:
            missing.append(name)

    parts += [rule("Lucide and Feather – key symbols (https://lucide.dev)"),
              (ROOT / "dailydeck" / "data" / "symbols" / "LICENSE").read_text(encoding="utf-8")]
    parts += [rule("GNU Lesser General Public License, version 3 (Qt, PySide6, shiboken6)"),
              (LICENSES / "LGPL-3.0.txt").read_text(encoding="utf-8")]
    if missing:
        print("no license file in the metadata of: " + ", ".join(missing), file=sys.stderr)
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(parts), encoding="utf-8", newline="\r\n" if sys.platform == "win32" else "\n")
    print(f"{output}: {len(packages)} packages, Python, hidapi, Qt, key symbols")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(Path(sys.argv[1])))
