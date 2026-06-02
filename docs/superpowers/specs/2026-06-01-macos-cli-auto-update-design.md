# macOS App: CLI Auto-Update — Design

Date: 2026-06-01
Status: Approved (design)

## Goal

Now that the macOS Newbro Executor app supervises the `newbro` CLI, give the app
correct, coordinated update logic:

- The app **checks GitHub releases** for the latest version (the release CI
  publishes a DMG + PyPI package from each `v*` tag, so the latest tag is the
  single source of truth for both the app and the CLI version).
- It **auto-updates the CLI** on user request and **surfaces "update available"**
  from a periodic background check, via the menu bar menu.
- For a newer **app** version it only **notifies** and opens the GitHub release;
  it does not replace itself (no Sparkle/self-update while the app is unsigned).
- Applying a CLI update is **orchestrated around the supervised nodes**: stop →
  update → restart, so the new code is actually in effect and no half-updated
  state is left running.

## Current state

- The CLI is a PyPI package (`newbro-cli`) installed/updated via
  `scripts/install-newbro-cli.sh`, which runs
  `uv tool install --python 3.12 --upgrade --force newbro-cli` (always latest
  PyPI). The macOS app's "Install runtime…" action already runs this script
  (`RuntimeLocator` / `AppModel.installRuntime()`).
- The executor node reports `cli_version` to the backend on registration
  (`protocol/executor_node.py`), computed from `metadata.version("newbro-cli")`
  (`observability/bootstrap.py`). There is **no `newbro --version` CLI command**
  and **no in-process self-updater**.
- The macOS app supervises `newbro executor run` profiles via `ProfileSupervisor`
  (start/stop/restart, aggregate status). Its menu is built in AppKit
  (`AppDelegate` `NSMenu`) from `AppModel`.
- Release CI (`.github/workflows/release.yml`) publishes the PyPI package and two
  DMGs to a GitHub Release on each `v*` tag. `package-app.sh` stamps the tag
  version into the app bundle's `CFBundleShortVersionString` (local dev builds
  default to `1.0`).
- Releases live on `AgoraIO/Synopse` (the `origin` remote).

## Decisions (from brainstorm)

- **Scope:** auto-update the CLI only; app updates are notify-and-open-GitHub.
- **Version source:** anonymous public GitHub Releases API,
  `https://api.github.com/repos/AgoraIO/Synopse/releases/latest`. Latest
  `tag_name` is the source of truth for both CLI and app version.
- **Apply behavior:** stop the running nodes → upgrade the CLI → restart the
  nodes that were stopped. Restart happens even if the update fails.
- **Surfacing:** periodic check (on launch + ~6h) updates a status shown in the
  menu; a menu item applies the update on demand.
- **CLI update mechanism:** reuse `install-newbro-cli.sh` (`--upgrade --force`,
  i.e. latest PyPI, which equals the latest tag), rather than pinning to the
  exact discovered tag.

## Architecture

### Core (pure, unit-tested; no UI/network)

In `NewbroExecutorCore`:

- `SemanticVersion`: parse `X.Y.Z` (tolerating a leading `v`), `Comparable`.
  Non-numeric / unparseable input → `nil`.
- `UpdateStatus` value:
  ```
  struct UpdateStatus: Equatable {
      var cliUpdate: String?  // newer CLI version available, else nil
      var appUpdate: String?  // newer app version available, else nil
  }
  ```
- `func updateStatus(installedCLI: String?, installedApp: String?, latestTag: String?) -> UpdateStatus`
  - `cliUpdate` = `latestTag` when `latest > installedCLI` (both parseable), else nil.
  - `appUpdate` = `latestTag` when `latest > installedApp`, **suppressed** when
    `installedApp` is the dev default (`1.0`) or unparseable.
  - Any nil/unparseable input yields nil for that field (never a false positive).

### App layer (`NewbroExecutor`)

- `ReleaseClient`: calls the GitHub latest-release endpoint and decodes
  `tag_name` plus the release page `html_url`. The URLSession data fetch is
  injected (`(URL) async throws -> Data`) so parsing is unit-testable against a
  canned JSON fixture. Returns `ReleaseInfo { tag: String, pageURL: URL? }`.
  (We open the release page rather than a specific DMG asset because there are
  two per-arch DMGs — the user picks the one for their Mac.)
- `CLIVersionProbe`: runs `<newbro> --version` using the path from
  `RuntimeLocator`, returns the trimmed version string (or nil on failure).
- `UpdateService: ObservableObject`:
  - Published `status: UpdateStatus` and `lastChecked: Date?`, `isUpdating: Bool`.
  - `check()` — fetch latest tag, probe CLI version, read
    `Bundle.main` `CFBundleShortVersionString`, compute and publish `UpdateStatus`.
    Called on launch, on a ~6h timer, and from the menu.
  - `updateCLI()` — the orchestrated apply:
    1. Snapshot the currently-active profile IDs (from `ProfileSupervisor`).
    2. Stop those nodes.
    3. Run `install-newbro-cli.sh` (via `NodeProcess`), capturing output.
    4. **Always** restart the snapshotted nodes (success or failure).
    5. Re-run `check()`; on installer failure, publish an error string for the menu.
  - `openAppDownload()` — opens the release page (`pageURL`) in the browser so
    the user downloads the DMG matching their Mac's architecture.
  - Holds weak references to `ProfileSupervisor`/`AppModel`; network and process
    spawns are injected so the apply-flow ordering can be tested with fakes.

### Python CLI (one small change)

- Add a top-level `newbro --version` that prints `metadata.version("newbro-cli")`
  (reuse `observability/bootstrap._app_version()` logic) and exits 0. This is how
  `CLIVersionProbe` reads the installed version.

## Menu integration

A dedicated section in the existing `AppDelegate` `NSMenu`, rebuilt on open from
`UpdateService.status`:

- Status line (disabled item): `newbro CLI vX · up to date` or
  `Update available: vX → vY`.
- `Update CLI to vY` — only when `status.cliUpdate != nil`; runs
  `UpdateService.updateCLI()`. Disabled (shows `Updating…`) while `isUpdating`.
- `Check for Updates…` — runs `UpdateService.check()`.
- `Download app update vZ…` — only when `status.appUpdate != nil`; runs
  `openAppDownload()`.

## Data flow

```
launch / 6h timer / "Check for Updates…"
   → ReleaseClient.latest()  ──► tag_name (vY), release pageURL
   → CLIVersionProbe()       ──► installed CLI (vX)
   → Bundle CFBundleShortVersionString ──► app version
   → updateStatus(...)       ──► UpdateStatus  ──► menu

"Update CLI to vY"
   → stop active nodes → install-newbro-cli.sh → restart nodes → check()
```

## Error handling & edge cases

- **Network/API failure:** keep the last `UpdateStatus`; record a quiet
  "couldn't check" state; never block the menu. Anonymous GitHub API is
  rate-limited (~60/hr) — ample; `lastChecked` throttles redundant calls.
- **Installer failure:** surface the captured error in the menu; the stopped
  nodes are restarted regardless, so the user is not left worse off.
- **CLI not installed:** out of scope here — the existing "Install runtime…"
  path handles a missing runtime; update logic applies once installed.
- **Dev-default app version (`1.0`):** suppress the app-update notice so local
  builds don't perpetually show "behind".
- **Prereleases:** `/releases/latest` excludes prereleases; release CI publishes
  non-draft, non-prerelease, so the latest stable tag is returned.

## Testing strategy

- **Core (automated):** `SemanticVersion` parse/compare (incl. leading `v`,
  unparseable); `updateStatus` across: CLI behind, app behind, both current,
  dev-default app suppressed, unparseable inputs → no false positives. Runs under
  the existing `swift test --package-path macos` gate.
- **App (automated):** `ReleaseClient` decoding from a canned GitHub JSON
  fixture (tag + release page URL); `UpdateService.updateCLI()` with a fake supervisor
  and fake installer asserting the stop → update → restart ordering, and that
  restart still happens when the installer fails.
- **Python (automated):** a test asserting `newbro --version` prints the package
  version and exits 0.
- **Manual:** trigger "Check for Updates…" and "Update CLI" against a real
  release; confirm the menu reflects status and the node restart cycle works.

## Out of scope (YAGNI)

- App self-update / Sparkle / code-signing for auto-install.
- Pinning the CLI to an exact tag (use latest PyPI via the installer).
- Backend-driven update push (the app polls GitHub directly).
- A menu bar icon badge for updates (menu text only for now).
- Rollback / downgrade.
