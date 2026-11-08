# Building and releasing

```
push / pull request ─▶ CI: version check · i18n check · ruff · pytest (Python 3.11, 3.14)
                           · Ubuntu package · macOS app (unsigned) · Windows tests + installer

tag v1.2.3 ─▶ Release: tag = version? ─▶ wheel + sdist · .deb · signed, notarized .dmg · setup.exe
                                         ─▶ SHA256SUMS ─▶ GitHub release (notes from CHANGELOG.md)
```

## Release

```bash
scripts/version.py bump 0.3.0      # sets the version everywhere, moves [Unreleased] in CHANGELOG.md
git commit -am "Release 0.3.0"
git tag v0.3.0 && git push && git push --tags
```

Tags with a hyphen (`v0.3.0-rc1`) become pre-releases. `scripts/version.py check` keeps
`dailydeck/__init__.py`, `debian/changelog`, AppStream metadata, man page and changelog in step.

## Ubuntu

`scripts/build-deb.sh` builds `dist/dailydeck_<version>_all.deb` in a clean `ubuntu:26.04`
container (Docker), the same script CI uses: build, tests, lintian, install into a fresh system,
smoke test. The package depends only on Ubuntu packages and installs:

- `dailydeck`, menu entries for the tray app and the editor
- udev rule `60-dailydeck.rules`: the logged-in user may use the Stream Deck and `/dev/uinput`
  (`uaccess`, as Steam or Input Remapper do), applied on install
- the GNOME Shell extension that reports the focused window; enabled per user on first start
- AppStream metadata with `modalias usb:v0FD9p*`, so software centers can suggest the app when a
  Stream Deck is plugged in
- an optional `systemd --user` service without tray icon

## macOS

`scripts/build-macos.sh` builds `Daily Deck.app` and the DMG for Apple Silicon, macOS 12+; see
[MACOS.md](MACOS.md) for local signing and the details. The release job imports the signing
certificate into a temporary keychain and notarizes with an App Store Connect API key, from
these repository secrets:

| Secret | |
|---|---|
| `MACOS_CERTIFICATE_P12`, `MACOS_CERTIFICATE_PASSWORD` | Developer ID Application certificate with key (base64) |
| `MACOS_NOTARY_KEY_P8`, `MACOS_NOTARY_KEY_ID`, `MACOS_NOTARY_ISSUER` | App Store Connect API key (base64), role Developer |

## Windows

`scripts/build-windows.ps1` builds the programs with PyInstaller and
`DailyDeck-<version>-windows-x64-setup.exe` with Inno Setup; see [WINDOWS.md](WINDOWS.md). The
release is not code-signed yet: SmartScreen warns on the first start of the setup. Signing plugs
in through `SIGN_COMMAND` (e.g. Azure Trusted Signing or a certificate with `signtool`).

## Licenses in binary builds

The Windows installer and the macOS app bundle third-party code. Both build scripts run
`scripts/third_party_notices.py` with the build environment's Python; it writes
`THIRD-PARTY-NOTICES.txt` from the license files of every installed package, Python's own
license and the texts in `packaging/licenses/` (LGPL-3.0 for Qt, hidapi), and fails if a package
ships no license file. A new runtime dependency is picked up automatically; a new bundled native
library needs its license added there.

## Platforms

| Target | Package | Status |
|---|---|---|
| Ubuntu 26.04 | `.deb` | released |
| macOS 12+, Apple Silicon | signed, notarized `.dmg` | released |
| Windows 10/11, x64 | Inno Setup installer (unsigned) | released |
| Windows | code signing, winget package | planned |
| macOS, Intel | second build or universal2 | planned |
| Debian, Fedora, Arch | same `debian/`, RPM spec, AUR | planned |
| Launchpad PPA | automatic updates via apt | planned |

Linux desktops other than GNOME and X11 need a focus backend in `dailydeck/focus/` (KDE: KWin
script, Sway/i3: i3 IPC, Hyprland: event socket). Flatpak and Snap are not an option: the app
needs udev rules, `/dev/uinput`, a shell extension and a view of other apps' windows.
