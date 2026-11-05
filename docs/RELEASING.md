# Build- und Release-Pipeline

## Grundprinzip

```
                 ┌──────────────────────────── CI (jeder Push / Pull Request) ───────────────────────────┐
  git push  ──▶  │ Versionen konsistent? ─▶ ruff ─▶ pytest (Py 3.11 + 3.14) ─▶ .deb bauen + testen     │
                 └────────────────────────────────────────────────────────────────────────────────────────┘

                 ┌──────────────────────────── Release (Tag v*) ─────────────────────────────────────────┐
  git tag v1.2.3 │ Tag = Version? ─▶ sdist/wheel ─┐                                                       │
  git push --tags│                ─▶ .deb ────────┼─▶ SHA256SUMS ─▶ GitHub Release (Notizen aus CHANGELOG)│
                 │                ─▶ .dmg ────────┤  (später .exe)                                       │
                 └────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Eine Quelle für alles:** `pyproject.toml` beschreibt das Python-Paket. Laufzeitdaten
  (Standardkonfiguration, GNOME-Erweiterung, Icon) liegen in `dailydeck/data/` und reisen in
  jedes Paketformat mit.
- **Jeder Build im sauberen Container:** `scripts/ci/build-deb.sh` läuft lokal (über
  `scripts/build-deb.sh`) und in GitHub Actions identisch. Es baut, führt die Tests im Paketbau
  aus, prüft mit lintian, installiert das Paket in einem frischen Ubuntu und macht einen
  Smoke-Test (CLI, Vorschau-Rendering, Editor offscreen).
- **Versionen können nicht auseinanderlaufen:** `scripts/version.py` setzt und prüft die
  Version in `dailydeck/__init__.py`, `debian/changelog`, AppStream-Metadaten, Manpage und
  `CHANGELOG.md`. CI bricht ab, wenn sie nicht übereinstimmen oder nicht zum Tag passen.

## Ein Release machen

```bash
scripts/version.py bump 0.2.0      # setzt die Version überall, legt CHANGELOG-Abschnitt an
$EDITOR CHANGELOG.md               # Änderungen unter "## [0.2.0]" eintragen
scripts/build-deb.sh               # optional: lokal genau wie CI bauen und testen
git commit -am "Release 0.2.0"
git tag v0.2.0
git push && git push --tags        # Release-Workflow baut und veröffentlicht
```

Tags mit Bindestrich (`v0.2.0-rc1`) werden als Pre-Release veröffentlicht.

## Ubuntu (aktueller Stand)

| | |
|---|---|
| Paket | `dailydeck_<version>_all.deb`, ca. 60 KB, `Architecture: all` |
| Abhängigkeiten | ausschließlich Ubuntu-Pakete (python3-elgato-streamdeck, python3-pyside6.*, python3-evdev, …) – Sicherheitsupdates kommen über Ubuntu |
| Bauen | `scripts/build-deb.sh` (Docker), Ergebnis in `dist/` |
| Installieren | `sudo apt install ./dist/dailydeck_<version>_all.deb` |

Das Paket installiert:

- `/usr/bin/dailydeck`, Python-Modul in `/usr/lib/python3/dist-packages`
- Startmenü: „Daily Deck“ (Leisten-App) und „Daily Deck Profile“ (Editor)
- udev-Regel `60-dailydeck.rules`: Zugriff auf Stream Deck und `/dev/uinput` für den
  angemeldeten Benutzer (`uaccess`). `postinst` wendet sie sofort an, ohne Neustart.
- GNOME-Erweiterung systemweit; aktiviert wird sie pro Benutzer beim ersten Start der
  Leisten-App (Hinweis: wirksam nach erneutem Anmelden). Fehlt das Leistensymbol, bietet die
  App an, die AppIndicator-Erweiterung zu aktivieren.
- AppStream-Metadaten mit `modalias usb:v0FD9p*`: Softwarecenter können das Paket vorschlagen,
  wenn ein Stream Deck angeschlossen wird.
- optional `systemd --user`-Dienst ohne Leistensymbol (`systemctl --user enable --now dailydeck`)

> Sicherheitshinweis: `uaccess` auf `/dev/uinput` erlaubt Programmen des angemeldeten Benutzers,
> Tastatureingaben zu erzeugen. Steam, Solaar und Input-Remapper machen es genauso; auf
> Mehrbenutzer-Systemen sollte man das bewusst entscheiden.

### Nächster Schritt: PPA für automatische Updates

Ein `.deb` aus dem GitHub-Release muss man bei jeder Version neu herunterladen. Über ein
**Launchpad-PPA** kommen Updates per `apt`:

1. Launchpad-Konto, GPG-Schlüssel hochladen, PPA `ppa:<user>/dailydeck` anlegen.
2. Release-Workflow um einen Job erweitern: Quellpaket bauen (`dpkg-buildpackage -S`), Version
   pro Ubuntu-Release mit Suffix versehen (`0.2.0~resolute1`, `0.2.0~questing1`), mit dem
   GPG-Schlüssel aus einem GitHub-Secret signieren, `dput ppa:<user>/dailydeck`.
3. Launchpad baut für alle gewählten Ubuntu-Versionen selbst.

## Roadmap weitere Plattformen

| Ziel | Build | Werkzeug | Artefakt | Signieren | Stand |
|---|---|---|---|---|---|
| Ubuntu 26.04 | Container `ubuntu:26.04` | debhelper + pybuild | `.deb` | – (PPA: GPG) | **fertig** |
| Debian 13+ | Container `debian:trixie` | gleiches `debian/` | `.deb` | – | Abhängigkeiten prüfen (PySide6-Version) |
| Fedora | Container `fedora:latest` | RPM-Spec, `python3-pyside6` aus Fedora | `.rpm` | – (COPR) | geplant |
| Arch | – | `PKGBUILD` im AUR | – | – | geplant |
| Universell Linux | – | `pipx install dailydeck` (PyPI) | wheel | – | sdist/wheel werden schon gebaut |
| Windows 10/11 | `windows-latest` | PyInstaller (onedir) + Inno Setup | `.exe`-Installer | Authenticode (z. B. Azure Trusted Signing) | Backends vorbereitet, ungetestet |
| macOS 12+ | `macos-15` (arm64) | PyInstaller `.app` + `hdiutil` | `.dmg` | Developer ID + Notarisierung | **fertig** (Apple Silicon), Intel offen |

**Warum kein Flatpak/Snap?** Die App braucht `/dev/uinput` und den USB-Zugriff (udev-Regeln
lassen sich aus einer Sandbox nicht installieren), eine GNOME-Shell-Erweiterung und den Blick auf
fremde Fenster. Das widerspricht dem Sandbox-Modell; native Pakete sind hier der saubere Weg.

### Andere Desktops und Window-Manager (Linux)

Gerät, Tastenversand (uinput) und Leistensymbol (StatusNotifier) funktionieren überall. Pro
Desktop fehlt nur ein **Fokus-Backend** in `dailydeck/focus/` (Schnittstelle `FocusProvider`):

| Desktop | Wie das aktive Fenster ermitteln | Stand |
|---|---|---|
| GNOME (Wayland/X11) | eigene Shell-Erweiterung, D-Bus | fertig |
| X11 allgemein (Xfce, MATE, Cinnamon, i3 …) | `_NET_ACTIVE_WINDOW` (xprop) | fertig |
| KDE Plasma (Wayland) | KWin-Skript, meldet per D-Bus | geplant |
| Sway / i3 (Wayland) | i3-IPC (`swaymsg -t subscribe window`) | geplant |
| Hyprland | Event-Socket `socket2` (`activewindow`) | geplant |

Die Auswahl passiert in `create_focus_provider()` anhand von `XDG_CURRENT_DESKTOP`; für Tests
gibt es `dailydeck --print-focus`.

### Windows

- **Bauen:** `pyinstaller` mit `dailydeck/data` als Daten, `hidapi.dll` (aus den
  hidapi-Releases) neben die EXE; Einstiegspunkt `launch_tray.pyw` (ohne Konsole).
- **Installer:** Inno Setup: Startmenü, optional Autostart (die App setzt ihn selbst über die
  Registry, siehe `autostart.py`), Deinstallation.
- **Offen im Code:** Programmicons aus EXE-Dateien lesen (`appicons.py`), Test von
  `focus/windows.py` und `keys/pynput_sender.py`. Die Elgato-Software darf nicht parallel laufen.
- **Signieren:** ohne Signatur warnt SmartScreen. Zertifikat als GitHub-Secret, Signieren im Job.

### macOS

- **Bauen:** `scripts/build-macos.sh` (lokal und im Release-Job gleich), Details und Fallstricke
  in `docs/MACOS.md`. CI baut bei jedem Push unsigniert und prüft dabei die Mindestversion.
- **Signieren/Notarisieren:** Der Release-Job legt einen temporären Schlüsselbund aus den Secrets
  `MACOS_CERTIFICATE_P12`/`MACOS_CERTIFICATE_PASSWORD` an und notarisiert mit dem
  App-Store-Connect-Schlüssel (`MACOS_NOTARY_KEY_P8`, `MACOS_NOTARY_KEY_ID`, `MACOS_NOTARY_ISSUER`).
- **Rechte:** Bedienungshilfen (Tastendrücke senden); die App fragt beim ersten Start.
- **Später:** Intel-Build, Homebrew-Cask.

## Vor dem ersten öffentlichen Release klären

- **Signaturschlüssel** (PPA-GPG, später Windows/macOS) als GitHub-Secrets anlegen.
- **Markenhinweis:** „Stream Deck“ ist eine Marke von Elgato/Corsair. Der Projektname
  „Daily Deck“ ist eigenständig; Beschreibungen nennen das Gerät nur als unterstützte Hardware
  und enthalten den Hinweis „not affiliated with Elgato or Corsair“.
