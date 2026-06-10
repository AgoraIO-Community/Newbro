import XCTest
@testable import NewbroExecutorCore

final class ProfileFamilySelectionTests: XCTestCase {
    func testInitialFamilyIsNilForNewProfileAndValidatesExisting() {
        XCTAssertNil(initialPickerFamily(for: nil))
        XCTAssertEqual(initialPickerFamily(for: ["hermes"]), "hermes")
        XCTAssertNil(initialPickerFamily(for: []))
        XCTAssertNil(initialPickerFamily(for: ["bogus"]))
    }
}
