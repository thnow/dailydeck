from pathlib import Path

from dailydeck.config import Button, parse_config
from dailydeck.layout import NavSlot, page_count, page_slots, render_page


def buttons(n):
    return tuple(Button(label=str(i)) for i in range(n))


def test_single_page_uses_all_keys():
    slots = page_slots(buttons(15), 15, 0)
    assert len(slots) == 15
    assert not any(isinstance(s, NavSlot) for s in slots)


def test_paging_reserves_last_key():
    assert page_count(16, 15) == 2
    first = page_slots(buttons(16), 15, 0)
    second = page_slots(buttons(16), 15, 1)
    assert first[-1] == NavSlot(2)
    assert [b.label for b in first[:14]] == [str(i) for i in range(14)]
    assert [b.label for b in second[:2]] == ["14", "15"]
    assert page_slots(buttons(16), 15, 2) == first  # wraps around


def test_render_page_produces_key_images():
    config = parse_config(
        {"settings": {"app_icon": False},
         "profiles": [{"name": "A", "buttons": [{"label": "Neuer Tab", "keys": "ctrl+t"}]}]},
        Path("/tmp/config.toml"),
    )
    images = render_page(config.profiles[0], config.settings)
    assert len(images) == 15
    assert all(img.size == (72, 72) for img in images)
    assert images[0].getextrema() != images[1].getextrema()  # button vs. empty key
