#!/usr/bin/env bash
# Regenerate macos/Resources/AppIcon.icns from the brand logo.
# Native tooling only (sips + swift + iconutil); run when the logo changes.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
LOGO_WEBP="$REPO/design/assets/newbro-logo.webp"
OUT="$HERE/../Resources/AppIcon.icns"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
LOGO_PNG="$WORK/logo.png"
ICONSET="$WORK/AppIcon.iconset"

echo "[make-appicon] converting logo webp -> png"
sips -s format png "$LOGO_WEBP" --out "$LOGO_PNG" >/dev/null

echo "[make-appicon] rendering iconset"
swift "$HERE/make-appicon.swift" "$LOGO_PNG" "$ICONSET"

echo "[make-appicon] building icns"
mkdir -p "$HERE/../Resources"
iconutil -c icns "$ICONSET" -o "$OUT"
echo "[make-appicon] wrote $OUT"
