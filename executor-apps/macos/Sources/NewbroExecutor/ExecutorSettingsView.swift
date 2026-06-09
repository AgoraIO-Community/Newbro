import AppKit
import SwiftUI
import NewbroExecutorCore

enum SettingsPane: Hashable {
    case updates
    case codex
    case hermes
}

struct NewbroSettingsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject var updates: UpdateService

    private var selectedPane: Binding<SettingsPane?> {
        Binding(
            get: { model.selectedSettingsPane },
            set: { model.selectedSettingsPane = $0 ?? .updates }
        )
    }

    var body: some View {
        HStack(spacing: 0) {
            List(selection: selectedPane) {
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
                switch model.selectedSettingsPane {
                case .updates:
                    UpdatesSettingsPane(model: model, updates: updates)
                case .codex:
                    CodexSettingsPane(model: model)
                case .hermes:
                    CodexSettingsPane(model: model) // placeholder until HermesSettingsPane lands in Task 9
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
            let diagnosed = firstDiagnosedProfile

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
                Button("Refresh") { model.refreshExecutorProbeAndStoredDiagnoses() }
                    .disabled(model.executorSettingsBusy)
            }

            VStack(alignment: .leading, spacing: 10) {
                SettingsInfoRow(
                    title: "Newbro CLI",
                    detail: newbroRuntimeMenuTitle(
                        path: model.runtimeAvailable ? "newbro" : nil,
                        version: model.cachedCLIVersion
                    )
                )
                SettingsInfoRow(title: "Codex", detail: model.statusByFamily["codex"]?.menuTitle ?? "No Codex found. Newbro may not work properly.")

                if let diagnosed {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(diagnosed.diagnosis.title)
                            .font(.body.weight(.medium))
                            .textSelection(.enabled)
                        if let detail = diagnosed.diagnosis.detail, !detail.isEmpty {
                            Text(detail)
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                    }

                    diagnosisActionButton(
                        action: diagnosed.diagnosis.primaryAction,
                        profile: diagnosed.profile
                    )
                } else if let action = settingsLevelAction {
                    settingsActionButton(action: action)
                }

                let codexSetupBusy = model.setupBusyByFamily["codex"] ?? false
                let codexSetupLog = model.setupLogByFamily["codex"] ?? ""
                if codexSetupBusy || !codexSetupLog.isEmpty {
                    ScrollView {
                        Text(codexSetupLog.isEmpty ? "Codex setup is running…" : codexSetupLog)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 72)
                }
            }
            .padding(10)
            .background(Color(nsColor: .controlBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 8))

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
                    ForEach(model.probeByFamily["codex"]?.candidates ?? []) { candidate in
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
        guard let current = model.probeByFamily["codex"]?.current else {
            return model.executorSettingsBusy ? "Checking…" : "No Codex probe data yet."
        }
        let version = current.version ?? "version unavailable"
        let path = current.resolvedPath ?? current.command
        return current.ok ? "\(version) · \(path)" : "Unavailable · \(path)"
    }

    private var firstDiagnosedProfile: (profile: Profile, diagnosis: ProfileStartDiagnosis)? {
        for profile in model.profiles {
            if let diagnosis = model.diagnosis(for: profile) {
                return (profile, diagnosis)
            }
        }
        return nil
    }

    private var settingsLevelAction: ProfileStartDiagnosisAction? {
        if !model.runtimeAvailable {
            return .installNewbroCLI
        }
        if model.executorSettingsCanUpdateCLI {
            return .updateNewbroCLI
        }
        let codexProbe = model.probeByFamily["codex"]
        if isLoginRequired(codexProbe?.current.error) {
            return .signInCodex
        }
        if let current = codexProbe?.current, !current.ok {
            if codexProbe?.candidates.contains(where: { $0.ok && !$0.isCurrent }) == true {
                return .openCodexSettings
            }
            return .setUpCodex
        }
        if model.statusByFamily["codex"]?.isAvailable != true && !model.executorSettingsBusy {
            return .setUpCodex
        }
        return nil
    }

    @ViewBuilder
    private func diagnosisActionButton(action: ProfileStartDiagnosisAction, profile: Profile) -> some View {
        switch action {
        case .installNewbroCLI, .updateNewbroCLI:
            Button("Install/Update Newbro CLI…") { model.updateCLIFromExecutorSettings() }
                .disabled(model.executorSettingsBusy)
        case .setUpCodex:
            Button("Set Up Codex…") { model.setUpCodex(for: profile) }
                .disabled(model.executorSettingsBusy || model.setupBusyByFamily["codex"] ?? false)
        case .openCodexSettings:
            Text("Choose a Codex binary below.")
                .foregroundStyle(.secondary)
        case .rerunDiagnosis:
            Button("Run Diagnosis") { model.rerunDiagnosis(for: profile) }
                .disabled(model.executorSettingsBusy || model.setupBusyByFamily["codex"] ?? false)
        case .openProfileSettings:
            Button("Edit Profile…") { model.editProfile(profile.id) }
        case .viewLog:
            Button("View Log…") { model.viewLog(profile.id) }
        case .signInCodex:
            Text("Sign in to Codex from the Codex app or CLI, then refresh.")
                .foregroundStyle(.secondary)
        case .setUpHermes:
            Button("Set Up Hermes…") { model.setUpHermes(for: profile) }
                .disabled(model.executorSettingsBusy)
        case .signInHermes:
            Text("Run `hermes setup --portal` in a terminal, then Refresh.")
                .foregroundStyle(.secondary)
        case .none:
            EmptyView()
        }
    }

    @ViewBuilder
    private func settingsActionButton(action: ProfileStartDiagnosisAction) -> some View {
        switch action {
        case .installNewbroCLI, .updateNewbroCLI:
            Button("Install/Update Newbro CLI…") { model.updateCLIFromExecutorSettings() }
                .disabled(model.executorSettingsBusy)
        case .setUpCodex:
            Button("Set Up Codex…") { model.setUpCodex(for: nil) }
                .disabled(model.executorSettingsBusy || model.setupBusyByFamily["codex"] ?? false)
        case .openCodexSettings:
            Text("Choose a Codex binary below.")
                .foregroundStyle(.secondary)
        case .rerunDiagnosis:
            Button("Run Diagnosis") { model.refreshExecutorProbeAndStoredDiagnoses() }
                .disabled(model.executorSettingsBusy || model.setupBusyByFamily["codex"] ?? false)
        case .signInCodex:
            Text("Sign in to Codex from the Codex app or CLI, then refresh.")
                .foregroundStyle(.secondary)
        case .setUpHermes:
            Button("Set Up Hermes…") { model.setUpHermes(for: nil) }
                .disabled(model.executorSettingsBusy)
        case .signInHermes:
            Text("Run `hermes setup --portal` in a terminal, then Refresh.")
                .foregroundStyle(.secondary)
        case .openProfileSettings, .viewLog, .none:
            EmptyView()
        }
    }

    private func isLoginRequired(_ error: String?) -> Bool {
        guard let error else { return false }
        let text = error.lowercased()
        return text.contains("login")
            || text.contains("log in")
            || text.contains("sign in")
            || text.contains("signin")
            || text.contains("auth")
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
