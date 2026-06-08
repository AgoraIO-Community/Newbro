import SwiftUI
import NewbroExecutorCore

struct LogView: View {
    @ObservedObject var model: AppModel
    let profileID: String?

    var body: some View {
        ScrollView {
            Text(lines.joined(separator: "\n"))
                .font(.system(.body, design: .monospaced))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(12)
        }
        .frame(width: 560, height: 360)
    }

    private var lines: [String] {
        guard let id = profileID,
              let profile = model.profiles.first(where: { $0.id == id }) else { return [] }
        let recent = model.recentLog(profile)
        return recent.isEmpty ? ["No log output yet."] : recent
    }
}
