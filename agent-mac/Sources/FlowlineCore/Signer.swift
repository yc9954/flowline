import Foundation
import CryptoKit

/// Ed25519 device key. Generated once, kept in the keychain (SCHEMA.md §12). If the keychain refuses
/// (it can, for an ad-hoc signed build whose code identity changes every build), the key falls back to
/// a 0600 file under Application Support so a record can still be signed and verified.
public final class Signer {
    public let key: Curve25519.Signing.PrivateKey
    public let source: String

    static let account = "device-key-ed25519"

    public init(supportDir: URL) {
        let fileURL = supportDir.appendingPathComponent("device.key")
        var keychainBlocked = false
        var loaded: Curve25519.Signing.PrivateKey?
        var src = "keychain"
        do {
            if let raw = try Keychain.read(Signer.account) { loaded = try? Curve25519.Signing.PrivateKey(rawRepresentation: raw) }
        } catch {
            keychainBlocked = true // item belongs to another code identity (ad-hoc rebuild) or keychain locked
        }
        if loaded == nil, let raw = try? Data(contentsOf: fileURL),
           let k = try? Curve25519.Signing.PrivateKey(rawRepresentation: raw) {
            loaded = k; src = "file"
        }
        if loaded == nil {
            let k = Curve25519.Signing.PrivateKey()
            var saved = false
            if !keychainBlocked, (try? Keychain.write(Signer.account, k.rawRepresentation)) != nil { saved = true }
            if !saved {
                try? FileManager.default.createDirectory(at: supportDir, withIntermediateDirectories: true)
                try? k.rawRepresentation.write(to: fileURL, options: [.atomic])
                try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
                src = "file"
            }
            loaded = k
        }
        key = loaded!
        source = src
    }

    public init(key: Curve25519.Signing.PrivateKey) { self.key = key; self.source = "memory" }

    public var pubkeyBase64: String { key.publicKey.rawRepresentation.base64EncodedString() }

    /// Signature over the UTF-8 bytes of the lowercase hex hash string, base64.
    public func sign(hashHex: String) throws -> String {
        try key.signature(for: Data(hashHex.utf8)).base64EncodedString()
    }

    /// Fills hash, pubkey and sig on a record.
    public func seal(_ record: Record) throws -> Record {
        var r = record
        r.hash = ""; r.pubkey = ""; r.sig = ""
        let h = try Canonical.hash(for: r)
        r.hash = h
        r.pubkey = pubkeyBase64
        r.sig = try sign(hashHex: h)
        return r
    }

    public static func verify(_ record: Record) -> Bool {
        guard let pk = Data(base64Encoded: record.pubkey), let sg = Data(base64Encoded: record.sig),
              let pub = try? Curve25519.Signing.PublicKey(rawRepresentation: pk),
              let h = try? Canonical.hash(for: record), h == record.hash else { return false }
        return pub.isValidSignature(sg, for: Data(h.utf8))
    }
}
