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
`install-newbro-cli.sh`.

On launch the app probes `codex` through the login-shell PATH. If Codex is
found, the menu shows its version and the CLI can auto-write the minimal Codex
executor config on first run. If Codex is not found, the menu shows
"No Codex found. Newbro may not work properly." Use `newbro executor setup`
for custom Codex paths, ACPX, or recovery.

The update section reports separate components:

- `Newbro CLI: vX.Y.Z` is the installed `newbro` command that runs executor
  nodes.
- `Menu bar app: vA.B.C` is this macOS app bundle. Local builds stamped with
  the default bundle version show as `Menu bar app: local build (bundle v1.0)`.
- CLI and app update rows name the component that is behind.

Runtime install, CLI upgrade, and manual update checks show disabled in-progress
rows while they run. Runtime install and CLI upgrade also send macOS
notifications when they finish or fail.

Profiles are stored in `~/.newbro/menubar.json`; logs in
`~/.newbro/logs/executor-ui-<id>.log`.

## Releases

Pushing a `v*` tag runs `.github/workflows/release.yml`, which builds the app
for both architectures and publishes two unsigned DMGs to a GitHub Release:

- `NewbroExecutor-<version>-arm64.dmg` — Apple Silicon (M-series)
- `NewbroExecutor-<version>-x86_64.dmg` — Intel

The app is unsigned, so the first launch on each Mac needs a one-time approval —
see [Installing on another Mac](#installing-on-another-mac-unsigned-build) below
for the steps (they differ by macOS version; no `xattr` needed).

## Installing on another Mac (unsigned build)

The app is ad-hoc signed but not notarized (no paid Apple Developer account), so
the **first** launch on a Mac other than the build machine needs a one-time
approval. No terminal or `xattr` is required.

1. **Build and share (you):**
   ```bash
   ./macos/package-app.sh
   ```
   Then compress `macos/dist/Newbro Executor.app` (Finder → Compress, or
   `ditto -c -k --keepParent "macos/dist/Newbro Executor.app" NewbroExecutor.zip`)
   and send it (AirDrop, download, etc.).

2. **Recipient:** unzip it, and optionally drag `Newbro Executor.app` to
   `/Applications`.

3. **First launch — one-time approval.** Double-click the app. If macOS blocks it
   ("can't verify the developer"):
   - **macOS 14 (Sonoma) or earlier:** Control-click (right-click) the app icon →
     **Open** → **Open** in the dialog.
   - **macOS 15 (Sequoia) or later:** open **System Settings → Privacy &
     Security**, scroll to **Security**, find the message
     "*Newbro Executor* was blocked…" → click **Open Anyway** → confirm and
     authenticate (Touch ID / password).

4. After approving once, the app opens normally every time — no terminal, no
   `xattr`.

This step exists only because the app isn't notarized; it is a one-time,
per-machine action.
