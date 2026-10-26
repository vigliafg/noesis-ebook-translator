#!/bin/bash
# Build a DMG from the PyInstaller onedir .app.
# Usage: packaging/macos/dmg.sh <app> <output.dmg> [version]
set -euo pipefail

APP="${1:?usage: dmg.sh <app> <output.dmg> [version]}"
OUT="${2:?usage: dmg.sh <app> <output.dmg> [version]}"
VERSION="${3:-0.10.0}"

if [ ! -d "$APP" ]; then
  echo "missing app bundle: $APP" >&2
  exit 1
fi

# PyInstaller signs the bundle ad-hoc on Apple Silicon. Verify it and, if the
# signature is missing, apply an ad-hoc signature (this is not notarization:
# Gatekeeper still requires the documented "Open" bypass for a downloaded app).
if ! codesign --verify --deep --strict "$APP" 2>/dev/null; then
  echo "ad-hoc signing $APP"
  codesign --force --deep --sign - "$APP"
fi
codesign --verify --deep --strict "$APP"
echo "signed (ad-hoc): $(codesign -dv "$APP" 2>&1 | head -1)"

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
# ditto preserves symlinks, extended attributes and resource forks better than cp.
ditto "$APP" "$STAGE/$(basename "$APP")"
ln -s /Applications "$STAGE/Applications"

rm -f "$OUT"
hdiutil create \
  -volname "Noesis Ebook Translator $VERSION" \
  -srcfolder "$STAGE" \
  -ov -format UDZO "$OUT"
echo "wrote $OUT"
