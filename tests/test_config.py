from pathlib import Path

import pytest

from dailydeck.config import DATA_DIR, ConfigError, button_chords, load_config, parse_config
from dailydeck.focus import WindowInfo
from dailydeck.keys import ShortcutError, parse_shortcut


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
    with pytest.raises(ConfigError, match="Firefox.*key 1"):
        make([{"name": "Firefox", "buttons": [{"label": "x", "keys": "ctrl+nonsense"}]}])


def test_settings_defaults_and_values():
    config = make([], {"brightness": 30, "font": "Ubuntu:Bold"})
    assert config.settings.brightness == 30
    assert config.settings.font == "Ubuntu:Bold"
    assert config.settings.app_icon is True


def test_platform_variants():
    button = {"keys": "primary+shift+z", "keys_windows": "primary+y"}
    assert button_chords(button, "macos") == parse_shortcut("cmd+shift+z")
    assert button_chords(button, "linux") == parse_shortcut("ctrl+shift+z")
    assert button_chords(button, "windows") == parse_shortcut("ctrl+y")
    assert button_chords({"keys_macos": "enter"}, "linux") == ()  # only on the Mac

    with pytest.raises(ShortcutError, match="keys_linux"):  # checked on every system
        button_chords({"keys": "f2", "keys_linux": "ctrl+foo"}, "macos")


@pytest.mark.parametrize("platform", ["macos", "windows", "linux"])
def test_bundled_default_config_on_every_system(platform):
    import tomllib

    data = tomllib.loads((DATA_DIR / "default_config.toml").read_text(encoding="utf-8"))
    for profile in data["profiles"]:
        for button in profile.get("buttons", []):
            button_chords(button, platform)  # raises on invalid keys


@pytest.mark.parametrize("version", ["0.1.0", "0.2.0"])
def test_untouched_old_default_is_updated(tmp_path, monkeypatch, version):
    import dailydeck.config as config

    fixture = Path(__file__).parent / "data" / f"default_config-{version}.toml"
    assert config._content_hash(fixture) in config.PREVIOUS_DEFAULTS
    old = fixture.read_bytes()
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    user = tmp_path / "config.toml"
    user.write_bytes(old.replace(b"\n", b"\r\n"))  # as checked out on Windows
    assert config.default_config_path().read_text(encoding="utf-8") == config.localized_default_config()
    assert (tmp_path / "config.toml.bak").read_bytes() == old.replace(b"\n", b"\r\n")

    user.write_bytes(old + b"# edited\n")  # edited configs stay
    config.default_config_path()
    assert user.read_bytes() == old + b"# edited\n"
