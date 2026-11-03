"""Finding and loading application icons.

Linux:   desktop file (by id or StartupWMClass) -> Icon= -> icon theme lookup.
macOS:   bundle id -> .app bundle -> CFBundleIconFile (.icns).
Windows: not implemented yet (returns None).
"""

import ctypes
import functools
import logging
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)

ICON_EXTENSIONS = (".png", ".svg", ".xpm")


def find_app_icon(ids: Iterable[str]) -> Path | None:
    ids = [i for i in ids if i and not any(c in i for c in "*?[")]
    if not ids:
        return None
    try:
        if sys.platform.startswith("linux"):
            return _find_linux(tuple(ids))
        if sys.platform == "darwin":
            return _find_macos(tuple(ids))
    except Exception:  # noqa: BLE001 - an icon is never worth crashing for
        log.exception("icon lookup failed for %s", ids)
    return None


@functools.lru_cache(maxsize=64)
def load_icon(path: Path, size: int = 512) -> Image.Image | None:
    """Load an icon as RGBA image (SVGs are rendered at ``size``)."""
    try:
        if path.suffix.lower() in (".svg", ".svgz"):
            return _render_svg(path, size)
        with Image.open(path) as img:
            if img.format == "ICNS":
                img.size = max(img.info.get("sizes", [img.size]))[:2]
            return img.convert("RGBA")
    except Exception as e:  # noqa: BLE001
        log.warning("cannot load icon %s: %s", path, e)
        return None


# --------------------------------------------------------------------- Linux

def _data_dirs() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    system = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [home] + [Path(d) for d in system.split(":") if d]
    for extra in ("/var/lib/snapd/desktop", "/var/lib/flatpak/exports/share",
                  str(Path.home() / ".local/share/flatpak/exports/share")):
        if Path(extra) not in dirs:
            dirs.append(Path(extra))
    return [d for d in dirs if d.is_dir()]


@functools.lru_cache(maxsize=1)
def _desktop_index() -> dict[str, list[str]]:
    """lower-case desktop id / StartupWMClass -> Icon= values, best first."""
    strong: dict[str, list[str]] = {}
    weak: dict[str, list[str]] = {}
    for data_dir in _data_dirs():
        apps = data_dir / "applications"
        if not apps.is_dir():
            continue
        for desktop in apps.rglob("*.desktop"):
            entry = _read_desktop_entry(desktop)
            icon = entry.get("Icon")
            if not icon:
                continue
            stem = desktop.stem.lower()
            strong.setdefault(stem, []).append(icon)
            if wm_class := entry.get("StartupWMClass"):
                strong.setdefault(wm_class.lower(), []).append(icon)
            # snaps: "firefox_firefox" -> "firefox"; reverse DNS: "org.gnome.Nautilus" -> "nautilus"
            weak.setdefault(stem.partition("_")[0], []).append(icon)
            weak.setdefault(stem.rsplit(".", 1)[-1], []).append(icon)
    return {k: strong.get(k, []) + weak.get(k, []) for k in strong.keys() | weak.keys()}


def _read_desktop_entry(path: Path) -> dict[str, str]:
    entry: dict[str, str] = {}
    in_section = False
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    in_section = line == "[Desktop Entry]"
                elif in_section and "=" in line:
                    key, _, value = line.partition("=")
                    entry.setdefault(key.strip(), value.strip())
    except OSError:
        pass
    return entry


@functools.lru_cache(maxsize=1)
def _theme_chain() -> list[str]:
    theme = None
    try:
        theme = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "icon-theme"],
            capture_output=True, text=True, timeout=2,
        ).stdout.strip().strip("'") or None
    except (OSError, subprocess.SubprocessError):
        pass
    chain: list[str] = []
    todo = [theme] if theme else []
    while todo:
        name = todo.pop(0)
        if name in chain:
            continue
        chain.append(name)
        for base in _icon_bases():
            index = base / name / "index.theme"
            if index.exists():
                inherits = _read_ini_value(index, "Icon Theme", "Inherits")
                todo += [t.strip() for t in inherits.split(",") if t.strip()]
                break
    if "hicolor" not in chain:
        chain.append("hicolor")
    return chain


def _read_ini_value(path: Path, section: str, key: str) -> str:
    current = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("["):
                current = line[1:-1]
            elif current == section and line.startswith(key + "="):
                return line.split("=", 1)[1]
    return ""


def _icon_bases() -> list[Path]:
    return [Path.home() / ".icons"] + [d / "icons" for d in _data_dirs()]


@functools.lru_cache(maxsize=16)
def _theme_files(theme: str) -> dict[str, list[Path]]:
    """icon name -> files, for all directories of one theme."""
    files: dict[str, list[Path]] = {}
    for base in _icon_bases():
        root = base / theme
        if not root.is_dir():
            continue
        for dirpath, _, names in os.walk(root):
            for name in names:
                stem, ext = os.path.splitext(name)
                if ext in ICON_EXTENSIONS:
                    files.setdefault(stem, []).append(Path(dirpath) / name)
    return files


def _icon_size(path: Path) -> int:
    if path.suffix == ".svg":
        return 10_000  # scalable: as good as it gets
    for part in reversed(path.parts):
        if m := re.fullmatch(r"(\d+)(?:x\d+)?(?:@(\d)x)?", part):
            return int(m.group(1)) * int(m.group(2) or 1)
    return 0


def _find_themed(name: str) -> Path | None:
    if name.startswith("/"):
        return Path(name) if Path(name).exists() else None
    for theme in _theme_chain():
        candidates = [p for p in _theme_files(theme).get(name, []) if "symbolic" not in p.parts]
        if candidates:
            return max(candidates, key=_icon_size)
    for data_dir in _data_dirs():
        for ext in ICON_EXTENSIONS:
            pixmap = data_dir / "pixmaps" / f"{name}{ext}"
            if pixmap.exists():
                return pixmap
    return None


@functools.lru_cache(maxsize=256)
def _find_linux(ids: tuple[str, ...]) -> Path | None:
    index = _desktop_index()
    for app_id in ids:
        for icon in index.get(app_id.lower().removesuffix(".desktop"), []):
            if path := _find_themed(icon):
                return path
    for app_id in ids:  # the id itself may be an icon name
        if path := _find_themed(app_id.removesuffix(".desktop")):
            return path
    return None


class _RsvgRect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double),
                ("width", ctypes.c_double), ("height", ctypes.c_double)]


@functools.lru_cache(maxsize=1)
def _svg_libs():
    rsvg = ctypes.CDLL("librsvg-2.so.2")
    cairo = ctypes.CDLL("libcairo.so.2")
    gobject = ctypes.CDLL("libgobject-2.0.so.0")
    vp = ctypes.c_void_p
    rsvg.rsvg_handle_new_from_file.restype = vp
    rsvg.rsvg_handle_new_from_file.argtypes = [ctypes.c_char_p, vp]
    rsvg.rsvg_handle_render_document.restype = ctypes.c_int
    rsvg.rsvg_handle_render_document.argtypes = [vp, vp, ctypes.POINTER(_RsvgRect), vp]
    cairo.cairo_image_surface_create.restype = vp
    cairo.cairo_image_surface_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    cairo.cairo_create.restype = vp
    cairo.cairo_create.argtypes = [vp]
    cairo.cairo_image_surface_get_data.restype = ctypes.POINTER(ctypes.c_ubyte)
    cairo.cairo_image_surface_get_data.argtypes = [vp]
    cairo.cairo_image_surface_get_stride.restype = ctypes.c_int
    cairo.cairo_image_surface_get_stride.argtypes = [vp]
    for fn in (cairo.cairo_surface_flush, cairo.cairo_destroy, cairo.cairo_surface_destroy, gobject.g_object_unref):
        fn.restype = None
        fn.argtypes = [vp]
    return rsvg, cairo, gobject


def _render_svg(path: Path, size: int) -> Image.Image | None:
    if not sys.platform.startswith("linux"):
        return None
    rsvg, cairo, gobject = _svg_libs()
    handle = rsvg.rsvg_handle_new_from_file(str(path).encode(), None)
    if not handle:
        return None
    surface = cairo.cairo_image_surface_create(0, size, size)  # CAIRO_FORMAT_ARGB32
    cr = cairo.cairo_create(surface)
    try:
        rect = _RsvgRect(0, 0, size, size)
        if not rsvg.rsvg_handle_render_document(handle, cr, ctypes.byref(rect), None):
            return None
        cairo.cairo_surface_flush(surface)
        stride = cairo.cairo_image_surface_get_stride(surface)
        data = ctypes.string_at(cairo.cairo_image_surface_get_data(surface), stride * size)
        # cairo ARGB32 is premultiplied, native endian (little: B G R A)
        return Image.frombuffer("RGBA", (size, size), data, "raw", "BGRa", stride, 1).copy()
    finally:
        cairo.cairo_destroy(cr)
        cairo.cairo_surface_destroy(surface)
        gobject.g_object_unref(handle)


# --------------------------------------------------------------------- macOS

@functools.lru_cache(maxsize=256)
def _find_macos(ids: tuple[str, ...]) -> Path | None:
    import plistlib

    from AppKit import NSWorkspace

    workspace = NSWorkspace.sharedWorkspace()
    for app_id in ids:
        url = workspace.URLForApplicationWithBundleIdentifier_(app_id)
        if url is None:
            continue
        bundle = Path(url.path())
        with open(bundle / "Contents" / "Info.plist", "rb") as f:
            icon = plistlib.load(f).get("CFBundleIconFile")
        if icon:
            path = bundle / "Contents" / "Resources" / icon
            path = path if path.suffix else path.with_suffix(".icns")
            if path.exists():
                return path
    return None
