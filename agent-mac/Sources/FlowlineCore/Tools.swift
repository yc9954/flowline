import Foundation

/// App name → short tool token used in DraftStep.tools / RecordStep.tools.
public enum Tools {
    public static func token(app: String, title: String?) -> String {
        let t = title ?? ""
        if t.hasSuffix("Google Sheets") || t.contains("- Google Sheets") { return "sheets" }
        if t.hasSuffix("Google Docs") || t.contains("- Google Docs") { return "docs" }
        if t.hasSuffix("Google Slides") || t.contains("- Google Slides") { return "slides" }
        switch app {
        case "Mail", "Microsoft Outlook", "Outlook", "Spark", "Airmail", "Mimestream": return "mail"
        case "Numbers", "Microsoft Excel", "Excel", "Google Sheets": return "sheets"
        case "Keynote", "Microsoft PowerPoint", "PowerPoint", "Google Slides": return "slides"
        case "Pages", "Microsoft Word", "Word", "Google Docs", "TextEdit": return "docs"
        case "Slack", "Microsoft Teams", "Discord", "Mattermost": return "chat"
        case "Zoom", "zoom.us", "Google Meet", "Webex", "FaceTime": return "call"
        case "Safari", "Google Chrome", "Arc", "Firefox", "Brave Browser", "Microsoft Edge": return "browser"
        case "Finder": return "finder"
        case "Preview": return "preview"
        case "Notes", "Obsidian", "Notion", "Bear": return "notes"
        case "Calendar", "Fantastical": return "calendar"
        case "Xcode", "Visual Studio Code", "Code", "Cursor", "Terminal", "iTerm2", "Warp": return "code"
        case "Figma", "Sketch": return "design"
        default: return app.lowercased().replacingOccurrences(of: " ", with: "-")
        }
    }

    /// Display name for a tool token.
    public static func display(_ token: String) -> String {
        switch token {
        case "sheets": return "Sheets"
        case "docs": return "Docs"
        case "slides": return "Slides"
        case "mail": return "Mail"
        case "chat": return "Chat"
        case "call": return "Call"
        case "browser": return "Browser"
        case "finder": return "Finder"
        case "preview": return "Preview"
        case "notes": return "Notes"
        case "calendar": return "Calendar"
        case "code": return "Code"
        case "design": return "Design"
        default: return token.capitalized
        }
    }

    public static let documentTools: Set<String> = ["sheets", "docs", "slides", "notes", "code", "design"]
}
