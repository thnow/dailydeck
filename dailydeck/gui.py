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
from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QIcon, QImage, QKeySequence, QPixmap
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

from . import i18n, symbols, sync
from .config import (
    KEY_FIELDS,
    PLATFORM_LABELS,
    Button,
    ConfigError,
    Profile,
    button_chords,
    current_platform,
    default_config_path,
    is_shared,
    load_button,
    local_path,
    parse_settings,
    read_config_data,
    resolve_icon,
    setup_language,
    sync_dir,
)
from .fonts import font_spec, list_fonts, split_spec
from .i18n import N_, _
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
KEYS_PLACEHOLDER = N_("e.g. primary+shift+t (primary = Ctrl, ⌘ on the Mac)")


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


def _form(parent: QWidget | None) -> QFormLayout:
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
        self.setPlaceholderText(_("Press a key combination …"))
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

    def __init__(self, inherit_text: str | None = None, parent=None):
        super().__init__(parent)
        self._color: str | None = None
        self._inherit = inherit_text or _("Default")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._button = QPushButton(clicked=self._pick)
        self._button.setMinimumWidth(110)
        self._reset = QToolButton(text="×", clicked=lambda: self._set(None, emit=True))
        self._reset.setToolTip(_("Reset"))
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
        color = QColorDialog.getColor(initial, self, _("Choose colour"))
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


class SymbolDialog(QDialog):
    """Grid of the built-in symbols (``symbol:name``), searchable and by category."""

    def __init__(self, current: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Choose symbol"))
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit(placeholderText=_("Search (English names, e.g. play, folder, arrow)"),
                                clearButtonEnabled=True)
        self.category = QComboBox()
        self.category.addItem(_("All categories"), None)
        for name in symbols.CATEGORIES:
            self.category.addItem(_(name), name)
        top.addWidget(self.search, 1)
        top.addWidget(self.category)
        layout.addLayout(top)

        self.grid = QListWidget(viewMode=QListWidget.ViewMode.IconMode, movement=QListWidget.Movement.Static,
                                resizeMode=QListWidget.ResizeMode.Adjust, uniformItemSizes=True)
        self.grid.setIconSize(QSize(40, 40))
        self.grid.setGridSize(QSize(64, 64))
        # the symbols are white; show them on a key-like dark background
        self.grid.setStyleSheet("QListWidget { background: #1e1e1e; } "
                                "QListWidget::item:selected { background: #3daee9; border-radius: 6px; }")
        for category, names in symbols.CATEGORIES.items():
            for name in names:
                path = symbols.symbol_path(name)
                if not path.exists():
                    continue
                item = QListWidgetItem(QIcon(str(path)), "")
                item.setToolTip(name)
                item.setData(Qt.ItemDataRole.UserRole, name)
                item.setData(Qt.ItemDataRole.UserRole + 1, category)
                self.grid.addItem(item)
                if current and symbols.symbol_path(current) == path:
                    self.grid.setCurrentItem(item)
        layout.addWidget(self.grid, 1)
        self.name_label = QLabel()
        layout.addWidget(self.name_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)

        self.search.textChanged.connect(self._filter)
        self.category.currentIndexChanged.connect(self._filter)
        self.grid.currentItemChanged.connect(self._selected)
        self.grid.itemDoubleClicked.connect(lambda _item: self.accept())
        self._selected(self.grid.currentItem())
        self.search.setFocus()

    def _filter(self) -> None:
        words = self.search.text().lower().split()
        category = self.category.currentData()
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            in_category = category is None or item.data(Qt.ItemDataRole.UserRole + 1) == category
            item.setHidden(not (in_category and all(w in name for w in words)))

    def _selected(self, item) -> None:
        self._ok.setEnabled(item is not None)
        self.name_label.setText(item.data(Qt.ItemDataRole.UserRole) if item else "")

    def value(self) -> str | None:
        item = self.grid.currentItem()
        return symbols.PREFIX + item.data(Qt.ItemDataRole.UserRole) if item else None


class IconPicker(QWidget):
    """Image file chooser. Chosen files are copied into the config directory
    so the config stays self-contained (and profiles can be exported).
    A built-in symbol is stored as ``symbol:name``."""

    changed = Signal(object)

    def __init__(self, config_dir_getter, placeholder: str | None = None, parent=None):
        super().__init__(parent)
        self._config_dir = config_dir_getter
        self._path: str | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLineEdit(readOnly=True, placeholderText=placeholder or _("no image"))
        layout.addWidget(self._label, 1)
        layout.addWidget(QPushButton(_("Symbol …"), clicked=self._pick_symbol))
        layout.addWidget(QPushButton(_("File …"), clicked=self._pick))
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

    def _pick_symbol(self) -> None:
        dialog = SymbolDialog(self._path if symbols.is_symbol(self._path) else None, self)
        if dialog.exec() and (value := dialog.value()):
            self._set(value, emit=True)

    def _pick(self) -> None:
        file, _filter = QFileDialog.getOpenFileName(
            self, _("Choose image"), str(Path.home()),
            _("Images") + " (*.png *.svg *.jpg *.jpeg *.gif *.webp *.ico *.icns)")
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
        menu.addAction(_("Clear key"), lambda: self.clearRequested.emit(self.index))
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
        self.lineEdit().setPlaceholderText(_("Search fonts …"))
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
            self.addItem(_("{family} – {style} (not installed)").format(family=family, style=style) if style
                         else _("{font} (not found)").format(font=spec), spec)
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
        self.status.emit(_("Preview on the deck – keys do nothing meanwhile."))

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
            self.status.emit(_("Preview failed: {error}").format(error=e))

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
                self.status.emit(_("No Stream Deck found."))
                self.stop()
                return
            request = request_from_payload(self._payload)
            config = Config(Path(self._payload["config_dir"]), request.settings, [request.profile])
            self._direct = DeckController(decks[0], NullKeySender(), config)
            self._direct.preview(request.profile, request.settings, request.ids, request.page)
            self.status.emit(_("Daily Deck is not running – showing the preview on the deck directly."))
        except Exception as e:  # noqa: BLE001
            self._direct = None
            self.status.emit(_("Stream Deck not available: {error}").format(error=e))
            self.stop()


# ------------------------------------------------------------------ settings dialog

class SettingsDialog(QDialog):
    """Changes are applied live through ``on_change``; Cancel restores them."""

    def __init__(self, settings: dict, on_change=None, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._original = copy.deepcopy(settings)
        self._on_change = on_change
        self.setWindowTitle(_("Settings"))
        defaults = parse_settings({})
        get = lambda key: settings.get(key, getattr(defaults, key))  # noqa: E731

        layout = QVBoxLayout(self)

        general = _form(None)
        self.language = QComboBox()
        system = i18n.native_name(i18n.resolve())
        self.language.addItem(_("System language ({language})").format(language=system), "auto")
        for code in i18n.available_languages():
            self.language.addItem(i18n.native_name(code), code)
        self.language.setCurrentIndex(max(0, self.language.findData(str(get("language")))))
        self.language.setToolTip(_("Takes effect after restarting Daily Deck"))
        general.addRow(_("Language"), self.language)
        layout.addLayout(general)

        keys = QGroupBox(_("Keys"))
        form = _form(keys)
        self.font = FontCombo(_("Default ({font})").format(font=default_font_name()))
        self.font.set_spec(settings.get("font"))
        self.font.setMinimumWidth(320)
        form.addRow(_("Font"), self.font)
        self.brightness = self._slider(int(get("brightness")))
        form.addRow(_("Deck brightness"), self.brightness)
        self.show_keys = QCheckBox(_("Show the shortcut below the label"), checked=bool(get("show_keys")))
        form.addRow("", self.show_keys)
        layout.addWidget(keys)

        icon = QGroupBox(_("App icon"))
        form = _form(icon)
        self.app_icon = QCheckBox(_("Show the icon of the app across all keys"), checked=bool(get("app_icon")))
        form.addRow("", self.app_icon)
        self.icon_brightness = self._slider(round(get("app_icon_brightness") * 100))
        form.addRow(_("Icon brightness"), self.icon_brightness)
        self.opacity = self._slider(round(get("button_opacity") * 100))
        self.opacity.setToolTip(_("How much the key colour covers the icon"))
        form.addRow(_("Key opacity"), self.opacity)
        self.flash = QDoubleSpinBox(minimum=0, maximum=5, singleStep=0.1, suffix=" s",
                                    value=float(get("app_icon_flash")))
        self.flash.setToolTip(_("How long the icon lights up at full brightness after switching apps; 0 = off"))
        form.addRow(_("Flash on switch"), _compact(self.flash))
        self.spacing = QSpinBox(minimum=0, maximum=100, suffix=" px", value=int(get("key_spacing")))
        self.spacing.setToolTip(_("Gap between the keys of the device, so the icon looks continuous"))
        form.addRow(_("Key spacing on the device"), _compact(self.spacing))
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
        if self.language.currentData() == "auto":
            settings.pop("language", None)
        else:
            settings["language"] = self.language.currentData()
        if self.font.spec():
            settings["font"] = self.font.spec()
        else:
            settings.pop("font", None)


# ------------------------------------------------------------------ main window

def bring_to_front(window: QWidget) -> None:
    """Show ``window`` in front, restoring it if minimized.

    Windows keeps a background process (the tray) from taking the focus; Qt's
    ``activateWindow`` then only flashes the taskbar button. Attaching to the
    input of the current foreground window lifts that restriction.
    """
    if window.isMinimized():
        window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
    window.show()
    window.raise_()
    window.activateWindow()
    if sys.platform == "win32":
        import ctypes

        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.BringWindowToTop.argtypes = [ctypes.c_void_p]
        hwnd = int(window.winId())
        fg = user32.GetForegroundWindow()
        if fg == hwnd:
            return
        own = kernel32.GetCurrentThreadId()
        other = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = bool(other and other != own and user32.AttachThreadInput(other, own, True))
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(other, own, False)


class SyncDialog(QDialog):
    """Where the configuration lives: locally or in a synchronised folder."""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window = window
        self.setWindowTitle(_("Synchronisation"))
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        intro = QLabel(_(
            "Keep the profiles in a folder that Nextcloud, OneDrive, Syncthing or a Git repository "
            "synchronises, and choose the same folder on your other computers.\n\n"
            "Brightness, language, font and keyboard settings stay separate on each computer."))
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.status = QLabel(textInteractionFlags=Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status.setWordWrap(True)
        self.status.setFrameShape(QFrame.Shape.StyledPanel)
        self.status.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.choose = QPushButton(_("Choose folder …"), clicked=self._choose)
        self.local = QPushButton(_("Keep locally again"), clicked=self._disconnect)
        row.addWidget(self.choose)
        row.addWidget(self.local)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, rejected=self.reject)
        layout.addWidget(buttons)
        self._update()

    def _update(self) -> None:
        folder = sync_dir()
        path = self.window.path
        if folder is None:
            text = _("The configuration is stored on this computer only:\n{path}").format(path=path)
        elif is_shared(path):
            text = _("Synchronised through the folder:\n{folder}").format(folder=folder)
        else:
            text = _("The sync folder {folder} has no configuration (yet) – maybe it is not synchronised "
                     "yet. Until then the local configuration is used:\n{path}").format(folder=folder, path=path)
        self.status.setText(text)
        self.local.setEnabled(folder is not None)

    def _ready(self) -> bool:
        if not self.window.dirty:
            return True
        answer = QMessageBox.question(self, _("Synchronisation"), _("Save the changes first?"),
                                      QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Save and self.window.save()

    def _choose(self) -> None:
        if not self._ready():
            return
        start = str(sync_dir() or Path.home())
        folder = QFileDialog.getExistingDirectory(self, _("Folder for the configuration"), start)
        if not folder:
            return
        folder = Path(folder)
        adopt = False
        if existing := sync.existing_config(folder):
            box = QMessageBox(QMessageBox.Icon.Question, _("Synchronisation"), _(
                "There already is a configuration in this folder ({profiles} profiles, changed {time}), "
                "e.g. from another computer.").format(
                    profiles=existing.profiles if existing.profiles >= 0 else "?",
                    time=sync.format_time(existing.modified)), parent=self)
            use = box.addButton(_("Use it"), QMessageBox.ButtonRole.AcceptRole)
            replace = box.addButton(_("Replace it with mine"), QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(use)
            box.exec()
            if box.clickedButton() not in (use, replace):
                return
            adopt = box.clickedButton() is use
        try:
            self.window.switch_config(sync.connect(folder, self.window.path, adopt))
        except (ConfigError, OSError) as e:
            QMessageBox.critical(self, _("Synchronisation"), str(e))
        self._update()

    def _disconnect(self) -> None:
        if not self._ready():
            return
        if QMessageBox.question(self, _("Synchronisation"), _(
                "Copy the configuration to this computer and stop using the folder? "
                "The folder and the other computers are not changed.")) != QMessageBox.StandardButton.Yes:
            return
        try:
            if is_shared(self.window.path):
                self.window.switch_config(sync.disconnect(self.window.path))
            else:  # the folder was never reached: just forget it
                from .config import read_local, write_local

                local = read_local()
                local.pop("sync_dir", None)
                local.pop("settings", None)
                write_local(local)
        except (ConfigError, OSError) as e:
            QMessageBox.critical(self, _("Synchronisation"), str(e))
        self._update()


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
        lv.addWidget(QLabel(_("<b>Profiles</b> (first match wins)")))
        self.profile_list = QListWidget()
        self.profile_list.currentRowChanged.connect(self._select_profile)
        lv.addWidget(self.profile_list, 1)
        row = QHBoxLayout()
        for text, tip, slot in (
            ("+", _("New profile"), self._add_profile),
            ("⧉", _("Duplicate profile"), self._duplicate_profile),
            ("−", _("Delete profile"), self._delete_profile),
            ("↑", _("Move up"), lambda: self._move_profile(-1)),
            ("↓", _("Move down"), lambda: self._move_profile(1)),
        ):
            b = QToolButton(text=text, clicked=slot)
            b.setToolTip(tip)
            row.addWidget(b)
        row.addStretch()
        lv.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QPushButton(_("Import …"), clicked=self._import_profile))
        row.addWidget(QPushButton(_("Export …"), clicked=self._export_profile))
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
        box = QGroupBox(_("Profile"))
        form = _form(box)
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._profile_changed)
        form.addRow(_("Name"), self.name_edit)
        match_row = QHBoxLayout()
        self.match_edit = QLineEdit(placeholderText=_("e.g. firefox, org.mozilla.firefox, firefox.exe"))
        self.match_edit.setToolTip(_("Identifiers of the application, separated by commas. * and ? as wildcards."))
        self.match_edit.textEdited.connect(self._profile_changed)
        self.capture_button = QPushButton(_("Use active window"), clicked=self._start_capture)
        self.capture_button.setToolTip(_("Detects the active window after 3 seconds – switch to it before."))
        match_row.addWidget(self.match_edit, 1)
        match_row.addWidget(self.capture_button)
        form.addRow(_("Detection"), match_row)
        self.title_edit = QLineEdit(placeholderText=_("optional, regular expression, e.g. YouTube"))
        self.title_edit.textEdited.connect(self._profile_changed)
        form.addRow(_("Window title"), self.title_edit)
        self.default_check = QCheckBox(_("Default profile when no other matches"))
        self.default_check.toggled.connect(self._profile_changed)
        form.addRow("", self.default_check)
        colors = QHBoxLayout()
        self.profile_color = ColorButton(_("Default"))
        self.profile_color.changed.connect(self._profile_changed)
        self.profile_text_color = ColorButton(_("Default"))
        self.profile_text_color.changed.connect(self._profile_changed)
        colors.addWidget(QLabel(_("Background")))
        colors.addWidget(self.profile_color)
        colors.addWidget(QLabel(_("Text")))
        colors.addWidget(self.profile_text_color)
        colors.addStretch()
        form.addRow(_("Colours"), colors)
        self.profile_icon = IconPicker(self.config_dir, _("automatic (icon of the application)"))
        self.profile_icon.changed.connect(self._profile_changed)
        form.addRow(_("App icon"), self.profile_icon)
        self.profile_font = FontCombo(_("from the settings"))
        self.profile_font.changed.connect(self._profile_changed)
        form.addRow(_("Font"), self.profile_font)
        rv.addWidget(box)

        # deck preview
        deck_box = QGroupBox(_("Deck  –  click a key to edit it, drag to move it"))
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
        nav.addWidget(QPushButton(_("Add page"), clicked=self._add_page))
        nav.addSpacing(20)
        self.preview_button = QPushButton(_("Preview on the deck"), checkable=True)
        self.preview_button.setToolTip(_("Shows the edited profile live on the Stream Deck (without saving)."))
        self.preview_button.toggled.connect(self._toggle_deck_preview)
        self.deck_preview.stopped.connect(lambda: self.preview_button.setChecked(False))
        nav.addWidget(self.preview_button)
        nav.addStretch()
        dv.addLayout(nav)
        hint = QLabel(_("With more than 15 keys, the bottom right key turns the pages."))
        hint.setStyleSheet("color: gray;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dv.addWidget(hint)
        rv.addWidget(deck_box)

        # button editor
        self.button_box = QGroupBox(_("Key"))
        bf = _form(self.button_box)
        self.label_edit = QLineEdit(placeholderText=_("Label"))
        self.label_edit.setToolTip(_("Mark with | where a long word may be hyphenated, e.g. Side|bar"))
        self.label_edit.textEdited.connect(self._button_changed)
        bf.addRow(_("Label"), self.label_edit)
        self.keys_edit, keys_row = self._shortcut_row(_(KEYS_PLACEHOLDER))
        bf.addRow(_("Shortcut"), keys_row)
        # per-system variants, for shortcuts that differ by more than Ctrl/Cmd
        self.variant_edits: dict[str, ShortcutEdit] = {}
        here = current_platform()
        for name, label in PLATFORM_LABELS.items():
            edit, row = self._shortcut_row(_("same as above"), compact=True)
            edit.setToolTip(_("Sent on {system} instead of the shortcut above, e.g. when the app uses "
                              "a different key there").format(system=label))
            self.variant_edits[name] = edit
            bf.addRow("  " + (_("{system} (this one)").format(system=label) if name == here else label), row)
        self.keys_error = QLabel()
        self.keys_error.setStyleSheet("color: #e53935;")
        bf.addRow("", self.keys_error)
        bf.setRowVisible(self.keys_error, False)  # only takes room when there is an error
        self._button_form = bf
        colors = QHBoxLayout()
        self.button_color = ColorButton(_("from the profile"))
        self.button_color.changed.connect(self._button_changed)
        self.button_text_color = ColorButton(_("from the profile"))
        self.button_text_color.changed.connect(self._button_changed)
        colors.addWidget(QLabel(_("Background")))
        colors.addWidget(self.button_color)
        colors.addWidget(QLabel(_("Text")))
        colors.addWidget(self.button_text_color)
        colors.addStretch()
        bf.addRow(_("Colours"), colors)
        self.button_icon = IconPicker(self.config_dir)
        self.button_icon.changed.connect(self._button_changed)
        bf.addRow(_("Image"), self.button_icon)
        size_row = QHBoxLayout()
        self.font_size = QSpinBox(minimum=0, maximum=40, specialValueText=_("automatic"))
        _compact(self.font_size).setMinimumWidth(130)  # room for "automatic"
        self.font_size.valueChanged.connect(self._button_changed)
        size_row.addWidget(self.font_size)
        size_row.addStretch()
        size_row.addWidget(QPushButton(_("Clear key"), clicked=lambda: self._clear_tile(self._tile_of_slot())))
        bf.addRow(_("Font size"), size_row)
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
        menu = self.menuBar().addMenu(_("&File"))
        for text, shortcut, slot in (
            (_("Save"), QKeySequence.StandardKey.Save, self.save),
            (_("Reload"), QKeySequence.StandardKey.Refresh, self._reload),
            (None, None, None),
            (_("Import profile …"), "Ctrl+I", self._import_profile),
            (_("Export profile …"), "Ctrl+E", self._export_profile),
            (None, None, None),
            (_("Settings …"), "Ctrl+,", self._settings),
            (_("Synchronisation …"), None, lambda: SyncDialog(self).exec()),
            (None, None, None),
            (_("Quit"), QKeySequence.StandardKey.Quit, self.close),
        ):
            if text is None:
                menu.addSeparator()
                continue
            action = QAction(text, self)
            if shortcut:
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

    def _file_mtime(self) -> tuple | None:
        """Modification time of the config (and of local.toml, which holds part of a shared config)."""
        try:
            mtime = self.path.stat().st_mtime_ns
        except OSError:
            return None
        try:
            local = local_path().stat().st_mtime_ns if is_shared(self.path) else None
        except OSError:
            local = None
        return mtime, local

    def switch_config(self, path: Path) -> None:
        """Continue with the configuration at ``path`` (moved to or from a sync folder)."""
        self.path = path
        self.load(keep_selection=True)
        self.statusBar().showMessage(_("The configuration is now read from {path}.").format(path=path), 8000)

    def load(self, keep_selection: bool = False) -> None:
        row, page, slot = self.profile_list.currentRow(), self.page, self.slot
        try:
            self.data = read_config_data(self.path) if self.path.exists() else {"profiles": []}
        except ConfigError as e:
            QMessageBox.critical(self, _("Configuration"), str(e))
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
                _("The configuration was changed outside the editor (e.g. from the tray menu)."), 10000)
        else:
            self.load(keep_selection=True)
            self.statusBar().showMessage(_("The configuration was changed outside – reloaded."), 5000)

    def select_profile(self, name: str) -> None:
        for i, p in enumerate(self.profiles):
            if p.get("name") == name:
                self.profile_list.setCurrentRow(i)
                return

    def new_profile_for(self, app_name: str, ids) -> None:
        """New profile prefilled for the given application (from the tray menu)."""
        index = self._default_index()
        self.profiles.insert(index, {
            "name": app_name or _("New profile"),
            "match": list(dict.fromkeys(i.lower() for i in ids)),
            "buttons": [],
        })
        self._refresh_profile_list(index)
        self._set_dirty()
        self.statusBar().showMessage(_("New profile created – assign keys and save."), 8000)

    def _reload(self) -> None:
        if self.dirty and QMessageBox.question(self, _("Reload"), _("Discard unsaved changes?")) \
                != QMessageBox.StandardButton.Yes:
            return
        self.load()

    def save(self) -> bool:
        if self._external_change or (self._known_mtime is not None and self._file_mtime() != self._known_mtime):
            answer = QMessageBox.question(
                self, _("File changed"),
                _("The configuration was changed outside the editor in the meantime "
                  "(e.g. the brightness from the tray menu).\n\nOverwrite it with the editor's version?"))
            if answer != QMessageBox.StandardButton.Yes:
                return False
        try:
            save_config(self.data, self.path)
            self._known_mtime = self._file_mtime()
            self._external_change = False
        except ConfigError as e:
            QMessageBox.warning(self, _("Not saved"), _("The configuration has errors:\n\n{error}").format(error=e))
            return False
        except OSError as e:
            QMessageBox.critical(self, _("Not saved"), str(e))
            return False
        self._set_dirty(False)
        self.statusBar().showMessage(_("Saved – the deck picks up the changes right away."), 5000)
        return True

    def closeEvent(self, event) -> None:
        self.deck_preview.stop()
        if self.dirty:
            answer = QMessageBox.question(
                self, _("Quit"), _("Save changes?"),
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
            item = QListWidgetItem(p.get("name") or _("(no name)"))
            if p.get("default"):
                item.setText(item.text() + "  ★")
                item.setToolTip(_("Default profile"))
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
        self.profiles.insert(max(0, self._default_index()), {"name": _("New profile"), "match": [], "buttons": []})
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
        clone["name"] = _("{name} (copy)").format(name=profile.get("name", ""))
        clone["default"] = False
        row = self.profile_list.currentRow() + 1
        self.profiles.insert(row, clone)
        self._refresh_profile_list(row)
        self._set_dirty()

    def _delete_profile(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        if QMessageBox.question(self, _("Delete profile"),
                                _("Delete profile “{name}”?").format(name=profile.get("name", ""))) \
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
        file, _filter = QFileDialog.getOpenFileName(self, _("Import profile"), str(Path.home()),
                                                    _("Daily Deck profile") + f" (*{PROFILE_SUFFIX})")
        if not file:
            return
        try:
            profile = import_profile(Path(file), self.config_dir())
        except (ConfigError, OSError) as e:
            QMessageBox.warning(self, _("Import failed"), str(e))
            return
        names = {p.get("name") for p in self.profiles}
        if profile.get("name") in names:
            answer = QMessageBox.question(
                self, _("Profile exists"),
                _("There is already a profile “{name}”. Replace it?\n(No = add it as a copy)").format(
                    name=profile["name"]),
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
            profile["name"] = _("{name} (imported)").format(name=profile["name"])
        if profile.get("default") and any(p.get("default") for p in self.profiles):
            profile["default"] = False
        index = self._default_index()
        self.profiles.insert(index, profile)
        self._refresh_profile_list(index)
        self._set_dirty()
        self.statusBar().showMessage(
            _("Profile “{name}” imported – save to apply it.").format(name=profile.get("name")), 6000)

    def _export_profile(self) -> None:
        profile = self.current_profile()
        if profile is None:
            return
        suggestion = Path.home() / f"{profile.get('name') or 'profile'}{PROFILE_SUFFIX}"
        file, _filter = QFileDialog.getSaveFileName(self, _("Export profile"), str(suggestion),
                                                    _("Daily Deck profile") + f" (*{PROFILE_SUFFIX})")
        if not file:
            return
        target = Path(file)
        if target.suffix != PROFILE_SUFFIX:
            target = target.with_name(target.name + PROFILE_SUFFIX)
        try:
            export_profile(profile, self.config_dir(), target)
        except OSError as e:
            QMessageBox.warning(self, _("Export failed"), str(e))
            return
        self.statusBar().showMessage(_("Exported to {file}").format(file=target), 6000)

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
        self.capture_button.setText(_("Switch windows … {seconds}").format(seconds=3))
        self._capture_timer.start()

    def _capture_tick(self) -> None:
        self._countdown -= 1
        if self._countdown > 0:
            self.capture_button.setText(_("Switch windows … {seconds}").format(seconds=self._countdown))
            return
        self._capture_timer.stop()
        self.capture_button.setText(_("Use active window"))
        self.capture_button.setEnabled(True)
        try:
            if self._focus is None:
                from .focus import create_focus_provider

                self._focus = create_focus_provider(self._settings_obj().focus_backend)
            info = self._focus.get()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, _("Detect window"),
                                _("Could not determine the active window:\n{error}").format(error=e))
            return
        bring_to_front(self)
        if info.empty:
            self.statusBar().showMessage(_("No window detected."), 5000)
            return
        if info.pid == os.getpid():
            self.statusBar().showMessage(_("That was the editor itself – please switch within 3 s."), 6000)
            return
        current = [m.strip() for m in self.match_edit.text().split(",") if m.strip()]
        lower = {m.lower() for m in current}
        current += [i.lower() for i in info.ids if i.lower() not in lower]
        self.match_edit.setText(", ".join(dict.fromkeys(current)))
        if self.name_edit.text().strip() in ("", _("New profile")):
            self.name_edit.setText(info.display_name)
        self._profile_changed()
        self.statusBar().showMessage(
            _("Detected: {app}  ({ids})").format(app=info.display_name, ids=", ".join(info.ids)), 8000)

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
        per, _pages, page = self._page_info()
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
                icon=resolve_icon(self.config_dir(), profile_data.get("icon")),
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
            tile.setToolTip(_("Error in the shortcut") if flat in errors else "")
            tile.set_selected(self.slot is not None and flat == self.slot and not isinstance(slots[i], NavSlot))
        self.page_label.setText(_("Page {page} / {pages}").format(page=page + 1, pages=pages))
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
            self.statusBar().showMessage(_("Preview ended."), 4000)

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
        _per, pages, _page = self._page_info()
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
        self.button_box.setTitle(_("Key {number}").format(number=self._tile_of_slot() + 1) if button is not None
                                 else _("Key  –  click a key above"))
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
        idle = "⏺" if compact else "⏺ " + _("Record")
        button = QPushButton(idle, clicked=lambda: edit.stop_recording() if edit.recording else edit.start_recording())
        button.setToolTip(_("Record a key combination"))
        edit.recordingChanged.connect(lambda on: button.setText(("■" if compact else "■ " + _("Done")) if on else idle))
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(button)
        return edit, row


def main(config_path: Path | None = None) -> int:
    setup_language(config_path)
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
