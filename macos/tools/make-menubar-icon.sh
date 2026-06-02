#!/usr/bin/env bash
# Regenerate macos/Resources/MenuBarBro.png (the menu bar template silhouette)
# from the brand logo. Native tooling only (swift). Run when the logo changes.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
LOGO_WEBP="$REPO/design/assets/newbro-logo.webp"
OUT="$HERE/../Resources/MenuBarBro.png"

mkdir -p "$HERE/../Resources"
echo "[make-menubar-icon] rendering silhouette"
swift "$HERE/make-menubar-icon.swift" "$LOGO_WEBP" "$OUT"
echo "[make-menubar-icon] wrote $OUT"
