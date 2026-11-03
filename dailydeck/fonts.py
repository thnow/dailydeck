"""Font lookup by name, so configs and exported profiles stay portable.

A font is configured as ``"Family:Style"`` (e.g. ``"Ubuntu:Bold"``) or as a
path to a font file.
"""

import functools
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".otc")

_FONT_DIRS = {
    "win32": [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
              Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/Windows/Fonts"],
    "darwin": [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library/Fonts"],
}


@dataclass(frozen=True)
class ResolvedFont:
    path: str
    index: int = 0
    instance: int = 0  # 1-based named instance of a variable font (e.g. "Bold"), 0 = default


def font_spec(family: str, style: str) -> str:
    return f"{family}:{style}" if style else family


def split_spec(spec: str) -> tuple[str, str]:
    family, _, style = spec.partition(":")
    return family.strip(), style.strip()


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


@functools.lru_cache(maxsize=1)
def list_fonts() -> list[tuple[str, str]]:
    """Sorted (family, style) pairs of installed scalable fonts."""
    if _is_linux():
        try:
            out = subprocess.run(
                ["fc-list", ":lang=de", "--format", "%{family[0]}\t%{style[0]}\t%{file}\n"],
                capture_output=True, text=True, timeout=10, check=True,
            ).stdout
            fonts = {
                (family, style)
                for family, style, file in (line.split("\t") for line in out.splitlines() if line.count("\t") == 2)
                if file.lower().endswith(FONT_SUFFIXES)
            }
            return sorted(fonts, key=lambda f: (f[0].lower(), f[1].lower()))
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("fc-list failed: %s", e)
    return sorted(_scan_index(), key=lambda f: (f[0].lower(), f[1].lower()))


@functools.lru_cache(maxsize=1)
def _scan_index() -> dict[tuple[str, str], str]:
    """(family, style) -> file, by reading the font files (Windows/macOS)."""
    from PIL import ImageFont

    index: dict[tuple[str, str], str] = {}
    for directory in _FONT_DIRS.get(sys.platform, []):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() not in FONT_SUFFIXES:
                continue
            try:
                family, style = ImageFont.truetype(str(path), 12).getname()
            except OSError:
                continue
            if family:
                index.setdefault((family, style or ""), str(path))
    return index


@functools.lru_cache(maxsize=64)
def resolve_font(spec: str | None) -> ResolvedFont | None:
    if not spec:
        return None
    if os.path.isfile(os.path.expanduser(spec)):
        return ResolvedFont(os.path.expanduser(spec))
    family, style = split_spec(spec)
    if _is_linux():
        pattern = f"{family}:style={style}" if style else family
        try:
            out = subprocess.run(
                ["fc-match", "-f", "%{family}\t%{file}\t%{index}", pattern],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout
            families, file, index = out.split("\t")
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            log.warning("fc-match failed for %r: %s", spec, e)
            return None
        # fc-match always answers; reject substitutes for fonts that are not installed
        if family.lower() not in (f.lower() for f in families.split(",")):
            log.warning("font %r is not installed, using the default", spec)
            return None
        # fontconfig encodes the named instance of variable fonts in the upper 16 bits
        index = int(index or 0)
        return ResolvedFont(file, index & 0xFFFF, index >> 16)
    for (fam, sty), path in _scan_index().items():
        if fam.lower() == family.lower() and (not style or sty.lower() == style.lower()):
            return ResolvedFont(path)
    log.warning("font %r not found, using the default", spec)
    return None
