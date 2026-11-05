#!/usr/bin/env python3
"""Maintain the translation catalogs in dailydeck/data/locale/.

    scripts/i18n.py update        collect all texts into dailydeck.pot and add new
                                  ones (untranslated) to every <lang>.po
    scripts/i18n.py new fr        start a new language from the template
    scripts/i18n.py check         CI: template current, catalogs valid and in sync,
                                  placeholders like {name} kept; prints coverage
    scripts/i18n.py stats         coverage per language

Texts come from ``_()``, ``N_()``, ``ngettext()`` and ``pgettext()`` calls in
dailydeck/ and from profile names and key labels of the default config
(context "default config"). Only the standard library is needed.
"""

import ast
import re
import string
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dailydeck.i18n import LOCALE_DIR, parse_po  # noqa: E402

TEMPLATE = LOCALE_DIR / "dailydeck.pot"
DEFAULT_CONFIG = ROOT / "dailydeck" / "data" / "default_config.toml"
CONFIG_CONTEXT = "default config"
SOFT_HYPHEN = "\u00ad"

# nplurals/plural formula and native name for languages people are likely to add;
# others get a placeholder to fill in (see https://docs.translatehouse.org/projects/localization-guide/en/latest/l10n/pluralforms.html)
LANGUAGES = {
    "de": ("Deutsch", "nplurals=2; plural=(n != 1);"),
    "fr": ("Français", "nplurals=2; plural=(n > 1);"),
    "es": ("Español", "nplurals=2; plural=(n != 1);"),
    "it": ("Italiano", "nplurals=2; plural=(n != 1);"),
    "nl": ("Nederlands", "nplurals=2; plural=(n != 1);"),
    "pt": ("Português", "nplurals=2; plural=(n != 1);"),
    "pt_BR": ("Português (Brasil)", "nplurals=2; plural=(n > 1);"),
    "pl": ("Polski", "nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);"),
    "cs": ("Čeština", "nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;"),
    "sv": ("Svenska", "nplurals=2; plural=(n != 1);"),
    "da": ("Dansk", "nplurals=2; plural=(n != 1);"),
    "nb": ("Norsk bokmål", "nplurals=2; plural=(n != 1);"),
    "fi": ("Suomi", "nplurals=2; plural=(n != 1);"),
    "tr": ("Türkçe", "nplurals=2; plural=(n != 1);"),
    "uk": ("Українська", "nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && "
                          "(n%100<10 || n%100>=20) ? 1 : 2);"),
    "ja": ("日本語", "nplurals=1; plural=0;"),
    "zh_CN": ("简体中文", "nplurals=1; plural=0;"),
}


# ------------------------------------------------------------------ collect

class Message:
    def __init__(self, msgid: str, context: str | None = None, plural: str | None = None):
        self.msgid, self.context, self.plural = msgid, context, plural
        self.sources: set[str] = set()

    @property
    def key(self) -> tuple[str | None, str]:
        return self.context, self.msgid


def collect() -> dict[tuple[str | None, str], Message]:
    messages: dict[tuple[str | None, str], Message] = {}

    def add(msgid, source, context=None, plural=None):
        msg = messages.setdefault((context, msgid), Message(msgid, context, plural))
        msg.sources.add(source)

    for path in sorted((ROOT / "dailydeck").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), rel)):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            args = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None
                    for a in node.args]
            name = node.func.id
            if name in ("_", "N_") and args and args[0] is not None:
                add(args[0], rel)
            elif name == "ngettext" and len(args) >= 2 and None not in args[:2]:
                add(args[0], rel, plural=args[1])
            elif name == "pgettext" and len(args) >= 2 and None not in args[:2]:
                add(args[1], rel, context=args[0])
            if name in ("_", "N_", "ngettext", "pgettext") and any(isinstance(a, ast.JoinedStr) for a in node.args):
                sys.exit(f"{rel}:{node.lineno}: {name}() needs a plain string – use _(\"… {{x}}\").format(x=…), "
                         "not an f-string")

    rel = DEFAULT_CONFIG.relative_to(ROOT).as_posix()
    data = tomllib.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    for profile in data.get("profiles", []):
        add(profile["name"], rel, CONFIG_CONTEXT)
        for button in profile.get("buttons", []):
            if label := button.get("label"):
                add(label.replace(SOFT_HYPHEN, "|"), rel, CONFIG_CONTEXT)
    return messages


# ------------------------------------------------------------------ write

def quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\n", "\\n")
    return f'"{escaped}"'


def field(name: str, text: str) -> str:
    if "\n" in text.rstrip("\n"):  # multi-line texts one line per line, like msgmerge
        parts = text.splitlines(keepends=True)
        return f'{name} ""\n' + "\n".join(quote(p) for p in parts)
    return f"{name} {quote(text)}"


def entry(msg: Message, translation=None, fuzzy: bool = False) -> str:
    lines = ["#: " + " ".join(sorted(msg.sources))]
    flags = (["fuzzy"] if fuzzy else []) + (["python-brace-format"] if placeholders(msg.msgid) else [])
    if flags:
        lines.append("#, " + ", ".join(flags))
    if msg.context is not None:
        lines.append(field("msgctxt", msg.context))
    lines.append(field("msgid", msg.msgid))
    if msg.plural is not None:
        lines.append(field("msgid_plural", msg.plural))
        forms = translation if isinstance(translation, list) else ["", ""]
        lines += [field(f"msgstr[{i}]", form) for i, form in enumerate(forms)]
    else:
        lines.append(field("msgstr", translation if isinstance(translation, str) else ""))
    return "\n".join(lines)


def header(lang: str | None, existing: str | None = None) -> str:
    if existing is not None:
        return 'msgid ""\n' + field("msgstr", existing)
    name, plural = LANGUAGES.get(lang or "", ("LANGUAGE NAME", "nplurals=INTEGER; plural=EXPRESSION;"))
    text = (
        "Project-Id-Version: dailydeck\n"
        "Report-Msgid-Bugs-To: https://github.com/thnow/dailydeck/issues\n"
        f"Language: {lang or ''}\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=UTF-8\n"
        "Content-Transfer-Encoding: 8bit\n"
        f"Plural-Forms: {plural}\n"
        f"X-Language-Name: {name}\n"
    )
    return 'msgid ""\n' + field("msgstr", text)


def render(messages, translations=None, lang=None, existing_header=None, template=False, fuzzy=()) -> str:
    def sort_key(m: Message):
        return (m.context or "", min(m.sources), m.msgid)

    head = "# Template for translations of Daily Deck – see docs/TRANSLATING.md\n" if template else (
        f"# {LANGUAGES.get(lang, (lang,))[0]} translation of Daily Deck – see docs/TRANSLATING.md\n")
    parts = [head + header(lang, existing_header)]
    for msg in sorted(messages.values(), key=sort_key):
        key = (msg.context, msg.msgid if msg.plural is None else f"{msg.msgid}\x00{msg.plural}")
        parts.append(entry(msg, (translations or {}).get(key), key in fuzzy))
    return "\n\n".join(parts) + "\n"


def read_catalog(path: Path) -> tuple[dict, str, set]:
    """All translations of a .po file, its header and the keys marked fuzzy."""
    text = path.read_text(encoding="utf-8")
    entries = parse_po(text.replace("#, fuzzy, ", "#, ").replace("#, fuzzy", "#"))
    reviewed = parse_po(text)
    head = entries.pop((None, ""), "")
    return entries, head, {k for k in entries if k not in reviewed}


# ------------------------------------------------------------------ check

def placeholders(text: str) -> set[str]:
    try:
        return {f for _lit, f, _spec, _conv in string.Formatter().parse(text) if f is not None}
    except ValueError:
        return set()


def catalogs() -> list[Path]:
    return sorted(LOCALE_DIR.glob("*.po"))


def coverage(path: Path, messages) -> tuple[int, int]:
    done = parse_po(path.read_text(encoding="utf-8"))
    done.pop((None, ""), None)
    keys = {(m.context, m.msgid if m.plural is None else f"{m.msgid}\x00{m.plural}") for m in messages.values()}
    return len(keys & set(done)), len(keys)


def check() -> int:
    messages = collect()
    errors = []
    if not TEMPLATE.exists() or TEMPLATE.read_text(encoding="utf-8") != render(messages, template=True):
        errors.append(f"{TEMPLATE.relative_to(ROOT)} is outdated – run scripts/i18n.py update")
    for path in catalogs():
        rel = path.relative_to(ROOT)
        try:
            translations, head, fuzzy = read_catalog(path)
        except ValueError as e:
            errors.append(f"{rel}: {e}")
            continue
        if path.read_text(encoding="utf-8") != render(messages, translations, path.stem, head, fuzzy=fuzzy):
            errors.append(f"{rel} is not in sync with the code – run scripts/i18n.py update")
        if not re.search(r"^Plural-Forms: nplurals=\d+; plural=", head, re.M):
            errors.append(f"{rel}: header needs a valid Plural-Forms line")
        for (_context, msgid), translation in translations.items():
            source = msgid.split("\x00")
            allowed = set().union(*map(placeholders, source))
            if isinstance(translation, str) and translation and placeholders(translation) != allowed:
                errors.append(f"{rel}: {translation!r} must use the placeholders of {msgid!r}: "
                              + (", ".join(f"{{{p}}}" for p in sorted(allowed)) or "none"))
            # plural forms may leave out the number ("one key"), but must not invent placeholders
            for form in translation if isinstance(translation, list) else []:
                if placeholders(form) - allowed:
                    errors.append(f"{rel}: unknown placeholder in {form!r} (for {source[0]!r})")
    for error in errors:
        print("error:", error, file=sys.stderr)
    stats(messages)
    return 1 if errors else 0


def stats(messages=None) -> int:
    messages = messages or collect()
    for path in catalogs():
        done, total = coverage(path, messages)
        print(f"  {path.stem:6} {done:4}/{total} translated ({100 * done // max(total, 1)} %)")
    return 0


# ------------------------------------------------------------------ main

def update() -> int:
    messages = collect()
    LOCALE_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE.write_text(render(messages, template=True), encoding="utf-8")
    for path in catalogs():
        translations, head, fuzzy = read_catalog(path)
        keys = {(m.context, m.msgid if m.plural is None else f"{m.msgid}\x00{m.plural}") for m in messages.values()}
        if dropped := [k for k in translations if k not in keys]:
            print(f"{path.stem}: {len(dropped)} translation(s) no longer used: "
                  + ", ".join(repr(k[1]) for k in dropped[:5]) + (" …" if len(dropped) > 5 else ""))
        path.write_text(render(messages, translations, path.stem, head, fuzzy=fuzzy), encoding="utf-8")
    return stats(messages)


def new(lang: str) -> int:
    if not re.fullmatch(r"[a-z]{2,3}(_[A-Z]{2})?", lang):
        sys.exit(f"language code like 'fr' or 'pt_BR' expected, not {lang!r}")
    path = LOCALE_DIR / f"{lang}.po"
    if path.exists():
        sys.exit(f"{path.relative_to(ROOT)} exists already")
    path.write_text(render(collect(), lang=lang), encoding="utf-8")
    print(f"created {path.relative_to(ROOT)} – translate it (e.g. with Poedit), then run: scripts/i18n.py check")
    if lang not in LANGUAGES:
        print("fill in Plural-Forms and X-Language-Name in its header")
    return 0


def main(argv: list[str]) -> int:
    if argv == ["update"]:
        return update()
    if argv == ["check"]:
        return check()
    if argv == ["stats"]:
        return stats()
    if len(argv) == 2 and argv[0] == "new":
        return new(argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
