import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    var controller: AppController!
    func applicationDidFinishLaunching(_ notification: Notification) {
        controller = AppController()
        AppController.shared = controller
        controller.start()
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

MainActor.assumeIsolated {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    let delegate = AppDelegate()
    app.delegate = delegate
    app.run()
}
