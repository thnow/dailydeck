"""Finding and loading application icons.

Linux:   desktop file (by id or StartupWMClass) -> Icon= -> icon theme lookup.
macOS:   bundle id -> .app bundle -> CFBundleIconFile (.icns).
Windows: exe name -> path of a running process (or the App Paths registry) ->
         icon resource, extracted once to a PNG in the cache directory.
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
        if sys.platform == "win32":
            return _find_windows(tuple(ids))
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


# ------------------------------------------------------------------- Windows

def _windows_cache_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "dailydeck" / "icons"


def _running_exe_paths() -> dict[str, str]:
    """lower-case exe name -> full path, for the running processes we may query."""
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return {}
    paths: dict[str, str] = {}
    try:
        entry = PROCESSENTRY32W(dwSize=ctypes.sizeof(PROCESSENTRY32W))
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            name = entry.szExeFile.lower()
            if name not in paths:
                handle = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)  # QUERY_LIMITED_INFORMATION
                if handle:
                    size = wintypes.DWORD(1024)
                    buf = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                        paths[name] = buf.value
                    kernel32.CloseHandle(handle)
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return paths


def _app_paths(exe: str) -> str | None:
    import winreg

    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                value = os.path.expandvars(str(winreg.QueryValue(key, None))).strip('"')
                if os.path.isfile(value):
                    return value
        except OSError:
            continue
    return None


def _exe_path(ids: tuple[str, ...]) -> str | None:
    exes = [i.lower() for i in ids if i.lower().endswith(".exe")]
    if not exes:
        return None
    running = _running_exe_paths()
    for exe in exes:
        if path := running.get(exe) or _app_paths(exe):
            return path
    return None


def _extract_exe_icon(exe: str, size: int = 256) -> Image.Image | None:
    """The exe's main icon as RGBA image, ``size`` pixels square."""
    from ctypes import wintypes

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                    ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    user32 = ctypes.WinDLL("user32")
    gdi32 = ctypes.WinDLL("gdi32")
    user32.PrivateExtractIconsW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                            ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
                                            wintypes.UINT, wintypes.UINT]
    user32.PrivateExtractIconsW.restype = wintypes.UINT
    user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(ICONINFO)]
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                ctypes.POINTER(BITMAPINFOHEADER), wintypes.UINT]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]

    hicon = wintypes.HICON()
    icon_id = wintypes.UINT()
    if user32.PrivateExtractIconsW(exe, 0, size, size, ctypes.byref(hicon), ctypes.byref(icon_id), 1, 0) != 1 \
            or not hicon:
        return None
    info = ICONINFO()
    hdc = user32.GetDC(None)
    try:
        if not user32.GetIconInfo(hicon, ctypes.byref(info)) or not info.hbmColor:
            return None

        def bits(bitmap) -> bytes:
            header = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=size, biHeight=-size,
                                      biPlanes=1, biBitCount=32, biCompression=0)  # BI_RGB, top-down
            buf = ctypes.create_string_buffer(size * size * 4)
            if gdi32.GetDIBits(hdc, bitmap, 0, size, buf, ctypes.byref(header), 0) != size:
                raise OSError("GetDIBits failed")
            return buf.raw

        image = Image.frombuffer("RGBA", (size, size), bits(info.hbmColor), "raw", "BGRA", 0, 1).copy()
        if image.getchannel("A").getextrema() == (0, 0):  # icon without alpha channel: use the AND mask
            mask = Image.frombuffer("RGBA", (size, size), bits(info.hbmMask), "raw", "BGRA", 0, 1)
            image.putalpha(mask.convert("L").point(lambda v: 0 if v else 255))
        return image
    finally:
        user32.ReleaseDC(None, hdc)
        for bitmap in (info.hbmColor, info.hbmMask):
            if bitmap:
                gdi32.DeleteObject(bitmap)
        user32.DestroyIcon(hicon)


@functools.lru_cache(maxsize=256)
def _find_windows(ids: tuple[str, ...]) -> Path | None:
    import hashlib

    exe = _exe_path(ids)
    if exe is None:
        return None
    stat = os.stat(exe)
    key = hashlib.sha1(f"{exe.lower()}|{stat.st_mtime_ns}|{stat.st_size}".encode()).hexdigest()[:16]
    png = _windows_cache_dir() / f"{Path(exe).stem.lower()}-{key}.png"
    if png.exists():
        return png
    image = _extract_exe_icon(exe)
    if image is None:
        return None
    png.parent.mkdir(parents=True, exist_ok=True)
    image.save(png)
    return png
