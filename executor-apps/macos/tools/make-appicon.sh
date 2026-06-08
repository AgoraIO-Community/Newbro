#!/usr/bin/env bash
# Regenerate executor-apps/macos/Resources/AppIcon.icns from the brand logo.
# Native tooling only (sips + swift + iconutil); run when the logo changes.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
LOGO_WEBP="$REPO/prototypes/design/assets/newbro-logo.webp"
OUT="$HERE/../Resources/AppIcon.icns"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
ICONSET="$WORK/AppIcon.iconset"

echo "[make-appicon] rendering iconset"
swift "$HERE/make-appicon.swift" "$LOGO_WEBP" "$ICONSET"

echo "[make-appicon] building icns"
mkdir -p "$HERE/../Resources"
iconutil -c icns "$ICONSET" -o "$OUT"
echo "[make-appicon] wrote $OUT"
