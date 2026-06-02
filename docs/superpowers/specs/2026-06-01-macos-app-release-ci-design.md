# macOS App Release in CI on Tag — Design

Date: 2026-06-01
Status: Approved (design)

## Goal

When a `v*` tag is pushed, GitHub CI must release the macOS Executor app
(`Newbro Executor.app`) as a `.dmg` on a GitHub Release, *alongside* the
existing PyPI publish of the `newbro` executor CLI. One tag push releases both
the executor (to PyPI) and the Mac app (to GitHub Releases).

## Current state

- `.github/workflows/publish-pypi.yml` triggers on `push: tags: v*` and runs a
  single `publish` job on `ubuntu-latest`: it derives `RELEASE_VERSION` from the
  tag (`v1.2.3` → `1.2.3`), builds/checks the distribution via
  `scripts/publish_pypi.sh --dry-run`, then publishes to PyPI using
  `pypa/gh-action-pypi-publish` (trusted publishing, `id-token: write`).
- The macOS app lives in `macos/`: a SwiftUI menu-bar app (Swift package
  `NewbroExecutor`) built into `dist/Newbro Executor.app` by
  `macos/package-app.sh`. The app is **unsigned** (no codesign/notarization
  anywhere in the repo) and resolves the `newbro` CLI at runtime.
- `macos/package-app.sh` hardcodes `CFBundleShortVersionString` (`1.0`) and
  `CFBundleVersion` (`1`) in the generated `Info.plist`.
- No workflow currently creates a GitHub Release.

## Design

### Workflow structure

Rename `publish-pypi.yml` → `release.yml`, keeping the same trigger
(`on: push: tags: v*`). The file holds two independent jobs that run in
parallel on the tag:

- `publish` — unchanged PyPI publish (runs on `ubuntu-latest`).
- `macos` — new, builds and releases the Mac app (runs on `macos-latest`).

The jobs are independent: a PyPI failure does not block the Mac release, and
vice-versa. Only the `macos` job touches the GitHub Release, so there is no
race over Release creation.

### Permissions

Move permissions to per-job scope:

- `publish`: `id-token: write` (PyPI trusted publishing), `contents: read`.
- `macos`: `contents: write` (create/attach the GitHub Release).

### Two architectures, two DMGs

The runner is Apple Silicon, but Intel Macs must be supported too — shipped as
**two separate packages** (not a universal binary). The `macos` job builds the
app twice, once per architecture, and produces two distinctly named DMGs
attached to the same Release:

- `NewbroExecutor-<version>-arm64.dmg` (Apple Silicon)
- `NewbroExecutor-<version>-x86_64.dmg` (Intel)

Per-arch builds use `swift build -c release --arch <arch>`. The Apple Silicon
runner can cross-compile the `x86_64` slice this way.

### `macos` job steps

1. **Checkout** (`actions/checkout@v4`).
2. **Test**: `swift test --package-path macos` — gate the release on the
   `NewbroExecutorCore` unit tests passing.
3. **Derive version**: reuse the existing tag logic to set `RELEASE_VERSION`
   (`v?*` → strip leading `v`; fail on a non-`v` tag).
4. **Install `create-dmg`**: `brew install create-dmg`.
5. **Build per arch (arm64, then x86_64)**: for each arch, run
   `macos/package-app.sh` with the release version and target arch, then build
   `NewbroExecutor-<version>-<arch>.dmg` from the resulting
   `Newbro Executor.app` with a drag-to-`/Applications` layout. The app is
   unsigned / ad-hoc — no signing secrets are used.
6. **Release**: create the GitHub Release for the tag with
   `softprops/action-gh-release`, **published immediately**, uploading both
   `.dmg` assets in a single step (one Release, no race). The Release body
   includes a Gatekeeper note for the unsigned app (first launch: right-click →
   **Open**, or `xattr -dr com.apple.quarantine "<app path>"`) and tells users
   which DMG matches their chip.

### `macos/package-app.sh` change

Make the version and architecture configurable instead of hardcoded:

- Read a version from an env var (e.g. `NEWBRO_APP_VERSION`), defaulting to
  `1.0` for local builds so existing behavior is preserved.
- Substitute it into both `CFBundleShortVersionString` and `CFBundleVersion`
  in the generated `Info.plist`.
- Accept an optional target architecture (e.g. `NEWBRO_APP_ARCH` =
  `arm64` | `x86_64`); when set, pass `--arch <arch>` to `swift build` and the
  `--show-bin-path` lookup. Default (unset) keeps the current native build.

This keeps `package-app.sh` the single source of truth for assembling the
bundle; CI only passes the version and arch in.

## Decisions / rationale

- **Unsigned (ad-hoc)**: simplest path, no Apple secrets. Acceptable for an
  early/internal release; users clear quarantine on first launch.
- **`.dmg` via `create-dmg`**: chosen for drag-to-Applications UX (the reason
  for picking `.dmg`); one `brew install`. Plain `hdiutil` would be
  zero-dependency but plainer.
- **GitHub Release** as the distribution channel, **published immediately**:
  standard, downloadable from the repo's Releases page; fully automated.
- **Two per-arch DMGs (arm64 + x86_64), not a universal binary**: explicit user
  choice to ship separate packages for Apple Silicon and Intel.
- **Add a job to the existing workflow** (rename to `release.yml`): both
  executor artifacts live in one workflow run, matching "together with
  executor."
- **Independent parallel jobs**: a Mac app release does not need PyPI to
  succeed, and keeping them decoupled is simpler and more robust.

## Out of scope (YAGNI)

- Code signing and notarization; Apple Developer secrets.
- Auto-update feed (Sparkle, etc.).
- Homebrew cask / other distribution channels.
- Universal (fat) binary — superseded by shipping two separate per-arch DMGs.
