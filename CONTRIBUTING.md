# Contributing

## Setup

**Linux**

```bash
scripts/dev-setup.sh              # .venv with all dependencies, menu entries for this tree
.venv/bin/dailydeck --tray        # run from source (-v: without tray, debug output)
```

The device and `/dev/uinput` need the udev rule once:
`sudo cp data/linux/60-dailydeck.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger`.

**macOS**

```bash
brew install hidapi
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/dailydeck --tray
```

Grant *Accessibility* to the program that starts it (Terminal, VS Code …).

## Checks

```bash
.venv/bin/ruff check . && .venv/bin/pytest     # what CI runs, plus:
python3 scripts/i18n.py check                   # translation catalogs in sync
```

Changed or added user-facing texts? Wrap them in `_()` and run `python3 scripts/i18n.py update`
– see [docs/TRANSLATING.md](docs/TRANSLATING.md).

## Layout

```
dailydeck/
  app.py, tray.py      daemon (device, focus, paging, reload) and tray icon
  gui.py               profile editor (PySide6)
  config.py            config file, profile matching, default config
  layout.py, render.py key images (shared by device and editor)
  i18n.py              translations (data/locale/*.po)
  focus/               which app has the focus: gnome, x11, macos, windows
  keys/                sending shortcuts: linux_uinput (+ xkb), macos_quartz, pynput_sender (Windows)
  data/                default config, translations, GNOME extension, icon
data/linux/            desktop files, udev rule, AppStream, man page, systemd unit
debian/                Ubuntu package
packaging/macos/       app bundle (PyInstaller)
scripts/               build-deb.sh, build-macos.sh, version.py, i18n.py
```

Device, rendering, configuration and editor are platform independent; each system adds a
focus backend and a key backend.

## Pull requests

- One topic per pull request; describe what you tested on which system.
- New default profiles: use `primary` for the system's main modifier and `keys_macos` /
  `keys_windows` / `keys_linux` only where an app really differs.
- Note user-visible changes under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md).

Building packages and releasing: [docs/RELEASING.md](docs/RELEASING.md).
