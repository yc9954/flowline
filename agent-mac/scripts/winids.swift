import CoreGraphics
import Foundation
let owner = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "Flowline"
let list = CGWindowListCopyWindowInfo([.optionAll], kCGNullWindowID) as! [[String: Any]]
for w in list where (w[kCGWindowOwnerName as String] as? String) == owner {
    let id = w[kCGWindowNumber as String] as! Int
    let b = w[kCGWindowBounds as String] as! [String: Any]
    let layer = w[kCGWindowLayer as String] as? Int ?? 0
    let onscreen = (w[kCGWindowIsOnscreen as String] as? Bool) ?? false
    print("\(id) layer=\(layer) onscreen=\(onscreen) \(b["Width"]!)x\(b["Height"]!) @\(b["X"]!),\(b["Y"]!)")
}
