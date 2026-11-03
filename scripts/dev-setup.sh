#!/usr/bin/env bash
# Development setup: run dailydeck from this source tree (Linux).
# For normal use install the package instead (scripts/build-deb.sh, docs/RELEASING.md).
#
#   scripts/dev-setup.sh             venv with all dependencies + dev tools, menu entries
#   scripts/dev-setup.sh --remove    remove the menu entries again (e.g. before installing the .deb)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if [[ "${1:-}" == "--remove" ]]; then
    rm -f "$APPS_DIR/io.github.thnow.dailydeck.desktop" "$APPS_DIR/io.github.thnow.dailydeck.Editor.desktop"
    echo "Menüeinträge der Entwicklerversion entfernt."
    exit 0
fi

echo "==> venv in $ROOT/.venv"
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q -e "$ROOT[dev]"

echo "==> Menüeinträge (zeigen auf diesen Quellbaum)"
mkdir -p "$APPS_DIR"
for kind in tray editor; do
    if [[ $kind == tray ]]; then file=io.github.thnow.dailydeck.desktop; arg=--tray; name="Stream Deck (dev)"
    else file=io.github.thnow.dailydeck.Editor.desktop; arg=--gui; name="Daily Deck Profile (dev)"; fi
    sed -e "s|^Exec=.*|Exec=\"$ROOT/.venv/bin/dailydeck\" $arg|" -e "s|^Name=.*|Name=$name|" \
        -e "/^Name\[de\]=/d" -e "s|^Icon=.*|Icon=$ROOT/dailydeck/data/io.github.thnow.dailydeck.svg|" \
        "$ROOT/data/linux/$file" > "$APPS_DIR/$file"
done

echo
echo "Start: $ROOT/.venv/bin/dailydeck --tray   (GNOME-Erweiterung richtet die App beim Start ein)"
echo "Geräterechte fehlen? Einmalig: sudo cp $ROOT/data/linux/60-dailydeck.rules /etc/udev/rules.d/ \\"
echo "    && sudo udevadm control --reload && sudo udevadm trigger"
