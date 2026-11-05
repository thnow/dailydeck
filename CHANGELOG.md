# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/de/1.1.0/), Versionen nach
[Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

## [0.2.0] – 2026-11-05

### Neu
- macOS: läuft am Mac (getestet mit Stream Deck MK.2, macOS 27, Apple Silicon). Tastendrücke per
  Quartz passend zum Tastaturlayout, inklusive der von macOS angepassten Menükürzel
  (deutsches Layout: ⌘[ → ⌘Ö); Hinweis, wenn die Freigabe unter Bedienungshilfen fehlt.
- Modifier `primary` (⌘ auf dem Mac, sonst Strg) und pro Taste `keys_macos`, `keys_windows`,
  `keys_linux` – ein Profil für alle Systeme. Der Editor nimmt Strg/⌘ als `primary` auf und hat
  Felder für die Varianten.
- Standardprofile auf `primary` umgestellt, mit Mac-Kürzeln; neu: Safari, iTerm2 im Terminal-Profil.
- Eine unveränderte Konfiguration aus einer früheren Version wird beim Start durch die neue
  Standardkonfiguration ersetzt (alte Fassung als `config.toml.bak`); bearbeitete bleiben, wie sie sind.
- macOS: signiertes, notarisiertes DMG für Apple Silicon ab macOS 12, gebaut im Release-Workflow
  (`scripts/build-macos.sh`).
- Editor: Deck-Vorschau kompakter (fester Abstand statt des Geräte-Tastenabstands); Einstellungen
  in „Tasten“ und „Programmicon“ gruppiert, Icon-Optionen nur aktiv, wenn das Icon eingeblendet wird.

### Behoben
- macOS: aktives Programm wurde ohne Leistensymbol (`-v`, `--print-focus`) nicht aktualisiert.
- macOS: ⌘ allein wurde im Editor als `super+ctrl` aufgenommen.
- Editor lief auf kleinen Bildschirmen unten aus dem Bild; passt sich jetzt an und scrollt.
- macOS: Eingabefelder im Editor blieben schmal statt die Breite zu nutzen; ungleichmäßige Zeilenabstände.
- Qt-eigene Schaltflächen (Abbrechen, Ja, Nein …) jetzt deutsch; Standardschrift wird pro System richtig benannt.

## [0.1.0] – 2026-11-03

Erste Version.

- Stream Deck zeigt die Tastenkürzel des fokussierten Programms (Profile pro Anwendung).
- Linux: Fenstererkennung unter GNOME/Wayland (Shell-Extension) und X11, Tastendrücke per
  uinput passend zum Tastaturlayout.
- Programmicon über das ganze Deck, Aufblitzen beim Wechsel.
- Profil-Editor mit Live-Vorschau auf dem Deck, Kürzel-Aufnahme, Schriftauswahl.
- Profile als `.dailydeck` exportieren/importieren.
- Leistensymbol mit Pause, Profil festhalten, Helligkeit, Autostart.
