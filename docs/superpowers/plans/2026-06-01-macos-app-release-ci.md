# macOS App Release in CI on Tag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a `v*` tag is pushed, CI publishes the `newbro` executor to PyPI (unchanged) *and* builds the macOS menu-bar app as two unsigned per-arch DMGs (arm64 + x86_64) attached to a published GitHub Release.

**Architecture:** Rename the existing `publish-pypi.yml` workflow to `release.yml`, keep the PyPI `publish` job as-is, and add a parallel `macos` job on `macos-latest`. The `macos` job runs the Swift Core tests, builds the app twice (once per architecture) via a version/arch-parameterized `macos/package-app.sh`, packages each into a `.dmg` with `create-dmg`, and uploads both to a GitHub Release via `softprops/action-gh-release`.

**Tech Stack:** GitHub Actions, Swift Package Manager (`swift build`/`swift test`), Bash, Homebrew `create-dmg`, `softprops/action-gh-release@v2`, `pypa/gh-action-pypi-publish`.

**Reference spec:** `docs/superpowers/specs/2026-06-01-macos-app-release-ci-design.md`

---

## File Structure

- **Modify** `macos/package-app.sh` — add `NEWBRO_APP_VERSION` (stamp into `Info.plist`) and `NEWBRO_APP_ARCH` (pass `--arch` to `swift build`) env overrides. Stays the single source of truth for assembling the bundle.
- **Rename + rewrite** `.github/workflows/publish-pypi.yml` → `.github/workflows/release.yml` — per-job permissions; unchanged `publish` job plus new `macos` job.
- **Modify** `macos/README.md` — add a short "Releases" note pointing users at the per-arch DMGs and the unsigned-app first-launch instructions.

No new source modules; this is build/release infrastructure.

> **Note on TDD:** This is shell/CI infrastructure, not application logic, so there are no unit tests to fail-first. Each task instead has an explicit **local verification** that runs the real commands on this macOS machine (which has Swift 6.3, arm64) and asserts on observable output. Run them exactly as written.

---

### Task 1: Parameterize `macos/package-app.sh` by version and architecture

**Files:**
- Modify: `macos/package-app.sh`

- [ ] **Step 1: Rewrite the script to read version + arch env overrides**

Replace the **entire** contents of `macos/package-app.sh` with:

```bash
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
```

- [ ] **Step 2: Verify the version is stamped into Info.plist**

Run:
```bash
NEWBRO_APP_VERSION=9.9.9 ./macos/package-app.sh
plutil -p "macos/dist/Newbro Executor.app/Contents/Info.plist" | grep -E 'CFBundle(Short)?Version'
```
Expected: both `CFBundleVersion` and `CFBundleShortVersionString` show `9.9.9`.

- [ ] **Step 3: Verify native build still defaults to 1.0 and the native arch**

Run:
```bash
./macos/package-app.sh
plutil -p "macos/dist/Newbro Executor.app/Contents/Info.plist" | grep CFBundleShortVersionString
lipo -archs "macos/dist/Newbro Executor.app/Contents/MacOS/NewbroExecutor"
```
Expected: version shows `1.0`; arch shows `arm64` (this machine is Apple Silicon).

- [ ] **Step 4: Verify cross-compiling the x86_64 slice works**

Run:
```bash
NEWBRO_APP_ARCH=x86_64 ./macos/package-app.sh
lipo -archs "macos/dist/Newbro Executor.app/Contents/MacOS/NewbroExecutor"
```
Expected: arch shows `x86_64`. (If `swift build --arch x86_64` errors with a missing SDK slice, stop and report — the CI design depends on this cross-build.)

- [ ] **Step 5: Commit**

```bash
git add macos/package-app.sh
git commit -m "build(macos): parameterize package-app.sh by version and arch

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Rename the workflow and add the `macos` release job

**Files:**
- Rename: `.github/workflows/publish-pypi.yml` → `.github/workflows/release.yml`
- Rewrite: `.github/workflows/release.yml`

- [ ] **Step 1: Rename the workflow file (preserve history)**

Run:
```bash
git mv .github/workflows/publish-pypi.yml .github/workflows/release.yml
```

- [ ] **Step 2: Replace the workflow contents**

Replace the **entire** contents of `.github/workflows/release.yml` with:

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

concurrency:
  group: release-${{ github.ref }}
  cancel-in-progress: false

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install release tooling
        run: python -m pip install '.[release]'

      - name: Derive release version from tag
        env:
          GITHUB_REF_NAME: ${{ github.ref_name }}
        run: |
          case "$GITHUB_REF_NAME" in
            v?*)
              echo "RELEASE_VERSION=${GITHUB_REF_NAME#v}" >> "$GITHUB_ENV"
              ;;
            *)
              echo "error: expected a tag like v1.2.3, got $GITHUB_REF_NAME" >&2
              exit 1
              ;;
          esac

      - name: Build and check distributions
        run: ./scripts/publish_pypi.sh --dry-run --yes --dist-dir dist --version "$RELEASE_VERSION"

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1

  macos:
    runs-on: macos-latest
    permissions:
      contents: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Run Core unit tests
        run: swift test --package-path macos

      - name: Derive release version from tag
        env:
          GITHUB_REF_NAME: ${{ github.ref_name }}
        run: |
          case "$GITHUB_REF_NAME" in
            v?*)
              echo "RELEASE_VERSION=${GITHUB_REF_NAME#v}" >> "$GITHUB_ENV"
              ;;
            *)
              echo "error: expected a tag like v1.2.3, got $GITHUB_REF_NAME" >&2
              exit 1
              ;;
          esac

      - name: Install create-dmg
        run: brew install create-dmg

      - name: Build DMGs (arm64 + x86_64)
        run: |
          set -euo pipefail
          export NEWBRO_APP_VERSION="$RELEASE_VERSION"
          mkdir -p macos/release
          for ARCH in arm64 x86_64; do
            echo "::group::build $ARCH"
            NEWBRO_APP_ARCH="$ARCH" ./macos/package-app.sh
            STAGE="$(mktemp -d)"
            cp -R "macos/dist/Newbro Executor.app" "$STAGE/"
            DMG="macos/release/NewbroExecutor-${NEWBRO_APP_VERSION}-${ARCH}.dmg"
            rm -f "$DMG"
            create-dmg \
              --volname "Newbro Executor ${NEWBRO_APP_VERSION}" \
              --window-size 540 380 \
              --icon-size 128 \
              --icon "Newbro Executor.app" 140 190 \
              --app-drop-link 400 190 \
              --no-internet-enable \
              "$DMG" \
              "$STAGE"
            rm -rf "$STAGE"
            echo "::endgroup::"
          done
          ls -la macos/release

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: macos/release/*.dmg
          fail_on_unmatched_files: true
          body: |
            ## Newbro Executor (macOS)

            Unsigned menu-bar app. On first launch, right-click the app in
            `/Applications` and choose **Open** (or run
            `xattr -dr com.apple.quarantine "/Applications/Newbro Executor.app"`).

            **Downloads**
            - Apple Silicon (M-series): `NewbroExecutor-<version>-arm64.dmg`
            - Intel: `NewbroExecutor-<version>-x86_64.dmg`
```

- [ ] **Step 3: Verify the workflow is valid YAML with both jobs and correct per-job permissions**

Run:
```bash
python3 - <<'PY'
import yaml
d = yaml.safe_load(open(".github/workflows/release.yml"))
jobs = d["jobs"]
assert set(jobs) == {"publish", "macos"}, jobs.keys()
assert jobs["publish"]["permissions"] == {"contents": "read", "id-token": "write"}
assert jobs["macos"]["permissions"] == {"contents": "write"}
assert jobs["macos"]["runs-on"] == "macos-latest"
assert d[True] == {"push": {"tags": ["v*"]}}  # 'on:' parses as bool True in YAML
print("workflow OK:", list(jobs))
PY
```
Expected: prints `workflow OK: ['publish', 'macos']` with no assertion error.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: release macOS DMGs alongside PyPI on tag

Rename publish-pypi.yml to release.yml; add a macos job that builds
arm64 + x86_64 DMGs and publishes them to a GitHub Release.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Local end-to-end dry run of the DMG build loop

This validates the riskiest part of Task 2 — the exact `create-dmg` invocation and per-arch DMG naming — on this machine before relying on CI. No code change; it produces throwaway artifacts under `macos/release/` (already covered by `macos/.gitignore`'s `dist/`? No — add nothing; just clean up).

**Files:** none (verification only)

- [ ] **Step 1: Install create-dmg if missing**

Run:
```bash
command -v create-dmg >/dev/null || brew install create-dmg
```
Expected: `create-dmg` is available afterward.

- [ ] **Step 2: Run the same loop the CI job runs, with a fake version**

Run:
```bash
set -euo pipefail
export NEWBRO_APP_VERSION="0.0.0-local"
mkdir -p macos/release
for ARCH in arm64 x86_64; do
  NEWBRO_APP_ARCH="$ARCH" ./macos/package-app.sh
  STAGE="$(mktemp -d)"
  cp -R "macos/dist/Newbro Executor.app" "$STAGE/"
  DMG="macos/release/NewbroExecutor-${NEWBRO_APP_VERSION}-${ARCH}.dmg"
  rm -f "$DMG"
  create-dmg \
    --volname "Newbro Executor ${NEWBRO_APP_VERSION}" \
    --window-size 540 380 \
    --icon-size 128 \
    --icon "Newbro Executor.app" 140 190 \
    --app-drop-link 400 190 \
    --no-internet-enable \
    "$DMG" \
    "$STAGE"
  rm -rf "$STAGE"
done
ls -la macos/release
```
Expected: two files exist — `NewbroExecutor-0.0.0-local-arm64.dmg` and `NewbroExecutor-0.0.0-local-x86_64.dmg`. (`create-dmg` may print AppleScript window-styling warnings; a nonzero-looking warning is fine **as long as both DMG files are produced**. If a DMG is missing, stop and report.)

- [ ] **Step 3: Sanity-check a DMG mounts and contains the app**

Run:
```bash
hdiutil attach "macos/release/NewbroExecutor-0.0.0-local-arm64.dmg" -nobrowse -mountpoint /tmp/newbro-dmg-check
ls -la /tmp/newbro-dmg-check
hdiutil detach /tmp/newbro-dmg-check
```
Expected: the mount lists `Newbro Executor.app` and an `Applications` symlink.

- [ ] **Step 4: Clean up local artifacts**

Run:
```bash
rm -rf macos/release macos/dist
git status --porcelain macos/
```
Expected: no tracked changes from this task (the `macos/.gitignore` ignores `dist/`; `macos/release/` was removed). If `macos/release/` shows as untracked, confirm it is gone.

---

### Task 4: Document the macOS release in the README

**Files:**
- Modify: `macos/README.md`

- [ ] **Step 1: Append a Releases section**

Add the following to the end of `macos/README.md`:

```markdown
## Releases

Pushing a `v*` tag runs `.github/workflows/release.yml`, which builds the app
for both architectures and publishes two unsigned DMGs to a GitHub Release:

- `NewbroExecutor-<version>-arm64.dmg` — Apple Silicon (M-series)
- `NewbroExecutor-<version>-x86_64.dmg` — Intel

The app is unsigned, so on first launch right-click it in `/Applications` and
choose **Open** (or run
`xattr -dr com.apple.quarantine "/Applications/Newbro Executor.app"`).
```

- [ ] **Step 2: Verify the section was added**

Run:
```bash
grep -n "## Releases" macos/README.md
```
Expected: prints the line number of the new section.

- [ ] **Step 3: Commit**

```bash
git add macos/README.md
git commit -m "docs(macos): document tagged DMG releases

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **Do not push a test tag to validate CI.** A real `v*` tag triggers the `publish` job, which uploads to PyPI. Validate the macOS path locally via Task 3; trust the YAML check in Task 2 for the workflow shape.
- **create-dmg flakiness:** On headless CI the AppleScript window-styling step can emit warnings; `softprops/action-gh-release` only needs the `.dmg` files to exist. If CI ever fails *because* `create-dmg` returns nonzero despite producing the DMG, the minimal fix is to not abort on its exit code while still asserting the file exists — but only add that if observed, per the project's "fix root causes, no speculative fallback" rule.
- **Architecture cross-build:** `swift build --arch x86_64` on the Apple Silicon runner produces the Intel slice. Task 1 Step 4 proves this works on this toolchain before CI depends on it.
```
