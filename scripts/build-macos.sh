#!/usr/bin/env bash
# Builds dist/Daily Deck.app and dist/DailyDeck-<version>-macos-<arch>.dmg.
#
#   scripts/build-macos.sh                       ad-hoc signed (runs on this Mac only)
#   SIGN_IDENTITY="Developer ID Application: …" scripts/build-macos.sh
#                                                signed with Hardened Runtime
#   SIGN_IDENTITY=… NOTARY_PROFILE=dailydeck scripts/build-macos.sh
#                                                also notarized and stapled
#
# NOTARY_PROFILE is a keychain profile created once with
#   xcrun notarytool store-credentials dailydeck --key AuthKey_….p8 --key-id … --issuer …
# Instead of a profile (CI): NOTARY_KEY=AuthKey_….p8 NOTARY_KEY_ID=… NOTARY_ISSUER=…
#
# The app runs on macOS $MACOS_MIN and newer. Everything inside has to be built for that
# version, so nothing comes from Homebrew:
#   - Python: a relocatable build targeting macOS 11 (python.org or `uv python install 3.13`);
#     set PYTHON=…, otherwise uv's 3.13 is used. Homebrew's Python targets the build machine.
#   - PySide6 pinned in packaging/macos/constraints.txt (newer wheels need macOS 15+).
#   - hidapi compiled from source below.
# A final check fails the build if any binary in the bundle needs a newer macOS.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$PWD
BUILD=$ROOT/build/macos
DIST=$ROOT/dist
ARCH=$(uname -m)
MACOS_MIN=${MACOS_MIN:-12.0}
HIDAPI_VERSION=0.15.0
HIDAPI_SHA256=5d84dec684c27b97b921d2f3b73218cb773cf4ea915caee317ac8fc73cef8136
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' dailydeck/__init__.py)
APP="$DIST/Daily Deck.app"
DMG="$DIST/DailyDeck-$VERSION-macos-$ARCH.dmg"
SIGN_IDENTITY=${SIGN_IDENTITY:-}
NOTARY_PROFILE=${NOTARY_PROFILE:-}
if [[ -n $NOTARY_PROFILE ]]; then
    NOTARY=(--keychain-profile "$NOTARY_PROFILE")
elif [[ -n ${NOTARY_KEY:-} ]]; then
    NOTARY=(--key "$NOTARY_KEY" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER")
else
    NOTARY=()
fi
export MACOSX_DEPLOYMENT_TARGET=$MACOS_MIN

if [[ -z ${PYTHON:-} ]]; then
    command -v uv >/dev/null || { echo "set PYTHON=… or install uv (brew install uv)" >&2; exit 1; }
    uv python install -q 3.13
    PYTHON=$(uv python find 3.13)
fi

minos() {  # minimum macOS a Mach-O file was built for
    otool -l "$1" 2>/dev/null | awk '
        /LC_BUILD_VERSION/ {b=1} b && /minos/ {print $2; exit}
        /LC_VERSION_MIN_MACOSX/ {v=1} v && /version/ {print $2; exit}'
}
newer() { [[ $(printf '%s\n%s\n' "$1" "$2" | sort -V | tail -1) != "$2" ]]; }  # $1 > $2

echo "==> Daily Deck $VERSION ($ARCH, macOS $MACOS_MIN+)"
py_min=$(minos "$("$PYTHON" -c 'import sys; print(sys.executable)')")
echo "    Python: $("$PYTHON" -V) (built for macOS $py_min)"
newer "$py_min" "$MACOS_MIN" && { echo "this Python needs macOS $py_min – use a portable build (see top)" >&2; exit 1; }

rm -rf "$BUILD" "$APP" "$DMG"
mkdir -p "$BUILD" "$DIST"

echo "==> build environment"
"$PYTHON" -m venv "$BUILD/venv"
PY=$BUILD/venv/bin/python
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q --only-binary=:all: -c packaging/macos/constraints.txt "$ROOT" pyinstaller

echo "==> hidapi $HIDAPI_VERSION"
curl -fsSL -o "$BUILD/hidapi.tar.gz" \
    "https://github.com/libusb/hidapi/archive/refs/tags/hidapi-$HIDAPI_VERSION.tar.gz"
echo "$HIDAPI_SHA256  $BUILD/hidapi.tar.gz" | shasum -a 256 -c --quiet
tar -xzf "$BUILD/hidapi.tar.gz" -C "$BUILD"
SRC=$BUILD/hidapi-hidapi-$HIDAPI_VERSION
clang -O2 -dynamiclib -arch "$ARCH" -mmacosx-version-min="$MACOS_MIN" \
    -I"$SRC/hidapi" -I"$SRC/mac" "$SRC/mac/hid.c" \
    -framework IOKit -framework CoreFoundation \
    -install_name @rpath/libhidapi.dylib -o "$BUILD/libhidapi.dylib"

echo "==> icon"
QT_QPA_PLATFORM=offscreen "$PY" - "$ROOT/dailydeck/data/io.github.thnow.dailydeck.svg" "$BUILD/DailyDeck.iconset" <<'EOF'
import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
app = QGuiApplication(sys.argv)
svg, out = QSvgRenderer(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
for size in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        px = size * scale
        img = QImage(px, px, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(img)
        svg.render(painter)
        painter.end()
        img.save(str(out / f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"))
EOF
iconutil -c icns "$BUILD/DailyDeck.iconset" -o "$BUILD/DailyDeck.icns"

echo "==> PyInstaller"
DAILYDECK_VERSION=$VERSION DAILYDECK_HIDAPI=$BUILD/libhidapi.dylib DAILYDECK_ICNS=$BUILD/DailyDeck.icns \
DAILYDECK_MACOS_MIN=$MACOS_MIN \
    "$PY" -m PyInstaller --noconfirm --log-level WARN \
    --workpath "$BUILD/work" --distpath "$DIST" packaging/macos/dailydeck.spec
rm -rf "$DIST/Daily Deck"  # the onedir copy next to the .app

echo "==> check: every binary runs on macOS $MACOS_MIN"
too_new=0
while IFS= read -r -d '' f; do
    file -b "$f" | grep -q 'Mach-O' || continue
    m=$(minos "$f")
    if [[ -n $m ]] && newer "$m" "$MACOS_MIN"; then
        echo "    needs macOS $m: ${f#"$APP"/}" >&2
        too_new=1
    fi
done < <(find "$APP/Contents" -type f -print0)
[[ $too_new == 0 ]] || { echo "bundle needs a newer macOS than $MACOS_MIN" >&2; exit 1; }

echo "==> sign"
if [[ -n $SIGN_IDENTITY ]]; then
    SIGN=(codesign --force --timestamp --options runtime
          --entitlements packaging/macos/entitlements.plist --sign "$SIGN_IDENTITY")
else
    echo "    (ad-hoc – set SIGN_IDENTITY for a Developer ID signature)"
    SIGN=(codesign --force --sign -)
fi
# inside out: every Mach-O file first, then the bundle
find "$APP/Contents" -type f \( -name '*.dylib' -o -name '*.so' -o -perm -u+x \) -print0 |
    while IFS= read -r -d '' f; do
        if file -b "$f" | grep -q 'Mach-O'; then "${SIGN[@]}" "$f" >/dev/null 2>&1 || "${SIGN[@]}" "$f"; fi
    done
"${SIGN[@]}" "$APP"
codesign --verify --deep --strict "$APP"

echo "==> smoke test"
"$APP/Contents/MacOS/Daily Deck" --dry-run "primary+shift+t"
"$APP/Contents/MacOS/Daily Deck" --preview "$BUILD/preview" >/dev/null
ls "$BUILD/preview" | head -3

echo "==> dmg"
STAGE=$BUILD/dmg
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "Daily Deck $VERSION" -srcfolder "$STAGE" -fs HFS+ -format UDZO -ov "$DMG"
if [[ -n $SIGN_IDENTITY ]]; then
    codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG"
fi

if [[ ${#NOTARY[@]} -gt 0 ]]; then
    [[ -n $SIGN_IDENTITY ]] || { echo "notarization needs SIGN_IDENTITY" >&2; exit 1; }
    echo "==> notarize (takes a few minutes)"
    xcrun notarytool submit "$DMG" "${NOTARY[@]}" --wait
    xcrun stapler staple "$DMG"
    xcrun stapler staple "$APP"
    spctl --assess --type open --context context:primary-signature -v "$DMG"
    spctl --assess --type execute -v "$APP"
fi

echo "==> done"
du -sh "$APP" "$DMG"
