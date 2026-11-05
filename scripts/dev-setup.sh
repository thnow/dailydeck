#!/usr/bin/env bash
# Development setup: run dailydeck from this source tree (Linux).
# For normal use install a release package instead (see README.md).
#
#   scripts/dev-setup.sh             venv with all dependencies + dev tools, menu entries
#   scripts/dev-setup.sh --remove    remove the menu entries again (e.g. before installing the .deb)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if [[ "${1:-}" == "--remove" ]]; then
    rm -f "$APPS_DIR/io.github.thnow.dailydeck.desktop" "$APPS_DIR/io.github.thnow.dailydeck.Editor.desktop"
    echo "Removed the menu entries of the development version."
    exit 0
fi

echo "==> venv in $ROOT/.venv"
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q -e "$ROOT[dev]"

echo "==> menu entries (pointing to this source tree)"
mkdir -p "$APPS_DIR"
for kind in tray editor; do
    if [[ $kind == tray ]]; then file=io.github.thnow.dailydeck.desktop; arg=--tray; name="Daily Deck (dev)"
    else file=io.github.thnow.dailydeck.Editor.desktop; arg=--gui; name="Daily Deck Profile (dev)"; fi
    sed -e "s|^Exec=.*|Exec=\"$ROOT/.venv/bin/dailydeck\" $arg|" -e "s|^Name=.*|Name=$name|" \
        -e "/^Name\[de\]=/d" -e "s|^Icon=.*|Icon=$ROOT/dailydeck/data/io.github.thnow.dailydeck.svg|" \
        "$ROOT/data/linux/$file" > "$APPS_DIR/$file"
done

echo
echo "Start: $ROOT/.venv/bin/dailydeck --tray   (sets up its GNOME extension on start)"
echo "No access to the device? Once: sudo cp $ROOT/data/linux/60-dailydeck.rules /etc/udev/rules.d/ \\"
echo "    && sudo udevadm control --reload && sudo udevadm trigger"
