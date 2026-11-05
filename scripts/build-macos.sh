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
#   xcrun notarytool store-credentials dailydeck --apple-id … --team-id …
# Needs: python3 (3.11+), Homebrew hidapi (brew install hidapi).
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$PWD
BUILD=$ROOT/build/macos
DIST=$ROOT/dist
ARCH=$(uname -m)
VERSION=$(python3 -c 'import re; print(re.search(r"__version__ = \"(.+)\"", open("dailydeck/__init__.py").read())[1])')
APP="$DIST/Daily Deck.app"
DMG="$DIST/DailyDeck-$VERSION-macos-$ARCH.dmg"
SIGN_IDENTITY=${SIGN_IDENTITY:-}
NOTARY_PROFILE=${NOTARY_PROFILE:-}

HIDAPI=${HIDAPI:-$(brew --prefix hidapi 2>/dev/null)/lib/libhidapi.dylib}
[[ -f $HIDAPI ]] || { echo "libhidapi.dylib not found (brew install hidapi, or set HIDAPI=…)" >&2; exit 1; }

echo "==> Daily Deck $VERSION ($ARCH)"
rm -rf "$BUILD" "$APP" "$DMG"
mkdir -p "$BUILD" "$DIST"

echo "==> build environment"
python3 -m venv "$BUILD/venv"
"$BUILD/venv/bin/pip" install -q --upgrade pip
"$BUILD/venv/bin/pip" install -q "$ROOT" "pyinstaller>=6.16"
PY=$BUILD/venv/bin/python

echo "==> libhidapi"
# own copy with a neutral install name; the real file behind Homebrew's symlink
cp "$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$HIDAPI")" "$BUILD/libhidapi.dylib"
chmod u+w "$BUILD/libhidapi.dylib"
install_name_tool -id @rpath/libhidapi.dylib "$BUILD/libhidapi.dylib" 2>/dev/null

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
    "$PY" -m PyInstaller --noconfirm --log-level WARN \
    --workpath "$BUILD/work" --distpath "$DIST" packaging/macos/dailydeck.spec
rm -rf "$DIST/Daily Deck"  # the onedir copy next to the .app

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

if [[ -n $NOTARY_PROFILE ]]; then
    [[ -n $SIGN_IDENTITY ]] || { echo "notarization needs SIGN_IDENTITY" >&2; exit 1; }
    echo "==> notarize (takes a few minutes)"
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
    xcrun stapler staple "$APP"
    spctl --assess --type open --context context:primary-signature -v "$DMG"
    spctl --assess --type execute -v "$APP"
fi

echo "==> done"
du -sh "$APP" "$DMG"
