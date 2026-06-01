#!/usr/bin/env bash
# Build Newbro Executor.app (menu-bar only) from the Swift package.
# The bundle is repo-independent: it resolves `newbro` at runtime.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/dist/Newbro Executor.app"
BIN_NAME="NewbroExecutor"

echo "[package-app] building release binary"
swift build -c release --package-path "$HERE"
BIN_PATH="$(swift build -c release --package-path "$HERE" --show-bin-path)/$BIN_NAME"

echo "[package-app] assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN_PATH" "$APP/Contents/MacOS/$BIN_NAME"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Newbro Executor</string>
  <key>CFBundleDisplayName</key><string>Newbro Executor</string>
  <key>CFBundleIdentifier</key><string>com.newbro.executor-ui</string>
  <key>CFBundleExecutable</key><string>NewbroExecutor</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

echo "[package-app] done: $APP"
