#!/usr/bin/env python3
"""Keep the version number consistent across all files.

    scripts/version.py check [TAG]   verify all files agree (and match vTAG, if given)
    scripts/version.py bump 0.2.0    set a new version everywhere, start a changelog entry
    scripts/version.py notes 0.2.0   print the CHANGELOG.md section of a version (release notes)

Files: dailydeck/__init__.py (source of truth), debian/changelog,
data/linux/io.github.thnow.dailydeck.metainfo.xml, data/linux/dailydeck.1, CHANGELOG.md
"""

import datetime
import email.utils
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "dailydeck" / "__init__.py"
DEB_CHANGELOG = ROOT / "debian" / "changelog"
METAINFO = ROOT / "data" / "linux" / "io.github.thnow.dailydeck.metainfo.xml"
MANPAGE = ROOT / "data" / "linux" / "dailydeck.1"
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-~][0-9A-Za-z.]+)?$")


def versions() -> dict[str, str | None]:
    def find(path: Path, pattern: str) -> str | None:
        m = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
        return m.group(1) if m else None

    return {
        "dailydeck/__init__.py": find(INIT, r'^__version__ = "([^"]+)"'),
        "debian/changelog": find(DEB_CHANGELOG, r"^dailydeck \(([^)]+)\)"),
        "metainfo (latest release)": find(METAINFO, r'<release version="([^"]+)"'),
        "man page": find(MANPAGE, r'"dailydeck ([^"]+)"'),
        "CHANGELOG.md (latest)": find(CHANGELOG, r"^## \[(\d[^\]]*)\]"),
    }


def check(tag: str | None) -> int:
    found = versions()
    expected = found["dailydeck/__init__.py"]
    ok = True
    for name, value in found.items():
        mark = "ok" if value == expected else "MISMATCH"
        ok &= value == expected
        print(f"  {mark:8} {name}: {value}")
    if tag is not None:
        tag_version = tag.removeprefix("refs/tags/").removeprefix("v")
        good = tag_version == expected
        ok &= good
        print(f"  {'ok' if good else 'MISMATCH':8} git tag: {tag}")
    if not ok:
        print("Versions differ – use: scripts/version.py bump X.Y.Z", file=sys.stderr)
    return 0 if ok else 1


def bump(new: str) -> int:
    if not SEMVER.match(new):
        print(f"not a version: {new}", file=sys.stderr)
        return 1
    today = datetime.date.today()

    INIT.write_text(re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{new}"',
                           INIT.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")

    stamp = email.utils.format_datetime(datetime.datetime.now().astimezone())
    old_deb = DEB_CHANGELOG.read_text(encoding="utf-8")
    maintainer = re.search(r"^ -- (.+?)  ", old_deb, re.M).group(1)
    distribution = re.search(r"^dailydeck \([^)]+\) (\S+);", old_deb, re.M).group(1)
    entry = (f"dailydeck ({new}) {distribution}; urgency=medium\n\n"
             f"  * New upstream release, see CHANGELOG.md.\n\n -- {maintainer}  {stamp}\n\n")
    DEB_CHANGELOG.write_text(entry + old_deb, encoding="utf-8")

    meta = METAINFO.read_text(encoding="utf-8")
    meta = meta.replace("<releases>\n", f'<releases>\n    <release version="{new}" date="{today}"/>\n', 1)
    METAINFO.write_text(meta, encoding="utf-8")

    MANPAGE.write_text(re.sub(r'^\.TH DAILYDECK 1 "[^"]*" "dailydeck [^"]*"',
                              f'.TH DAILYDECK 1 "{today}" "dailydeck {new}"',
                              MANPAGE.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")

    log = CHANGELOG.read_text(encoding="utf-8")
    if "## [Unreleased]" in log:
        log = log.replace("## [Unreleased]", f"## [Unreleased]\n\n## [{new}] – {today}", 1)
    CHANGELOG.write_text(log, encoding="utf-8")
    print(f"Version {new} gesetzt. Jetzt CHANGELOG.md prüfen, committen und taggen: git tag v{new}")
    return check(None)


def notes(version: str) -> int:
    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    if not m:
        print(f"no CHANGELOG.md section for {version}", file=sys.stderr)
        return 1
    print(m.group(1).strip())
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "check":
        return check(argv[1] if len(argv) > 1 else None)
    if len(argv) == 2 and argv[0] == "bump":
        return bump(argv[1])
    if len(argv) == 2 and argv[0] == "notes":
        return notes(argv[1].removeprefix("v"))
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
