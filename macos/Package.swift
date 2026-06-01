// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "NewbroExecutor",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "NewbroExecutorCore"),
        .target(
            name: "NewbroExecutor",
            dependencies: ["NewbroExecutorCore"]
        ),
        .testTarget(
            name: "NewbroExecutorCoreTests",
            dependencies: ["NewbroExecutorCore"]
        ),
    ]
)
