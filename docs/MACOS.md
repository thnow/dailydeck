# macOS-Port – Stand und Plan

Übergabe für die Arbeit am Mac. Linux (Ubuntu/GNOME) ist fertig und als v0.1.0 veröffentlicht;
für macOS ist der Code vorbereitet, aber **nie auf einem Mac gelaufen**.

## Schon vorhanden (ungetestet)

| Bereich | Datei | Ansatz |
|---|---|---|
| Aktives Programm | `dailydeck/focus/macos.py` | `NSWorkspace.frontmostApplication()` (pyobjc), liefert Bundle-ID + Name, keinen Fenstertitel |
| Tasten senden | `dailydeck/keys/pynput_sender.py` | pynput; `super`/`cmd` → ⌘ |
| Programmicon | `dailydeck/appicons.py` (`_find_macos`) | Bundle-ID → `.app` → `CFBundleIconFile` (`.icns`, Pillow kann es lesen) |
| Schriften | `dailydeck/fonts.py` | Schriftordner scannen (`/System/Library/Fonts` …) |
| Autostart | `dailydeck/autostart.py` | LaunchAgent `~/Library/LaunchAgents/io.github.thnow.dailydeck.plist` |
| Konfiguration | `dailydeck/config.py` | `~/Library/Application Support/dailydeck/config.toml` |
| Leistensymbol | `dailydeck/tray.py` | Template-Icon (`setIsMask`), Linksklick öffnet den Editor |
| Kürzel-Aufnahme | `dailydeck/gui.py` | Qt vertauscht auf macOS Ctrl/Meta – wird berücksichtigt |

Plattformunabhängig und unverändert nutzbar: Gerät, Rendering, Profile, Editor, Vorschau,
Export/Import, Daemon-Logik.

## Erste Schritte am Mac

```bash
brew install hidapi
git clone https://github.com/thnow/dailydeck.git && cd dailydeck
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                                  # plattformunabhängige Tests
.venv/bin/dailydeck --print-focus                 # erkennt es das aktive Programm?
.venv/bin/dailydeck -v                            # Daemon ohne Leistensymbol
.venv/bin/dailydeck --tray                        # mit Menüleisten-Symbol
```

Die Elgato-Software („Stream Deck“-App) muss beendet sein, sonst ist das Gerät belegt.

## Erwartete Stolpersteine

1. **hidapi finden:** Auf Apple Silicon liegt Homebrew unter `/opt/homebrew/lib`, das ist nicht
   im Standard-Suchpfad von `ctypes`. Ggf. Pfad ergänzen, bevor `StreamDeck` die Bibliothek lädt.
2. **Bedienungshilfen:** Tastendrücke senden erfordert die Freigabe unter *Systemeinstellungen →
   Datenschutz & Sicherheit → Bedienungshilfen* (für Terminal bzw. später die App). Ohne Freigabe
   scheitert pynput still – die App sollte das prüfen (`AXIsProcessTrusted`) und darauf hinweisen.
3. **⌘ statt Strg:** Die Standardprofile nutzen `ctrl+…`. Vorschlag: einen plattformneutralen
   Modifier `primary` einführen (⌘ auf macOS, Strg sonst) und die Standardprofile darauf umstellen,
   statt doppelte Profile zu pflegen. Profile brauchen außerdem die Bundle-IDs in `match`
   (z. B. `com.microsoft.VSCode`, `org.mozilla.firefox`) – `--print-focus` zeigt sie.
4. **Tastaturlayout:** pynput und deutsches Layout (Sonderzeichen wie `/`, `@`, `#`) prüfen; unter
   Linux löst das `keys/xkb.py`, auf macOS ggf. über `UCKeyTranslate`/Carbon nötig.
5. **Fokus aus dem Hintergrund-Thread:** Der Daemon fragt `frontmostApplication` aus einem Thread
   ab; der Wert wird über den Main-Runloop aktualisiert, den Qt im `--tray`-Modus betreibt. Ohne
   Qt (`dailydeck -v`) könnte er einfrieren – testen.

## Danach: Paket bauen

Ziel laut `docs/RELEASING.md`: PyInstaller-`.app` mit gebündelter `libhidapi.dylib`, DMG,
Signatur (Developer ID) und Notarisierung; CI-Jobs auf `macos-14` (arm64) und `macos-13` (x86_64)
im Release-Workflow. Für Signatur/Notarisierung ist ein Apple-Developer-Konto nötig.
