#!/usr/bin/env bash
# Build, lint and smoke-test the .deb in a clean Ubuntu container (run as root).
# Used by scripts/build-deb.sh locally and by GitHub Actions.
#
#   build-deb.sh SRC_DIR OUT_DIR
set -euo pipefail

SRC="${1:-/src}"
OUT="${2:-/out}"
export DEBIAN_FRONTEND=noninteractive

echo "::group::Build tools"
apt-get update -qq
apt-get install -y -qq --no-install-recommends build-essential devscripts equivs lintian >/dev/null
echo "::endgroup::"

# work on a clean copy: dpkg-buildpackage writes next to the source tree
rm -rf /build && mkdir -p /build/dailydeck
tar -C "$SRC" --exclude=.venv --exclude=dist --exclude=.git --exclude='__pycache__' \
    --exclude=.pytest_cache --exclude=.ruff_cache --exclude='*.egg-info' --exclude=build -cf - . \
    | tar -C /build/dailydeck -xf -
cd /build/dailydeck

echo "::group::Build dependencies"
mk-build-deps --install --remove --tool "apt-get -y -qq --no-install-recommends" debian/control >/dev/null
echo "::endgroup::"

echo "::group::dpkg-buildpackage"
dpkg-buildpackage -us -uc -b
echo "::endgroup::"

DEB=$(ls /build/dailydeck_*_all.deb)

echo "::group::lintian"
lintian --info --display-info --fail-on error "$DEB"
echo "::endgroup::"

echo "::group::Install and smoke test"
apt-get install -y -qq --no-install-recommends "$DEB" >/dev/null
dpkg -L dailydeck | grep -E "bin/|applications|udev|gnome-shell|icons|systemd" 
dailydeck --help >/dev/null
dailydeck --dry-run "ctrl+shift+t" 2>/dev/null || true   # no /dev/uinput in containers
QT_QPA_PLATFORM=offscreen dailydeck --preview /tmp/preview
QT_QPA_PLATFORM=offscreen python3 - <<'PY'
from PySide6.QtWidgets import QApplication
app = QApplication([])
from dailydeck.config import default_config_path
from dailydeck.gui import MainWindow
from dailydeck.tray import make_tray_icon
from StreamDeck.DeviceManager import DeviceManager
from dailydeck import app as daemon_app  # streamdeck API compatibility shim
w = MainWindow(default_config_path())
print("editor ok:", w.profile_list.count(), "profiles; tray icon ok:", not make_tray_icon().isNull())
PY
echo "::endgroup::"

mkdir -p "$OUT"
cp /build/dailydeck_*.deb /build/dailydeck_*.buildinfo /build/dailydeck_*.changes "$OUT"/
if [[ -n "${HOST_UID:-}" ]]; then chown "$HOST_UID:${HOST_GID:-$HOST_UID}" "$OUT"/dailydeck_*; fi
echo "Built: $OUT/$(basename "$DEB")"
