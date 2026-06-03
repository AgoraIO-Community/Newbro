import AppKit
import SwiftUI
import NewbroExecutorCore

private enum SettingsPane: Hashable {
    case updates
    case codex
}

struct NewbroSettingsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var updates: UpdateService
    @State private var selectedPane: SettingsPane? = .updates

    var body: some View {
        HStack(spacing: 0) {
            List(selection: $selectedPane) {
                Text("Updates")
                    .tag(SettingsPane.updates)

                Section("Executors") {
                    Text("Codex")
                        .tag(SettingsPane.codex)
                }
            }
            .frame(width: 180)

            Divider()

            Group {
                switch selectedPane ?? .updates {
                case .updates:
                    UpdatesSettingsPane(model: model, updates: updates)
                case .codex:
                    CodexSettingsPane(model: model)
                }
            }
            .padding(18)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(width: 760, height: 480)
    }
}

private struct UpdatesSettingsPane: View {
    @ObservedObject var model: AppModel
    @ObservedObject var updates: UpdateService

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Updates")
                        .font(.title3.weight(.semibold))
                    Text("Newbro CLI and menu bar app versions")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(updates.isChecking ? "Checking…" : "Check for Updates…") {
                    Task { await updates.check() }
                }
                .disabled(updates.isChecking || updates.isUpdating)
            }

            let rows = updateSettingsRows(
                installedCLI: updates.installedCLI,
                installedApp: model.appVersion,
                status: updates.status)
            SettingsInfoRow(title: "Newbro CLI", detail: rows.cliVersionRow)
            SettingsInfoRow(title: "Menu bar app", detail: rows.appVersionRow)

            if updates.isUpdating {
                Text("Updating Newbro CLI…")
                    .foregroundStyle(.secondary)
            } else if let cliUpdate = rows.cliUpdateRow {
                SettingsInfoRow(title: "CLI update", detail: cliUpdate)
            }

            if let appUpdate = rows.appUpdateRow {
                SettingsInfoRow(title: "App update", detail: appUpdate)
            }

            HStack(spacing: 10) {
                if let available = updates.status.cliUpdate {
                    Button("Update CLI to \(available)") { updates.updateCLI() }
                        .disabled(updates.isUpdating)
                }
                if let appAvailable = updates.status.appUpdate {
                    Button("Download menu bar app \(appAvailable)…") {
                        guard let url = updates.releasePageURL else { return }
                        NSWorkspace.shared.open(url)
                    }
                    .disabled(updates.releasePageURL == nil)
                }
            }

            if let error = updates.lastError {
                Text(error)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
            }

            Spacer()
        }
    }
}

private struct CodexSettingsPane: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Codex")
                        .font(.title3.weight(.semibold))
                    Text(currentSummary)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
                Spacer()
                Button("Refresh") { model.refreshExecutorProbe() }
                    .disabled(model.executorSettingsBusy)
            }

            if let error = model.executorSettingsError {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(error)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                    Spacer()
                    if model.executorSettingsCanUpdateCLI {
                        Button("Update CLI…") { model.updateCLIFromExecutorSettings() }
                            .disabled(model.executorSettingsBusy)
                    }
                }
            }

            Text("Detected binaries")
                .font(.headline)

            ScrollView {
                LazyVStack(spacing: 8) {
                    ForEach(model.executorProbe?.candidates ?? []) { candidate in
                        CandidateRow(
                            candidate: candidate,
                            onUse: { model.useCodexCandidate(candidate) },
                            busy: model.executorSettingsBusy
                        )
                    }
                }
            }
        }
    }

    var currentSummary: String {
        guard let current = model.executorProbe?.current else {
            return model.executorSettingsBusy ? "Checking…" : "No Codex probe data yet."
        }
        let version = current.version ?? "version unavailable"
        let path = current.resolvedPath ?? current.command
        return current.ok ? "\(version) · \(path)" : "Unavailable · \(path)"
    }
}

private struct SettingsInfoRow: View {
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(title)
                .font(.body.weight(.medium))
                .frame(width: 120, alignment: .leading)
            Text(detail)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            Spacer()
        }
    }
}

private struct CandidateRow: View {
    let candidate: ExecutorCandidateProbe
    let onUse: () -> Void
    let busy: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Text(candidate.isCurrent ? "✓" : "")
                .frame(width: 16)
            VStack(alignment: .leading, spacing: 3) {
                Text(candidate.version ?? "Version unavailable")
                    .font(.body.weight(.medium))
                Text(candidate.path)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                if let error = candidate.error, !candidate.ok {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                }
            }
            Spacer()
            Button(candidate.isCurrent ? "Current" : "Use This Codex") { onUse() }
                .disabled(candidate.isCurrent || !candidate.ok || busy)
        }
        .padding(10)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}
