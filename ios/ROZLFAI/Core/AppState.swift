import Foundation
import SwiftUI

enum ConnectionState {
    case notConfigured, checking, online, degraded, offline
}

@MainActor
final class AppState: ObservableObject {
    @Published var baseURLString: String = UserDefaults.standard.string(forKey: "rozlf.baseURL") ?? ""
    @Published var language: Language = Language(rawValue: UserDefaults.standard.string(forKey: "rozlf.language") ?? "ar") ?? .arabic
    @Published var connection: ConnectionState = .notConfigured
    @Published var connectionDetail: String = ""
    @Published var markets: [MarketOverview] = []
    @Published var recommendations: [Recommendation] = []
    @Published var history: [HistorySignal] = []
    @Published var stats: Stats = .empty
    @Published var minConfidence: Double = 60
    @Published var lastUpdate: String = ""
    @Published var isLoading = false
    @Published var message: String?
    @Published var selectedTab: Int = 0

    private var refreshTask: Task<Void, Never>?

    var isConfigured: Bool { URL.validateServer(baseURLString) != nil }

    var client: APIClient? {
        guard let url = URL.validateServer(baseURLString) else { return nil }
        return APIClient(baseURL: url)
    }

    func text(_ key: String) -> String { L.t(key, language) }

    func saveServer(_ raw: String) {
        baseURLString = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        UserDefaults.standard.set(baseURLString, forKey: "rozlf.baseURL")
    }

    func setLanguage(_ value: Language) {
        language = value
        UserDefaults.standard.set(value.rawValue, forKey: "rozlf.language")
    }

    func connect() async -> Bool {
        guard let client else {
            connection = .notConfigured
            connectionDetail = text("setup.invalid")
            return false
        }
        connection = .checking
        connectionDetail = ""
        do {
            let health = try await client.health()
            connection = health.engine == "ONLINE" ? .online : .degraded
            connectionDetail = health.database.map { "engine \(health.engine) · db \($0)" } ?? "engine \(health.engine)"
            await loadAll()
            startAutoRefresh()
            return true
        } catch {
            connection = .offline
            connectionDetail = error.localizedDescription
            return false
        }
    }

    func loadAll() async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }
        async let bootstrapCall = client.bootstrap()
        async let recsCall = client.recommendations()
        async let historyCall = client.history()
        do {
            let (boot, recs, hist) = try await (bootstrapCall, recsCall, historyCall)
            markets = boot.markets
            recommendations = recs.items
            history = hist.signals
            stats = hist.stats
            if let minimum = boot.settings?.minConfidence { minConfidence = minimum }
            connection = boot.connection.engine == "ONLINE" ? .online : .degraded
            connectionDetail = boot.connection.database.map { "engine \(boot.connection.engine) · db \($0)" } ?? ""
            lastUpdate = Self.pretty(boot.lastUpdate ?? recs.generatedAt)
            message = nil
        } catch {
            connection = .offline
            connectionDetail = error.localizedDescription
            message = error.localizedDescription
        }
    }

    func refreshRecommendations() async {
        guard let client else { return }
        do {
            let recs = try await client.recommendations()
            recommendations = recs.items
            lastUpdate = Self.pretty(recs.generatedAt)
            if connection == .offline { connection = .online }
            message = nil
        } catch {
            connection = .offline
            connectionDetail = error.localizedDescription
        }
    }

    func refreshHistory() async {
        guard let client else { return }
        do {
            let hist = try await client.history()
            history = hist.signals
            stats = hist.stats
        } catch {
            /* keep last verified view */
        }
    }

    func saveThreshold(_ value: Double) async {
        guard let client else { return }
        do {
            _ = try await client.saveSettings(value)
            minConfidence = value
            await refreshRecommendations()
        } catch {
            message = error.localizedDescription
        }
    }

    func startAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 30_000_000_000)
                guard !Task.isCancelled, let self else { return }
                await self.refreshRecommendations()
                await self.refreshHistory()
            }
        }
    }

    func stopAutoRefresh() {
        refreshTask?.cancel()
        refreshTask = nil
    }

    static func pretty(_ raw: String?) -> String {
        guard let raw, !raw.isEmpty else { return "—" }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var date = formatter.date(from: raw)
        if date == nil {
            formatter.formatOptions = [.withInternetDateTime]
            date = formatter.date(from: raw)
        }
        guard let date else { return raw }
        let out = DateFormatter()
        out.dateFormat = "HH:mm:ss"
        return out.string(from: date)
    }
}
