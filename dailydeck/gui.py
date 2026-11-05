"""Profile editor (PySide6).

Edits the same config.toml the daemon reads; the daemon reloads it as soon as
it is saved.
"""

import copy
import os
import shutil
import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .config import (
    KEY_FIELDS,
    PLATFORM_LABELS,
    Button,
    ConfigError,
    Profile,
    button_chords,
    current_platform,
    default_config_path,
    load_button,
    parse_settings,
    read_config_data,
)
from .fonts import font_spec, list_fonts, split_spec
from .keys import ShortcutError
from .layout import NavSlot, backdrop_tiles, icon_for, page_count, page_slots, per_page, render_slot
from .preview import clear_request, make_payload, read_ack, request_from_payload, send_request
from .profile_io import PROFILE_SUFFIX, clean_profile, export_profile, import_profile, save_config
from .render import default_font_name

COLS, ROWS = 5, 3
KEY_COUNT = COLS * ROWS
KEY_SIZE = (72, 72)
PREVIEW_PX = 88
SOFT_HYPHEN = "­"
SLOT_MIME = "application/x-dailydeck-slot"


def to_pixmap(image: Image.Image, size: int = PREVIEW_PX) -> QPixmap:
    image = image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
    data = image.tobytes("raw", "RGB")
    qimage = QImage(data, image.width, image.height, 3 * image.width, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimage.copy())


# ------------------------------------------------------------------ key capture

def _k(name: str) -> int:
    return Qt.Key[name].value


QT_KEY_NAMES = {
    _k("Key_Return"): "enter", _k("Key_Enter"): "enter", _k("Key_Escape"): "esc",
    _k("Key_Tab"): "tab", _k("Key_Backtab"): "tab", _k("Key_Space"): "space",
    _k("Key_Backspace"): "backspace", _k("Key_Delete"): "delete", _k("Key_Insert"): "insert",
    _k("Key_Home"): "home", _k("Key_End"): "end", _k("Key_PageUp"): "pageup",
    _k("Key_PageDown"): "pagedown", _k("Key_Up"): "up", _k("Key_Down"): "down",
    _k("Key_Left"): "left", _k("Key_Right"): "right", _k("Key_Print"): "print",
    _k("Key_Menu"): "menu", _k("Key_CapsLock"): "capslock", _k("Key_Pause"): "pause",
    _k("Key_VolumeUp"): "volumeup", _k("Key_VolumeDown"): "volumedown",
    _k("Key_VolumeMute"): "mute", _k("Key_MediaPlay"): "playpause",
    _k("Key_MediaTogglePlayPause"): "playpause", _k("Key_MediaPause"): "playpause",
    _k("Key_MediaNext"): "nexttrack", _k("Key_MediaPrevious"): "prevtrack",
    **{_k(f"Key_F{i}"): f"f{i}" for i in range(1, 25)},
}
# Qt reports Cmd as Control and Ctrl as Meta on macOS. Control/Cmd is the platform's
# primary modifier, recorded as "primary" so the shortcut also works on the other systems.
_META = "ctrl" if sys.platform == "darwin" else "super"
QT_MODIFIER_KEYS = {
    _k("Key_Control"): "primary", _k("Key_Shift"): "shift", _k("Key_Alt"): "alt",
    _k("Key_AltGr"): "altgr", _k("Key_Meta"): _META, _k("Key_Super_L"): "super",
    _k("Key_Super_R"): "super",
}
CHAR_NAMES = {"+": "plus", "-": "minus", " ": "space"}
KEYS_PLACEHOLDER = "z. B. primary+shift+t (primary = Strg, auf dem Mac ⌘)"


def _modifier_names(mods) -> list[str]:
    KM = Qt.KeyboardModifier
    names = []
    if mods & KM.ControlModifier:
        names.append("primary")
    if mods & KM.AltModifier:
        names.append("alt")
    if mods & KM.GroupSwitchModifier:
        names.append("altgr")
    if mods & KM.ShiftModifier:
        names.append("shift")
    if mods & KM.MetaModifier:
        names.append(_META)
    return names


def chord_from_event(event) -> str | None:
    key = int(event.key())
    mods = _modifier_names(event.modifiers())
    if key in QT_KEY_NAMES:
        name = QT_KEY_NAMES[key]
    elif 0x20 <= key < 0x110000:
        char = chr(key)
        if char.isalpha():
            name = char.lower()
        else:
            # the character already implies Shift/AltGr in the current layout
            mods = [m for m in mods if m not in ("shift", "altgr")]
            name = CHAR_NAMES.get(char, char)
    else:
        return None
    return "+".join(mods + [name])


def _form(parent: QWidget) -> QFormLayout:
    """A form whose fields use the free width (macOS keeps them at their size hint)."""
    form = QFormLayout(parent)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setVerticalSpacing(10)  # even rows; the style spaces rows with buttons further apart
    return form


def _compact(widget: QWidget) -> QWidget:
    """Keeps a spin box at its natural width inside a growing form."""
    widget.setSizePolicy(QSizePolicy.Policy.Fixed, widget.sizePolicy().verticalPolicy())
    widget.setMinimumWidth(110)
    return widget


class ShortcutEdit(QLineEdit):
    """Line edit that can record key presses ("ctrl+k z")."""

    recordingChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recording = False
        self._chords: list[str] = []
        self._pending_mods: list[str] = []
        self._idle = QTimer(self, singleShot=True, interval=1500, timeout=self.stop_recording)

    @property
    def recording(self) -> bool:
        return self._recording

    def start_recording(self) -> None:
        self._recording = True
        self._chords = []
        self._pending_mods = []
        self.setText("")
        self.setPlaceholderText("Tastenkombination drücken …")
        self.setFocus()
        self.grabKeyboard()
        self.recordingChanged.emit(True)

    def stop_recording(self) -> None:
        if not self._recording:
            return
        self._recording = False
        self._idle.stop()
        self.releaseKeyboard()
        self.setPlaceholderText(KEYS_PLACEHOLDER)
        self.recordingChanged.emit(False)
        self.editingFinished.emit()

    def event(self, event) -> bool:
        if self._recording:
            # keep window shortcuts (Ctrl+S ...) and Tab focus changes out of the way
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            if event.type() == QEvent.Type.KeyPress and int(event.key()) in (_k("Key_Tab"), _k("Key_Backtab")):
                self.keyPressEvent(event)
                return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:
        if not self._recording:
            return super().keyPressEvent(event)
        key = int(event.key())
        if key in QT_MODIFIER_KEYS:
            self._pending_mods = _modifier_names(event.modifiers()) or [QT_MODIFIER_KEYS[key]]
            if QT_MODIFIER_KEYS[key] not in self._pending_mods:
                self._pending_mods.append(QT_MODIFIER_KEYS[key])
            return
        self._pending_mods = []
        if (chord := chord_from_event(event)) is not None:
            self._append(chord)

    def keyReleaseEvent(self, event) -> None:
        if not self._recording:
            return super().keyReleaseEvent(event)
        # a modifier pressed and released alone, e.g. "super" for the overview
        if int(event.key()) in QT_MODIFIER_KEYS and self._pending_mods:
            self._append("+".join(self._pending_mods))
            self._pending_mods = []

    def _append(self, chord: str) -> None:
        self._chords.append(chord)
        self.setText(" ".join(self._chords))
        self._idle.start()

    def focusOutEvent(self, event) -> None:
        self.stop_recording()
        super().focusOutEvent(event)


# ------------------------------------------------------------------ small widgets

class ColorButton(QWidget):
    """Colour swatch with a reset button; ``None`` means "inherit"."""

    changed = Signal(object)

    def __init__(self, inherit_text: str = "Standard", parent=None):
        super().__init__(parent)
        self._color: str | None = None
        self._inherit = inherit_text
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._button = QPushButton(clicked=self._pick)
        self._button.setMinimumWidth(110)
        self._reset = QToolButton(text="×", clicked=lambda: self._set(None, emit=True))
        self._reset.setToolTip("Zurücksetzen")
        layout.addWidget(self._button)
        layout.addWidget(self._reset)
        self._update()

    def color(self) -> str | None:
        return self._color

    def set_color(self, color: str | None) -> None:
        self._set(color, emit=False)

    def _set(self, color: str | None, emit: bool) -> None:
        self._color = color
        self._update()
        if emit:
            self.changed.emit(color)

    def _pick(self) -> None:
        initial = QColor(self._color) if self._color else QColor("#303030")
        color = QColorDialog.getColor(initial, self, "Farbe wählen")
        if color.isValid():
            self._set(color.name(), emit=True)

    def _update(self) -> None:
        if self._color:
            fg = "#000" if QColor(self._color).lightness() > 150 else "#fff"
            self._button.setText(self._color)
            self._button.setStyleSheet(f"background:{self._color}; color:{fg};")
        else:
            self._button.setText(self._inherit)
            self._button.setStyleSheet("")
        self._reset.setEnabled(self._color is not None)


class IconPicker(QWidget):
    """Image file chooser. Chosen files are copied into the config directory
    so the config stays self-contained (and profiles can be exported)."""

    changed = Signal(object)

    def __init__(self, config_dir_getter, placeholder: str = "kein Bild", parent=None):
        super().__init__(parent)
        self._config_dir = config_dir_getter
        self._path: str | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLineEdit(readOnly=True, placeholderText=placeholder)
        layout.addWidget(self._label, 1)
        layout.addWidget(QPushButton("Wählen …", clicked=self._pick))
        self._reset = QToolButton(text="×", clicked=lambda: self._set(None, emit=True))
        layout.addWidget(self._reset)
        self._update()

    def path(self) -> str | None:
        return self._path

    def set_path(self, path: str | None) -> None:
        self._set(path, emit=False)

    def _set(self, path: str | None, emit: bool) -> None:
        self._path = path
        self._update()
        if emit:
            self.changed.emit(path)

    def _update(self) -> None:
        self._label.setText(self._path or "")
        self._reset.setEnabled(self._path is not None)

    def _pick(self) -> None:
        file, _ = QFileDialog.getOpenFileName(
            self, "Bild wählen", str(Path.home()), "Bilder (*.png *.svg *.jpg *.jpeg *.gif *.webp *.ico *.icns)")
        if not file:
            return
        src = Path(file)
        config_dir = self._config_dir()
        icons = config_dir / "icons"
        try:
            src.relative_to(config_dir)
            target = src
        except ValueError:
            icons.mkdir(parents=True, exist_ok=True)
            target = icons / src.name
            n = 1
            while target.exists() and target.read_bytes() != src.read_bytes():
                n += 1
                target = icons / f"{src.stem}-{n}{src.suffix}"
            if not target.exists():
                shutil.copy2(src, target)
        self._set(str(target.relative_to(config_dir)), emit=True)


class KeyTile(QLabel):
    """One key of the deck preview: click to select, drag to move."""

    clicked = Signal(int)
    dropped = Signal(int, int)
    clearRequested = Signal(int)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.movable = True
        self._press: QPoint | None = None
        self.setFixedSize(PREVIEW_PX + 8, PREVIEW_PX + 8)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        color = "#3daee9" if selected else "transparent"
        self.setStyleSheet(f"border: 3px solid {color}; border-radius: 6px;")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self.clicked.emit(self.index)

    def mouseMoveEvent(self, event) -> None:
        if not self.movable or self._press is None:
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(SLOT_MIME, str(self.index).encode())
        drag.setMimeData(mime)
        if self.pixmap():
            drag.setPixmap(self.pixmap())
        self._press = None
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:
        if self.movable and event.mimeData().hasFormat(SLOT_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        src = int(bytes(event.mimeData().data(SLOT_MIME)).decode())
        if src != self.index:
            self.dropped.emit(src, self.index)
        event.acceptProposedAction()

    def contextMenuEvent(self, event) -> None:
        if not self.movable:
            return
        menu = QMenu(self)
        menu.addAction("Taste leeren", lambda: self.clearRequested.emit(self.index))
        menu.exec(event.globalPos())


class FontCombo(QComboBox):
    """Searchable font list; stores "Family:Style", ``None`` = default."""

    changed = Signal(object)

    def __init__(self, default_text: str, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(20)
        self.addItem(default_text, None)
        for family, style in list_fonts():
            self.addItem(f"{family} – {style}" if style else family, font_spec(family, style))
        completer = self.completer()
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.lineEdit().setPlaceholderText("Schrift suchen …")
        self._spec: str | None = None
        self.activated.connect(self._on_activated)
        self.lineEdit().editingFinished.connect(self._on_edit_finished)

    def spec(self) -> str | None:
        return self._spec

    def set_spec(self, spec: str | None) -> None:
        self._spec = spec
        index = self.findData(spec)
        if index < 0:  # e.g. a font of another machine or a file path
            family, style = split_spec(spec)
            self.addItem(f"{family} – {style} (nicht installiert)" if style else f"{spec} (nicht gefunden)", spec)
            index = self.count() - 1
        self.blockSignals(True)
        self.setCurrentIndex(index)
        self.blockSignals(False)

    def _on_activated(self, index: int) -> None:
        spec = self.itemData(index)
        if spec != self._spec:
            self._spec = spec
            self.changed.emit(spec)

    def _on_edit_finished(self) -> None:
        index = self.findText(self.currentText())
        if index >= 0:
            self._on_activated(index)
        else:  # unknown text: show the current choice again
            self.set_spec(self._spec)


class DeckPreview(QObject):
    """Shows the edited profile on the real deck.

    Asks the running daemon (via the preview request file). If the daemon
    does not answer, the deck is opened directly from the editor.
    """

    status = Signal(str)
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False
        self._payload: dict | None = None
        self._counter = 0
        self._direct = None  # DeckController when the daemon is not running
        self._heartbeat = QTimer(self, interval=2000, timeout=self._beat)
        self._ack_timer = QTimer(self, singleShot=True, interval=1500, timeout=self._check_ack)

    def start(self, profile: dict, settings: dict, config_dir: Path, ids, page: int) -> None:
        self.active = True
        self.update(profile, settings, config_dir, ids, page)
        self._heartbeat.start()
        self._ack_timer.start()
        self.status.emit("Vorschau auf dem Deck – Tasten lösen dabei nichts aus.")

    def update(self, profile: dict, settings: dict, config_dir: Path, ids, page: int) -> None:
        if not self.active:
            return
        self._counter += 1
        self._payload = make_payload(f"{os.getpid()}-{self._counter}", profile, settings, config_dir, ids, page)
        try:
            if self._direct is not None:
                request = request_from_payload(self._payload)
                self._direct.preview(request.profile, request.settings, request.ids, request.page)
            else:
                send_request(self._payload)
        except Exception as e:  # noqa: BLE001
            self.status.emit(f"Vorschau fehlgeschlagen: {e}")

    def stop(self) -> None:
        if not self.active:
            return
        self.active = False
        self._heartbeat.stop()
        self._ack_timer.stop()
        clear_request()
        if self._direct is not None:
            self._direct.close()
            self._direct = None
        self.stopped.emit()

    def _beat(self) -> None:
        if self.active and self._direct is None and self._payload:
            send_request(self._payload)

    def _check_ack(self) -> None:
        if not self.active or self._direct is not None:
            return
        if (read_ack() or "").startswith(f"{os.getpid()}-"):
            return  # the daemon shows it
        self._open_direct()

    def _open_direct(self) -> None:
        clear_request()
        try:
            from StreamDeck.DeviceManager import DeviceManager

            from .app import DeckController
            from .config import Config
            from .keys.base import NullKeySender

            decks = DeviceManager().enumerate()
            if not decks:
                self.status.emit("Kein Stream Deck gefunden.")
                self.stop()
                return
            request = request_from_payload(self._payload)
            config = Config(Path(self._payload["config_dir"]), request.settings, [request.profile])
            self._direct = DeckController(decks[0], NullKeySender(), config)
            self._direct.preview(request.profile, request.settings, request.ids, request.page)
            self.status.emit("Daemon läuft nicht – Vorschau direkt auf dem Deck.")
        except Exception as e:  # noqa: BLE001
            self._direct = None
            self.status.emit(f"Stream Deck nicht verfügbar: {e}")
            self.stop()


# ------------------------------------------------------------------ settings dialog

class SettingsDialog(QDialog):
    """Changes are applied live through ``on_change``; Cancel restores them."""

    def __init__(self, settings: dict, on_change=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._original = copy.deepcopy(settings)
        self._on_change = on_change
        self.setWindowTitle("Einstellungen")
        defaults = parse_settings({})
        get = lambda key: settings.get(key, getattr(defaults, key))  # noqa: E731

        layout = QVBoxLayout(self)

        keys = QGroupBox("Tasten")
        form = _form(keys)
        self.font = FontCombo(f"Standard ({default_font_name()})")
        self.font.set_spec(settings.get("font"))
        self.font.setMinimumWidth(320)
        form.addRow("Schriftart", self.font)
        self.brightness = self._slider(int(get("brightness")))
        form.addRow("Helligkeit Deck", self.brightness)
        self.show_keys = QCheckBox("Kürzel unter der Beschriftung anzeigen", checked=bool(get("show_keys")))
        form.addRow("", self.show_keys)
        layout.addWidget(keys)

        icon = QGroupBox("Programmicon")
        form = _form(icon)
        self.app_icon = QCheckBox("Icon des Programms über alle Tasten einblenden", checked=bool(get("app_icon")))
        form.addRow("", self.app_icon)
        self.icon_brightness = self._slider(round(get("app_icon_brightness") * 100))
        form.addRow("Helligkeit Icon", self.icon_brightness)
        self.opacity = self._slider(round(get("button_opacity") * 100))
        self.opacity.setToolTip("Wie stark die Tastenfarbe das Icon überdeckt")
        form.addRow("Deckkraft der Tasten", self.opacity)
        self.flash = QDoubleSpinBox(minimum=0, maximum=5, singleStep=0.1, suffix=" s",
                                    value=float(get("app_icon_flash")))
        self.flash.setToolTip("So lange leuchtet das Icon nach einem Programmwechsel in voller Helligkeit; 0 = aus")
        form.addRow("Aufblitzen beim Wechsel", _compact(self.flash))
        self.spacing = QSpinBox(minimum=0, maximum=100, suffix=" px", value=int(get("key_spacing")))
        self.spacing.setToolTip("Abstand zwischen den Tasten am Gerät, damit das Icon durchgehend wirkt")
        form.addRow("Tastenabstand am Gerät", _compact(self.spacing))
        layout.addWidget(icon)
        self.app_icon.toggled.connect(self._icon_rows_enabled)
        self._icon_rows_enabled(self.app_icon.isChecked())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.font.changed.connect(self._changed)
        for box in (self.brightness, self.icon_brightness, self.opacity):
            box.slider.valueChanged.connect(self._changed)
        for check in (self.show_keys, self.app_icon):
            check.toggled.connect(self._changed)
        self.flash.valueChanged.connect(self._changed)
        self.spacing.valueChanged.connect(self._changed)

    def _icon_rows_enabled(self, on: bool) -> None:
        for widget in (self.icon_brightness, self.opacity, self.flash, self.spacing):
            widget.setEnabled(on)

    def _changed(self, *_) -> None:
        self.apply(self._settings)
        if self._on_change:
            self._on_change()

    def reject(self) -> None:
        self._settings.clear()
        self._settings.update(self._original)
        if self._on_change:
            self._on_change()
        super().reject()

    @staticmethod
    def _slider(value: int) -> QWidget:
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Orientation.Horizontal, minimum=0, maximum=100, value=value)
        label = QLabel(f"{value} %")
        label.setMinimumWidth(45)
        slider.valueChanged.connect(lambda v: label.setText(f"{v} %"))
        layout.addWidget(slider, 1)
        layout.addWidget(label)
        box.slider = slider
        return box

    def apply(self, settings: dict) -> None:
        settings["brightness"] = self.brightness.slider.value()
        settings["show_keys"] = self.show_keys.isChecked()
        settings["app_icon"] = self.app_icon.isChecked()
        settings["app_icon_brightness"] = round(self.icon_brightness.slider.value() / 100, 2)
        settings["button_opacity"] = round(self.opacity.slider.value() / 100, 2)
        settings["app_icon_flash"] = round(self.flash.value(), 2)
        settings["key_spacing"] = self.spacing.value()
        if self.font.spec():
            settings["font"] = self.font.spec()
        else:
            settings.pop("font", None)


# ------------------------------------------------------------------ main window

class MainWindow(QMainWindow):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.data: dict = {}
        self.dirty = False
        self.page = 0
        self.slot: int | None = None  # flat button index
        self._loading = False
        self._focus = None
        self._countdown = 0

        self._render_timer = QTimer(self, singleShot=True, interval=60, timeout=self._render_deck)
        self.deck_preview = DeckPreview(self)
        self.deck_preview.status.connect(lambda text: self.statusBar().showMessage(text, 8000))
        self._capture_timer = QTimer(self, interval=1000, timeout=self._capture_tick)
        # the tray menu (or a text editor) may change the file while we are open
        self._known_mtime: int | None = None
        self._external_change = False
        self._watch_timer = QTimer(self, interval=1000, timeout=self._check_external_change)
        self._watch_timer.start()

        self._build_ui()
        self._build_menu()
        self.load()

    # --- UI construction --------------------------------------------------

    def _build_ui(self) -> None:
        splitter = QSplitter()
        self.setCentralWidget(splitter)

        # profiles
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel("<b>Profile</b> (erstes passendes gewinnt)"))
        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._select_profile)
        lv.addWidget(self.profile_list, 1)
        row = QHBoxLayout()
        for text, tip, slot in (
            ("+", "Neues Profil", self._add_profile),
            ("⧉", "Profil duplizieren", self._duplicate_profile),
            ("−", "Profil löschen", self._delete_profile),
            ("↑", "Nach oben", lambda: self._move_profile(-1)),
            ("↓", "Nach unten", lambda: self._move_profile(1)),
        ):
            b = QToolButton(text=text, clicked=slot)
            b.setToolTip(tip)
            row.addWidget(b)
        row.addStretch()
        lv.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Importieren …", clicked=self._import_profile))
        row.addWidget(QPushButton("Exportieren …", clicked=self._export_profile))
        lv.addLayout(row)
        splitter.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        # scrolls on small screens (e.g. a 13" notebook) instead of running off the bottom
        scroll = QScrollArea()
        scroll.setWidget(right)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 760])

        # profile properties
        box = QGroupBox("Profil")
        form = _form(box)
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._profile_changed)
        form.addRow("Name", self.name_edit)
        match_row = QHBoxLayout()
        self.match_edit = QLineEdit(placeholderText="z. B. firefox, org.mozilla.firefox, firefox.exe")
        self.match_edit.setToolTip("Kennungen der Anwendung, durch Komma getrennt. * und ? als Platzhalter.")
        self.match_edit.textEdited.connect(self._profile_changed)
        self.capture_button = QPushButton("Aktives Fenster übernehmen", clicked=self._start_capture)
        self.capture_button.setToolTip("Nach 3 Sekunden wird das dann aktive Fenster erkannt – vorher hinüberwechseln.")
        match_row.addWidget(self.match_edit, 1)
        match_row.addWidget(self.capture_button)
        form.addRow("Erkennung", match_row)
        self.title_edit = QLineEdit(placeholderText="optional, regulärer Ausdruck, z. B. YouTube")
        self.title_edit.textEdited.connect(self._profile_changed)
        form.addRow("Fenstertitel", self.title_edit)
        self.default_check = QCheckBox("Standardprofil, wenn kein anderes passt")
        self.default_check.toggled.connect(self._profile_changed)
        form.addRow("", self.default_check)
        colors = QHBoxLayout()
        self.profile_color = ColorButton("Standard")
        self.profile_color.changed.connect(self._profile_changed)
        self.profile_text_color = ColorButton("Standard")
        self.profile_text_color.changed.connect(self._profile_changed)
        colors.addWidget(QLabel("Hintergrund"))
        colors.addWidget(self.profile_color)
        colors.addWidget(QLabel("Schrift"))
        colors.addWidget(self.profile_text_color)
        colors.addStretch()
        form.addRow("Farben", colors)
        self.profile_icon = IconPicker(self.config_dir, "automatisch (Icon der Anwendung)")
        self.profile_icon.changed.connect(self._profile_changed)
        form.addRow("Programmicon", self.profile_icon)
        self.profile_font = FontCombo("aus den Einstellungen")
        self.profile_font.changed.connect(self._profile_changed)
        form.addRow("Schriftart", self.profile_font)
        rv.addWidget(box)

        # deck preview
        deck_box = QGroupBox("Deck  –  Taste anklicken zum Bearbeiten, ziehen zum Verschieben")
        dv = QVBoxLayout(deck_box)
        frame = QFrame()
        frame.setStyleSheet("background:#151515; border-radius:10px;")
        grid = QGridLayout(frame)
        grid.setContentsMargins(14, 14, 14, 14)
        # compact: the tiles' selection margin alone leaves an 8 px gap; the device keeps key_spacing
        grid.setSpacing(0)
        self.deck_grid = grid
        self.tiles: list[KeyTile] = []
        for i in range(KEY_COUNT):
            tile = KeyTile(i)
            tile.clicked.connect(self._tile_clicked)
            tile.dropped.connect(self._tile_dropped)
            tile.clearRequested.connect(self._clear_tile)
            grid.addWidget(tile, i // COLS, i % COLS)
            self.tiles.append(tile)
        frame_row = QHBoxLayout()
        frame_row.addStretch()
        frame_row.addWidget(frame)
        frame_row.addStretch()
        dv.addLayout(frame_row)
        nav = QHBoxLayout()
        self.prev_button = QToolButton(text="◀", clicked=lambda: self._go_page(-1))
        self.page_label = QLabel()
        self.next_button = QToolButton(text="▶", clicked=lambda: self._go_page(1))
        nav.addStretch()
        nav.addWidget(self.prev_button)
        nav.addWidget(self.page_label)
        nav.addWidget(self.next_button)
        nav.addWidget(QPushButton("Seite hinzufügen", clicked=self._add_page))
        nav.addSpacing(20)
        self.preview_button = QPushButton("Vorschau auf dem Deck", checkable=True)
        self.preview_button.setToolTip("Zeigt das bearbeitete Profil live auf dem Stream Deck (ohne Speichern).")
        self.preview_button.toggled.connect(self._toggle_deck_preview)
        self.deck_preview.stopped.connect(lambda: self.preview_button.setChecked(False))
        nav.addWidget(self.preview_button)
        nav.addStretch()
        dv.addLayout(nav)
        hint = QLabel("Bei mehr als 15 Tasten wird die Taste unten rechts zum Blättern.")
        hint.setStyleSheet("color: gray;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dv.addWidget(hint)
        rv.addWidget(deck_box)

        # button editor
        self.button_box = QGroupBox("Taste")
        bf = _form(self.button_box)
        self.label_edit = QLineEdit(placeholderText="Beschriftung")
        self.label_edit.setToolTip("Mit | markierst du, wo ein langes Wort getrennt werden darf, z. B. Seiten|leiste")
        self.label_edit.textEdited.connect(self._button_changed)
        bf.addRow("Beschriftung", self.label_edit)
        self.keys_edit, keys_row = self._shortcut_row(KEYS_PLACEHOLDER)
        bf.addRow("Kürzel", keys_row)
        # per-system variants, for shortcuts that differ by more than Ctrl/Cmd
        self.variant_edits: dict[str, ShortcutEdit] = {}
        here = current_platform()
        for name, label in PLATFORM_LABELS.items():
            edit, row = self._shortcut_row("wie oben", compact=True)
            edit.setToolTip(f"Nur auf {label} statt des Kürzels oben senden, z. B. wenn das Programm "
                            "dort eine ganz andere Taste nutzt")
            self.variant_edits[name] = edit
            bf.addRow(f"  {label}" + (" (hier)" if name == here else ""), row)
        self.keys_error = QLabel()
        self.keys_error.setStyleSheet("color: #e53935;")
        bf.addRow("", self.keys_error)
        bf.setRowVisible(self.keys_error, False)  # only takes room when there is an error
        self._button_form = bf
        colors = QHBoxLayout()
        self.button_color = ColorButton("vom Profil")
        self.button_color.changed.connect(self._button_changed)
        self.button_text_color = ColorButton("vom Profil")
        self.button_text_color.changed.connect(self._button_changed)
        colors.addWidget(QLabel("Hintergrund"))
        colors.addWidget(self.button_color)
        colors.addWidget(QLabel("Schrift"))
        colors.addWidget(self.button_text_color)
        colors.addStretch()
        bf.addRow("Farben", colors)
        self.button_icon = IconPicker(self.config_dir)
        self.button_icon.changed.connect(self._button_changed)
        bf.addRow("Symbol", self.button_icon)
        size_row = QHBoxLayout()
        self.font_size = QSpinBox(minimum=0, maximum=40, specialValueText="automatisch")
        _compact(self.font_size).setMinimumWidth(130)  # room for "automatisch"
        self.font_size.valueChanged.connect(self._button_changed)
        size_row.addWidget(self.font_size)
        size_row.addStretch()
        size_row.addWidget(QPushButton("Taste leeren", clicked=lambda: self._clear_tile(self._tile_of_slot())))
        bf.addRow("Schriftgröße", size_row)
        rv.addWidget(self.button_box)
        rv.addStretch()

        self.statusBar()
        width, height = 1080, 900
        screen = QApplication.primaryScreen()
        if screen is not None:
            free = screen.availableGeometry()
            width, height = min(width, free.width() - 40), min(height, free.height() - 40)
        self.resize(width, height)

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("&Datei")
        for text, shortcut, slot in (
            ("Speichern", QKeySequence.StandardKey.Save, self.save),
            ("Neu laden", QKeySequence.StandardKey.Refresh, self._reload),
            (None, None, None),
            ("Profil importieren …", "Ctrl+I", self._import_profile),
            ("Profil exportieren …", "Ctrl+E", self._export_profile),
            (None, None, None),
            ("Einstellungen …", "Ctrl+,", self._settings),
            (None, None, None),
            ("Beenden", QKeySequence.StandardKey.Quit, self.close),
        ):
            if text is None:
                menu.addSeparator()
                continue
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            menu.addAction(action)

    # --- data helpers -----------------------------------------------------

    def config_dir(self) -> Path:
        return self.path.parent

    @property
    def profiles(self) -> list[dict]:
        return self.data.setdefault("profiles", [])

    def current_profile(self) -> dict | None:
        row = self.profile_list.currentRow()
        return self.profiles[row] if 0 <= row < len(self.profiles) else None

    def current_buttons(self) -> list[dict]:
        profile = self.current_profile()
        return profile.setdefault("buttons", []) if profile is not None else []

    def current_button(self) -> dict | None:
        buttons = self.current_buttons()
        if self.slot is None:
            return None
        while len(buttons) <= self.slot:
            buttons.append({})
        return buttons[self.slot]

    def _settings_obj(self):
        try:
            return parse_settings(self.data)
        except (TypeError, ValueError):
            return parse_settings({})

    def _set_dirty(self, dirty: bool = True) -> None:
        self.dirty = dirty
        self.setWindowTitle(f"{'● ' if dirty else ''}Daily Deck Profile – {self.path}")

    # --- loading / saving ---------------------------------------------------

    def _file_mtime(self) -> int | None:
        try:
            return self.path.stat().st_mtime_ns
        except OSError:
            return None

    def load(self, keep_selection: bool = False) -> None:
        row, page, slot = self.profile_list.currentRow(), self.page, self.slot
        try:
            self.data = read_config_data(self.path) if self.path.exists() else {"profiles": []}
        except ConfigError as e:
            QMessageBox.critical(self, "Konfiguration", str(e))
            self.data = {"profiles": []}
        self._known_mtime = self._file_mtime()
        self._external_change = False
        self._refresh_profile_list(row if keep_selection else 0)
        if keep_selection:
            self.page, self.slot = page, slot
            self._load_button()
            self._render_deck()
        self._set_dirty(False)

    def _check_external_change(self) -> None:
        mtime = self._file_mtime()
        if mtime is None or mtime == self._known_mtime or self._external_change:
            return
        if self.dirty:
            self._external_change = True
            self.statusBar().showMessage(
                "Die Konfiguration wurde außerhalb des Editors geändert (z. B. über die Leiste).", 10000)
        else:
            self.load(keep_selection=True)
            self.statusBar().showMessage("Konfiguration wurde außerhalb geändert – neu geladen.", 5000)

    def select_profile(self, name: str) -> None:
        for i, p in enumerate(self.profiles):
            if p.get("name") == name:
                self.profile_list.setCurrentRow(i)
                return

    def new_profile_for(self, app_name: str, ids) -> None:
        """New profile prefilled for the given application (from the tray menu)."""
        index = self._default_index()
        self.profiles.insert(index, {
            "name": app_name or "Neues Profil",
            "match": list(dict.fromkeys(i.lower() for i in ids)),
            "buttons": [],
        })
        self._refresh_profile_list(index)
        self._set_dirty()
        self.statusBar().showMessage("Neues Profil angelegt – Tasten belegen und speichern.", 8000)

    def _reload(self) -> None:
        if self.dirty and QMessageBox.question(self, "Neu laden", "Ungespeicherte Änderungen verwerfen?") \
                != QMessageBox.StandardButton.Yes:
            return
        self.load()

    def save(self) -> bool:
        if self._external_change or (self._known_mtime is not None and self._file_mtime() != self._known_mtime):
            answer = QMessageBox.question(
                self, "Datei geändert",
                "Die Konfiguration wurde inzwischen außerhalb des Editors geändert "
                "(z. B. Helligkeit über die Leiste).\n\nMit dem Stand des Editors überschreiben?")
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            save_config(self.data, self.path)
            self._known_mtime = self._file_mtime()
            self._external_change = False
        except ConfigError as e:
            QMessageBox.warning(self, "Nicht gespeichert", f"Die Konfiguration enthält Fehler:\n\n{e}")
            return False
        except OSError as e:
            QMessageBox.critical(self, "Nicht gespeichert", str(e))
            return False
        self._set_dirty(False)
        self.statusBar().showMessage("Gespeichert – das Deck übernimmt die Änderungen sofort.", 5000)
        return True

    def closeEvent(self, event) -> None:
        self.deck_preview.stop()
        if self.dirty:
            answer = QMessageBox.question(
                self, "Beenden", "Änderungen speichern?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel or (
                    answer == QMessageBox.StandardButton.Save and not self.save()):
                event.ignore()
                return
        event.accept()

    # --- profile list -------------------------------------------------------

    def _refresh_profile_list(self, select: int | None = None) -> None:
        row = self.profile_list.currentRow() if select is None else select
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        for p in self.profiles:
            item = QListWidgetItem(p.get("name") or "(ohne Namen)")
            if p.get("default"):
                item.setText(item.text() + "  ★")
                item.setToolTip("Standardprofil")
            self.profile_list.addItem(item)
        self.profile_list.blockSignals(False)
        if self.profiles:
            self.profile_list.setCurrentRow(max(0, min(row, len(self.profiles) - 1)))
            self._select_profile(self.profile_list.currentRow())
        else:
            self._select_profile(-1)

    def _select_profile(self, row: int) -> None:
        profile = self.current_profile()
        self._loading = True
        enabled = profile is not None
        for w in (self.name_edit, self.match_edit, self.title_edit, self.default_check,
                  self.profile_color, self.profile_text_color, self.profile_icon, self.capture_button,
                  self.profile_font):
            w.setEnabled(enabled)
        p = profile or {}
        self.name_edit.setText(p.get("name", ""))
        match = p.get("match", [])
        self.match_edit.setText(", ".join([match] if isinstance(match, str) else match))
        self.title_edit.setText(p.get("title", ""))
        self.default_check.setChecked(bool(p.get("default")))
        self.profile_color.set_color(p.get("color"))
        self.profile_text_color.set_color(p.get("text_color"))
        self.profile_icon.set_path(p.get("icon"))
        self.profile_font.set_spec(p.get("font"))
        self._loading = False
        self.page = 0
        self.slot = None
        self._load_button()
        self._render_deck()

    def _profile_changed(self, *_) -> None:
        profile = self.current_profile()
        if self._loading or profile is None:
            return
        profile["name"] = self.name_edit.text().strip()
        profile["match"] = [m.strip() for m in self.match_edit.text().split(",") if m.strip()]
        profile["title"] = self.title_edit.text()
        was_default = bool(profile.get("default"))
        profile["default"] = self.default_check.isChecked()
        if profile["default"] and not was_default:  # only one default profile
            for other in self.profiles:
                if other is not profile:
                    other["default"] = False
        profile["color"] = self.profile_color.color()
        profile["text_color"] = self.profile_text_color.color()
        profile["icon"] = self.profile_icon.path()
        profile["font"] = self.profile_font.spec()
        row = self.profile_list.currentRow()
        for i, p in enumerate(self.profiles):
            text = (p.get("name") or "(ohne Namen)") + ("  ★" if p.get("default") else "")
            self.profile_list.item(i).setText(text)
        self.profile_list.setCurrentRow(row)
        self._set_dirty()
        self._render_timer.start()

    def _add_profile(self) -> None:
        self.profiles.insert(max(0, self._default_index()), {"name": "Neues Profil", "match": [], "buttons": []})
        self._refresh_profile_list(max(0, self._default_index() - 1))
        self._set_dirty()
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _default_index(self) -> int:
        """New profiles go before the default profile (order matters)."""
        for i, p in enumerate(self.profiles):
            if p.get("default"):
                return i
        return len(self.profiles)

    def _duplicate_profile(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        clone = copy.deepcopy(profile)
        clone["name"] = f"{profile.get('name', '')} (Kopie)"
        clone["default"] = False
        row = self.profile_list.currentRow() + 1
        self.profiles.insert(row, clone)
        self._refresh_profile_list(row)
        self._set_dirty()

    def _delete_profile(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        if QMessageBox.question(self, "Profil löschen", f"Profil „{profile.get('name', '')}“ löschen?") \
                != QMessageBox.StandardButton.Yes:
            return
        row = self.profile_list.currentRow()
        del self.profiles[row]
        self._refresh_profile_list(row)
        self._set_dirty()

    def _move_profile(self, delta: int) -> None:
        row = self.profile_list.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < len(self.profiles):
            return
        self.profiles[row], self.profiles[target] = self.profiles[target], self.profiles[row]
        self._refresh_profile_list(target)
        self._set_dirty()

    def _import_profile(self) -> None:
        file, _ = QFileDialog.getOpenFileName(self, "Profil importieren", str(Path.home()),
                                              f"Stream-Deck-Profil (*{PROFILE_SUFFIX})")
        if not file:
            return
        try:
            profile = import_profile(Path(file), self.config_dir())
        except (ConfigError, OSError) as e:
            QMessageBox.warning(self, "Import fehlgeschlagen", str(e))
            return
        names = {p.get("name") for p in self.profiles}
        if profile.get("name") in names:
            answer = QMessageBox.question(
                self, "Profil existiert",
                f"Es gibt bereits ein Profil „{profile['name']}“. Ersetzen?\n(Nein = als Kopie hinzufügen)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Yes:
                index = next(i for i, p in enumerate(self.profiles) if p.get("name") == profile["name"])
                profile["default"] = self.profiles[index].get("default", False)
                self.profiles[index] = profile
                self._refresh_profile_list(index)
                self._set_dirty()
                return
            profile["name"] += " (importiert)"
        if profile.get("default") and any(p.get("default") for p in self.profiles):
            profile["default"] = False
        index = self._default_index()
        self.profiles.insert(index, profile)
        self._refresh_profile_list(index)
        self._set_dirty()
        self.statusBar().showMessage(f"Profil „{profile.get('name')}“ importiert – zum Übernehmen speichern.", 6000)

    def _export_profile(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        suggestion = Path.home() / f"{profile.get('name') or 'profil'}{PROFILE_SUFFIX}"
        file, _ = QFileDialog.getSaveFileName(self, "Profil exportieren", str(suggestion),
                                              f"Stream-Deck-Profil (*{PROFILE_SUFFIX})")
        if not file:
            return
        target = Path(file)
        if target.suffix != PROFILE_SUFFIX:
            target = target.with_name(target.name + PROFILE_SUFFIX)
        try:
            export_profile(profile, self.config_dir(), target)
        except OSError as e:
            QMessageBox.warning(self, "Export fehlgeschlagen", str(e))
            return
        self.statusBar().showMessage(f"Exportiert nach {target}", 6000)

    def _settings(self) -> None:
        settings = self.data.setdefault("settings", {})
        was_dirty = self.dirty
        dialog = SettingsDialog(settings, on_change=self._render_deck, parent=self)
        if dialog.exec():
            dialog.apply(settings)
            self._set_dirty()
        else:
            self._set_dirty(was_dirty)
        self._render_deck()

    # --- active window capture ----------------------------------------------

    def _start_capture(self) -> None:
        self._countdown = 3
        self.capture_button.setEnabled(False)
        self.capture_button.setText("Fenster wechseln … 3")
        self._capture_timer.start()

    def _capture_tick(self) -> None:
        self._countdown -= 1
        if self._countdown > 0:
            self.capture_button.setText(f"Fenster wechseln … {self._countdown}")
            return
        self._capture_timer.stop()
        self.capture_button.setText("Aktives Fenster übernehmen")
        self.capture_button.setEnabled(True)
        try:
            if self._focus is None:
                from .focus import create_focus_provider

                self._focus = create_focus_provider(self._settings_obj().focus_backend)
            info = self._focus.get()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Fenster erkennen", f"Das aktive Fenster ließ sich nicht ermitteln:\n{e}")
            return
        self.raise_()
        self.activateWindow()
        if info.empty:
            self.statusBar().showMessage("Kein Fenster erkannt.", 5000)
            return
        if info.pid == os.getpid():
            self.statusBar().showMessage("Das war der Editor selbst – bitte innerhalb von 3 s wechseln.", 6000)
            return
        current = [m.strip() for m in self.match_edit.text().split(",") if m.strip()]
        lower = {m.lower() for m in current}
        current += [i.lower() for i in info.ids if i.lower() not in lower]
        self.match_edit.setText(", ".join(dict.fromkeys(current)))
        if self.name_edit.text().strip() in ("", "Neues Profil"):
            self.name_edit.setText(info.display_name)
        self._profile_changed()
        self.statusBar().showMessage(f"Erkannt: {info.display_name}  ({', '.join(info.ids)})", 8000)

    # --- deck preview ---------------------------------------------------------

    def _page_info(self) -> tuple[int, int, int]:
        n = len(self.current_buttons())
        pages = page_count(n, KEY_COUNT)
        self.page = max(0, min(self.page, pages - 1))
        return per_page(n, KEY_COUNT), pages, self.page

    def _slot_of_tile(self, tile: int) -> int | None:
        per, pages, page = self._page_info()
        if pages > 1 and tile == KEY_COUNT - 1:
            return None  # navigation key
        return page * per + tile

    def _tile_of_slot(self) -> int:
        per, _, page = self._page_info()
        return (self.slot or 0) - page * per

    def _render_deck(self) -> None:
        profile_data = self.current_profile()
        settings = self._settings_obj()
        raw = profile_data.get("buttons", []) if profile_data else []
        buttons, errors = [], set()
        for i, b in enumerate(raw):
            try:
                buttons.append(load_button(b, self.config_dir()))
            except ShortcutError:
                errors.add(i)
                buttons.append(Button(label=b.get("label", ""), color="#b00020"))
        profile = None
        if profile_data is not None:
            match = profile_data.get("match", [])
            profile = Profile(
                name=profile_data.get("name", ""),
                match=tuple(m.lower() for m in ([match] if isinstance(match, str) else match)),
                color=profile_data.get("color"),
                text_color=profile_data.get("text_color"),
                icon=self.config_dir() / profile_data["icon"] if profile_data.get("icon") else None,
                buttons=tuple(buttons),
            )
        per, pages, page = self._page_info()
        slots = page_slots(profile.buttons, KEY_COUNT, page) if profile else [None] * KEY_COUNT
        ids = tuple(m for m in (profile.match if profile else ()) if not any(c in m for c in "*?["))
        tiles = backdrop_tiles(icon_for(profile, ids, settings), COLS, ROWS, KEY_SIZE, settings.key_spacing)
        for i, tile in enumerate(self.tiles):
            image = render_slot(slots[i], profile, settings, KEY_SIZE, tiles[i] if tiles else None, page)
            tile.setPixmap(to_pixmap(image))
            tile.movable = not isinstance(slots[i], NavSlot)
            flat = page * per + i
            tile.setToolTip("Fehler im Kürzel" if flat in errors else "")
            tile.set_selected(self.slot is not None and flat == self.slot and not isinstance(slots[i], NavSlot))
        self.page_label.setText(f"Seite {page + 1} / {pages}")
        self._push_deck_preview()
        self.prev_button.setEnabled(page > 0)
        self.next_button.setEnabled(page < pages - 1)

    # --- preview on the device ---------------------------------------------------

    def _preview_args(self):
        profile = clean_profile(copy.deepcopy(self.current_profile() or {"name": ""}))
        for button in profile.get("buttons", []):  # invalid shortcuts must not block the preview
            try:
                button_chords(button)
            except ShortcutError:
                for field in KEY_FIELDS:
                    button.pop(field, None)
        if profile.get("title"):
            del profile["title"]
        ids = [m for m in profile.get("match", []) if not any(c in m for c in "*?[")]
        return profile, copy.deepcopy(self.data.get("settings", {})), self.config_dir(), ids, self.page

    def _toggle_deck_preview(self, on: bool) -> None:
        if on and not self.deck_preview.active:
            self.deck_preview.start(*self._preview_args())
        elif not on and self.deck_preview.active:
            self.deck_preview.stop()
            self.statusBar().showMessage("Vorschau beendet.", 4000)

    def _push_deck_preview(self) -> None:
        if self.deck_preview.active:
            self.deck_preview.update(*self._preview_args())

    def _go_page(self, delta: int) -> None:
        self.page += delta
        self.slot = None
        self._load_button()
        self._render_deck()

    def _add_page(self) -> None:
        if self.current_profile() is None:
            return
        buttons = self.current_buttons()
        _, pages, _ = self._page_info()
        target = (KEY_COUNT - 1) * (pages if len(buttons) > KEY_COUNT else 1) + 1
        while len(buttons) < target:
            buttons.append({})
        self.page = page_count(len(buttons), KEY_COUNT) - 1
        self.slot = None
        self._load_button()
        self._render_deck()

    def _tile_clicked(self, tile: int) -> None:
        if self.current_profile() is None:
            return
        slot = self._slot_of_tile(tile)
        if slot is None:
            self._go_page(1 if self.page < self._page_info()[1] - 1 else -self.page)
            return
        self.slot = slot
        self.current_button()  # extends the list up to this slot
        self._load_button()
        self._render_deck()
        self.label_edit.setFocus()

    def _tile_dropped(self, src_tile: int, dst_tile: int) -> None:
        src, dst = self._slot_of_tile(src_tile), self._slot_of_tile(dst_tile)
        if src is None or dst is None:
            return
        buttons = self.current_buttons()
        while len(buttons) <= max(src, dst):
            buttons.append({})
        buttons[src], buttons[dst] = buttons[dst], buttons[src]
        self.slot = dst
        self._set_dirty()
        self._load_button()
        self._render_deck()

    def _clear_tile(self, tile: int) -> None:
        slot = self._slot_of_tile(tile)
        buttons = self.current_buttons()
        if slot is None or slot >= len(buttons):
            return
        buttons[slot] = {}
        self._set_dirty()
        self._load_button()
        self._render_deck()

    # --- button editor ----------------------------------------------------------

    def _load_button(self) -> None:
        button = self.current_button() if self.slot is not None else None
        self.button_box.setEnabled(button is not None)
        self.button_box.setTitle(f"Taste {self._tile_of_slot() + 1}" if button is not None else
                                 "Taste  –  oben eine Taste anklicken")
        b = button or {}
        self._loading = True
        self.keys_edit.stop_recording()
        self.label_edit.setText(b.get("label", "").replace(SOFT_HYPHEN, "|"))
        self.keys_edit.setText(b.get("keys", ""))
        for name, edit in self.variant_edits.items():
            edit.stop_recording()
            edit.setText(b.get(f"keys_{name}", ""))
        self.button_color.set_color(b.get("color"))
        self.button_text_color.set_color(b.get("text_color"))
        self.button_icon.set_path(b.get("icon"))
        self.font_size.setValue(int(b.get("font_size") or 0))
        self._loading = False
        self._validate_keys()

    def _button_changed(self, *_) -> None:
        if self._loading:
            return
        button = self.current_button()
        if button is None:
            return
        button["label"] = self.label_edit.text().replace("|", SOFT_HYPHEN)
        button.update(self._key_fields())
        button["color"] = self.button_color.color()
        button["text_color"] = self.button_text_color.color()
        button["icon"] = self.button_icon.path()
        button["font_size"] = self.font_size.value() or None
        for key in [k for k, v in button.items() if v in (None, "")]:
            del button[key]
        self._validate_keys()
        self._set_dirty()
        self._render_timer.start()

    def _validate_keys(self) -> None:
        edits = [self.keys_edit, *self.variant_edits.values()]
        if any(e.recording for e in edits):
            self._show_keys_error("")
            return
        try:
            button_chords(self._key_fields())
            self._show_keys_error("")
        except ShortcutError as e:
            self._show_keys_error(str(e))

    def _show_keys_error(self, text: str) -> None:
        self.keys_error.setText(text)
        self._button_form.setRowVisible(self.keys_error, bool(text))

    def _key_fields(self) -> dict:
        fields = {"keys": self.keys_edit.text().strip()}
        fields.update({f"keys_{n}": e.text().strip() for n, e in self.variant_edits.items()})
        return fields

    def _shortcut_row(self, placeholder: str, compact: bool = False):
        edit = ShortcutEdit()
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(self._button_changed)
        idle = "⏺" if compact else "⏺ Aufnehmen"
        button = QPushButton(idle, clicked=lambda: edit.stop_recording() if edit.recording else edit.start_recording())
        button.setToolTip("Tastenkombination aufnehmen")
        edit.recordingChanged.connect(lambda on: button.setText(("■" if compact else "■ Fertig") if on else idle))
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(button)
        return edit, row


def main(config_path: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Daily Deck Profile")
    from .tray import app_icon, install_translations

    install_translations(app)
    app.setDesktopFileName("io.github.thnow.dailydeck.Editor")
    app.setWindowIcon(app_icon())
    path = (config_path or default_config_path()).expanduser().resolve()
    window = MainWindow(path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
