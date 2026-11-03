"""Page layout and key images of a profile, shared by the daemon and the GUI."""

import functools
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .appicons import find_app_icon, load_icon
from .config import Button, Profile, Settings
from .keys import format_shortcut
from .render import deck_backdrop, render_key


@dataclass(frozen=True)
class NavSlot:
    """The "next page" key shown when a profile has more buttons than keys."""

    pages: int


Slot = Button | NavSlot | None


def per_page(button_count: int, key_count: int) -> int:
    return key_count if button_count <= key_count else key_count - 1


def page_count(button_count: int, key_count: int) -> int:
    n = per_page(button_count, key_count)
    return max(1, (button_count + n - 1) // n)


def page_slots(buttons: tuple[Button, ...], key_count: int, page: int) -> list[Slot]:
    n = per_page(len(buttons), key_count)
    pages = page_count(len(buttons), key_count)
    page %= pages
    chunk: list[Slot] = list(buttons[page * n:(page + 1) * n])
    chunk += [None] * (n - len(chunk))
    if pages > 1:
        chunk.append(NavSlot(pages))
    return chunk


def icon_for(profile: Profile | None, ids: tuple[str, ...], settings: Settings) -> Path | None:
    if not settings.app_icon:
        return None
    if profile is not None and profile.icon is not None:
        return profile.icon
    return find_app_icon(ids)


@functools.lru_cache(maxsize=32)
def backdrop_tiles(icon: Path | None, cols: int, rows: int, key_size: tuple[int, int], spacing: int):
    if icon is None:
        return None
    image = load_icon(icon, 512)
    if image is None:
        return None
    return tuple(deck_backdrop(image, cols, rows, key_size, spacing))


def render_slot(
    slot: Slot,
    profile: Profile | None,
    settings: Settings,
    key_size: tuple[int, int],
    tile: Image.Image | None = None,
    page: int = 0,
    pressed: bool = False,
) -> Image.Image:
    s = settings
    font = (profile.font if profile else None) or s.font
    common = dict(font=font, backdrop=tile, backdrop_brightness=s.app_icon_brightness, opacity=s.button_opacity)
    if isinstance(slot, Button) and not slot.empty:
        profile_bg = (profile.color if profile else None) or s.background
        profile_fg = (profile.text_color if profile else None) or s.text_color
        return render_key(
            key_size,
            label=slot.label,
            hint=format_shortcut(slot.chords) if s.show_keys and slot.chords else "",
            background=slot.color or profile_bg,
            text_color=slot.text_color or (None if slot.color else profile_fg),
            icon=slot.icon,
            font_size=slot.font_size,
            pressed=pressed,
            **common,
        )
    if isinstance(slot, NavSlot):
        return render_key(
            key_size, label="▶", hint=f"{page % slot.pages + 1}/{slot.pages}",
            background="#3a3a3a", text_color="#ffffff", font_size=26, pressed=pressed, **common,
        )
    return render_key(key_size, background="#000000", **common)


def render_page(
    profile: Profile | None,
    settings: Settings,
    ids: tuple[str, ...] = (),
    page: int = 0,
    cols: int = 5,
    rows: int = 3,
    key_size: tuple[int, int] = (72, 72),
) -> list[Image.Image]:
    """All key images of one page, as the deck would show them."""
    key_count = cols * rows
    slots = page_slots(profile.buttons, key_count, page) if profile else [None] * key_count
    tiles = backdrop_tiles(icon_for(profile, ids, settings), cols, rows, key_size, settings.key_spacing)
    return [
        render_slot(slot, profile, settings, key_size, tiles[i] if tiles else None, page)
        for i, slot in enumerate(slots)
    ]


def match_ids(profile: Profile) -> tuple[str, ...]:
    """Ids of a profile usable for an icon lookup (wildcards removed)."""
    return tuple(m for m in profile.match if not any(c in m for c in "*?["))
