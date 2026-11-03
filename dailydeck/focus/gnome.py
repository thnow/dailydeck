"""GNOME Shell (Wayland and X11) backend.

Talks to the ``dailydeck-focus@thnow.github.io`` shell extension over D-Bus.
"""

import json

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection
from jeepney.wrappers import DBusErrorResponse, unwrap_msg

from .base import FocusProvider, FocusUnavailable, WindowInfo

BUS_NAME = "io.github.thnow.dailydeck.Focus"
OBJECT_PATH = "/io/github/thnow/dailydeck/Focus"


class GnomeFocusProvider(FocusProvider):
    name = "gnome"

    def __init__(self):
        self._conn = open_dbus_connection(bus="SESSION")
        self._addr = DBusAddress(OBJECT_PATH, bus_name=BUS_NAME, interface=BUS_NAME)

    def get(self) -> WindowInfo:
        try:
            reply = self._conn.send_and_get_reply(
                new_method_call(self._addr, "GetFocus"), timeout=1.0
            )
            (raw,) = unwrap_msg(reply)
        except (DBusErrorResponse, TimeoutError, OSError) as e:
            raise FocusUnavailable(f"GNOME extension not reachable: {e}") from e
        data = json.loads(raw or "{}")
        ids = []
        for key in ("wm_class", "wm_class_instance", "app_id"):
            value = data.get(key) or ""
            if value and value not in ids:
                ids.append(value)
            # "org.gnome.Terminal.desktop" -> also offer "org.gnome.Terminal"
            if value.endswith(".desktop") and value[:-8] not in ids:
                ids.append(value[:-8])
        return WindowInfo(
            ids=tuple(ids),
            title=data.get("title", ""),
            name=data.get("app_name", ""),
            pid=data.get("pid", 0) or 0,
            extra=data,
        )

    def close(self) -> None:
        self._conn.close()
