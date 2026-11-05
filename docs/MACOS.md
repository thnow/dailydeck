# macOS-Port – Stand und Plan

Läuft am Mac: getestet mit Stream Deck MK.2, macOS 27, Apple Silicon, deutsches Tastaturlayout.
Releases enthalten ein signiertes, notarisiertes DMG für Apple Silicon ab macOS 12.

## Umgesetzt

| Bereich | Datei | Ansatz / Stand |
|---|---|---|
| Aktives Programm | `dailydeck/focus/macos.py` | `NSWorkspace.frontmostApplication()`, Bundle-ID + Name, kein Fenstertitel. Getestet. |
| Tasten senden | `dailydeck/keys/macos_quartz.py` | Quartz-Events mit echten Tastencodes, Layout über `UCKeyTranslate`. Getestet. |
| ⌘ / Strg | `dailydeck/keys/parse.py`, `config.py` | `primary` + `keys_macos`/`keys_windows`/`keys_linux` pro Taste |
| Bedienungshilfen | `dailydeck/keys/macos_quartz.py` | `AXIsProcessTrustedWithOptions` mit Systemdialog, Warnung im Log |
| Programmicon | `dailydeck/appicons.py` (`_find_macos`) | Bundle-ID → `.app` → `.icns` (ungeprüft, ob es bei allen Apps greift) |
| Schriften | `dailydeck/fonts.py` | Schriftordner scannen |
| Autostart | `dailydeck/autostart.py` | LaunchAgent – **noch nicht getestet** |
| Konfiguration | `dailydeck/config.py` | `~/Library/Application Support/dailydeck/config.toml` |
| Leistensymbol | `dailydeck/tray.py` | Template-Icon, Linksklick öffnet den Editor |
| Kürzel-Aufnahme | `dailydeck/gui.py` | ⌘ → `primary`, ⌃ → `ctrl` (Qt vertauscht Ctrl/Meta) |

## Am Mac starten

```bash
brew install hidapi        # braucht einmal: sudo xcodebuild -license accept
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/dailydeck --tray
```

Die Elgato-Software muss beendet sein. Beim ersten Tastendruck fragt macOS nach der Freigabe unter
*Bedienungshilfen* – sie gilt für das Programm, das Daily Deck startet (Terminal, VS Code, später
die `.app`).

## Erkenntnisse

1. **hidapi** wird von der `streamdeck`-Bibliothek unter `/opt/homebrew/lib` gefunden.
2. **Fokus ohne Qt:** `frontmostApplication` wird nur über den Main-Runloop aktualisiert. Ohne Qt
   (`-v`, `--print-focus`) pumpt der Provider den Runloop selbst, wenn er im Main-Thread läuft.
3. **pynput reicht auf macOS nicht:** Zeichen, die ⌥ brauchen (`[` = ⌥5), gingen als Taste „A“
   raus, und ⌘⇧-Kürzel kamen im Finder nicht an. Deshalb ein eigener Quartz-Sender; pynput bleibt
   für Windows.
4. **Lokalisierte Menükürzel:** macOS verlegt Kürzel, die auf dem Layout ⌥ bräuchten – auf Deutsch
   ⌘[ → ⌘Ö, ⌘] → ⌘Ä, ⌘\ → ⌘#. `LOCALIZED` in `macos_quartz.py` bildet das nach; weitere Layouts
   (Schweiz, Frankreich …) dort ergänzen. Die echten Kürzel eines Programms lassen sich über die
   Bedienungshilfen aus der Menüleiste lesen (`AXMenuItemCmdChar`/`AXMenuItemCmdModifiers`).
5. **Tastaturlayout nur im Main-Thread lesen:** Die TIS-Funktionen brechen den Prozess ab
   (SIGTRAP), wenn sie außerhalb des Main-Threads laufen, während ein Textfeld den Fokus hat. Der
   Sender reicht die Abfrage deshalb an den Main-Runloop weiter.
6. Kein Fenstertitel: `title`-Regeln greifen auf dem Mac nicht (bräuchte die AX-API).
7. **Mindestversion des Pakets:** Jede Binärdatei im Bundle trägt ein `minos`; ist eine davon neuer
   als das laufende macOS, kann das Programm abstürzen. Homebrew baut für die eigene Maschine
   (Python, hidapi: macOS 26/27), und PySide6 ab 6.10 baut seine Module für macOS 15 bzw. 26,
   obwohl die Wheels 13/14 angeben. Deshalb: portables Python 3.13 (uv/python.org, macOS 11),
   PySide6 6.9.3 (`packaging/macos/constraints.txt`, macOS 12), hidapi aus dem Quelltext. Das
   Build-Skript prüft am Ende alle Dateien und bricht ab, wenn eine neuer als `MACOS_MIN` ist.

## Paket bauen

```bash
brew install uv
scripts/build-macos.sh        # ad-hoc signiert, nur für diesen Mac
SIGN_IDENTITY=<SHA-1 des Zertifikats> NOTARY_PROFILE=dailydeck scripts/build-macos.sh
```

Ergebnis: `dist/Daily Deck.app` und `dist/DailyDeck-<version>-macos-arm64.dmg`. Logs der App:
`~/Library/Logs/Daily Deck.log`.

Einmalig für Signatur und Notarisierung:

- **Developer ID Application**-Zertifikat. Xcode legte es nicht an („can only be performed by the
  account holder“, obwohl Inhaber); geklappt hat: Schlüssel + CSR per `openssl`, im Portal unter
  Certificates → Developer ID Application hochladen, `.cer` installieren. Fehlt danach die
  „valid identity“, das Zwischenzertifikat *Developer ID G2 CA* von apple.com/certificateauthority
  installieren.
- **Notarisierung** per App-Store-Connect-API-Schlüssel (Benutzer und Zugriff → Integrationen,
  Rolle Developer); `xcrun notarytool store-credentials dailydeck --key … --key-id … --issuer …`.
  Ein app-spezifisches Passwort brachte nur 401.
- **CI:** Secrets `MACOS_CERTIFICATE_P12` (Base64), `MACOS_CERTIFICATE_PASSWORD`,
  `MACOS_NOTARY_KEY_P8` (Base64), `MACOS_NOTARY_KEY_ID`, `MACOS_NOTARY_ISSUER`.

## Offen

- Autostart (LaunchAgent) und Programmicons über viele Apps hinweg testen.
- Windows-Seite der neuen Profile (`keys_windows`, pynput) am Windows-Rechner prüfen.
- Intel-Macs: eigener Build auf einem x86_64-Runner (oder universal2) – bisher nur Apple Silicon.
