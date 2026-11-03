import zipfile

import pytest
from PIL import Image

from dailydeck.config import ConfigError, load_config
from dailydeck.profile_io import export_profile, import_profile, save_config


def test_save_roundtrip_drops_empty_values(tmp_path):
    path = tmp_path / "config.toml"
    data = {
        "settings": {"brightness": 40},
        "profiles": [{"name": "A", "match": ["a"], "color": None,
                      "buttons": [{"label": "X", "keys": "ctrl+x", "icon": None}, {}, {}]}],
    }
    save_config(data, path)
    config = load_config(path)
    assert config.settings.brightness == 40
    assert len(config.profiles[0].buttons) == 1  # trailing empty buttons removed


def test_save_refuses_invalid_config(tmp_path):
    with pytest.raises(ConfigError):
        save_config({"profiles": [{"name": "A", "buttons": [{"keys": "ctrl+?+"}]}]}, tmp_path / "c.toml")


def test_export_import_with_icon(tmp_path):
    src_dir, dst_dir = tmp_path / "src", tmp_path / "dst"
    (src_dir / "icons").mkdir(parents=True)
    dst_dir.mkdir()
    Image.new("RGB", (8, 8), "red").save(src_dir / "icons" / "play.png")
    profile = {"name": "Spotify", "match": ["spotify"],
               "buttons": [{"label": "Play", "keys": "playpause", "icon": "icons/play.png"}]}
    target = tmp_path / "spotify.dailydeck"
    export_profile(profile, src_dir, target)

    imported = import_profile(target, dst_dir)
    icon = imported["buttons"][0]["icon"]
    assert (dst_dir / icon).is_file()
    assert imported["name"] == "Spotify"


def test_import_ignores_non_images_and_foreign_paths(tmp_path):
    target = tmp_path / "evil.dailydeck"
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr("profile.toml", 'format = "dailydeck-profile"\nversion = 1\n'
                                    '[profile]\nname = "X"\nicon = "../../evil.sh"\n'
                                    '[[profile.buttons]]\nlabel = "a"\nicon = "icons/fake.png"\n')
        zf.writestr("icons/fake.png", "#!/bin/sh\necho not an image\n")
        zf.writestr("../../evil.sh", "boom")
    imported = import_profile(target, tmp_path)
    assert "icon" not in imported
    assert "icon" not in imported["buttons"][0]
    assert not (tmp_path.parent / "evil.sh").exists()


def test_import_rejects_other_files(tmp_path):
    target = tmp_path / "x.dailydeck"
    with zipfile.ZipFile(target, "w") as zf:
        zf.writestr("profile.toml", 'format = "something-else"\n')
    with pytest.raises(ConfigError):
        import_profile(target, tmp_path)
