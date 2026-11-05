# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- English and German user interface, messages and default profiles. The language follows the
  system and can be set under Settings → Language. New languages are a single `.po` file, no
  build step – see [docs/TRANSLATING.md](docs/TRANSLATING.md).
- An untouched default configuration from 0.2.0 is recreated in your language (the old file is
  kept as `config.toml.bak`).

### Changed
- Documentation in English.

## [0.2.0] – 2026-11-05

### Added
- macOS support: signed, notarized DMG for Apple Silicon, macOS 12 or later. Key presses follow
  the keyboard layout, including the menu shortcuts macOS localizes (⌘[ → ⌘Ö on German layouts).
- `primary` modifier (⌘ on the Mac, Ctrl elsewhere) and per-key `keys_macos`, `keys_windows`,
  `keys_linux`: one configuration for every system. The editor records Ctrl/⌘ as `primary`.
- Default profiles use `primary` and include Mac shortcuts; new Safari profile, iTerm2 in the
  Terminal profile.
- An untouched default configuration from an earlier version is replaced by the new default
  (old file kept as `config.toml.bak`); edited configurations are left alone.

### Changed
- Editor: compact deck preview, settings grouped into “Keys” and “App icon”.

### Fixed
- Editor ran off the bottom of small screens; it now fits and scrolls.
- macOS: the focused app was not updated without the tray icon (`-v`, `--print-focus`); ⌘ alone
  was recorded as `super+ctrl`; editor fields did not use the full width.

## [0.1.0] – 2026-11-03

First release.

- The Stream Deck shows the shortcuts of the focused application (a profile per application).
- Linux: focus detection on GNOME/Wayland (shell extension) and X11; key presses via uinput,
  matching the keyboard layout.
- Application icon across the deck, flashing on a switch.
- Profile editor with live preview on the device, shortcut recording and font selection.
- Profile export/import as `.dailydeck` files.
- Tray icon with pause, pinned profile, brightness and start at login.
