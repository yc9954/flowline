// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Flowline",
    platforms: [.macOS(.v14)],
    targets: [
        .target(
            name: "FlowlineCore",
            path: "Sources/FlowlineCore"
        ),
        .executableTarget(
            name: "Flowline",
            dependencies: ["FlowlineCore"],
            path: "Sources/Flowline",
            resources: [
                .copy("Resources/demo-day.jsonl"),
                .copy("Resources/demo-week.json"),
                .copy("Resources/demo-names.json"),
            ],
            linkerSettings: [
                .linkedFramework("Carbon"),
            ]
        ),
        .testTarget(
            name: "FlowlineCoreTests",
            dependencies: ["FlowlineCore"],
            path: "Tests/FlowlineCoreTests"
        ),
    ]
)
