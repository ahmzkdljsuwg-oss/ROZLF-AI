import Foundation

struct Bootstrap: Decodable {
    let brand: Brand
    let connection: ConnectionInfo
    let markets: [MarketOverview]
    let availableMarkets: Int
    let totalMarkets: Int
    let lastUpdate: String?
    let settings: AppSettings?
    let durations: [Int]?
    let stats: Stats?
}

struct Brand: Decodable {
    let name: String
    let tagline: String
}

struct ConnectionInfo: Decodable {
    let engine: String
    let database: String?
    let aiConfigured: Bool?
    let checkedAt: String?
}

struct AppSettings: Decodable {
    let minConfidence: Double?
    let markets: [String]?
}

struct MarketOverview: Decodable, Identifiable {
    let key: String
    let label: String
    let icon: String
    let status: String
    let dataState: String?
    let source: String?
    let lastTime: String?
    let error: String?
    let assets: Int?
    let assetPreview: String?

    var id: String { key }
    var isLive: Bool { status == "LIVE" }
}

struct MarketsResponse: Decodable {
    let markets: [MarketOverview]
    let availableMarkets: Int
    let totalMarkets: Int
    let lastUpdate: String?
}

struct MarketSnapshot: Decodable {
    let key: String
    let label: String
    let icon: String?
    let available: Bool
    let assets: [SnapAsset]
    let source: String?
    let status: String
    let price: Double?
    let priceDisplay: String?
    let candles: [ChartCandle]
    let durations: [Int]
    let error: String?
    let lastTime: String?
    let timeframe: String?
}

struct SnapAsset: Decodable, Identifiable {
    let key: String
    let display: String
    let symbol: String
    var id: String { key }
}

struct ChartCandle: Decodable, Identifiable {
    let t: String
    let o: Double
    let h: Double
    let l: Double
    let c: Double
    var id: String { t }
}

struct AnalysisResponse: Decodable {
    let market: String?
    let marketLabel: String?
    let assetKey: String?
    let asset: String?
    let direction: String?
    let signalAr: String?
    let confidence: Double?
    let rawDirection: String?
    let duration: Int?
    let durationLabel: String?
    let durationAr: String?
    let price: Double?
    let priceDisplay: String?
    let timeframe: String?
    let source: String?
    let dataStatus: String?
    let trend: String?
    let momentum: String?
    let reasons: [String]?
    let noTradeReason: String?
    let note: String?
    let signalId: Int?
    let generatedAt: String?
    let availableDurations: [Int]?
    let durationMode: String?
    let durationReason: String?
    let entry: EntryPlan?
    let candleAnalysis: CandleAnalysis?
    let invalidation: [String]?
    let warnings: [String]?
    let status: String?
    let error: String?
    let message: String?
    let detail: String?
}

struct EntryPlan: Decodable {
    let ready: Bool
    let condition: String
    let price: Double?
    let priceDisplay: String?
    let windowSeconds: Int
    let validUntil: String?
    let invalidation: [String]
}

struct CandleAnalysis: Decodable {
    let candles: [CandleRow]
    let formingCandle: CandleRow?
    let summary: String
    let note: String?
}

struct CandleRow: Decodable, Identifiable {
    let time: String
    let open: Double
    let high: Double
    let low: Double
    let close: Double
    let direction: String
    let bodyPct: Double?
    let upperWickPct: Double?
    let lowerWickPct: Double?
    let closePositionPct: Double?
    let closed: Bool
    var id: String { time + String(close) }
}

struct AnalysisDetails: Decodable {
    let candleAnalysis: CandleAnalysis?
    let entry: EntryPlan?
    let evidence: Double?
    let invalidations: [String]?
    let status: String?
}

struct Recommendation: Decodable, Identifiable {
    let market: String
    let marketLabel: String
    let icon: String?
    let asset: String
    let assetKey: String?
    let direction: String
    let signalAr: String?
    let confidence: Double
    let duration: Int
    let durationLabel: String
    let price: Double?
    let priceDisplay: String?
    let source: String?
    let reason: String?
    let timeframe: String?
    let generatedAt: String?
    let status: String?
    let dataStatus: String?
    let details: DetailsPayload?

    var id: String { "\(market)-\(assetKey ?? asset)-\(direction)-\(duration)" }
}

struct DetailsPayload: Decodable {
    let candleAnalysis: CandleAnalysis?
    let entry: EntryPlan?
    let evidence: Double?
    let status: String?
    let invalidations: [String]?

    enum CodingKeys: String, CodingKey {
        case candleAnalysis, entry, evidence, status, invalidation
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        candleAnalysis = try? c.decodeIfPresent(CandleAnalysis.self, forKey: .candleAnalysis)
        entry = try? c.decodeIfPresent(EntryPlan.self, forKey: .entry)
        evidence = try? c.decodeIfPresent(Double.self, forKey: .evidence)
        status = try? c.decodeIfPresent(String.self, forKey: .status)
        invalidations = try? c.decodeIfPresent([String].self, forKey: .invalidation)
    }
}

struct SettingsSaveResponse: Decodable {
    let ok: Bool
    let settings: AppSettings
}

struct RecommendationsResponse: Decodable {
    let items: [Recommendation]
    let threshold: Double?
    let empty: Bool?
    let generatedAt: String?
}

struct HistoryResponse: Decodable {
    let signals: [HistorySignal]
    let stats: Stats
}

struct HistorySignal: Decodable, Identifiable {
    let id: Int
    let market: String
    let marketLabel: String
    let asset: String
    let direction: String
    let signalAr: String?
    let confidence: Double
    let duration: Int
    let durationLabel: String
    let entry: Double?
    let entryDisplay: String?
    let createdAt: String?
    let expiresAt: String?
    let status: String
    let closePrice: Double?
    let resultReason: String?
    let source: String?
}

struct Stats: Decodable {
    let total: Int?
    let active: Int?
    let wins: Int?
    let losses: Int?
    let draws: Int?
    let unverified: Int?
    let verified: Int?
    let accuracy: Double?
    let avgConfidence: Double?
    let bestAsset: String?
    let bestAssetWins: Int?
    let profitFactor: Double?

    static let empty = Stats(total: nil, active: nil, wins: nil, losses: nil, draws: nil,
                             unverified: nil, verified: nil, accuracy: nil, avgConfidence: nil,
                             bestAsset: nil, bestAssetWins: nil, profitFactor: nil)
}

struct AppHealth: Decodable {
    let status: String
    let service: String
    let engine: String
    let database: String?
    let checkedAt: String?
    let ai: AIDetail?
    let error: String?
    let message: String?
}

struct AIDetail: Decodable {
    let configured: Bool?
    let online: Bool?
    let model: String?
}

struct ServerError: Decodable {
    let error: String?
    let message: String?
    let detail: String?
}

extension JSONDecoder {
    static func rozlf() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }
}
