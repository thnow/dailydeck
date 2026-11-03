# Daily Deck

Daily Deck: Das Stream Deck zeigt die Tastenkürzel der Anwendung, die gerade den Fokus hat.
Ein Tastendruck auf dem Deck löst das jeweilige Kürzel aus.

- Profile pro Anwendung in `config.toml`. Änderungen werden beim Speichern sofort übernommen.
- Hat ein Profil mehr Kürzel als das Deck Tasten, wird die letzte Taste zum Blättern benutzt.
- Das Programmicon der aktiven Anwendung liegt über dem ganzen Deck: beim Wechsel blitzt es
  kurz auf, danach scheint es gedimmt durch die Tasten.
- Grafischer Editor für Profile; einzelne Profile lassen sich als `.dailydeck` exportieren
  und importieren, um sie weiterzugeben.
- Kürzel werden passend zum Tastaturlayout gesendet: `ctrl+z` bleibt auch auf QWERTZ „Rückgängig“.
- Getestet mit Stream Deck MK.2 unter Ubuntu 26.04 / GNOME 50 (Wayland). Andere Stream-Deck-Modelle
  werden über die Bibliothek [`streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck)
  ebenfalls unterstützt.

## Installation (Ubuntu)

```bash
scripts/build-deb.sh                                  # baut dist/dailydeck_<version>_all.deb (Docker)
sudo apt install ./dist/dailydeck_*_all.deb
```

Danach im Startmenü **„Daily Deck“** starten (Symbol in der oberen Leiste). Beim
ersten Start richtet die App die GNOME-Erweiterung zur Fenstererkennung ein; unter Wayland wirkt
sie nach **einmal Ab- und Anmelden**. Den Autostart schaltet man im Leistenmenü ein.

Releases, weitere Plattformen und die Build-Pipeline: [docs/RELEASING.md](docs/RELEASING.md).

### Entwicklung

```bash
scripts/dev-setup.sh                                  # venv mit allen Abhängigkeiten, Menüeinträge
.venv/bin/dailydeck --tray                          # aus dem Quellbaum starten
.venv/bin/dailydeck -v                              # ohne Leistensymbol, mit Debug-Ausgaben
.venv/bin/pytest && .venv/bin/ruff check .            # Tests und Lint wie in der CI
```

### Leistensymbol

Das Menü zeigt das aktive Programm und Profil und bietet:

- **Profil „…“ bearbeiten** – öffnet den Editor direkt bei diesem Profil; gibt es noch keins,
  wird eins für das aktive Programm angelegt (Erkennung schon ausgefüllt).
- **Pausieren** – Display aus, Tasten ohne Funktion.
- **Profil festhalten** – ein Profil unabhängig vom aktiven Fenster anzeigen (z. B. Spotify).
- **Helligkeit**, **Programmicon einblenden**, **Kürzel auf den Tasten anzeigen** – werden
  sofort in der Konfiguration gespeichert. Ein offener Editor lädt sie nach bzw. fragt beim
  Speichern nach, falls er selbst ungespeicherte Änderungen hat.
- **Beim Anmelden starten** – Autostart an/aus (Linux: `~/.config/autostart`, Windows:
  Registry „Run“, macOS: LaunchAgent).

Unter GNOME braucht das Symbol die Erweiterung *AppIndicator* (unter Ubuntu vorinstalliert,
die App bietet beim Start an, sie zu aktivieren). Unter Windows erscheint es im Infobereich (Linksklick öffnet
den Editor), unter macOS in der Menüleiste.

Profil-Editor: im Startmenü „Daily Deck Profile“ oder

```bash
PYTHONPATH=. .venv/bin/python -m dailydeck --gui
```

Nur bei `--service`: `systemctl --user status|restart|disable dailydeck`, Log mit
`journalctl --user -u dailydeck -f`.

## Konfiguration

Gelesen wird `~/.config/dailydeck/config.toml` (Windows: `%APPDATA%\dailydeck`, macOS:
`~/Library/Application Support/dailydeck`). Beim ersten Start wird sie aus
`dailydeck/data/default_config.toml` angelegt; dort ist das Format ausführlich kommentiert.
Der Editor schreibt die Datei neu (Kommentare gehen dabei verloren); die Fassung vor dem
ersten Speichern bleibt als `config.toml.bak` erhalten.

### Editor

- **Profile** links: Reihenfolge zählt (erstes passendes gewinnt), ★ = Standardprofil.
- **Erkennung:** „Aktives Fenster übernehmen“ drücken, innerhalb von 3 s ins Zielprogramm
  wechseln – dessen Kennungen werden eingetragen.
- **Deck-Vorschau:** zeigt exakt das, was das Deck anzeigt. Taste anklicken zum Bearbeiten,
  ziehen zum Tauschen, Rechtsklick zum Leeren.
- **Kürzel:** „Aufnehmen“ und die Tastenkombination drücken; mehrere nacheinander ergeben
  eine Folge (`ctrl+k z`). Nach 1,5 s Pause endet die Aufnahme.
- **Beschriftung:** `|` markiert, wo ein langes Wort getrennt werden darf (`Seiten|leiste`).
- Bilder (Programmicon, Tastensymbole) werden nach `~/.config/dailydeck/icons/` kopiert.
- **Schriftart:** global unter *Einstellungen*, pro Profil im Profilbereich. Gespeichert wird der
  Name („Ubuntu:Bold“), nicht der Pfad, damit Profile auf anderen Rechnern funktionieren. Fehlen
  der Schrift Zeichen (z. B. Pfeile), wird dafür die Standardschrift verwendet.
- **Vorschau auf dem Deck:** zeigt das gerade bearbeitete Profil live auf dem Stream Deck, ohne
  zu speichern. Tasten lösen dabei nichts aus, ▶ blättert. Läuft der Daemon, übernimmt er die
  Anzeige; sonst öffnet der Editor das Deck selbst.
- **Datei → Einstellungen:** Schriftart, Helligkeit, Programmicon an/aus, Icon-Helligkeit,
  Deckkraft der Tasten, Aufblitz-Dauer, Tastenabstand. Änderungen wirken sofort in der Vorschau
  (auch auf dem Deck), *Abbrechen* nimmt sie zurück.

### Profile austauschen

*Exportieren …* erzeugt eine `.dailydeck`-Datei (ZIP mit `profile.toml` und den eigenen
Bildern). *Importieren …* übernimmt sie; gibt es den Namen schon, wird gefragt, ob ersetzt
oder als Kopie angelegt wird. Beim Import werden nur Bilddateien übernommen.

```toml
[[profiles]]
name = "Firefox"
match = ["firefox", "org.mozilla.firefox", "firefox.exe"]   # Linux, macOS, Windows
color = "#8f2d00"

  [[profiles.buttons]]
  label = "Neuer Tab"
  keys = "ctrl+t"
```

Hilfsbefehle:

| Befehl | Zweck |
|---|---|
| `python -m dailydeck --print-focus` | zeigt die Kennungen des aktiven Fensters, die in `match` gehören |
| `python -m dailydeck --dry-run "ctrl+/"` | zeigt, welche physischen Tasten gedrückt würden |
| `python -m dailydeck --preview DIR` | rendert alle Profile als PNG, ohne Gerät |

## Aufbau

```
dailydeck/
  app.py            Daemon-Hauptschleife, Deck-Steuerung, Blättern, Hot-Reload, Pause/Festhalten
  tray.py           Leistensymbol (QSystemTrayIcon), startet den Daemon in einem Thread
  autostart.py      Autostart für Linux / Windows / macOS
  config.py         TOML laden, Profil-Matching
  layout.py         Seitenaufteilung und Tastenbilder (gemeinsam für Deck und Editor)
  render.py         Tastenbilder und Icon-Hintergrund mit Pillow
  appicons.py       Programmicon finden (Desktop-Datei + Icon-Theme, SVG via librsvg; macOS .icns)
  gui.py            Profil-Editor (PySide6)
  preview.py        Live-Vorschau: Anfrage-Datei Editor -> Daemon
  fonts.py          Schriftarten per Name finden (fontconfig; Windows/macOS: Schriftordner)
  profile_io.py     Speichern, .dailydeck-Export/-Import
  integration.py    GNOME: Erweiterungen einrichten/aktivieren beim Start
  data/             Standardkonfiguration, GNOME-Erweiterung, App-Icon (reisen in jedes Paket mit)
  focus/            "Welches Fenster hat den Fokus?"
    gnome.py          GNOME (Wayland + X11) über die Shell-Extension per D-Bus
    x11.py            X11 über xprop (Fallback)
    windows.py        Win32 GetForegroundWindow        (vorbereitet, ungetestet)
    macos.py          NSWorkspace frontmostApplication (vorbereitet, ungetestet)
  keys/             "Kürzel senden"
    parse.py          "ctrl+shift+t" -> Chords
    linux_uinput.py   virtuelle Tastatur über /dev/uinput (Wayland + X11)
    xkb.py            Layout-Auflösung über libxkbcommon
    pynput_sender.py  Windows/macOS                    (vorbereitet, ungetestet)
data/linux/         Desktop-Dateien, udev-Regel, AppStream-Metadaten, Manpage, systemd-Dienst
debian/             Ubuntu/Debian-Paket
scripts/            build-deb.sh, dev-setup.sh, version.py; ci/ = Build-Skript für Container/CI
tests/              pytest
.github/workflows/  CI und Release
```

### Portierung auf Windows / macOS

Gerät, Rendering, Konfiguration, Editor und Leistensymbol sind plattformunabhängig. Pro Plattform
gibt es ein Fokus- und ein Tasten-Backend (beide als Entwurf vorhanden). Wie daraus Installer
werden, steht in [docs/RELEASING.md](docs/RELEASING.md).
