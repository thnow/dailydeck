import pytest


@pytest.fixture(autouse=True)
def _isolated_config_dir(tmp_path_factory, monkeypatch):
    """No test may touch the real configuration (local.toml, config.toml) of the developer."""
    import dailydeck.config as config

    home = tmp_path_factory.mktemp("config-home")
    monkeypatch.setattr(config, "config_dir", lambda: home)
    for var in ("APPDATA", "XDG_CONFIG_HOME", "LOCALAPPDATA"):
        monkeypatch.setenv(var, str(home))
