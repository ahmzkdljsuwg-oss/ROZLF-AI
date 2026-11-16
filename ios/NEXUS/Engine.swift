import SwiftUI
import Foundation
import Security

enum NexusError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self { case .message(let text): return text }
    }
}

struct NexusMarket: Decodable, Identifiable {
    let key, label, icon: String
    let assets: [NexusAsset]
    var id: String { key }
}
struct NexusAsset: Decodable, Identifiable {
    let key, symbol, display: String
    var id: String { key }
}
struct NexusCandle: Codable, Identifiable {
    let time: String
    let open, high, low, close: Double
    var id: String { time }
}
struct NexusResult: Codable, Identifiable {
    let market, marketLabel, asset, assetKey, source, direction, mode, frame: String
    let price, confidence: Double?
    let trend, volatility, targetAt, endsAt: String?
    let generatedAt: String
    let reasons: [String]
    let candles: [NexusCandle]
    var id: String { assetKey + frame + (targetAt ?? generatedAt) + mode }
    var live: Bool { direction != "NO TRADE" && (Self.date(endsAt) ?? .distantPast) > Date() }

    static func date(_ value: String?) -> Date? {
        guard let value else { return nil }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = parser.date(from: value) { return date }
        parser.formatOptions = [.withInternetDateTime]
        return parser.date(from: value)
    }
}
struct NexusScan: Decodable { let items: [NexusResult]; let checked: Int; let unavailable: [String] }
struct NexusMarkets: Decodable { let markets: [NexusMarket] }
struct NexusHealth: Decodable { let status: String; let vision: Bool }
struct NexusImage: Decodable { let text: String }
struct NexusAPIError: Decodable { let message: String? }

enum DeviceKey {
    static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "ai.nexus.marketdata",
         kSecAttrAccount as String: "access"]
    }
    static func read() -> String {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &result) == errSecSuccess, let data = result as? Data else { return "" }
        return String(decoding: data, as: UTF8.self)
    }
    static func save(_ value: String) -> Bool {
        if value.isEmpty {
            let status = SecItemDelete(query as CFDictionary)
            return status == errSecSuccess || status == errSecItemNotFound
        }
        let data = Data(value.utf8)
        let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecSuccess { return true }
        guard status == errSecItemNotFound else { return false }
        var q = query
        q[kSecValueData as String] = data
        q[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        return SecItemAdd(q as CFDictionary, nil) == errSecSuccess
    }
}

struct NexusAPI {
    let base: URL
    let access: String

    static func address(_ raw: String) -> URL? {
        guard let c = URLComponents(string: raw.trimmingCharacters(in: .whitespacesAndNewlines)),
              c.scheme?.lowercased() == "https", let host = c.host, !host.isEmpty,
              c.user == nil, c.password == nil, c.query == nil, c.fragment == nil,
              c.path.isEmpty || c.path == "/" else { return nil }
        return c.url
    }

    func call<T: Decodable>(_ path: String, method: String = "GET", data: Data? = nil,
                            content: String = "application/json") async throws -> T {
        guard var url = URLComponents(url: base, resolvingAgainstBaseURL: false),
              let suffix = URLComponents(string: path) else { throw NexusError.message("عنوان الخادم غير صالح") }
        url.path = "/api/nexus/v1/" + suffix.path
        url.queryItems = suffix.queryItems
        guard let address = url.url else { throw NexusError.message("عنوان الخادم غير صالح") }
        var request = URLRequest(url: address, timeoutInterval: 120)
        request.httpMethod = method
        request.setValue("Bearer " + access, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue(content, forHTTPHeaderField: "Content-Type")
        request.httpBody = data
        let (payload, response) = try await URLSession.shared.data(for: request)
        guard let status = (response as? HTTPURLResponse)?.statusCode else {
            throw NexusError.message("رد الخادم غير صالح")
        }
        guard (200..<300).contains(status) else {
            let e = try? JSONDecoder().decode(NexusAPIError.self, from: payload)
            let message = status == 404 ? "العنوان لا يحتوي واجهة NEXUS لهذا الإصدار" : "رد الخادم HTTP \(status)"
            throw NexusError.message(e?.message ?? message)
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(T.self, from: payload)
    }
}

@MainActor final class NexusStore: ObservableObject {
    @Published var tab = NexusTab.home
    @Published var name = UserDefaults.standard.string(forKey: "nexus.name") ?? ""
    @Published var address = UserDefaults.standard.string(forKey: "nexus.address") ?? ""
    @Published var access = DeviceKey.read()
    @Published private(set) var connected = false
    @Published private(set) var vision = false
    @Published private(set) var markets: [NexusMarket] = []
    @Published private(set) var history: [NexusResult] = []
    @Published private(set) var scan: NexusScan?
    @Published var message: String?
    @Published var busy = false
    @Published var mode = "strong"

    init() {
        if let data = UserDefaults.standard.data(forKey: "nexus.history"),
           let entries = try? JSONDecoder().decode([NexusResult].self, from: data) { history = entries }
        if ProcessInfo.processInfo.arguments.contains("--uitest") { address = ""; access = ""; history = [] }
    }

    var api: NexusAPI? {
        guard let base = NexusAPI.address(address), !access.isEmpty else { return nil }
        return NexusAPI(base: base, access: access)
    }

    func saveProfile() {
        UserDefaults.standard.set(name, forKey: "nexus.name")
        UserDefaults.standard.set(address, forKey: "nexus.address")
        if !DeviceKey.save(access) { message = "تعذر حفظ رمز الاتصال في الجهاز" }
    }

    func connect() async {
        guard !busy else { return }
        guard let api else { message = "أدخل رابط HTTPS ورمز اتصال الخادم من الإعدادات."; return }
        busy = true
        defer { busy = false }
        do {
            let response: NexusHealth = try await api.call("health")
            guard response.status == "ok" else { throw NexusError.message("محرك التحليل غير جاهز") }
            let sources: NexusMarkets = try await api.call("markets")
            markets = sources.markets
            connected = true
            vision = response.vision
            message = nil
        } catch {
            connected = false
            vision = false
            markets = []
            message = error.localizedDescription
        }
    }

    func runScan() async {
        guard !busy else { return }
        guard let api else { message = "اضبط اتصال المحرك من الإعدادات أولاً."; return }
        busy = true
        scan = nil
        defer { busy = false }
        do {
            let result: NexusScan = try await api.call("scan?mode=\(mode)", method: "POST")
            scan = result
            connected = true
            message = nil
            record(result.items)
        } catch { message = error.localizedDescription }
    }

    func analyze(market: String, asset: String) async -> NexusResult? {
        guard let api, !busy else { return nil }
        busy = true
        defer { busy = false }
        do {
            let body = try JSONEncoder().encode(["market": market, "asset": asset, "mode": mode])
            let result: NexusResult = try await api.call("analyze", method: "POST", data: body)
            message = nil
            record([result])
            return result
        } catch { message = error.localizedDescription; return nil }
    }

    func analyzeImage(_ data: Data) async -> String? {
        guard let api, !busy else { return nil }
        guard data.count < 5 * 1024 * 1024 else { message = "الحد الأقصى للصورة 5 ميغابايت."; return nil }
        busy = true
        defer { busy = false }
        do {
            let result: NexusImage = try await api.call("image", method: "POST", data: data, content: "application/octet-stream")
            return result.text
        } catch { message = error.localizedDescription; return nil }
    }

    private func record(_ entries: [NexusResult]) {
        var seen = Set<String>()
        history = Array((entries + history).filter { seen.insert($0.id).inserted }.prefix(75))
        if let data = try? JSONEncoder().encode(history) { UserDefaults.standard.set(data, forKey: "nexus.history") }
    }
}
