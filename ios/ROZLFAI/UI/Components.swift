import SwiftUI

struct ConnectionBadge: View {
    @EnvironmentObject private var app: AppState

    private var label: String {
        switch app.connection {
        case .online: return app.text("section.connection.online")
        case .degraded: return app.text("section.connection.partial")
        case .offline: return app.text("section.connection.offline")
        case .checking: return app.text("section.connection.checking")
        case .notConfigured: return app.text("section.connection.notConfigured")
        }
    }

    private var color: Color {
        switch app.connection {
        case .online: return Palette.emerald
        case .degraded: return Palette.gold
        case .offline: return Palette.danger
        case .checking, .notConfigured: return Palette.muted
        }
    }

    var body: some View {
        HStack(spacing: 7) {
            Circle().fill(color).frame(width: 7, height: 7)
                .shadow(color: color.opacity(0.7), radius: 4)
            Text(label).font(.caption2.weight(.bold)).foregroundStyle(color)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(color.opacity(0.10))
        .clipShape(Capsule())
        .accessibilityIdentifier("connectionBadge")
    }
}

struct DirectionBadge: View {
    let direction: String
    var body: some View {
        let up = direction.uppercased().contains("UP") || direction.contains("شراء")
        let down = direction.uppercased().contains("DOWN") || direction.contains("بيع")
        let color = up ? Palette.emerald : (down ? Palette.danger : Palette.muted)
        HStack(spacing: 5) {
            Image(systemName: up ? "arrow.up.right" : (down ? "arrow.down.right" : "minus"))
                .font(.system(size: 11, weight: .heavy))
            Text(up ? "UP" : (down ? "DOWN" : "NO TRADE"))
                .font(.caption.weight(.heavy))
        }
        .foregroundStyle(color)
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(color.opacity(0.12))
        .clipShape(Capsule())
    }
}

struct StatTile: View {
    let title: String
    let value: String
    var accent: Color = Palette.emerald
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(Palette.muted)
            Text(value)
                .font(.system(size: 22, weight: .bold, design: .rounded))
                .foregroundStyle(accent)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(padding: 14)
    }
}

struct CandleStrip: View {
    let candles: [CandleRow]
    var body: some View {
        HStack(alignment: .bottom, spacing: 5) {
            ForEach(candles.suffix(10)) { candle in
                let up = candle.close >= candle.open
                VStack(spacing: 2) {
                    Rectangle()
                        .fill(up ? Palette.emerald : Palette.danger)
                        .frame(width: 4, height: 6)
                    RoundedRectangle(cornerRadius: 1.5)
                        .fill(up ? Palette.emerald : Palette.danger)
                        .frame(width: 8, height: 22)
                    Rectangle()
                        .fill(up ? Palette.emerald : Palette.danger)
                        .frame(width: 4, height: 6)
                }
                .opacity(candle.closed ? 1 : 0.45)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct RecommendationCard: View {
    @EnvironmentObject private var app: AppState
    let item: Recommendation
    @State private var expanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text(item.icon ?? "chart.xyaxis.line")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.gold)
                    .frame(width: 30, height: 30)
                    .background(Palette.gold.opacity(0.10))
                    .clipShape(RoundedRectangle(cornerRadius: 9))
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.asset)
                        .font(.headline.weight(.semibold))
                        .foregroundStyle(Palette.text)
                    Text("\(item.marketLabel) · \(item.durationLabel)")
                        .font(.caption2)
                        .foregroundStyle(Palette.muted)
                }
                Spacer()
                DirectionBadge(direction: item.direction)
            }

            HStack(spacing: 14) {
                metric(app.text("card.entry"), item.priceDisplay ?? "—")
                metric(app.text("card.expiry"), item.durationLabel)
                metric(app.text("analysis.confidence"), String(format: "%.0f%%", item.confidence))
            }

            if let details = item.details, let analysis = details.candleAnalysis {
                CandleStrip(candles: analysis.candles)
            }

            if let reason = item.reason, !reason.isEmpty {
                Text(reason)
                    .font(.caption)
                    .foregroundStyle(Palette.muted)
                    .lineLimit(expanded ? nil : 2)
            }

            if expanded, let details = item.details {
                if let entry = details.entry {
                    infoLine(app.text("analysis.status"), entry.ready ? app.text("analysis.ready") : app.text("card.noTrade"),
                             color: entry.ready ? Palette.emerald : Palette.gold)
                    if let until = entry.validUntil {
                        infoLine("Valid until", AppState.pretty(until))
                    }
                }
                if let reasons = details.candleAnalysis?.summary, !reasons.isEmpty {
                    Text(reasons)
                        .font(.caption2)
                        .foregroundStyle(Palette.muted)
                        .lineSpacing(3)
                }
                ForEach(details.invalidations ?? [], id: \.self) { text in
                    Label(text, systemImage: "xmark.octagon")
                        .font(.caption2)
                        .foregroundStyle(Palette.danger.opacity(0.85))
                }
            }

            Button {
                withAnimation(.easeInOut(duration: 0.2)) { expanded.toggle() }
            } label: {
                HStack {
                    Text(expanded ? app.text("common.close") : app.text("card.why"))
                    Spacer()
                    Image(systemName: expanded ? "chevron.up" : "chevron.down")
                }
                .font(.caption.weight(.semibold))
                .foregroundStyle(Palette.emerald)
            }
        }
        .glassCard(padding: 16)
    }

    private func metric(_ title: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.system(size: 9, weight: .semibold)).foregroundStyle(Palette.muted)
            Text(value).font(.caption.weight(.bold)).foregroundStyle(Palette.text)
        }
    }

    private func infoLine(_ title: String, _ value: String, color: Color = Palette.text) -> some View {
        HStack(spacing: 6) {
            Text(title).font(.caption2).foregroundStyle(Palette.muted)
            Text(value).font(.caption2.weight(.semibold)).foregroundStyle(color)
        }
    }
}
