import Foundation
import FlowlineCore

/// On-device storage: ~/Library/Application Support/Flowline/
///   days/YYYY-MM-DD.jsonl   raw Events, deleted once the day's record is approved
///   history/YYYY-MM-DD.json tool-pattern signatures for repeat detection (no titles)
///   records/<id>.json       approved records (stay on the device even after Withdraw)
final class EventStore {
    let root: URL
    private var handle: FileHandle?
    private var handleDay: String?
    private let enc = JSONEncoder()

    init() {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        root = base.appendingPathComponent("Flowline", isDirectory: true)
        for sub in ["days", "history", "records"] {
            try? FileManager.default.createDirectory(at: root.appendingPathComponent(sub), withIntermediateDirectories: true)
        }
    }

    func dayURL(_ day: String) -> URL { root.appendingPathComponent("days/\(day).jsonl") }

    func append(_ e: Event, day: String) {
        if handleDay != day {
            try? handle?.close()
            let url = dayURL(day)
            if !FileManager.default.fileExists(atPath: url.path) { FileManager.default.createFile(atPath: url.path, contents: nil) }
            handle = try? FileHandle(forWritingTo: url)
            try? handle?.seekToEnd()
            handleDay = day
        }
        guard let data = try? enc.encode(e) else { return }
        handle?.write(data)
        handle?.write(Data("\n".utf8))
    }

    func events(day: String) -> [Event] {
        guard let text = try? String(contentsOf: dayURL(day), encoding: .utf8) else { return [] }
        let dec = JSONDecoder()
        return text.split(separator: "\n").compactMap { try? dec.decode(Event.self, from: Data($0.utf8)) }
    }

    func deleteDay(_ day: String) {
        if handleDay == day { try? handle?.close(); handle = nil; handleDay = nil }
        try? FileManager.default.removeItem(at: dayURL(day))
    }

    func history() -> [StepHistory] {
        let dir = root.appendingPathComponent("history")
        let files = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
        return files.compactMap { try? JSONDecoder().decode(StepHistory.self, from: Data(contentsOf: $0)) }
    }

    func saveHistory(_ h: StepHistory) {
        let url = root.appendingPathComponent("history/\(h.date).json")
        try? (try? enc.encode(h))?.write(to: url, options: .atomic)
    }

    func saveRecord(_ r: Record) {
        let e = JSONEncoder(); e.outputFormatting = [.prettyPrinted, .sortedKeys]
        try? (try? e.encode(r))?.write(to: root.appendingPathComponent("records/\(r.id).json"), options: .atomic)
    }
}
