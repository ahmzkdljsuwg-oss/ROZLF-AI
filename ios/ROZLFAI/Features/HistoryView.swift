import SwiftUI

struct HistoryView: View {
    @EnvironmentObject private var app: AppState

    private var accuracyText: String {
        guard let accuracy = app.stats.accuracy else { return "—" }
        return String(format: "%.1f%%", accuracy)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text(app.text("history.title"))
                        .font(.system(size: 28, weight: .heavy, design: .rounded))
                        .foregroundStyle(Palette.text)
                    Spacer()
                    ConnectionBadge()
                }

                LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                    StatTile(title: app.text("history.accuracy"), value: accuracyText, accent: Palette.emerald)
                    StatTile(title: app.text("history.verified"), value: "\(app.stats.verified ?? 0)", accent: Palette.gold)
                    StatTile(title: app.text("history.wins"), value: "\(app.stats.wins ?? 0)", accent: Palette.emerald)
                    StatTile(title: app.text("history.losses"), value: "\(app.stats.losses ?? 0)", accent: Palette.danger)
                    StatTile(title: app.text("history.draws"), value: "\(app.stats.draws ?? 0)", accent: Palette.muted)
                    StatTile(title: app.text("history.active"), value: "\(app.stats.active ?? 0)", accent: Palette.gold)
                }

                Text(app.text("history.note"))
                    .font(.caption2)
                    .foregroundStyle(Palette.muted)

                if app.history.isEmpty {
                    Text(app.text("history.empty"))
                        .font(.footnote)
                        .foregroundStyle(Palette.muted)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.vertical, 30)
                        .glassCard()
                } else {
                    VStack(spacing: 10) {
                        ForEach(app.history) { signal in
                            HistoryRow(signal: signal)
                        }
                    }
                }

                if let best = app.stats.bestAsset {
                    HStack(spacing: 8) {
                        Image(systemName: "trophy.fill").foregroundStyle(Palette.gold)
                        Text("Best asset · \(best) · \(app.stats.bestAssetWins ?? 0) wins")
                            .font(.caption).foregroundStyle(Palette.muted)
                    }
                }
            }
            .padding(.horizontal, 18)
            .padding(.top, 14)
            .padding(.bottom, 20)
        }
        .refreshable { await app.refreshHistory() }
        .scrollIndicators(.hidden)
    }
}

private struct HistoryRow: View {
    @EnvironmentObject private var app: AppState
    let signal: HistorySignal

    private var resultColor: Color {
        switch signal.status.uppercased() {
        case "WIN": return Palette.emerald
        case "LOSS": return Palette.danger
        case "DRAW": return Palette.muted
        case "ACTIVE": return Palette.gold
        default: return Palette.muted
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(signal.asset).font(.subheadline.weight(.bold)).foregroundStyle(Palette.text)
                    Text("\(signal.marketLabel) · \(signal.durationLabel)")
                        .font(.caption2).foregroundStyle(Palette.muted)
                }
                Spacer()
                DirectionBadge(direction: signal.direction)
                Pill(text: app.text("status.\(signal.status.uppercased())"), color: resultColor)
            }
            HStack(spacing: 18) {
                value(app.text("history.entry"), signal.entryDisplay ?? (signal.entry).map { String(format: "%.5f", $0) } ?? "—")
                value(app.text("history.exit"), signal.closePrice.map { String(format: "%.5f", $0) } ?? "—")
                value(app.text("analysis.confidence"), String(format: "%.0f%%", signal.confidence))
                Spacer()
                Text(AppState.pretty(signal.createdAt)).font(.caption2).foregroundStyle(Palette.muted)
            }
            if let reason = signal.resultReason, !reason.isEmpty {
                Text(reason).font(.caption2).foregroundStyle(Palette.muted)
            }
        }
        .glassCard(padding: 14)
    }

    private func value(_ title: String, _ text: String) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(title).font(.system(size: 8)).foregroundStyle(Palette.muted)
            Text(text).font(.caption2.weight(.semibold)).foregroundStyle(Palette.text)
        }
    }
}
