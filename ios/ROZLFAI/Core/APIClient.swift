import Foundation

enum APIError: LocalizedError {
    case invalidURL
    case server(String)
    case transport(String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid server address"
        case .server(let message): return message
        case .transport(let message): return message
        case .decoding(let message): return message
        }
    }
}

struct APIClient {
    let baseURL: URL
    private let session: URLSession

    init(baseURL: URL) {
        self.baseURL = baseURL
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 25
        config.timeoutIntervalForResource = 40
        config.waitsForConnectivity = false
        session = URLSession(configuration: config)
    }

    private func request(path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> Data {
        guard let url = URL(string: path, relativeTo: baseURL) else { throw APIError.invalidURL }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                throw APIError.transport("No HTTP response from server")
            }
            guard (200..<300).contains(http.statusCode) else {
                let serverError = try? JSONDecoder().decode(ServerError.self, from: data)
                let message = serverError?.message ?? serverError?.detail ?? serverError?.error
                throw APIError.server(message ?? "Server returned HTTP \(http.statusCode)")
            }
            return data
        } catch let error as APIError {
            throw error
        } catch let error as URLError {
            throw APIError.transport(error.localizedDescription)
        } catch {
            throw APIError.transport(error.localizedDescription)
        }
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do {
            return try JSONDecoder.rozlf().decode(T.self, from: data)
        } catch {
            throw APIError.decoding("Unexpected response: \(error.localizedDescription)")
        }
    }

    func health() async throws -> AppHealth {
        try decode(try await request(path: "/api/app/health"))
    }

    func bootstrap() async throws -> Bootstrap {
        try decode(try await request(path: "/api/app/bootstrap"))
    }

    func markets() async throws -> MarketsResponse {
        try decode(try await request(path: "/api/app/markets"))
    }

    func market(_ key: String) async throws -> MarketSnapshot {
        try decode(try await request(path: "/api/app/market/\(key.lowercased())"))
    }

    func analyse(market: String, asset: String?, duration: Int?) async throws -> AnalysisResponse {
        var body: [String: Any] = ["market": market.lowercased()]
        if let asset { body["asset"] = asset }
        if let duration { body["duration"] = duration } else { body["duration"] = "auto" }
        return try decode(try await request(path: "/api/app/analyse", method: "POST", body: body))
    }

    func recommendations() async throws -> RecommendationsResponse {
        try decode(try await request(path: "/api/app/recommendations"))
    }

    func history() async throws -> HistoryResponse {
        try decode(try await request(path: "/api/app/history"))
    }

    func saveSettings(_ minimum: Double) async throws -> SettingsSaveResponse {
        try decode(try await request(path: "/api/app/settings", method: "POST", body: ["min_confidence": minimum]))
    }
}

extension URL {
    static func validateServer(_ raw: String) -> URL? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard !trimmed.isEmpty, let url = URL(string: trimmed), let scheme = url.scheme?.lowercased(),
              let host = url.host, !host.isEmpty else { return nil }
        if scheme == "https" { return url }
        if scheme == "http", host == "localhost" || host == "127.0.0.1" { return url }
        return nil
    }
}
