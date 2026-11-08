import tomllib

import pytest

import dailydeck.config as config
from dailydeck import sync
from dailydeck.config import active_config_path, conflict_files, load_config, read_config_data
from dailydeck.profile_io import save_config

PROFILE = {"name": "Editor", "match": ["code"], "buttons": [{"label": "Save", "keys": "primary+s",
                                                              "icon": "icons/save.png"}]}


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A computer with its own local config directory; returns a function to switch computers."""
    def use(name: str):
        local = tmp_path / name
        local.mkdir(exist_ok=True)
        monkeypatch.setattr(config, "config_dir", lambda: local)
        return local

    return use


def _toml(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_move_to_folder_and_adopt_on_second_computer(tmp_path, machine):
    cloud = tmp_path / "Nextcloud" / "dailydeck"
    cloud.mkdir(parents=True)

    a = machine("a")
    (a / "icons").mkdir()
    (a / "icons" / "save.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    save_config({"settings": {"brightness": 80, "language": "de", "app_icon": False},
                 "profiles": [PROFILE]}, a / "config.toml")

    shared = sync.connect(cloud, a / "config.toml", adopt=False)
    assert shared == (cloud / "config.toml").resolve() or shared == cloud.resolve() / "config.toml"
    assert active_config_path().resolve() == shared.resolve()
    assert (cloud / "icons" / "save.png").is_file()
    stored = _toml(cloud / "config.toml")
    assert stored["settings"] == {"app_icon": False}  # local settings stay on this computer
    assert _toml(a / "local.toml")["settings"] == {"brightness": 80, "language": "de"}
    assert read_config_data(shared)["settings"] == {"app_icon": False, "brightness": 80, "language": "de"}

    # second computer: has its own (default) config, adopts the shared one
    b = machine("b")
    save_config({"settings": {"brightness": 30}, "profiles": []}, b / "config.toml")
    existing = sync.existing_config(cloud)
    assert existing is not None and existing.profiles == 1
    sync.connect(cloud, b / "config.toml", adopt=True)
    data = read_config_data(cloud / "config.toml")
    assert data["settings"]["brightness"] == 30  # its own brightness
    assert data["profiles"][0]["name"] == "Editor"  # the shared profiles
    assert load_config(cloud / "config.toml").settings.brightness == 30

    # a change on b reaches the shared file, b's brightness does not
    data["settings"]["brightness"] = 10
    data["settings"]["show_keys"] = False
    save_config(data, cloud / "config.toml")
    assert _toml(cloud / "config.toml")["settings"] == {"app_icon": False, "show_keys": False}
    machine("a")
    assert load_config(cloud / "config.toml").settings.brightness == 80


def test_unchanged_shared_file_is_not_rewritten(tmp_path, machine):
    cloud = tmp_path / "cloud"
    cloud.mkdir()
    a = machine("a")
    save_config({"profiles": [PROFILE]}, a / "config.toml")
    shared = sync.connect(cloud, a / "config.toml", adopt=False)
    before = shared.stat().st_mtime_ns
    data = read_config_data(shared)
    data.setdefault("settings", {})["brightness"] = 5  # local only
    save_config(data, shared)
    assert shared.stat().st_mtime_ns == before
    assert _toml(a / "local.toml")["settings"]["brightness"] == 5


def test_unreachable_folder_falls_back_without_creating_anything(tmp_path, machine):
    a = machine("a")
    cloud = tmp_path / "not-synced-yet"
    config.write_local({"sync_dir": str(cloud)})
    assert active_config_path() == a / "config.toml"
    cloud.mkdir()  # folder there, file not yet downloaded
    assert active_config_path() == a / "config.toml"
    assert not (cloud / "config.toml").exists()


def test_disconnect_copies_back(tmp_path, machine):
    cloud = tmp_path / "cloud"
    cloud.mkdir()
    a = machine("a")
    save_config({"settings": {"brightness": 70, "show_keys": False}, "profiles": [PROFILE]}, a / "config.toml")
    shared = sync.connect(cloud, a / "config.toml", adopt=False)
    back = sync.disconnect(shared)
    assert back == a / "config.toml"
    assert active_config_path() == back
    assert _toml(back)["settings"] == {"brightness": 70, "show_keys": False}
    assert "sync_dir" not in config.read_local()


def test_adopt_requires_config(tmp_path, machine):
    a = machine("a")
    save_config({"profiles": []}, a / "config.toml")
    with pytest.raises(config.ConfigError):
        sync.connect(tmp_path, a / "config.toml", adopt=True)
    assert config.sync_dir() is None


def test_conflict_files(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("")
    for name in ("config (conflicted copy 2026-11-08 154512).toml", "config.sync-conflict-20261108-1.toml",
                 "config.toml.bak", "other (conflicted copy).toml", "config (Thomas's conflicted copy).toml"):
        (tmp_path / name).write_text("")
    assert sorted(p.name for p in conflict_files(path)) == sorted([
        "config (Thomas's conflicted copy).toml", "config (conflicted copy 2026-11-08 154512).toml",
        "config.sync-conflict-20261108-1.toml"])
