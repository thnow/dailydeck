"""Translations.

Texts in the code are English and wrapped in ``_()`` (or ``ngettext``/``pgettext``).
Translations live as plain gettext catalogs in ``dailydeck/data/locale/<lang>.po``
and are read directly at runtime – contributors edit a .po file (Poedit, Weblate,
any text editor) and nothing has to be compiled. See docs/TRANSLATING.md.

The language follows the system (``LANGUAGE``/``LC_*``/``LANG``, the macOS and
Windows UI language) unless ``language`` is set under ``[settings]``.
"""

import ast
import gettext
import io
import locale
import logging
import os
import re
import struct
import sys
from pathlib import Path

log = logging.getLogger(__name__)

LOCALE_DIR = Path(__file__).resolve().parent / "data" / "locale"
SOURCE_LANGUAGE = "en"

_translation: gettext.NullTranslations = gettext.NullTranslations()
_language = SOURCE_LANGUAGE


def _(message: str) -> str:
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return _translation.ngettext(singular, plural, n)


def pgettext(context: str, message: str) -> str:
    return _translation.pgettext(context, message)


def N_(message: str) -> str:
    """Marks a text for translation without translating it yet (module constants)."""
    return message


def language() -> str:
    """The language in use, e.g. "de" or "en"."""
    return _language


def available_languages() -> list[str]:
    """Source language plus every language with a catalog, e.g. ["de", "en"]."""
    found = {p.stem for p in LOCALE_DIR.glob("*.po")} if LOCALE_DIR.is_dir() else set()
    return sorted(found | {SOURCE_LANGUAGE})


def native_name(lang: str) -> str:
    """Name of a language in that language, from its catalog header ("Deutsch")."""
    if lang == SOURCE_LANGUAGE:
        return "English"
    try:
        header = parse_po((LOCALE_DIR / f"{lang}.po").read_text(encoding="utf-8")).get((None, ""), "")
    except (OSError, ValueError):
        return lang
    m = re.search(r"^X-Language-Name:\s*(.+)$", header, re.M)
    return m.group(1).strip() if m else lang


def resolve(preferred: str | None = None) -> str:
    """The language ``setup`` would choose: ``preferred`` if a catalog exists for it,
    otherwise the first system language with a catalog, otherwise English."""
    candidates = [preferred] if preferred and preferred != "auto" else []
    for lang in candidates + system_languages():
        for code in _variants(lang):
            if code == SOURCE_LANGUAGE or (LOCALE_DIR / f"{code}.po").is_file():
                return code
    return SOURCE_LANGUAGE


def setup(preferred: str | None = None) -> str:
    """Activates the catalog for ``preferred`` (a code; None, "" or "auto" = system language)."""
    global _translation, _language
    code = resolve(preferred)
    _translation, _language = gettext.NullTranslations(), SOURCE_LANGUAGE
    if code != SOURCE_LANGUAGE:
        try:
            _translation, _language = load_po(LOCALE_DIR / f"{code}.po"), code
        except (OSError, ValueError) as e:
            log.warning("cannot load translation %s: %s", code, e)
    return _language


def setup_from_config(path: Path) -> str:
    """Like ``setup``, with the ``language`` setting of a config file (if readable)."""
    import tomllib

    try:
        settings = tomllib.loads(path.read_text(encoding="utf-8")).get("settings", {})
        preferred = settings.get("language") if isinstance(settings, dict) else None
    except (OSError, ValueError):
        preferred = None
    return setup(preferred if isinstance(preferred, str) else None)


def _variants(code: str) -> list[str]:
    """"de_AT.UTF-8" -> ["de_AT", "de"]; "pt-BR" -> ["pt_BR", "pt"]."""
    code = code.split(".")[0].split("@")[0].replace("-", "_")
    if not code or code in ("C", "POSIX"):
        return []
    base = code.split("_")[0].lower()
    return [code, base] if code != base else [base]


def system_languages() -> list[str]:
    """Preferred UI languages of the user, most preferred first."""
    langs: list[str] = []
    if env := os.environ.get("LANGUAGE"):
        langs += [part for part in env.split(":") if part]
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if value := os.environ.get(var):
            langs.append(value)
            break
    if sys.platform == "darwin":
        try:
            from Foundation import NSLocale

            langs += [str(code) for code in NSLocale.preferredLanguages()]
        except ImportError:
            pass
    elif sys.platform == "win32":
        try:
            import ctypes

            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if name := locale.windows_locale.get(lcid):
                langs.append(name)
        except (AttributeError, OSError):
            pass
    return langs


# ------------------------------------------------------------------ .po files

def _unquote(text: str) -> str:
    return ast.literal_eval(text) if text.startswith('"') else ""


def parse_po(text: str) -> dict[tuple[str | None, str], str | list[str]]:
    """Entries of a .po file as {(context, msgid): msgstr}; plural entries map
    (context, "singular\\x00plural") to a list of forms. Fuzzy and empty
    translations are left out (they fall back to English)."""
    entries: dict = {}
    entry: dict = {}
    field = None
    fuzzy = False

    def finish():
        nonlocal entry, fuzzy
        if "msgid" in entry and not fuzzy:
            key_id = entry["msgid"]
            if "msgid_plural" in entry:
                forms = [entry[k] for k in sorted(k for k in entry if k.startswith("msgstr["))]
                if any(forms):
                    entries[(entry.get("msgctxt"), f"{key_id}\x00{entry['msgid_plural']}")] = forms
            elif entry.get("msgstr") or key_id == "":
                entries[(entry.get("msgctxt"), key_id)] = entry.get("msgstr", "")
        entry, fuzzy = {}, False

    def has_msgstr() -> bool:
        return any(k.startswith("msgstr") for k in entry)

    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):  # comments start the next entry
            if has_msgstr():
                finish()
            if line.startswith("#,") and "fuzzy" in line:
                fuzzy = True
            continue
        m = re.match(r"^(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+(\".*\")$", line)
        try:
            if m:
                if m.group(1) in ("msgctxt", "msgid") and has_msgstr():
                    finish()
                field = m.group(1)
                entry[field] = _unquote(m.group(2))
            elif line.startswith('"') and field:
                entry[field] += _unquote(line)
            else:
                raise ValueError(line)
        except (ValueError, SyntaxError) as e:
            raise ValueError(f"line {number}: cannot parse {raw!r}") from e
    finish()
    return entries


def _mo_bytes(entries: dict) -> bytes:
    """Compiles parsed entries into the binary .mo format gettext reads."""
    pairs = []
    for (context, msgid), msgstr in entries.items():
        key = f"{context}\x04{msgid}" if context is not None else msgid
        value = "\x00".join(msgstr) if isinstance(msgstr, list) else msgstr
        pairs.append((key.encode("utf-8"), value.encode("utf-8")))
    pairs.sort()
    count = len(pairs)
    ids = b"".join(k + b"\x00" for k, _v in pairs)
    strs = b"".join(v + b"\x00" for _k, v in pairs)
    key_start = 7 * 4 + 16 * count
    value_start = key_start + len(ids)
    offsets, pos_k, pos_v = [], 0, 0
    for k, v in pairs:
        offsets.append((len(k), key_start + pos_k, len(v), value_start + pos_v))
        pos_k += len(k) + 1
        pos_v += len(v) + 1
    header = struct.pack("Iiiiiii", 0x950412DE, 0, count, 7 * 4, 7 * 4 + count * 8, 0, 0)
    table_k = b"".join(struct.pack("ii", n, o) for n, o, _n2, _o2 in offsets)
    table_v = b"".join(struct.pack("ii", n2, o2) for _n, _o, n2, o2 in offsets)
    return header + table_k + table_v + ids + strs


def load_po(path: Path) -> gettext.GNUTranslations:
    return gettext.GNUTranslations(io.BytesIO(_mo_bytes(parse_po(path.read_text(encoding="utf-8")))))
