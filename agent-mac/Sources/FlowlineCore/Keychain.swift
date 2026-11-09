import Foundation
import Security

/// Thin generic-password keychain wrapper. Values are never logged.
public enum Keychain {
    public static let service = "co.sweetspot.flowline"

    public enum KeychainError: Error { case status(OSStatus), interactionNotAllowed }

    /// Reads without ever showing a keychain password dialog. An ad-hoc signed build gets a new code
    /// identity every build, so an item written by the previous build would otherwise prompt; callers
    /// treat `interactionNotAllowed` as "not available" and fall back.
    public static func read(_ account: String) throws -> Data? {
        SecKeychainSetUserInteractionAllowed(false)
        defer { SecKeychainSetUserInteractionAllowed(true) }
        let q: [String: Any] = [
            kSecUseAuthenticationUI as String: kSecUseAuthenticationUIFail,
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var out: CFTypeRef?
        let st = SecItemCopyMatching(q as CFDictionary, &out)
        if st == errSecItemNotFound { return nil }
        if st == errSecInteractionNotAllowed || st == errSecAuthFailed { throw KeychainError.interactionNotAllowed }
        guard st == errSecSuccess else { throw KeychainError.status(st) }
        return out as? Data
    }

    public static func write(_ account: String, _ data: Data) throws {
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecKeychainSetUserInteractionAllowed(false)
        defer { SecKeychainSetUserInteractionAllowed(true) }
        let st = SecItemCopyMatching(base as CFDictionary, nil)
        if st == errSecInteractionNotAllowed || st == errSecAuthFailed {
            // Written by another code identity: replace it rather than prompt.
            SecItemDelete(base as CFDictionary)
        }
        if st == errSecSuccess {
            let up = SecItemUpdate(base as CFDictionary, [kSecValueData as String: data] as CFDictionary)
            guard up == errSecSuccess else { throw KeychainError.status(up) }
        } else {
            var add = base
            add[kSecValueData as String] = data
            add[kSecAttrLabel as String] = "Flowline · \(account)"
            let st2 = SecItemAdd(add as CFDictionary, nil)
            guard st2 == errSecSuccess else { throw KeychainError.status(st2) }
        }
    }

    public static func delete(_ account: String) {
        let q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(q as CFDictionary)
    }

    public static func readString(_ account: String) -> String? {
        guard let d = try? read(account) else { return nil }
        return String(data: d, encoding: .utf8)
    }

    public static func writeString(_ account: String, _ s: String) throws {
        if s.isEmpty { delete(account) } else { try write(account, Data(s.utf8)) }
    }
}
