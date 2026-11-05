"""Tray icon (GNOME top bar via AppIndicator, Windows notification area,
macOS menu bar) that runs the daemon and offers quick settings."""

import logging
import signal
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLockFile, QObject, QPointF, QRectF, Qt, QTimer, QTranslator
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import autostart, integration
from .app import Daemon, DaemonStatus
from .config import DATA_DIR, ConfigError, default_config_path, parse_settings, read_config_data
from .preview import runtime_dir
from .profile_io import save_config

log = logging.getLogger(__name__)

BRIGHTNESS_STEPS = (10, 25, 40, 60, 80, 100)


def make_tray_icon(dimmed: bool = False) -> QIcon:
    """A small deck: rounded frame with 3x2 keys, drawn in white.

    On macOS the icon is a template ("mask") so the menu bar recolours it.
    """
    icon = QIcon()
    for size in (16, 22, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(255, 255, 255, 110 if dimmed else 255)
        if sys.platform == "darwin":
            color = QColor(0, 0, 0, 110 if dimmed else 255)
        pen_w = max(1.0, size / 14)
        p.setPen(color)
        pen = p.pen()
        pen.setWidthF(pen_w)
        p.setPen(pen)
        frame = QRectF(pen_w / 2 + size * 0.04, size * 0.2, size * 0.92 - pen_w, size * 0.6)
        p.drawRoundedRect(frame, size * 0.12, size * 0.12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        cols, rows = 3, 2
        gap = size * 0.07
        inner = frame.adjusted(size * 0.11, size * 0.1, -size * 0.11, -size * 0.1)
        kw = (inner.width() - gap * (cols - 1)) / cols
        kh = (inner.height() - gap * (rows - 1)) / rows
        for r in range(rows):
            for c in range(cols):
                x = inner.left() + c * (kw + gap)
                y = inner.top() + r * (kh + gap)
                p.drawRoundedRect(QRectF(QPointF(x, y), QPointF(x + kw, y + kh)), kw * 0.2, kw * 0.2)
        p.end()
        icon.addPixmap(pixmap)
    if sys.platform == "darwin":
        icon.setIsMask(True)
    return icon


class TrayApp(QObject):
    def __init__(self, app: QApplication, config_path: Path):
        super().__init__()
        self.app = app
        self.config_path = config_path
        self.editor = None
        self._last: DaemonStatus | None = None
        self._profile_names: tuple[str, ...] | None = None

        self.daemon = Daemon(config_path)
        self.thread = threading.Thread(target=self._run_daemon, name="daemon", daemon=True)
        self.thread.start()

        self._icons = {False: make_tray_icon(False), True: make_tray_icon(True)}
        self.tray = QSystemTrayIcon(self._icons[True], app)
        self.tray.setToolTip("Daily Deck")
        self._build_menu()
        self.tray.activated.connect(self._activated)
        self.tray.show()

        self.timer = QTimer(self, interval=500, timeout=self.refresh)
        self.timer.start()
        self.refresh()

    def _run_daemon(self) -> None:
        try:
            self.daemon.run()
        except Exception:  # noqa: BLE001
            log.exception("daemon crashed")

    # --- menu ---------------------------------------------------------------

    def _build_menu(self) -> None:
        m = self.menu = QMenu()
        self.header = m.addAction("Daily Deck")
        self.header.setEnabled(False)
        self.status_action = m.addAction("")
        self.status_action.setEnabled(False)
        m.addSeparator()
        self.edit_profile_action = m.addAction("Profil bearbeiten …", self._edit_current_profile)
        m.addAction("Editor öffnen …", lambda: self.open_editor())
        m.addSeparator()

        self.pause_action = QAction("Pausieren", m, checkable=True)
        self.pause_action.toggled.connect(self.daemon.set_paused)
        m.addAction(self.pause_action)
        self.pin_menu = m.addMenu("Profil festhalten")
        self.pin_group = QActionGroup(self.pin_menu)
        self.pin_group.setExclusive(True)
        m.addSeparator()

        self.brightness_menu = m.addMenu("Helligkeit")
        self.brightness_group = QActionGroup(self.brightness_menu)
        for value in BRIGHTNESS_STEPS:
            action = QAction(f"{value} %", self.brightness_menu, checkable=True)
            action.setData(value)
            action.triggered.connect(lambda _=False, v=value: self._set_setting("brightness", v))
            self.brightness_group.addAction(action)
            self.brightness_menu.addAction(action)
        self.app_icon_action = QAction("Programmicon einblenden", m, checkable=True)
        self.app_icon_action.triggered.connect(lambda on: self._set_setting("app_icon", on))
        m.addAction(self.app_icon_action)
        self.show_keys_action = QAction("Kürzel auf den Tasten anzeigen", m, checkable=True)
        self.show_keys_action.triggered.connect(lambda on: self._set_setting("show_keys", on))
        m.addAction(self.show_keys_action)
        m.addSeparator()

        self.autostart_action = QAction("Beim Anmelden starten", m, checkable=True)
        self.autostart_action.setChecked(autostart.is_enabled())
        self.autostart_action.triggered.connect(self._set_autostart)
        m.addAction(self.autostart_action)
        m.addAction("Beenden", self.quit)
        self.tray.setContextMenu(m)

    def _rebuild_pin_menu(self, names: tuple[str, ...]) -> None:
        self.pin_menu.clear()
        for action in self.pin_group.actions():
            self.pin_group.removeAction(action)
        auto = QAction("Automatisch (aktives Fenster)", self.pin_menu, checkable=True)
        auto.setData(None)
        self.pin_group.addAction(auto)
        self.pin_menu.addAction(auto)
        self.pin_menu.addSeparator()
        for name in names:
            action = QAction(name, self.pin_menu, checkable=True)
            action.setData(name)
            self.pin_group.addAction(action)
            self.pin_menu.addAction(action)
        for action in self.pin_group.actions():
            action.triggered.connect(lambda _=False, a=action: self.daemon.set_pinned(a.data()))
        self._profile_names = names

    def refresh(self) -> None:
        st = self.daemon.status
        if st == self._last:
            return
        self._last = st

        if st.error:
            line = f"Fehler: {st.error}"
        elif not st.connected:
            line = "Kein Stream Deck verbunden"
        elif st.paused:
            line = "Pausiert"
        elif st.previewing:
            line = "Vorschau aus dem Editor"
        elif st.pinned:
            line = f"Festgehalten: {st.pinned}"
        else:
            line = f"Profil: {st.profile or '–'}"
        self.status_action.setText(line)
        self.header.setText(st.app_name or "Daily Deck")
        self.header.setIcon(QIcon(str(st.icon)) if st.icon else QIcon())
        self.tray.setToolTip(f"Daily Deck – {line}")
        self.tray.setIcon(self._icons[not st.connected or st.paused])

        self.edit_profile_action.setText(f"Profil „{st.profile}“ bearbeiten …" if st.profile
                                         else "Profil für dieses Programm anlegen …")
        if self.pause_action.isChecked() != st.paused:
            self.pause_action.blockSignals(True)
            self.pause_action.setChecked(st.paused)
            self.pause_action.blockSignals(False)
        if st.profiles != self._profile_names:
            self._rebuild_pin_menu(st.profiles)
        for action in self.pin_group.actions():
            action.setChecked(action.data() == st.pinned)

        settings = self._settings()
        for action in self.brightness_group.actions():
            action.setChecked(action.data() == min(BRIGHTNESS_STEPS, key=lambda v: abs(v - settings.brightness)))
        self.app_icon_action.setChecked(settings.app_icon)
        self.show_keys_action.setChecked(settings.show_keys)

    def _settings(self):
        try:
            return parse_settings(read_config_data(self.config_path))
        except (ConfigError, TypeError, ValueError):
            return parse_settings({})

    # --- actions --------------------------------------------------------------

    def _activated(self, reason) -> None:
        # left click: on Windows/macOS open the editor; GNOME always shows the menu
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) \
                and sys.platform != "linux":
            self.open_editor()

    def _set_setting(self, key: str, value) -> None:
        try:
            data = read_config_data(self.config_path)
            data.setdefault("settings", {})[key] = value
            save_config(data, self.config_path)
        except (ConfigError, OSError) as e:
            self.tray.showMessage("Daily Deck", f"Einstellung nicht gespeichert: {e}",
                                  QSystemTrayIcon.MessageIcon.Warning)
        self._last = None  # force refresh of check marks
        self.refresh()

    def _set_autostart(self, on: bool) -> None:
        try:
            autostart.set_enabled(on)
        except OSError as e:
            self.tray.showMessage("Daily Deck", f"Autostart nicht geändert: {e}",
                                  QSystemTrayIcon.MessageIcon.Warning)
        self.autostart_action.setChecked(autostart.is_enabled())

    def _edit_current_profile(self) -> None:
        st = self.daemon.status
        if st.profile:
            self.open_editor(profile=st.profile)
        else:
            self.open_editor(new_for=(st.app_name, st.app_ids))

    def open_editor(self, profile: str | None = None, new_for=None) -> None:
        from .gui import MainWindow

        if self.editor is None or not self.editor.isVisible():
            self.editor = MainWindow(self.config_path)
        self.editor.show()
        self.editor.raise_()
        self.editor.activateWindow()
        if profile:
            self.editor.select_profile(profile)
        elif new_for:
            self.editor.new_profile_for(*new_for)

    def quit(self) -> None:
        if self.editor is not None and self.editor.isVisible() and not self.editor.close():
            return
        self.timer.stop()
        self.daemon.stop()
        self.thread.join(timeout=5)
        self.tray.hide()
        self.app.quit()


def app_icon() -> QIcon:
    """Themed icon of the installed app, else the bundled SVG."""
    themed = QIcon.fromTheme("io.github.thnow.dailydeck")
    return themed if not themed.isNull() else QIcon(str(DATA_DIR / "io.github.thnow.dailydeck.svg"))


def check_desktop_integration(tray: TrayApp) -> None:
    """GNOME: focus extension enabled? Tray icon visible? Offer fixes."""
    if not integration.is_gnome():
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning("no system tray available; the deck works anyway")
        return
    if message := integration.ensure_focus_extension():
        _notify(tray, message)
    if QSystemTrayIcon.isSystemTrayAvailable():
        return
    uuid, active = integration.appindicator_extension()
    if uuid and not active:
        answer = QMessageBox.question(
            None, "Daily Deck",
            "Damit das Daily-Deck-Symbol in der oberen Leiste erscheint, muss die GNOME-Erweiterung "
            "„AppIndicator“ aktiviert werden.\n\nJetzt aktivieren? (Danach erscheinen dort auch die "
            "Symbole anderer Programme, die so etwas anbieten.)")
        if answer == QMessageBox.StandardButton.Yes:
            integration.enable_extension(uuid)
            # register again with the new StatusNotifier host
            QTimer.singleShot(1500, lambda: (tray.tray.hide(), tray.tray.show()))
    elif not uuid:
        QMessageBox.information(
            None, "Daily Deck",
            "Für das Symbol in der oberen Leiste fehlt eine AppIndicator-Erweiterung für GNOME "
            "(Paket „gnome-shell-extension-appindicator“). Das Stream Deck funktioniert trotzdem; "
            "Einstellungen gibt es dann im Editor.")


def _notify(tray: TrayApp, message: str) -> None:
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.tray.showMessage("Daily Deck", message, QSystemTrayIcon.MessageIcon.Information, 15000)
    else:
        QMessageBox.information(None, "Daily Deck", message)


def install_translations(app: QApplication) -> None:
    """German texts for Qt's own buttons and dialogs (Abbrechen, Ja, Nein …), matching the rest of the UI."""
    translator = QTranslator(app)
    if translator.load("qtbase_de", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)


def main(config_path: Path | None = None) -> int:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                            datefmt="%H:%M:%S")
        logging.getLogger("PIL").setLevel(logging.INFO)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Daily Deck")
    install_translations(app)
    app.setDesktopFileName("io.github.thnow.dailydeck")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(str(runtime_dir() / "tray.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Daily Deck", "Daily Deck läuft bereits (Symbol in der Leiste).")
        return 0

    path = (config_path or default_config_path()).expanduser().resolve()
    tray = TrayApp(app, path)
    QTimer.singleShot(1000, lambda: check_desktop_integration(tray))

    # let Ctrl+C / SIGTERM end the Qt loop cleanly
    signal.signal(signal.SIGINT, lambda *_: tray.quit())
    signal.signal(signal.SIGTERM, lambda *_: tray.quit())
    keepalive = QTimer(interval=300, timeout=lambda: None)  # lets Python run signal handlers
    keepalive.start()
    try:
        return app.exec()
    finally:
        lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
