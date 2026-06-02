# macOS App CLI Auto-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The macOS app checks GitHub releases for the latest version, surfaces "update available" (periodic + menu), updates the `newbro` CLI on request by stopping the supervised nodes → upgrading → restarting them, and notifies (opens the release page) when a newer app exists.

**Architecture:** Pure, testable update logic (`SemanticVersion`, `updateStatus`, `ReleaseClient`, `UpdateService`) lives in the UI-free `NewbroExecutorCore` library; the app layer (`AppModel` accessors + `AppDelegate`) wires real dependencies and renders the menu. The CLI gains a `newbro --version`.

**Tech Stack:** Swift / Combine / Foundation (URLSession), AppKit menu, XCTest; Python `argparse` + pytest.

**Reference spec:** `docs/superpowers/specs/2026-06-01-macos-cli-auto-update-design.md`

---

## File Structure

- **Create (Core):**
  - `macos/Sources/NewbroExecutorCore/SemanticVersion.swift` — `SemanticVersion` (parse/compare).
  - `macos/Sources/NewbroExecutorCore/UpdateStatus.swift` — `UpdateStatus` + `updateStatus(...)`.
  - `macos/Sources/NewbroExecutorCore/ReleaseClient.swift` — `ReleaseInfo` + `ReleaseClient` (GitHub fetch).
  - `macos/Sources/NewbroExecutorCore/UpdateService.swift` — `UpdateService` (ObservableObject orchestrator).
- **Create (Core tests):**
  - `SemanticVersionTests.swift`, `UpdateStatusTests.swift`, `ReleaseClientTests.swift`, `UpdateServiceTests.swift` under `macos/Tests/NewbroExecutorCoreTests/`.
- **Modify (app):**
  - `macos/Sources/NewbroExecutor/AppModel.swift` — accessors: `activeProfileIDs()`, `start(profileID:)`, `stop(profileID:)`, `installedCLIVersion()`, `runInstaller(_:)`, `appVersion`.
  - `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift` — `AppDelegate` owns a wired `UpdateService` + 6h timer + launch check; adds the update section to the menu.
- **Modify (Python CLI):**
  - `src/newbro/cli/parser.py` — top-level `--version`.
  - `tests/unit/cli/test_version.py` — asserts `--version` output.

---

### Task 1: `SemanticVersion` in Core

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/SemanticVersion.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/SemanticVersionTests.swift`

- [ ] **Step 1: Write the failing test**

Create `macos/Tests/NewbroExecutorCoreTests/SemanticVersionTests.swift`:

```swift
import XCTest
@testable import NewbroExecutorCore

final class SemanticVersionTests: XCTestCase {
    func testParsesPlainAndVPrefixed() {
        XCTAssertEqual(SemanticVersion("1.2.3"), SemanticVersion("v1.2.3"))
        XCTAssertEqual(SemanticVersion("1.2.3")?.major, 1)
        XCTAssertEqual(SemanticVersion("1.2.3")?.minor, 2)
        XCTAssertEqual(SemanticVersion("1.2.3")?.patch, 3)
    }

    func testMissingComponentsDefaultToZero() {
        XCTAssertEqual(SemanticVersion("1.0"), SemanticVersion("1.0.0"))
        XCTAssertEqual(SemanticVersion("2"), SemanticVersion("2.0.0"))
    }

    func testIgnoresPreReleaseAndBuildSuffix() {
        XCTAssertEqual(SemanticVersion("1.2.3-rc1"), SemanticVersion("1.2.3"))
        XCTAssertEqual(SemanticVersion("1.2.3+build5"), SemanticVersion("1.2.3"))
    }

    func testUnparseableIsNil() {
        XCTAssertNil(SemanticVersion(""))
        XCTAssertNil(SemanticVersion("abc"))
        XCTAssertNil(SemanticVersion("1.x.0"))
    }

    func testOrdering() {
        XCTAssertTrue(SemanticVersion("1.2.3")! < SemanticVersion("1.2.4")!)
        XCTAssertTrue(SemanticVersion("1.2.3")! < SemanticVersion("1.3.0")!)
        XCTAssertTrue(SemanticVersion("1.9.9")! < SemanticVersion("2.0.0")!)
        XCTAssertFalse(SemanticVersion("1.2.3")! < SemanticVersion("1.2.3")!)
    }
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `swift test --package-path macos --filter SemanticVersionTests`
Expected: FAIL to build — "cannot find 'SemanticVersion' in scope".

- [ ] **Step 3: Write the implementation**

Create `macos/Sources/NewbroExecutorCore/SemanticVersion.swift`:

```swift
/// A minimal `X.Y.Z` version, tolerant of a leading `v` and ignoring any
/// pre-release/build suffix (`-rc1`, `+build`). Missing minor/patch default to 0.
public struct SemanticVersion: Comparable, Equatable, Sendable {
    public let major: Int
    public let minor: Int
    public let patch: Int

    public init?(_ string: String) {
        var text = string.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasPrefix("v") { text.removeFirst() }
        let core = text.split(whereSeparator: { $0 == "-" || $0 == "+" }).first.map(String.init) ?? ""
        let parts = core.split(separator: ".", omittingEmptySubsequences: false).map(String.init)
        guard let first = parts.first, let major = Int(first) else { return nil }
        let minor: Int
        if parts.count > 1 {
            guard let value = Int(parts[1]) else { return nil }
            minor = value
        } else { minor = 0 }
        let patch: Int
        if parts.count > 2 {
            guard let value = Int(parts[2]) else { return nil }
            patch = value
        } else { patch = 0 }
        self.major = major
        self.minor = minor
        self.patch = patch
    }

    public static func < (lhs: SemanticVersion, rhs: SemanticVersion) -> Bool {
        (lhs.major, lhs.minor, lhs.patch) < (rhs.major, rhs.minor, rhs.patch)
    }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `swift test --package-path macos --filter SemanticVersionTests`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/SemanticVersion.swift macos/Tests/NewbroExecutorCoreTests/SemanticVersionTests.swift
git commit -m "feat(macos): SemanticVersion parse/compare in Core

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `UpdateStatus` + `updateStatus(...)` in Core

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/UpdateStatus.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/UpdateStatusTests.swift`

- [ ] **Step 1: Write the failing test**

Create `macos/Tests/NewbroExecutorCoreTests/UpdateStatusTests.swift`:

```swift
import XCTest
@testable import NewbroExecutorCore

final class UpdateStatusTests: XCTestCase {
    func testCLIBehind() {
        let s = updateStatus(installedCLI: "0.1.0", installedApp: "0.2.0", latestTag: "v0.2.0")
        XCTAssertEqual(s.cliUpdate, "v0.2.0")
        XCTAssertNil(s.appUpdate)
    }

    func testAppBehind() {
        let s = updateStatus(installedCLI: "0.2.0", installedApp: "0.1.0", latestTag: "v0.2.0")
        XCTAssertNil(s.cliUpdate)
        XCTAssertEqual(s.appUpdate, "v0.2.0")
    }

    func testBothCurrent() {
        let s = updateStatus(installedCLI: "0.2.0", installedApp: "0.2.0", latestTag: "v0.2.0")
        XCTAssertNil(s.cliUpdate)
        XCTAssertNil(s.appUpdate)
    }

    func testDevDefaultAppVersionSuppressed() {
        let s = updateStatus(installedCLI: "0.2.0", installedApp: "1.0", latestTag: "v0.2.0")
        XCTAssertNil(s.appUpdate)
    }

    func testUnparseableInputsNoFalsePositive() {
        XCTAssertEqual(updateStatus(installedCLI: nil, installedApp: nil, latestTag: nil), UpdateStatus())
        XCTAssertEqual(updateStatus(installedCLI: "abc", installedApp: "x", latestTag: "v0.2.0"), UpdateStatus())
    }
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `swift test --package-path macos --filter UpdateStatusTests`
Expected: FAIL — "cannot find 'updateStatus'/'UpdateStatus' in scope".

- [ ] **Step 3: Write the implementation**

Create `macos/Sources/NewbroExecutorCore/UpdateStatus.swift`:

```swift
/// The result of comparing installed versions against the latest release tag.
/// Each field holds the available version string, or nil when up to date.
public struct UpdateStatus: Equatable, Sendable {
    public var cliUpdate: String?
    public var appUpdate: String?

    public init(cliUpdate: String? = nil, appUpdate: String? = nil) {
        self.cliUpdate = cliUpdate
        self.appUpdate = appUpdate
    }
}

/// Compute which components have an update available. Never reports a false
/// positive: any nil/unparseable input leaves that field nil. The app's
/// dev-default version ("1.0") is treated as "not a real release" and suppressed.
public func updateStatus(installedCLI: String?, installedApp: String?, latestTag: String?) -> UpdateStatus {
    guard let latestTag, let latest = SemanticVersion(latestTag) else { return UpdateStatus() }
    var result = UpdateStatus()
    if let installed = installedCLI.flatMap(SemanticVersion.init), latest > installed {
        result.cliUpdate = latestTag
    }
    if let appString = installedApp, appString != "1.0",
       let app = SemanticVersion(appString), latest > app {
        result.appUpdate = latestTag
    }
    return result
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `swift test --package-path macos --filter UpdateStatusTests`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/UpdateStatus.swift macos/Tests/NewbroExecutorCoreTests/UpdateStatusTests.swift
git commit -m "feat(macos): updateStatus comparison in Core

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `ReleaseClient` in Core

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/ReleaseClient.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/ReleaseClientTests.swift`

- [ ] **Step 1: Write the failing test**

Create `macos/Tests/NewbroExecutorCoreTests/ReleaseClientTests.swift`:

```swift
import XCTest
@testable import NewbroExecutorCore

final class ReleaseClientTests: XCTestCase {
    func testDecodesTagAndPageURL() async throws {
        let json = """
        {
          "tag_name": "v0.2.0",
          "html_url": "https://github.com/AgoraIO/Synopse/releases/tag/v0.2.0",
          "assets": [
            {"name": "NewbroExecutor-0.2.0-arm64.dmg",
             "browser_download_url": "https://example.com/a.dmg"}
          ]
        }
        """
        let client = ReleaseClient(fetch: { _ in Data(json.utf8) })
        let info = try await client.latest()
        XCTAssertEqual(info.tag, "v0.2.0")
        XCTAssertEqual(info.pageURL,
                       URL(string: "https://github.com/AgoraIO/Synopse/releases/tag/v0.2.0"))
    }

    func testMissingHTMLURLIsNil() async throws {
        let client = ReleaseClient(fetch: { _ in Data(#"{"tag_name":"v0.3.0"}"#.utf8) })
        let info = try await client.latest()
        XCTAssertEqual(info.tag, "v0.3.0")
        XCTAssertNil(info.pageURL)
    }
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `swift test --package-path macos --filter ReleaseClientTests`
Expected: FAIL — "cannot find 'ReleaseClient' in scope".

- [ ] **Step 3: Write the implementation**

Create `macos/Sources/NewbroExecutorCore/ReleaseClient.swift`:

```swift
import Foundation

/// The latest release info the app needs.
public struct ReleaseInfo: Equatable, Sendable {
    public let tag: String
    public let pageURL: URL?
    public init(tag: String, pageURL: URL?) {
        self.tag = tag
        self.pageURL = pageURL
    }
}

/// Reads the latest published release from the public GitHub API. The network
/// fetch is injected so decoding is unit-testable.
public struct ReleaseClient {
    public static let latestURL = URL(string:
        "https://api.github.com/repos/AgoraIO/Synopse/releases/latest")!

    private let fetch: (URLRequest) async throws -> Data

    public init(fetch: @escaping (URLRequest) async throws -> Data = ReleaseClient.defaultFetch) {
        self.fetch = fetch
    }

    public func latest() async throws -> ReleaseInfo {
        var request = URLRequest(url: ReleaseClient.latestURL)
        // GitHub requires a User-Agent; Accept pins the API version.
        request.setValue("NewbroExecutor", forHTTPHeaderField: "User-Agent")
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        let data = try await fetch(request)
        let decoded = try JSONDecoder().decode(GitHubRelease.self, from: data)
        return ReleaseInfo(tag: decoded.tag_name,
                           pageURL: decoded.html_url.flatMap { URL(string: $0) })
    }

    public static func defaultFetch(_ request: URLRequest) async throws -> Data {
        try await URLSession.shared.data(for: request).0
    }

    private struct GitHubRelease: Decodable {
        let tag_name: String
        let html_url: String?
    }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `swift test --package-path macos --filter ReleaseClientTests`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/ReleaseClient.swift macos/Tests/NewbroExecutorCoreTests/ReleaseClientTests.swift
git commit -m "feat(macos): GitHub ReleaseClient in Core

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `UpdateService` orchestrator in Core

**Files:**
- Create: `macos/Sources/NewbroExecutorCore/UpdateService.swift`
- Test: `macos/Tests/NewbroExecutorCoreTests/UpdateServiceTests.swift`

- [ ] **Step 1: Write the failing test**

Create `macos/Tests/NewbroExecutorCoreTests/UpdateServiceTests.swift`:

```swift
import XCTest
@testable import NewbroExecutorCore

@MainActor
final class UpdateServiceTests: XCTestCase {
    private func make(order: ActorRef, installerExit: Int32 = 0,
                      latest: ReleaseInfo? = ReleaseInfo(tag: "v0.2.0", pageURL: nil),
                      cli: String? = "0.1.0", app: String? = "1.0") -> UpdateService {
        UpdateService(
            fetchLatest: { latest },
            installedCLIVersion: { cli },
            appVersion: { app },
            activeProfileIDs: { ["a", "b"] },
            stopProfile: { id in order.append("stop:\(id)") },
            startProfile: { id in order.append("start:\(id)") },
            runInstaller: { completion in order.append("install"); completion(installerExit) })
    }

    func testCheckComputesStatusAndReleaseURL() async {
        let svc = make(order: ActorRef(),
                       latest: ReleaseInfo(tag: "v0.2.0",
                                           pageURL: URL(string: "https://x/rel")))
        await svc.check()
        XCTAssertEqual(svc.status.cliUpdate, "v0.2.0")
        XCTAssertNil(svc.status.appUpdate)            // app "1.0" suppressed
        XCTAssertEqual(svc.releasePageURL, URL(string: "https://x/rel"))
        XCTAssertNil(svc.lastError)
    }

    func testCheckNetworkFailureSetsError() async {
        let svc = make(order: ActorRef(), latest: nil)
        await svc.check()
        XCTAssertNotNil(svc.lastError)
    }

    func testUpdateCLIStopsUpdatesRestartsInOrder() {
        let order = ActorRef()
        let svc = make(order: order, installerExit: 0)
        svc.updateCLI()
        XCTAssertEqual(order.values, ["stop:a", "stop:b", "install", "start:a", "start:b"])
        XCTAssertFalse(svc.isUpdating)
    }

    func testUpdateCLIRestartsEvenWhenInstallerFails() {
        let order = ActorRef()
        let svc = make(order: order, installerExit: 1)
        svc.updateCLI()
        XCTAssertEqual(order.values, ["stop:a", "stop:b", "install", "start:a", "start:b"])
        XCTAssertNotNil(svc.lastError)
    }
}

/// Simple ordered recorder for the fakes.
@MainActor
final class ActorRef {
    private(set) var values: [String] = []
    func append(_ s: String) { values.append(s) }
}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `swift test --package-path macos --filter UpdateServiceTests`
Expected: FAIL — "cannot find 'UpdateService' in scope".

- [ ] **Step 3: Write the implementation**

Create `macos/Sources/NewbroExecutorCore/UpdateService.swift`:

```swift
import Foundation
import Combine

/// Drives update checks and the orchestrated CLI update (stop → upgrade →
/// restart). UI-free: all side effects (network, version probe, supervisor
/// start/stop, installer) are injected, so it is fully unit-testable and the
/// app wires the real implementations.
@MainActor
public final class UpdateService: ObservableObject {
    @Published public private(set) var status = UpdateStatus()
    @Published public private(set) var installedCLI: String?
    @Published public private(set) var isUpdating = false
    @Published public private(set) var isChecking = false
    @Published public private(set) var lastError: String?
    public private(set) var releasePageURL: URL?

    // All side-effect closures are @MainActor because they call into the
    // @MainActor AppModel; fetchLatest stays nonisolated/async (network, off main).
    private let fetchLatest: () async -> ReleaseInfo?
    private let installedCLIVersion: @MainActor () -> String?
    private let appVersion: @MainActor () -> String?
    private let activeProfileIDs: @MainActor () -> [String]
    private let stopProfile: @MainActor (String) -> Void
    private let startProfile: @MainActor (String) -> Void
    private let runInstaller: @MainActor (@escaping @MainActor (Int32) -> Void) -> Void

    public init(
        fetchLatest: @escaping () async -> ReleaseInfo?,
        installedCLIVersion: @escaping @MainActor () -> String?,
        appVersion: @escaping @MainActor () -> String?,
        activeProfileIDs: @escaping @MainActor () -> [String],
        stopProfile: @escaping @MainActor (String) -> Void,
        startProfile: @escaping @MainActor (String) -> Void,
        runInstaller: @escaping @MainActor (@escaping @MainActor (Int32) -> Void) -> Void
    ) {
        self.fetchLatest = fetchLatest
        self.installedCLIVersion = installedCLIVersion
        self.appVersion = appVersion
        self.activeProfileIDs = activeProfileIDs
        self.stopProfile = stopProfile
        self.startProfile = startProfile
        self.runInstaller = runInstaller
    }

    public func check() async {
        isChecking = true
        defer { isChecking = false }
        guard let release = await fetchLatest() else {
            lastError = "Couldn't check for updates."
            return
        }
        lastError = nil
        releasePageURL = release.pageURL
        let cli = installedCLIVersion()
        installedCLI = cli
        status = updateStatus(installedCLI: cli,
                              installedApp: appVersion(),
                              latestTag: release.tag)
    }

    public func updateCLI() {
        guard !isUpdating else { return }
        isUpdating = true
        lastError = nil
        let ids = activeProfileIDs()
        for id in ids { stopProfile(id) }
        runInstaller { [weak self] code in
            guard let self else { return }
            for id in ids { self.startProfile(id) }
            self.isUpdating = false
            if code != 0 {
                self.lastError = "Update failed (exit \(code)). Nodes restarted."
            } else {
                Task { await self.check() }
            }
        }
    }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `swift test --package-path macos --filter UpdateServiceTests`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutorCore/UpdateService.swift macos/Tests/NewbroExecutorCoreTests/UpdateServiceTests.swift
git commit -m "feat(macos): UpdateService orchestrator in Core

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `newbro --version` in the Python CLI

**Files:**
- Modify: `src/newbro/cli/parser.py`
- Test: `tests/unit/cli/test_version.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/cli/test_version.py`:

```python
from pathlib import Path

import pytest

from newbro.cli.parser import build_parser


def _parser():
    return build_parser(cli_name="newbro", env_file=Path("/tmp/.env"), start_public_port=8000)


def test_version_flag_prints_package_version(capsys):
    parser = _parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    # argparse prints "newbro <version>"; version is a non-empty dotted string.
    parts = out.split()
    assert parts[0] == "newbro"
    assert parts[1][0].isdigit()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_version.py -v`
Expected: FAIL — `--version` is unrecognized (argparse error / SystemExit code 2).

- [ ] **Step 3: Write the implementation**

In `src/newbro/cli/parser.py`, add the import near the top (after `import argparse`):

```python
from importlib import metadata
```

Then, inside `build_parser`, immediately after the parser is created and before `subparsers = parser.add_subparsers(...)`, add:

```python
    try:
        _version = metadata.version("newbro-cli")
    except metadata.PackageNotFoundError:
        _version = "0+unknown"
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_version}",
        help="Show the installed newbro-cli version and exit.",
    )
```

So the relevant section reads:

```python
    parser = argparse.ArgumentParser(prog=cli_name, description="Newbro developer CLI.")
    try:
        _version = metadata.version("newbro-cli")
    except metadata.PackageNotFoundError:
        _version = "0+unknown"
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_version}",
        help="Show the installed newbro-cli version and exit.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
```

(The `version` action calls `parser.exit()` as soon as `--version` is seen, so it short-circuits the `required=True` subcommand check.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_version.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/newbro/cli/parser.py tests/unit/cli/test_version.py
git commit -m "feat(cli): add 'newbro --version'

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `AppModel` update accessors

**Files:**
- Modify: `macos/Sources/NewbroExecutor/AppModel.swift`

- [ ] **Step 1: Add the accessors `UpdateService` needs**

In `macos/Sources/NewbroExecutor/AppModel.swift`, add these methods/properties inside the `AppModel` class (e.g. just after the existing `func conflicts()` line). Add a stored property near the other private vars for retaining the installer process:

Add near the top private vars (after `private var installProcess: NodeProcess?`):

```swift
    private var updateInstallProcess: NodeProcess?
```

Add the accessors:

```swift
    // MARK: - Update support

    /// IDs of profiles currently being supervised (active).
    func activeProfileIDs() -> [String] { Array(supervisor.activeIDs()) }

    func start(profileID id: String) {
        guard runtimeAvailable, let profile = profiles.first(where: { $0.id == id }) else { return }
        supervisor.start(profile)
    }

    func stop(profileID id: String) {
        controlQueue.async { [supervisor] in supervisor.stop(id) }
    }

    /// The installed CLI version, read by running `newbro --version` (e.g. "0.1.2").
    func installedCLIVersion() -> String? {
        guard let newbro = locator.resolveNewbro() else { return nil }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: newbro)
        process.arguments = ["--version"]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        let output = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        // Output is "newbro 0.1.2" → take the last whitespace-separated token.
        return output.split(separator: " ").last.map(String.init)
    }

    /// Run the CLI installer/upgrader; `completion` is invoked on the main actor
    /// with the process exit code.
    func runInstaller(_ completion: @escaping @MainActor (Int32) -> Void) {
        let argv = locator.installCommandArgv()
        updateInstallProcess = NodeProcess(
            argv: argv,
            onLine: { _ in },
            onExit: { [weak self] code in
                Task { @MainActor in
                    self?.updateInstallProcess = nil
                    completion(code)
                }
            })
        updateInstallProcess?.start()
    }

    /// The app's own version from the bundle (CFBundleShortVersionString).
    var appVersion: String? {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
    }
```

- [ ] **Step 2: Build**

Run: `swift build --package-path macos`
Expected: builds with no errors. (Pre-existing `Sendable` warnings are unrelated.)

- [ ] **Step 3: Commit**

```bash
git add macos/Sources/NewbroExecutor/AppModel.swift
git commit -m "feat(macos): AppModel accessors for update orchestration

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Wire `UpdateService` into the menu + periodic check

**Files:**
- Modify: `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift`

- [ ] **Step 1: Own and wire the `UpdateService` in `AppDelegate`**

In `macos/Sources/NewbroExecutor/NewbroExecutorApp.swift`, add stored properties to `AppDelegate` (next to `private var cancellable`):

```swift
    private var updates: UpdateService!
    private var updateTimer: Timer?
```

At the end of `applicationDidFinishLaunching(_:)` (after `updatePip()`), wire and start the update service:

```swift
        let releaseClient = ReleaseClient()
        let updates = UpdateService(
            fetchLatest: { try? await releaseClient.latest() },
            installedCLIVersion: { [weak model] in model?.installedCLIVersion() },
            appVersion: { [weak model] in model?.appVersion },
            activeProfileIDs: { [weak model] in model?.activeProfileIDs() ?? [] },
            stopProfile: { [weak model] id in model?.stop(profileID: id) },
            startProfile: { [weak model] id in model?.start(profileID: id) },
            runInstaller: { [weak model] completion in model?.runInstaller(completion) })
        self.updates = updates
        Task { await updates.check() }
        updateTimer = Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.updates.check() }
        }
```

- [ ] **Step 2: Add the update section to the menu**

In `build(into:)`, just before the final `menu.addItem(.separator())` + `Quit` block, insert the update section:

```swift
        menu.addItem(.separator())
        let cliLabel = updates.installedCLI.map { "newbro CLI v\($0)" } ?? "newbro CLI"
        let statusTitle: String
        if updates.isUpdating {
            statusTitle = "Updating CLI…"
        } else if let available = updates.status.cliUpdate {
            statusTitle = "Update available: \(available)"
        } else {
            statusTitle = "\(cliLabel) · up to date"
        }
        let statusRow = NSMenuItem(title: statusTitle, action: nil, keyEquivalent: "")
        statusRow.isEnabled = false
        menu.addItem(statusRow)

        if let available = updates.status.cliUpdate, !updates.isUpdating {
            menu.addItem(ActionMenuItem(title: "Update CLI to \(available)") { [weak self] in
                self?.updates.updateCLI()
            })
        }
        menu.addItem(ActionMenuItem(title: "Check for Updates…") { [weak self] in
            Task { @MainActor in await self?.updates.check() }
        })
        if let appAvailable = updates.status.appUpdate {
            menu.addItem(ActionMenuItem(title: "Download app update \(appAvailable)…") { [weak self] in
                guard let url = self?.updates.releasePageURL else { return }
                NSWorkspace.shared.open(url)
            })
        }
        if let error = updates.lastError {
            let errorRow = NSMenuItem(title: error, action: nil, keyEquivalent: "")
            errorRow.isEnabled = false
            menu.addItem(errorRow)
        }
```

- [ ] **Step 3: Build and run the full test gate**

Run:
```bash
swift build --package-path macos
swift test --package-path macos
```
Expected: builds; all tests pass (existing + the new `SemanticVersionTests`, `UpdateStatusTests`, `ReleaseClientTests`, `UpdateServiceTests`).

- [ ] **Step 4: Manual smoke check**

Run:
```bash
pkill -f "Newbro Executor" 2>/dev/null || true
./macos/package-app.sh
open "macos/dist/Newbro Executor.app"
```
Open the menu and confirm an update section appears: a status line, "Check for Updates…", and — when behind — "Update CLI to vX" / "Download app update vY…". (A real GitHub release is needed to see "available"; with none reachable it should show "couldn't check"/up-to-date without crashing.) Confirm the menu's existing items still work.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/NewbroExecutor/NewbroExecutorApp.swift
git commit -m "feat(macos): CLI update section in the menu + periodic check

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Notes for the implementer

- **Concurrency:** `UpdateService` is `@MainActor`; `runInstaller`'s completion is typed `@MainActor (Int32) -> Void`, and `AppModel.runInstaller` hops to the main actor (`Task { @MainActor in … }`) before calling it — keep both sides in sync.
- **GitHub User-Agent is required** — `ReleaseClient.defaultFetch` sets it; don't switch to `URLSession.shared.data(from:)` (no headers → 403).
- **No live menu refresh needed:** the `NSMenu` is rebuilt on each open (`menuNeedsUpdate`), so it reflects the latest `UpdateService` state then. Surfacing updates without opening the menu (icon badge) is intentionally out of scope.
- **Don't pin the CLI version:** the installer upgrades to latest PyPI, which equals the latest tag; this avoids a PyPI/GitHub publish race.
