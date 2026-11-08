import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from dailydeck import i18n
from dailydeck.config import SOFT_HYPHEN, localized_default_config, parse_config

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def english_afterwards():
    yield
    i18n.setup("en")


def test_parse_po():
    entries = i18n.parse_po('''
msgid ""
msgstr "Plural-Forms: nplurals=2; plural=(n != 1);\\n"

#: a.py
msgid "Save"
msgstr "Speichern"

#, fuzzy
msgid "Old"
msgstr "Alt"

msgctxt "default config"
msgid "Side|bar"
msgstr "Seiten|"
"leiste"

msgid "{n} key"
msgid_plural "{n} keys"
msgstr[0] "{n} Taste"
msgstr[1] "{n} Tasten"

msgid "Untranslated"
msgstr ""
''')
    assert entries[(None, "Save")] == "Speichern"
    assert (None, "Old") not in entries  # fuzzy: falls back to English
    assert (None, "Untranslated") not in entries
    assert entries[("default config", "Side|bar")] == "Seiten|leiste"
    assert entries[(None, "{n} key\x00{n} keys")] == ["{n} Taste", "{n} Tasten"]


def test_parse_po_reports_line():
    with pytest.raises(ValueError, match="line 2"):
        i18n.parse_po('msgid "a"\nnonsense\n')


def test_setup_and_fallback(monkeypatch):
    assert i18n.setup("de") == "de"
    assert i18n._("Save") == "Speichern"
    assert i18n.pgettext("default config", "New tab") == "Neuer Tab"
    assert i18n.setup("xx") in i18n.available_languages()  # unknown: system language or English
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LANG", "de_AT.UTF-8")
    monkeypatch.setattr(i18n, "system_languages", lambda: ["de_AT.UTF-8"])
    assert i18n.resolve() == "de"
    monkeypatch.setattr(i18n, "system_languages", lambda: ["sw_KE", "C"])
    assert i18n.resolve() == "en"
    assert i18n.setup("en") == "en"
    assert i18n._("Save") == "Save"


def test_every_catalog_loads():
    for code in i18n.available_languages():
        assert i18n.setup(code) == code
        assert i18n.native_name(code)


def test_german_default_config_matches_previous_release():
    i18n.setup("de")
    data = tomllib.loads(localized_default_config())
    parse_config(data, Path("config.toml"))  # still valid after translation
    old = tomllib.loads((ROOT / "tests" / "data" / "default_config-0.2.0.toml").read_text(encoding="utf-8"))

    def labels(d):
        return [(p["name"], [b.get("label") for b in p.get("buttons", [])]) for p in d["profiles"]]

    old_names = {p["name"] for p in old["profiles"]}
    assert [entry for entry in labels(data) if entry[0] in old_names] == labels(old)  # later profiles may follow
    assert any(SOFT_HYPHEN in (b.get("label") or "") for p in data["profiles"] for b in p.get("buttons", []))


def test_english_default_config_is_the_template():
    i18n.setup("en")
    template = (i18n.LOCALE_DIR.parent / "default_config.toml").read_text(encoding="utf-8")
    assert tomllib.loads(localized_default_config()) == tomllib.loads(template)


@pytest.mark.skipif(not (ROOT / "scripts" / "i18n.py").exists(), reason="needs the source tree")
def test_catalogs_in_sync_with_code():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "i18n.py"), "check"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_no_fstrings_in_translations():
    for path in (ROOT / "dailydeck").rglob("*.py"):
        assert not re.search(r"\b_\(f[\"']", path.read_text(encoding="utf-8")), path
