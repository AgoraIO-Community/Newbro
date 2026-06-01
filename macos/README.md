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
