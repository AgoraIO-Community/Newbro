import Foundation
import UserNotifications

@MainActor
protocol AppNotifying {
    func notify(title: String, body: String)
}

@MainActor
final class MacAppNotifier: AppNotifying {
    private let center: UNUserNotificationCenter

    init(center: UNUserNotificationCenter = .current()) {
        self.center = center
        center.requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    func notify(title: String, body: String) {
        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        let request = UNNotificationRequest(
            identifier: "newbro-profile-\(UUID().uuidString)",
            content: content,
            trigger: nil)
        center.add(request)
    }
}
