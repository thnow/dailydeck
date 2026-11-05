# Translating Daily Deck

Daily Deck is written in English and translated with standard gettext catalogs. Every
language is one file: `dailydeck/data/locale/<code>.po` (e.g. `de.po`, `fr.po`, `pt_BR.po`).
The app reads these files directly, so nothing has to be compiled – edit, save, restart.

What gets translated:

- the profile editor, the tray menu and all messages
- profile names and key labels of the **default profiles** (context `default config`) – they
  are written in the user's language when the config file is first created

Key names on the keys (Ctrl, Shift, Cmd …) stay as printed on most keyboards.

## Add a language

```bash
python3 scripts/i18n.py new fr            # creates dailydeck/data/locale/fr.po
```

Translate the file with any gettext editor – [Poedit](https://poedit.net) is free and easy –
or a plain text editor. Then check it and try it:

```bash
python3 scripts/i18n.py check             # placeholders, syntax, coverage
dailydeck --gui                           # follows the system language
```

or pick the language in the editor under *Settings → Language* and restart.
Open a pull request with the `.po` file – partial translations are welcome, untranslated
texts simply stay English.

## Rules for translators

- **Placeholders** in braces must stay unchanged: `Delete profile “{name}”?` →
  `Profil „{name}“ löschen?`. `check` reports missing or unknown ones.
- **Key labels** (context `default config`) have little room: about 10 characters per line
  on a key. `|` marks where a long word may be hyphenated (`Side|bar` → `Seiten|leiste`);
  use it in long words of your language too.
- `&` in menu titles (`&File`) marks the keyboard accelerator; keep one `&` in the translation.
- Entries marked `#, fuzzy` are ignored by the app until the mark is removed (Poedit: “Needs
  work” off).
- Use the typographic quotes and punctuation of your language.

## When the code changes (developers)

Texts in the code are English and wrapped like this:

```python
from .i18n import N_, _, ngettext, pgettext

QPushButton(_("Save"))
_("Delete profile “{name}”?").format(name=name)        # never an f-string inside _()
ngettext("{n} key", "{n} keys", n).format(n=n)
LABEL = N_("Shortcut")   # module constant: marked here, translated where used: _(LABEL)
```

After adding or changing texts (or default profiles), run

```bash
python3 scripts/i18n.py update
```

It rewrites the template `dailydeck/data/locale/dailydeck.pot` and adds new texts to every
`.po` (untranslated); texts that no longer exist are dropped. CI runs `check` and fails if
this step was forgotten. Only the Python standard library is needed.

Translation platforms such as Weblate can work directly with these files (format
“gettext PO”, template `dailydeck/data/locale/dailydeck.pot`).
