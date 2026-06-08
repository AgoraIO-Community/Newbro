import SwiftUI
import NewbroExecutorCore

struct ProfileEditView: View {
    @ObservedObject var model: AppModel
    let profileID: String?
    let onClose: () -> Void

    @State private var label = ""
    @State private var baseURL = ""
    @State private var nodeID = ""
    @State private var token = ""
    @State private var codex = false
    @State private var acpx = false
    @State private var autoActivate = false

    var body: some View {
        Form {
            TextField("Label", text: $label)
            TextField("Base URL", text: $baseURL)
            TextField("Node ID", text: $nodeID)
            TextField("Token", text: $token)
            Toggle("codex", isOn: $codex)
            Toggle("acpx", isOn: $acpx)
            Toggle("Auto-activate at login", isOn: $autoActivate)
            HStack {
                Button("Cancel") { onClose() }
                Button("Save") { save() }
            }
        }
        .padding(20)
        .frame(width: 380)
        .onAppear(perform: load)
    }

    private func load() {
        guard let id = profileID,
              let profile = model.profiles.first(where: { $0.id == id }) else { return }
        label = profile.label
        baseURL = profile.baseURL
        nodeID = profile.nodeID
        token = profile.token
        codex = profile.enabledExecutors.contains("codex")
        acpx = profile.enabledExecutors.contains("acpx")
        autoActivate = profile.autoActivate
    }

    private func save() {
        var executors: [String] = []
        if codex { executors.append("codex") }
        if acpx { executors.append("acpx") }
        let id = profileID ?? "profile-\(UUID().uuidString.prefix(8))"
        model.upsert(Profile(id: id, label: label, baseURL: baseURL, nodeID: nodeID,
                             token: token, enabledExecutors: executors, autoActivate: autoActivate))
        onClose()
    }
}
