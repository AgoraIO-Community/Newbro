import AppKit
import Foundation
import NewbroExecutorCore

@MainActor
final class ClipboardConnectMonitor {
    private let pasteboard: NSPasteboard
    private let apply: (String) throws -> Void
    private var timer: Timer?
    private var lastChangeCount: Int
    private var lastAppliedText: String?

    init(pasteboard: NSPasteboard = .general, apply: @escaping (String) throws -> Void) {
        self.pasteboard = pasteboard
        self.apply = apply
        self.lastChangeCount = pasteboard.changeCount
    }

    func start() {
        guard timer == nil else { return }
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.checkPasteboard()
            }
        }
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    private func checkPasteboard() {
        let changeCount = pasteboard.changeCount
        guard changeCount != lastChangeCount else { return }
        lastChangeCount = changeCount

        guard let text = pasteboard.string(forType: .string) else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed != lastAppliedText else { return }
        guard (try? parseConnectSettings(trimmed)) != nil else { return }

        do {
            try apply(trimmed)
            lastAppliedText = trimmed
        } catch {
            return
        }
    }
}
