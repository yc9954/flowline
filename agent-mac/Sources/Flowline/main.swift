import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    var controller: AppController!
    /// `flowline://join?api=…&code=…` (CFBundleURLTypes in scripts/bundle.sh). The controller exists before
    /// `applicationDidFinishLaunching` so a launch-by-URL is kept until `start()` has run.
    override init() {
        super.init()
        controller = AppController()
        AppController.shared = controller
        NSAppleEventManager.shared().setEventHandler(self, andSelector: #selector(handleGetURL(_:with:)),
                                                     forEventClass: AEEventClass(kInternetEventClass), andEventID: AEEventID(kAEGetURL))
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        controller.start()
    }
    @objc func handleGetURL(_ event: NSAppleEventDescriptor, with reply: NSAppleEventDescriptor) {
        guard let s = event.paramDescriptor(forKeyword: AEKeyword(keyDirectObject))?.stringValue, let url = URL(string: s) else { return }
        controller.handle(url: url)
    }
    func application(_ application: NSApplication, open urls: [URL]) {
        for u in urls { controller.handle(url: u) }
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
