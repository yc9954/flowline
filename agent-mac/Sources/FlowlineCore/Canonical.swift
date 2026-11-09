import Foundation
import CryptoKit

/// Canonical JSON exactly as SCHEMA.md section 12:
/// keys sorted recursively (by Unicode code point, like Python's `sort_keys`), separators `,` and `:`
/// with no spaces, UTF-8, non-ASCII unescaped, integers without `.0`.
public indirect enum JSON: Equatable {
    case null
    case bool(Bool)
    case int(Int64)
    case double(Double)
    case string(String)
    case array([JSON])
    case object([String: JSON])

    /// Build from any Foundation JSON object graph (NSNull / NSNumber / String / Array / Dictionary).
    public init(any: Any) throws {
        switch any {
        case is NSNull: self = .null
        case let s as String: self = .string(s)
        case let n as NSNumber:
            if CFGetTypeID(n) == CFBooleanGetTypeID() { self = .bool(n.boolValue) }
            else if CFNumberIsFloatType(n) {
                let d = n.doubleValue
                if d.rounded() == d, abs(d) < 1e15 { self = .int(Int64(d)) } else { self = .double(d) }
            } else { self = .int(n.int64Value) }
        case let a as [Any]: self = .array(try a.map { try JSON(any: $0) })
        case let o as [String: Any]:
            var out: [String: JSON] = [:]
            for (k, v) in o { out[k] = try JSON(any: v) }
            self = .object(out)
        default:
            throw CanonicalError.unsupported(String(describing: type(of: any)))
        }
    }

    /// Build from any Encodable by round-tripping through JSONEncoder → JSONSerialization.
    public init<T: Encodable>(encodable: T) throws {
        let enc = JSONEncoder()
        let data = try enc.encode(encodable)
        let obj = try JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed])
        try self.init(any: obj)
    }

    public func removing(keys: Set<String>) -> JSON {
        guard case .object(let o) = self else { return self }
        var c = o
        for k in keys { c.removeValue(forKey: k) }
        return .object(c)
    }

    public var canonical: String {
        var out = ""
        write(into: &out)
        return out
    }

    private func write(into out: inout String) {
        switch self {
        case .null: out += "null"
        case .bool(let b): out += b ? "true" : "false"
        case .int(let i): out += String(i)
        case .double(let d): out += JSON.pythonRepr(d)
        case .string(let s): JSON.writeString(s, into: &out)
        case .array(let a):
            out += "["
            for (i, v) in a.enumerated() { if i > 0 { out += "," }; v.write(into: &out) }
            out += "]"
        case .object(let o):
            out += "{"
            let keys = o.keys.sorted { $0.unicodeScalars.lexicographicallyPrecedes($1.unicodeScalars) }
            for (i, k) in keys.enumerated() {
                if i > 0 { out += "," }
                JSON.writeString(k, into: &out)
                out += ":"
                o[k]!.write(into: &out)
            }
            out += "}"
        }
    }

    /// Python json.dumps(ensure_ascii=False) string escaping: only `"`, `\` and control chars < 0x20.
    static func writeString(_ s: String, into out: inout String) {
        out += "\""
        for u in s.unicodeScalars {
            switch u {
            case "\"": out += "\\\""
            case "\\": out += "\\\\"
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            case "\u{08}": out += "\\b"
            case "\u{0C}": out += "\\f"
            default:
                if u.value < 0x20 { out += String(format: "\\u%04x", u.value) }
                else { out.unicodeScalars.append(u) }
            }
        }
        out += "\""
    }

    /// Shortest round-trip, formatted like Python's float repr for the common range.
    static func pythonRepr(_ d: Double) -> String {
        if d.isNaN { return "NaN" }
        if d.isInfinite { return d > 0 ? "Infinity" : "-Infinity" }
        if d == d.rounded(), abs(d) < 1e16 { return String(format: "%.1f", d) }
        var s = "\(d)" // Swift prints shortest round-trip
        // Swift: "1e-05" / "1e+16" match Python; "0.0001" vs Python "0.0001" match.
        if s.contains("e"), !s.contains("e-"), !s.contains("e+") { s = s.replacingOccurrences(of: "e", with: "e+") }
        return s
    }
}

public enum CanonicalError: Error { case unsupported(String) }

public enum Canonical {
    /// Canonical bytes of a Record without hash / pubkey / sig.
    public static func bytes(for record: Record) throws -> Data {
        let json = try JSON(encodable: record).removing(keys: ["hash", "pubkey", "sig"])
        return Data(json.canonical.utf8)
    }

    public static func hashHex(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    public static func hash(for record: Record) throws -> String {
        hashHex(try bytes(for: record))
    }

    public static func sha256Hex(_ s: String) -> String { hashHex(Data(s.utf8)) }
}
