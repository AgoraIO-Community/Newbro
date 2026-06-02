#!/usr/bin/env bash
# Build Newbro Executor.app (menu-bar only) from the Swift package.
# The bundle is repo-independent: it resolves `newbro` at runtime.
#
# Env overrides:
#   NEWBRO_APP_VERSION  version stamped into Info.plist (default: 1.0)
#   NEWBRO_APP_ARCH     target arch for swift build: arm64 | x86_64
#                       (default: empty = native build)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/dist/Newbro Executor.app"
BIN_NAME="NewbroExecutor"
VERSION="${NEWBRO_APP_VERSION:-1.0}"
ARCH="${NEWBRO_APP_ARCH:-}"

ARCH_ARGS=()
if [[ -n "$ARCH" ]]; then
  ARCH_ARGS=(--arch "$ARCH")
fi

echo "[package-app] building release binary (version=$VERSION arch=${ARCH:-native})"
# ${ARCH_ARGS[@]+...} keeps this safe under bash 3.2 + set -u when the array is empty.
swift build -c release --package-path "$HERE" ${ARCH_ARGS[@]+"${ARCH_ARGS[@]}"}
BIN_PATH="$(swift build -c release --package-path "$HERE" ${ARCH_ARGS[@]+"${ARCH_ARGS[@]}"} --show-bin-path)/$BIN_NAME"

echo "[package-app] assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN_PATH" "$APP/Contents/MacOS/$BIN_NAME"

# Unquoted heredoc delimiter so ${VERSION} expands. The body contains no other
# shell metacharacters ($, backtick, backslash), so this is safe.
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Newbro Executor</string>
  <key>CFBundleDisplayName</key><string>Newbro Executor</string>
  <key>CFBundleIdentifier</key><string>com.newbro.executor-ui</string>
  <key>CFBundleExecutable</key><string>NewbroExecutor</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

echo "[package-app] done: $APP"
