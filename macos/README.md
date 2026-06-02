# Newbro Executor (macOS, SwiftUI)

Native menu-bar app that supervises `newbro executor run` node profiles.

## Build & run

```bash
swift test --package-path macos          # run the Core unit tests
./macos/package-app.sh                    # build dist/Newbro Executor.app
open "macos/dist/Newbro Executor.app"     # launch (menu-bar only, no Dock icon)
```

The app resolves the `newbro` CLI at runtime (override → `~/.local/bin/newbro`
→ login-shell `command -v newbro`). If `newbro` is missing, the menu shows
"Node runtime not found" with an "Install runtime…" action that runs the public
`install-newbro-cli.sh`. Per-executor binaries (codex/acpx) still need a one-time
`newbro executor setup`.

Profiles are stored in `~/.newbro/menubar.json`; logs in
`~/.newbro/logs/executor-ui-<id>.log`.

## Releases

Pushing a `v*` tag runs `.github/workflows/release.yml`, which builds the app
for both architectures and publishes two unsigned DMGs to a GitHub Release:

- `NewbroExecutor-<version>-arm64.dmg` — Apple Silicon (M-series)
- `NewbroExecutor-<version>-x86_64.dmg` — Intel

The app is unsigned, so on first launch right-click it in `/Applications` and
choose **Open** (or run
`xattr -dr com.apple.quarantine "/Applications/Newbro Executor.app"`).
