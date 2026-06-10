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
    @State private var family: String? = nil
    @State private var existingProfileHasNoFamily = false
    @State private var autoActivate = false

    var body: some View {
        Form {
            TextField("Label", text: $label)
            TextField("Base URL", text: $baseURL)
            TextField("Node ID", text: $nodeID)
            TextField("Token", text: $token)

            Picker("Agent client", selection: $family) {
                Text("Choose an agent client").tag(String?.none)
                ForEach(supportedExecutorFamilies, id: \.self) { f in
                    Text(f).tag(Optional(f))
                }
            }

            if existingProfileHasNoFamily && family == nil {
                Text("This profile has no valid agent client — choose one.")
                    .foregroundColor(.red)
                    .font(.caption)
            }

            Toggle("Auto-activate at login", isOn: $autoActivate)

            HStack {
                Button("Cancel") { onClose() }
                Button("Save") { save() }
                    .disabled(family == nil)
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
        family = initialPickerFamily(for: profile.enabledExecutors)
        existingProfileHasNoFamily = family == nil
        autoActivate = profile.autoActivate
    }

    private func save() {
        let executors = family.map { [$0] } ?? []
        let id = profileID ?? "profile-\(UUID().uuidString.prefix(8))"
        model.upsert(Profile(id: id, label: label, baseURL: baseURL, nodeID: nodeID,
                             token: token, enabledExecutors: executors, autoActivate: autoActivate))
        onClose()
    }
}
