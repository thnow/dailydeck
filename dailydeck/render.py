"""Rendering of key images with Pillow (independent of the device)."""

import functools
import logging
import sys
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFont, ImageOps

from . import symbols
from .appicons import load_icon
from .fonts import ResolvedFont, resolve_font
from .i18n import _

log = logging.getLogger(__name__)

_FONT_CANDIDATES = {
    "linux": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ],
    "win32": ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf"],
    "darwin": ["/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc"],
}

DEFAULT_FONT_NAMES = {"linux": "DejaVu Sans Bold", "win32": "Segoe UI Bold", "darwin": "SF Pro"}


def default_font_name() -> str:
    """What the built-in font is called on this system, for the settings dialog."""
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    return DEFAULT_FONT_NAMES.get(platform) or _("system font")


@functools.cache
def _resolve(preferred: str | None) -> ResolvedFont | None:
    if preferred and (resolved := resolve_font(preferred)):
        return resolved
    platform = "linux" if sys.platform.startswith("linux") else sys.platform
    for candidate in _FONT_CANDIDATES.get(platform, []):
        if Path(candidate).exists():
            return ResolvedFont(candidate)
    return None


@functools.lru_cache(maxsize=512)
def _font(preferred: str | None, size: int) -> ImageFont.ImageFont:
    """``preferred`` is a "Family:Style" name or a font file path."""
    resolved = _resolve(preferred)
    if resolved is None:
        return ImageFont.load_default(size)
    try:
        font = ImageFont.truetype(resolved.path, size, index=resolved.index)
    except OSError as e:
        log.warning("cannot load font %s: %s", resolved.path, e)
        return ImageFont.load_default(size)
    if resolved.instance:
        try:
            font.set_variation_by_name(font.get_variation_names()[resolved.instance - 1])
        except (OSError, ValueError, IndexError) as e:
            log.debug("instance %d of %s: %s", resolved.instance, resolved.path, e)
    return font


SOFT_HYPHEN = "\u00ad"
HYPHENATE_BELOW = 13


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, hyphenate: bool = True) -> list[str]:
    """Greedy word wrap; words may be split at soft hyphens (U+00AD)."""
    if not hyphenate:
        text = text.replace(SOFT_HYPHEN, "")

    def fits(s: str) -> bool:
        return draw.textlength(s, font=font) <= max_width

    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split():
            frags = word.split(SOFT_HYPHEN)
            whole = "".join(frags)
            candidate = f"{current} {whole}" if current else whole
            if fits(candidate):
                current = candidate
                continue
            if current and (fits(whole) or len(frags) == 1):
                lines.append(current)
                current = whole
                continue
            if len(frags) == 1:
                current = whole
                continue
            if current:
                lines.append(current)
                current = ""
            for i, frag in enumerate(frags):
                suffix = "" if i == len(frags) - 1 else "-"
                if current and not fits(current + frag + suffix):
                    lines.append(current + "-")
                    current = frag
                else:
                    current += frag
        lines.append(current)
    return lines


@functools.lru_cache(maxsize=64)
def _notdef_mask(preferred: str | None) -> tuple:
    mask = _font(preferred, 24).getmask("\U0010fffd")
    return mask.size, bytes(mask)


@functools.lru_cache(maxsize=4096)
def _has_glyph(preferred: str | None, char: str) -> bool:
    if char.isspace() or char == SOFT_HYPHEN:
        return True
    mask = _font(preferred, 24).getmask(char)
    return (mask.size, bytes(mask)) != _notdef_mask(preferred)


def _font_for(preferred: str | None, text: str) -> str | None:
    """``preferred`` if it has all glyphs of ``text``, else the default font
    (e.g. arrows and ▶ are missing in many fonts)."""
    if preferred and not all(_has_glyph(preferred, c) for c in text):
        return None
    return preferred


def _fit_text(draw, text: str, font_name: str | None, box: tuple[int, int], max_size: int, min_size: int = 9):
    """Largest font size at which ``text`` fits in ``box`` (wrapped).

    Hyphenation at soft hyphens is only used when the text would otherwise
    have to shrink below ``HYPHENATE_BELOW``.
    """
    width, height = box
    passes = [(False, max(min_size, min(max_size, HYPHENATE_BELOW))), (True, min_size)]
    for hyphenate, smallest in passes:
        for size in range(max_size, smallest - 1, -1):
            font = _font(font_name, size)
            lines = _wrap(draw, text, font, width, hyphenate)
            line_h = size * 1.15
            if len(lines) * line_h <= height and all(draw.textlength(line, font=font) <= width for line in lines):
                return font, lines, line_h
    font = _font(font_name, min_size)
    return font, _wrap(draw, text, font, width), min_size * 1.15


def _contrast_color(color) -> tuple[int, int, int]:
    r, g, b = color[:3]
    return (0, 0, 0) if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else (255, 255, 255)


def render_key(
    size: tuple[int, int],
    label: str = "",
    hint: str = "",
    background: str = "#1e1e1e",
    text_color: str | None = None,
    icon: Path | None = None,
    font: str | None = None,
    font_size: int | None = None,
    pressed: bool = False,
    backdrop: Image.Image | None = None,
    backdrop_brightness: float = 0.45,
    opacity: float = 1.0,
) -> Image.Image:
    """Render one key.

    ``backdrop`` is this key's tile of the application icon (see
    ``deck_backdrop``). It is dimmed by ``backdrop_brightness`` and the button
    colour is laid over it with ``opacity``. A key without label, hint and icon
    shows only the (dimmed) backdrop.
    """
    w, h = size
    bg = ImageColor.getrgb(background)
    fg = ImageColor.getrgb(text_color) if text_color else _contrast_color(bg)
    has_content = bool(label or hint or icon)
    if pressed:
        bg, fg = fg, bg

    if backdrop is not None:
        image = ImageEnhance.Brightness(backdrop.convert("RGB")).enhance(backdrop_brightness)
        if not has_content:
            return image
        if not pressed:
            image = Image.blend(image, Image.new("RGB", size, bg), max(0.0, min(1.0, opacity)))
        else:
            image = Image.new("RGB", size, bg)
    else:
        image = Image.new("RGB", size, bg)
    # outline the text when the icon shines through, so it stays readable
    stroke = 1 if backdrop is not None and not pressed else 0
    stroke_fill = tuple(c // 3 for c in bg)
    draw = ImageDraw.Draw(image)
    pad = max(3, w // 18)

    hint_h = 0
    if hint:
        hint_font, hint_lines, hint_line_h = _fit_text(
            draw, hint, _font_for(font, hint), (w - 2 * pad, h // 4), max_size=12, min_size=8)
        hint_line = hint_lines[0] if len(hint_lines) == 1 else hint
        hint_h = int(hint_line_h) + 2
        hint_color = tuple((c * 2 + b) // 3 for c, b in zip(fg, bg, strict=True)) if not stroke else fg
        draw.text((w / 2, h - pad), hint_line, font=hint_font, fill=hint_color, anchor="ms",
                  stroke_width=stroke, stroke_fill=stroke_fill)

    area_top, area_bottom = pad, h - pad - hint_h
    if icon:
        icon_img = load_icon(icon, 256)
        if icon_img is not None and symbols.is_symbol_file(icon):
            icon_img = symbols.tinted(icon_img, fg)
        if icon_img is not None:
            icon_h = (area_bottom - area_top) * (0.62 if label else 1.0)
            icon_img = ImageOps.contain(icon_img, (w - 2 * pad, int(icon_h)))
            image.paste(icon_img, ((w - icon_img.width) // 2, area_top), icon_img)
            area_top += icon_img.height + 1

    if label:
        box = (w - 2 * pad, max(10, area_bottom - area_top))
        max_size = font_size or (17 if not icon else 13)
        label_font, lines, line_h = _fit_text(draw, label, _font_for(font, label), box, max_size=max_size)
        total = len(lines) * line_h
        y = area_top + (area_bottom - area_top - total) / 2 + line_h / 2
        for line in lines:
            draw.text((w / 2, y), line, font=label_font, fill=fg, anchor="mm",
                      stroke_width=stroke, stroke_fill=stroke_fill)
            y += line_h
    return image


def deck_backdrop(
    icon: Image.Image, cols: int, rows: int, key_size: tuple[int, int], spacing: int, fill: float = 0.92
) -> list[Image.Image]:
    """Cut ``icon`` into one tile per key, as if it were drawn across the
    whole deck including the gaps between the keys. Tiles are row-major."""
    kw, kh = key_size
    width, height = cols * kw + (cols - 1) * spacing, rows * kh + (rows - 1) * spacing
    canvas = Image.new("RGB", (width, height), "black")
    side = int(min(width, height) * fill)
    scaled = ImageOps.contain(icon.convert("RGBA"), (side, side), Image.Resampling.LANCZOS)
    canvas.paste(scaled, ((width - scaled.width) // 2, (height - scaled.height) // 2), scaled)
    tiles = []
    for r in range(rows):
        for c in range(cols):
            x, y = c * (kw + spacing), r * (kh + spacing)
            tiles.append(canvas.crop((x, y, x + kw, y + kh)))
    return tiles
