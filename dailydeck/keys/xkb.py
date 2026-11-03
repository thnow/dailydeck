"""Minimal ctypes binding to libxkbcommon.

Used to find out which physical key (and which Shift/AltGr level) produces a
given keysym in the user's keyboard layout. uinput only knows physical keys,
so without this ``ctrl+z`` would come out as ``ctrl+y`` on a German layout.
"""

import ast
import ctypes
import ctypes.util
import logging
import subprocess
from ctypes import POINTER, c_char_p, c_int, c_size_t, c_uint32, c_void_p

log = logging.getLogger(__name__)

EVDEV_OFFSET = 8  # xkb keycode = evdev keycode + 8

# xkb modifier name -> our modifier name; masks with other mods are skipped
_MOD_NAMES = {"Shift": "shift", "Mod5": "altgr", "LevelThree": "altgr"}


class _RuleNames(ctypes.Structure):
    _fields_ = [(n, c_char_p) for n in ("rules", "model", "layout", "variant", "options")]


def _load():
    lib = ctypes.CDLL(ctypes.util.find_library("xkbcommon") or "libxkbcommon.so.0")
    sig = {
        "xkb_context_new": (c_void_p, [c_int]),
        "xkb_context_unref": (None, [c_void_p]),
        "xkb_keymap_new_from_names": (c_void_p, [c_void_p, POINTER(_RuleNames), c_int]),
        "xkb_keymap_unref": (None, [c_void_p]),
        "xkb_keymap_min_keycode": (c_uint32, [c_void_p]),
        "xkb_keymap_max_keycode": (c_uint32, [c_void_p]),
        "xkb_keymap_num_levels_for_key": (c_uint32, [c_void_p, c_uint32, c_uint32]),
        "xkb_keymap_key_get_syms_by_level": (
            c_int, [c_void_p, c_uint32, c_uint32, c_uint32, POINTER(POINTER(c_uint32))]),
        "xkb_keymap_key_get_mods_for_level": (
            c_size_t, [c_void_p, c_uint32, c_uint32, c_uint32, POINTER(c_uint32), c_size_t]),
        "xkb_keymap_num_mods": (c_uint32, [c_void_p]),
        "xkb_keymap_mod_get_name": (c_char_p, [c_void_p, c_uint32]),
        "xkb_keysym_from_name": (c_uint32, [c_char_p, c_int]),
        "xkb_utf32_to_keysym": (c_uint32, [c_uint32]),
    }
    for name, (restype, argtypes) in sig.items():
        fn = getattr(lib, name)
        fn.restype = restype
        fn.argtypes = argtypes
    return lib


def detect_layout() -> tuple[str, str]:
    """Return (layout, variant) of the first GNOME input source, else 'us'."""
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.input-sources", "sources"],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout.strip()
        for kind, value in ast.literal_eval(out.removeprefix("@a(ss) ")):
            if kind == "xkb":
                layout, _, variant = value.partition("+")
                return layout, variant
    except (OSError, subprocess.SubprocessError, ValueError, SyntaxError) as e:
        log.debug("could not read GNOME input sources: %s", e)
    try:
        out = subprocess.run(["localectl", "status"], capture_output=True, text=True, timeout=2).stdout
        fields = dict(
            line.strip().split(": ", 1) for line in out.splitlines() if ": " in line
        )
        if fields.get("X11 Layout"):
            return fields["X11 Layout"].split(",")[0], fields.get("X11 Variant", "").split(",")[0]
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("localectl failed: %s", e)
    return "us", ""


class XkbKeymap:
    def __init__(self, layout: str, variant: str = ""):
        self.layout = layout
        self.variant = variant
        self._lib = lib = _load()
        ctx = lib.xkb_context_new(0)
        names = _RuleNames(None, None, layout.encode(), variant.encode() or None, None)
        keymap = lib.xkb_keymap_new_from_names(ctx, ctypes.byref(names), 0)
        if not keymap:
            lib.xkb_context_unref(ctx)
            raise ValueError(f"cannot compile keymap for layout {layout!r} variant {variant!r}")
        try:
            self._index = self._build_index(keymap)
        finally:
            lib.xkb_keymap_unref(keymap)
            lib.xkb_context_unref(ctx)

    def _build_index(self, keymap) -> dict[int, tuple[int, frozenset[str]]]:
        """keysym -> (evdev code, required modifiers), easiest variant wins."""
        lib = self._lib
        mod_names = {
            i: (lib.xkb_keymap_mod_get_name(keymap, i) or b"").decode()
            for i in range(lib.xkb_keymap_num_mods(keymap))
        }
        best: dict[int, tuple[tuple, int, frozenset[str]]] = {}
        syms_p = POINTER(c_uint32)()
        masks = (c_uint32 * 16)()
        for kc in range(lib.xkb_keymap_min_keycode(keymap), lib.xkb_keymap_max_keycode(keymap) + 1):
            for level in range(lib.xkb_keymap_num_levels_for_key(keymap, kc, 0)):
                n_syms = lib.xkb_keymap_key_get_syms_by_level(keymap, kc, 0, level, ctypes.byref(syms_p))
                if n_syms != 1:
                    continue
                sym = syms_p[0]
                n_masks = lib.xkb_keymap_key_get_mods_for_level(keymap, kc, 0, level, masks, len(masks))
                for m in range(n_masks):
                    mods = self._mask_to_mods(masks[m], mod_names)
                    if mods is None:
                        continue
                    rank = (len(mods), level, kc)
                    if sym not in best or rank < best[sym][0]:
                        best[sym] = (rank, kc - EVDEV_OFFSET, mods)
        return {sym: (code, mods) for sym, (_, code, mods) in best.items()}

    @staticmethod
    def _mask_to_mods(mask: int, mod_names: dict[int, str]) -> frozenset[str] | None:
        mods = set()
        for i, name in mod_names.items():
            if mask & (1 << i):
                if name not in _MOD_NAMES:
                    return None
                mods.add(_MOD_NAMES[name])
        return frozenset(mods)

    def keysym_for_char(self, char: str) -> int:
        return self._lib.xkb_utf32_to_keysym(ord(char))

    def keysym_for_name(self, name: str) -> int:
        return self._lib.xkb_keysym_from_name(name.encode(), 0)

    def lookup(self, keysym: int) -> tuple[int, frozenset[str]] | None:
        return self._index.get(keysym)
