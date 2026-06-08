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
