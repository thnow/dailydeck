// Daily Deck Focus Bridge
//
// On Wayland, regular clients cannot ask the compositor which window has the
// focus. This extension runs inside GNOME Shell and publishes that information
// on the session bus:
//
//   bus name:  io.github.thnow.dailydeck.Focus
//   path:      /io/github/thnow/dailydeck/Focus
//   method:    GetFocus() -> s   (JSON object)
//   signal:    FocusChanged(s)   (JSON object, also emitted on title changes)

import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'io.github.thnow.dailydeck.Focus';
const OBJECT_PATH = '/io/github/thnow/dailydeck/Focus';
const IFACE_XML = `
<node>
  <interface name="io.github.thnow.dailydeck.Focus">
    <method name="GetFocus">
      <arg type="s" direction="out" name="info"/>
    </method>
    <signal name="FocusChanged">
      <arg type="s" name="info"/>
    </signal>
  </interface>
</node>`;

export default class StreamDeckFocusExtension extends Extension {
    enable() {
        this._window = null;
        this._titleId = 0;

        this._impl = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, this);
        this._impl.export(Gio.DBus.session, OBJECT_PATH);
        this._nameId = Gio.bus_own_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
            null, null, null);

        this._focusId = global.display.connect('notify::focus-window',
            () => this._onFocusChanged());
        this._onFocusChanged();
    }

    disable() {
        this._disconnectTitle();
        if (this._focusId) {
            global.display.disconnect(this._focusId);
            this._focusId = 0;
        }
        if (this._nameId) {
            Gio.bus_unown_name(this._nameId);
            this._nameId = 0;
        }
        if (this._impl) {
            this._impl.unexport();
            this._impl = null;
        }
    }

    GetFocus() {
        const win = global.display.focus_window;
        if (!win)
            return '{}';
        const app = Shell.WindowTracker.get_default().get_window_app(win);
        return JSON.stringify({
            wm_class: win.get_wm_class() ?? '',
            wm_class_instance: win.get_wm_class_instance() ?? '',
            app_id: app?.get_id() ?? '',
            app_name: app?.get_name() ?? '',
            title: win.get_title() ?? '',
            pid: win.get_pid(),
        });
    }

    _onFocusChanged() {
        this._disconnectTitle();
        this._window = global.display.focus_window;
        if (this._window) {
            this._titleId = this._window.connect('notify::title',
                () => this._emitChanged());
        }
        this._emitChanged();
    }

    _disconnectTitle() {
        if (this._window && this._titleId) {
            try {
                this._window.disconnect(this._titleId);
            } catch (e) {
                // window already disposed
            }
        }
        this._window = null;
        this._titleId = 0;
    }

    _emitChanged() {
        this._impl?.emit_signal('FocusChanged',
            new GLib.Variant('(s)', [this.GetFocus()]));
    }
}
