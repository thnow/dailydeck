from pathlib import Path

import pytest

from dailydeck.config import DATA_DIR, ConfigError, load_config, parse_config
from dailydeck.focus import WindowInfo


def test_bundled_default_config_is_valid():
    config = load_config(DATA_DIR / "default_config.toml")
    assert config.profiles
    assert config.default_profile is not None


def make(profiles, settings=None):
    return parse_config({"settings": settings or {}, "profiles": profiles}, Path("/tmp/config.toml"))


def test_first_matching_profile_wins_and_default():
    config = make([
        {"name": "YouTube", "match": ["firefox"], "title": "youtube"},
        {"name": "Firefox", "match": ["firefox", "org.mozilla.*"]},
        {"name": "Standard", "default": True},
    ])
    assert config.profile_for(WindowInfo(ids=("Firefox",), title="Cats - YouTube")).name == "YouTube"
    assert config.profile_for(WindowInfo(ids=("firefox",), title="News")).name == "Firefox"
    assert config.profile_for(WindowInfo(ids=("org.mozilla.firefox",))).name == "Firefox"
    assert config.profile_for(WindowInfo(ids=("code",))).name == "Standard"


def test_invalid_shortcut_names_profile_and_button():
    with pytest.raises(ConfigError, match="Firefox.*button 1"):
        make([{"name": "Firefox", "buttons": [{"label": "x", "keys": "ctrl+nonsense"}]}])


def test_settings_defaults_and_values():
    config = make([], {"brightness": 30, "font": "Ubuntu:Bold"})
    assert config.settings.brightness == 30
    assert config.settings.font == "Ubuntu:Bold"
    assert config.settings.app_icon is True
