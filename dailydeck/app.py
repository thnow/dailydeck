import logging
import queue
import signal
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper
from StreamDeck.Transport.Transport import TransportError

from .appicons import find_app_icon
from .config import Config, ConfigError, Profile, load_config
from .focus import FocusUnavailable, WindowInfo, create_focus_provider
from .i18n import _
from .keys import KeySender, create_key_sender, format_shortcut
from .layout import NavSlot, backdrop_tiles, icon_for, page_slots, render_slot
from .preview import PreviewWatcher
from .render import render_key

log = logging.getLogger(__name__)

# streamdeck < 0.10 (e.g. Ubuntu's python3-elgato-streamdeck 0.9) calls it to_native_format
_to_native = getattr(PILHelper, "to_native_key_format", None) or PILHelper.to_native_format


class DeckController:
    """Shows one profile on a deck and handles its key presses."""

    def __init__(self, deck, sender: KeySender, config: Config):
        self.deck = deck
        self.sender = sender
        self.config = config
        self.profile: Profile | None = None
        self.window = WindowInfo()
        self.icon: Path | None = None
        self.page = 0
        self._slots: list = []
        self._tiles = None
        self._generation = 0
        self.sending = True  # False while previewing: keys only light up
        self.paused = False
        self._saved_config: Config | None = None  # real config while previewing
        self._lock = threading.RLock()
        self._jobs: queue.Queue = queue.Queue()
        self._key_size = deck.key_image_format()["size"]
        self._rows, self._cols = deck.key_layout()

        deck.open()
        deck.reset()
        self._apply_brightness()
        deck.set_key_callback(self._on_key)
        threading.Thread(target=self._worker, daemon=True, name="key-sender").start()
        log.info("connected to %s (serial %s, %d keys)", deck.deck_type(), deck.get_serial_number(), deck.key_count())

    # --- display -----------------------------------------------------------

    def set_config(self, config: Config) -> None:
        with self._lock:
            if self._saved_config is not None:  # previewing: apply when the preview ends
                self._saved_config = config
                return
            self.config = config
            self._apply_brightness()

    def show(
        self,
        profile: Profile | None,
        window: WindowInfo,
        force: bool = False,
        flash: bool | None = None,
        page: int | None = None,
    ) -> None:
        """Show ``profile``. ``flash=None`` flashes the app icon when profile or icon changed."""
        with self._lock:
            s = self.config.settings
            icon = icon_for(profile, window.ids, s)
            show_info = profile is None and window.display_name != self.window.display_name
            switched = profile != self.profile or icon != self.icon
            self.window = window
            if not (switched or force or show_info):
                return
            if page is not None:
                self.page = page
            elif profile != self.profile:
                self.page = 0
            if profile != self.profile and self.sending:
                log.info("profile: %s (%s)", profile.name if profile else "-", window.display_name)
            self.profile = profile
            self.icon = icon
            self._tiles = backdrop_tiles(icon, self._cols, self._rows, self._key_size, s.key_spacing)
            self._slots = self._layout()
            self._generation += 1
            if (switched if flash is None else flash) and self._tiles and s.app_icon_flash > 0:
                self._flash(self._generation, s.app_icon_flash)
            else:
                self._draw_all()

    def preview(self, profile: Profile, settings, ids: tuple[str, ...], page: int) -> None:
        """Show an (unsaved) profile from the editor; key presses send nothing."""
        with self._lock:
            starting = self._saved_config is None
            if starting:
                self._saved_config = self.config
                log.info("preview started")
            self.config = Config(self._saved_config.path, settings, [profile])
            self.sending = False
            self._apply_brightness()
            icon_changed = icon_for(profile, ids, settings) != self.icon
            self.show(profile, WindowInfo(ids=ids, name=profile.name), force=True,
                      flash=starting or icon_changed, page=page)

    def end_preview(self) -> None:
        with self._lock:
            if self._saved_config is None:
                return
            log.info("preview ended")
            self.config = self._saved_config
            self._saved_config = None
            self.sending = True
            self._apply_brightness()
            self.profile = None  # forces a redraw (and flash) of the real profile

    def set_paused(self, paused: bool) -> None:
        """Paused: display off, key presses ignored."""
        with self._lock:
            if paused == self.paused:
                return
            self.paused = paused
            self._generation += 1  # cancel a running flash
            self._apply_brightness()
            if not paused:
                self._draw_all()

    def _apply_brightness(self) -> None:
        with self.deck:
            self.deck.set_brightness(0 if self.paused else self.config.settings.brightness)

    def _flash(self, generation: int, seconds: float) -> None:
        """Show the plain application icon, then the buttons on top of it."""
        for key, tile in enumerate(self._tiles):
            self._set_image(key, tile)
        timer = threading.Timer(seconds, self._end_flash, args=(generation,))
        timer.daemon = True
        timer.start()

    def _end_flash(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                return  # switched again in the meantime
            try:
                self._draw_all()
            except TransportError:
                pass

    def _layout(self) -> list:
        n = self.deck.key_count()
        if self.profile is None:
            return [None] * n
        return page_slots(self.profile.buttons, n, self.page)

    def _draw_all(self) -> None:
        for key in range(self.deck.key_count()):
            self._draw(key)

    def _draw(self, key: int, pressed: bool = False) -> None:
        s = self.config.settings
        slot = self._slots[key] if key < len(self._slots) else None
        tile = self._tiles[key] if self._tiles else None
        if self.profile is None and key == 0 and self.window.display_name:
            image = render_key(
                self._key_size, label=self.window.display_name, hint=_("no profile"),
                background="#000000", text_color="#808080", font=s.font, font_size=12,
                backdrop=tile, backdrop_brightness=s.app_icon_brightness, opacity=s.button_opacity,
            )
        else:
            image = render_slot(slot, self.profile, s, self._key_size, tile, self.page, pressed)
        self._set_image(key, image)

    def _set_image(self, key: int, image) -> None:
        native = _to_native(self.deck, image)
        with self.deck:
            self.deck.set_key_image(key, native)

    # --- input -------------------------------------------------------------

    def _on_key(self, deck, key: int, pressed: bool) -> None:
        with self._lock:
            if self.paused:
                return
            slot = self._slots[key] if key < len(self._slots) else None
            if slot is None:
                return
            try:
                if isinstance(slot, NavSlot):
                    if pressed:
                        self.page += 1
                        self._generation += 1  # cancel a running flash
                        self._slots = self._layout()
                        self._draw_all()
                    return
                if slot.empty:
                    return
                self._draw(key, pressed=pressed)
            except TransportError:
                return
            if pressed and slot.chords and self.sending:
                self._jobs.put(slot)

    def _worker(self) -> None:
        while True:
            button = self._jobs.get()
            if button is None:
                return
            try:
                log.debug("send %s", format_shortcut(button.chords))
                self.sender.send(button.chords)
            except Exception:  # noqa: BLE001 - keep the worker alive
                log.exception("failed to send %s", format_shortcut(button.chords))

    def close(self) -> None:
        self._jobs.put(None)
        try:
            with self.deck:
                self.deck.reset()
                self.deck.close()
        except TransportError:
            pass


def _find_deck():
    decks = DeviceManager().enumerate()
    return decks[0] if decks else None


@dataclass
class DaemonStatus:
    """Snapshot for the tray icon."""

    connected: bool = False
    deck_name: str = ""
    profile: str | None = None
    app_name: str = ""
    app_ids: tuple[str, ...] = ()
    icon: Path | None = None
    previewing: bool = False
    paused: bool = False
    pinned: str | None = None
    profiles: tuple[str, ...] = ()
    error: str | None = None


class Daemon:
    """Main loop: watches focus, config and preview requests and drives the deck.

    Thread safe controls (``set_paused``, ``set_pinned``, ``stop``) and
    ``status`` let a UI (the tray icon) run it in a background thread.
    """

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._paused = False
        self._pinned: str | None = None
        self._status = DaemonStatus()

    # --- controls (any thread) ---------------------------------------------

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
        self._wake.set()

    def set_pinned(self, profile_name: str | None) -> None:
        """Always show this profile, regardless of the focused window (None = automatic)."""
        with self._lock:
            self._pinned = profile_name
        self._wake.set()

    @property
    def status(self) -> DaemonStatus:
        with self._lock:
            return replace(self._status)

    # --- loop ------------------------------------------------------------------

    def _profile_for(self, config: Config, window: WindowInfo, pinned: str | None) -> Profile | None:
        if pinned:
            for profile in config.profiles:
                if profile.name == pinned:
                    return profile
        return config.profile_for(window)

    def _update_status(self, controller, config: Config, window: WindowInfo, previewing: bool, error=None) -> None:
        with self._lock:
            st = self._status
            st.connected = controller is not None
            st.deck_name = controller.deck.deck_type() if controller else ""
            st.profile = controller.profile.name if controller and controller.profile else None
            st.app_name = window.display_name
            st.app_ids = window.ids
            st.icon = find_app_icon(window.ids)
            st.previewing = previewing
            st.paused = self._paused
            st.pinned = self._pinned
            st.profiles = tuple(p.name for p in config.profiles)
            st.error = error

    def run(self) -> int:
        config_path = self.config_path
        try:
            config = load_config(config_path)
        except ConfigError as e:
            log.error("%s", e)
            with self._lock:
                self._status.error = str(e)
            return 1
        log.info("config: %s (%d profiles)", config_path, len(config.profiles))
        s = config.settings
        sender = create_key_sender(s.key_backend, s.keyboard_layout, s.keyboard_variant)
        focus = create_focus_provider(s.focus_backend)

        stop = self._stop
        mtime = config_path.stat().st_mtime
        previews = PreviewWatcher()
        previewing = False
        controller = None
        waiting_logged = False
        window = WindowInfo()
        applied = (False, None)  # (paused, pinned) last applied to the controller
        try:
            while not stop.is_set():
                if controller is None:
                    self._update_status(None, config, window, False)
                    deck = _find_deck()
                    if deck is None:
                        if not waiting_logged:
                            log.info("waiting for a Stream Deck ...")
                            waiting_logged = True
                        self._wake.wait(2)
                        self._wake.clear()
                        continue
                    waiting_logged = False
                    try:
                        controller = DeckController(deck, sender, config)
                        controller.show(config.default_profile, WindowInfo(), force=True)
                        previews.reset()
                        previewing = False
                        applied = (False, None)
                    except TransportError as e:
                        log.warning("cannot open deck: %s", e)
                        self._wake.wait(2)
                        self._wake.clear()
                        continue
                    window = WindowInfo()

                try:
                    with self._lock:
                        paused, pinned = self._paused, self._pinned

                    new_mtime = config_path.stat().st_mtime
                    if new_mtime != mtime:
                        mtime = new_mtime
                        try:
                            config = load_config(config_path)
                            controller.set_config(config)
                            if not previewing:
                                controller.show(self._profile_for(config, window, pinned), window, force=True)
                            log.info("config reloaded (%d profiles)", len(config.profiles))
                        except ConfigError as e:
                            log.error("config not reloaded: %s", e)

                    changed, request = previews.poll()
                    if changed:
                        if request is not None:
                            controller.preview(request.profile, request.settings, request.ids, request.page)
                            previews.acknowledge(request.rev)
                        else:
                            controller.end_preview()
                            controller.show(self._profile_for(config, window, pinned), window, force=True)
                    previewing = request is not None

                    if (paused, pinned) != applied:
                        controller.set_paused(paused)
                        if pinned != applied[1] and not previewing:
                            log.info("pinned profile: %s", pinned or "(automatic)")
                            controller.show(self._profile_for(config, window, pinned), window, force=True)
                        applied = (paused, pinned)

                    try:
                        current = focus.get()
                    except FocusUnavailable as e:
                        log.debug("%s", e)
                        current = window
                    # keep the last profile while nothing is focused (overview, desktop switch)
                    if not current.empty and current != window:
                        window = current
                        log.debug("focus: ids=%s title=%r", window.ids, window.title)
                        if not previewing:
                            controller.show(self._profile_for(config, window, pinned), window)

                    if not controller.deck.connected():
                        raise TransportError("device disconnected")
                except TransportError as e:
                    log.warning("Stream Deck lost: %s", e)
                    controller.close()
                    controller = None
                    continue
                self._update_status(controller, config, window, previewing)
                self._wake.wait(config.settings.poll_interval)
                self._wake.clear()
        finally:
            if controller:
                controller.close()
            focus.close()
            sender.close()
            self._update_status(None, config, window, False)
        return 0


def run(config_path: Path) -> int:
    daemon = Daemon(config_path)
    signal.signal(signal.SIGTERM, lambda *_: daemon.stop())
    signal.signal(signal.SIGINT, lambda *_: daemon.stop())
    return daemon.run()
