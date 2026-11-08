"""Render the built-in key symbols (dailydeck/symbols.py) from Lucide into dailydeck/data/symbols/.

    python scripts/build-symbols.py

Downloads the SVGs of a pinned lucide-static release and renders them as white
192 px PNGs with QtSvg, so every system can show them without an SVG library.
"""

import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QByteArray, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

from dailydeck.symbols import SYMBOLS_DIR, all_names  # noqa: E402

VERSION = "1.61.0"
BASE = f"https://cdn.jsdelivr.net/npm/lucide-static@{VERSION}"
SIZE = 192
STROKE = "2.25"  # Lucide's default is 2; a little bolder reads better on the small keys


def fetch(path: str) -> bytes:
    with urllib.request.urlopen(f"{BASE}/{path}", timeout=30) as response:
        return response.read()


def render(svg: bytes) -> QImage:
    text = svg.decode("utf-8")
    text = text.replace("currentColor", "#ffffff")
    text = re.sub(r'stroke-width="[\d.]+"', f'stroke-width="{STROKE}"', text)
    renderer = QSvgRenderer(QByteArray(text.encode("utf-8")))
    if not renderer.isValid():
        raise ValueError("invalid SVG")
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, SIZE, SIZE))
    painter.end()
    return image


def main() -> int:
    QGuiApplication.instance() or QGuiApplication(["build-symbols", "-platform", "offscreen"])
    SYMBOLS_DIR.mkdir(parents=True, exist_ok=True)
    names = all_names()
    if len(set(names)) != len(names):
        print("duplicate names in CATEGORIES", file=sys.stderr)
        return 1
    failed = []
    for name in names:
        try:
            image = render(fetch(f"icons/{name}.svg"))
        except Exception as e:  # noqa: BLE001
            failed.append(f"{name}: {e}")
            continue
        image.save(str(SYMBOLS_DIR / f"{name}.png"))
    wanted = {f"{n}.png" for n in names}
    for stale in SYMBOLS_DIR.glob("*.png"):
        if stale.name not in wanted:
            stale.unlink()
    license_text = fetch("LICENSE").decode("utf-8")
    (SYMBOLS_DIR / "LICENSE").write_text(
        f"The symbols in this directory are rendered from Lucide {VERSION} (https://lucide.dev).\n\n"
        + license_text, encoding="utf-8", newline="\n")
    print(f"{len(names) - len(failed)} symbols written to {SYMBOLS_DIR}")
    for line in failed:
        print("FAILED", line, file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
