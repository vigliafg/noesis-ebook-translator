#!/bin/bash
# Assemble an AppDir from the PyInstaller onedir and build the AppImage.
# Usage: packaging/linux/build-appimage.sh <version> <output.AppImage> [appimagetool]
set -euo pipefail

VERSION="${1:?usage: build-appimage.sh <version> <output.AppImage> [tool]}"
OUT="${2:?usage: build-appimage.sh <version> <output.AppImage> [tool]}"
TOOL="${3:-${APPIMAGETOOL:-/tmp/appimagetool}}"

APPDIR="build/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/256x256/apps" \
         "$APPDIR/usr/share/metainfo" \
         "$APPDIR/usr/share/doc/noesis-ebook-translator"

# The PyInstaller onedir must stay together: the executable finds _internal/
# (Qt plugins, WebEngine helper and resources) next to itself.
cp -a dist/NoesisEbookTranslator/. "$APPDIR/usr/bin/"
chmod +x "$APPDIR/usr/bin/NoesisEbookTranslator"
# The desktop entry uses the lowercase command name (same as deb/rpm).
ln -sf NoesisEbookTranslator "$APPDIR/usr/bin/noesis-ebook-translator"

cp packaging/linux/noesis-ebook-translator.desktop "$APPDIR/"
cp packaging/linux/noesis-ebook-translator.desktop \
   "$APPDIR/usr/share/applications/"
cp assets/linux/hicolor/256x256/apps/noesis-ebook-translator.png "$APPDIR/"
cp assets/linux/hicolor/256x256/apps/noesis-ebook-translator.png \
   "$APPDIR/usr/share/icons/hicolor/256x256/apps/"
cp packaging/linux/noesis-ebook-translator.metainfo.xml \
   "$APPDIR/usr/share/metainfo/"
cp LICENSE THIRD_PARTY_NOTICES.md \
   "$APPDIR/usr/share/doc/noesis-ebook-translator/"
cp -a LICENSES "$APPDIR/usr/share/doc/noesis-ebook-translator/" 2>/dev/null || true
cp packaging/linux/AppRun "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

# No sandbox override here: Chromium runs with its sandbox. Hosts without
# unprivileged user namespaces can opt out explicitly (see README).
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "$OUT"
echo "wrote $OUT"
