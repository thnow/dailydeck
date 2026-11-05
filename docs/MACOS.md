# macOS-Port – Stand und Plan

Läuft am Mac: getestet mit Stream Deck MK.2, macOS 27, Apple Silicon, deutsches Tastaturlayout,
aus dem Quellbaum (`--tray` und `-v`). Ein Paket (`.app`/DMG) gibt es noch nicht.

## Umgesetzt

| Bereich | Datei | Ansatz / Stand |
|---|---|---|
| Aktives Programm | `dailydeck/focus/macos.py` | `NSWorkspace.frontmostApplication()`, Bundle-ID + Name, kein Fenstertitel. Getestet. |
| Tasten senden | `dailydeck/keys/macos_quartz.py` | Quartz-Events mit echten Tastencodes, Layout über `UCKeyTranslate`. Getestet. |
| ⌘ / Strg | `dailydeck/keys/parse.py`, `config.py` | `primary` + `keys_macos`/`keys_windows`/`keys_linux` pro Taste |
| Bedienungshilfen | `dailydeck/keys/pynput_sender.py` | `AXIsProcessTrustedWithOptions` mit Systemdialog, Warnung im Log |
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

## Offen

- Autostart (LaunchAgent) und Programmicons über viele Apps hinweg testen.
- Windows-Seite der neuen Profile (`keys_windows`, pynput) am Windows-Rechner prüfen.
- Paket: PyInstaller-`.app` mit gebündelter `libhidapi.dylib`, DMG, Signatur (Developer ID) und
  Notarisierung; CI-Jobs auf `macos-14` (arm64) und `macos-13` (x86_64), siehe
  `docs/RELEASING.md`. Dafür im Schlüsselbund ein „Developer ID Application“-Zertifikat anlegen
  (Xcode → Settings → Accounts → Manage Certificates); bisher ist keins installiert.
