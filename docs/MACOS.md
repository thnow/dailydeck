# macOS notes

Tested with a Stream Deck MK.2 on macOS 27, Apple Silicon, German keyboard layout.

| | |
|---|---|
| Focused app | `focus/macos.py` – `NSWorkspace.frontmostApplication()`: bundle ID and name, no window title |
| Key presses | `keys/macos_quartz.py` – Quartz events with real key codes, layout via `UCKeyTranslate`; needs *Accessibility* |
| App icons | `appicons.py` – bundle ID → `.app` → `.icns` |
| Start at login | `autostart.py` – LaunchAgent (not yet tested) |

## Build the app

```bash
brew install uv
scripts/build-macos.sh                                       # ad-hoc signed, this Mac only
SIGN_IDENTITY=<certificate SHA-1> NOTARY_PROFILE=dailydeck scripts/build-macos.sh
```

The result is `dist/Daily Deck.app` and `dist/DailyDeck-<version>-macos-arm64.dmg`; the app
logs to `~/Library/Logs/Daily Deck.log`. With an ad-hoc signature, macOS asks for the
Accessibility permission again after every build.

Every binary in the bundle must be built for the minimum macOS (`MACOS_MIN`, 12.0), so the build
uses a portable Python 3.13 (uv or python.org, built for macOS 11), PySide6 6.9.3
([constraints](../packaging/macos/constraints.txt) – newer wheels contain modules built for
macOS 15 or 26 despite their tags) and hidapi compiled from source. Homebrew's libraries target
the build machine. The script fails if any binary needs a newer macOS.

### Signing setup (once)

1. **Developer ID Application certificate.** If Xcode refuses (“can only be performed by the
   account holder”), create a key and CSR with `openssl req`, upload the CSR in the developer
   portal under Certificates → Developer ID Application and install the `.cer`. If the identity
   is not listed as valid by `security find-identity -v -p codesigning`, install the *Developer
   ID G2* intermediate certificate from apple.com/certificateauthority.
2. **Notarization** with an App Store Connect API key (Users and Access → Integrations, role
   Developer): `xcrun notarytool store-credentials dailydeck --key AuthKey_….p8 --key-id …
   --issuer …`. App-specific passwords may fail with HTTP 401.

For the release workflow, the same certificate (as `.p12`) and key go into repository secrets,
see [RELEASING.md](RELEASING.md).

## Implementation notes

- **Focus without Qt.** `frontmostApplication` only updates through the main run loop; without
  Qt (`-v`, `--print-focus`) the provider pumps it itself.
- **Why not pynput.** Characters that need ⌥ (`[` is ⌥5 on German layouts) were sent as the wrong
  key, and ⌘⇧ shortcuts did not reach Finder. The Quartz sender sets full modifier flags on every
  event.
- **Localized menu shortcuts.** macOS moves shortcuts that would need ⌥ on the current layout –
  on German layouts ⌘[ becomes ⌘Ö, ⌘] ⌘Ä, ⌘\ ⌘#. `LOCALIZED` in `macos_quartz.py` maps them; add
  other layouts there. An app's real shortcuts can be read from its menu bar via the
  Accessibility API (`AXMenuItemCmdChar`, `AXMenuItemCmdModifiers`).
- **Keyboard layout on the main thread only.** The TIS functions abort the process (SIGTRAP)
  when called from another thread while a text field has the focus; the sender hands the query
  to the main run loop.
- **Qt swaps Ctrl and Meta** on macOS: ⌘ arrives as Ctrl. The editor records ⌘ as `primary` and ⌃
  as `ctrl`.
- **No window titles.** `title` rules do not apply on the Mac (would need the Accessibility API).
