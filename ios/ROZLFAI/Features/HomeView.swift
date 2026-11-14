import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var app: AppState
    @State private var selectedMarket: MarketOverview?

    private let columns = [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                connectionCard
                opportunities
                marketsSection
                footer
            }
            .padding(.horizontal, 18)
            .padding(.top, 14)
        }
        .refreshable { await app.loadAll() }
        .scrollIndicators(.hidden)
        .sheet(item: $selectedMarket) { market in
            MarketDetailView(marketKey: market.key)
                .environmentObject(app)
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 5) {
                Text("ROZLF AI")
                    .font(.system(size: 32, weight: .heavy, design: .rounded))
                    .foregroundStyle(Palette.text)
                Text(app.text("app.tagline"))
                    .font(.system(size: 10, weight: .bold))
                    .tracking(2)
                    .foregroundStyle(Palette.gold)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 6) {
                ConnectionBadge()
                Text(app.text("home.updated") + " " + (app.lastUpdate.isEmpty ? "—" : app.lastUpdate))
                    .font(.system(size: 9))
                    .foregroundStyle(Palette.muted)
            }
        }
    }

    private var connectionCard: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle().fill(Palette.emeraldDeep).frame(width: 42, height: 42)
                Image(systemName: "antenna.radiowaves.left.and.right")
                    .foregroundStyle(Palette.emerald)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(app.text("home.connection"))
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(Palette.muted)
                Text(app.connectionDetail.isEmpty ? app.baseURLString : app.connectionDetail)
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Palette.text)
                    .lineLimit(1)
            }
            Spacer()
            Button {
                Task { await app.loadAll() }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.emerald)
                    .rotationEffect(.degrees(app.isLoading ? 360 : 0))
                    .animation(app.isLoading ? .linear(duration: 1).repeatForever(autoreverses: false) : .default, value: app.isLoading)
            }
            .accessibilityIdentifier("homeRefresh")
        }
        .glassCard(padding: 14)
    }

    private var opportunities: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle(app.text("home.best"), trailing: "\(app.recommendations.count)")
            if app.recommendations.isEmpty {
                Text(app.text("home.noRecs"))
                    .font(.footnote)
                    .foregroundStyle(Palette.muted)
                    .lineSpacing(4)
                    .glassCard(padding: 16)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        ForEach(app.recommendations.prefix(5)) { item in
                            VStack(alignment: .leading, spacing: 10) {
                                HStack {
                                    Text(item.asset).font(.subheadline.weight(.bold)).foregroundStyle(Palette.text)
                                    Spacer()
                                    DirectionBadge(direction: item.direction)
                                }
                                Text(item.marketLabel).font(.caption2).foregroundStyle(Palette.muted)
                                if let details = item.details, let analysis = details.candleAnalysis {
                                    CandleStrip(candles: analysis.candles)
                                }
                                HStack {
                                    Text(item.durationLabel).font(.caption2.weight(.semibold)).foregroundStyle(Palette.gold)
                                    Spacer()
                                    Text(String(format: "%.0f%%", item.confidence)).font(.caption.weight(.bold)).foregroundStyle(Palette.emerald)
                                }
                            }
                            .frame(width: 238)
                            .glassCard(padding: 14)
                        }
                    }
                }
            }
        }
    }

    private var marketsSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle(app.text("home.markets"), trailing: "\(app.markets.count)")
            if app.markets.isEmpty {
                Text(app.text("common.loading"))
                    .font(.footnote).foregroundStyle(Palette.muted)
                    .glassCard()
            } else {
                LazyVGrid(columns: columns, spacing: 12) {
                    ForEach(app.markets) { market in
                        Button { selectedMarket = market } label: { MarketCard(market: market) }
                            .buttonStyle(.plain)
                    }
                }
            }
        }
    }

    private var footer: some View {
        HStack(spacing: 6) {
            Image(systemName: "shield.lefthalf.filled").font(.caption2)
            Text("ANALYSIS ONLY · NO AUTOMATED TRADES · REAL MARKET DATA")
                .font(.system(size: 8, weight: .semibold))
                .tracking(0.6)
        }
        .foregroundStyle(Palette.muted)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 14)
    }

    private func sectionTitle(_ title: String, trailing: String) -> some View {
        HStack {
            Text(title).font(.caption.weight(.bold)).tracking(1.4).foregroundStyle(Palette.text)
            Spacer()
            Text(trailing).font(.caption2.weight(.bold)).foregroundStyle(Palette.muted)
        }
    }
}

private struct MarketCard: View {
    @EnvironmentObject private var app: AppState
    let market: MarketOverview

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(market.icon)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(market.isLive ? Palette.emerald : Palette.muted)
                    .frame(width: 34, height: 34)
                    .background((market.isLive ? Palette.emerald : Palette.muted).opacity(0.10))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                Spacer()
                Circle()
                    .fill(market.isLive ? Palette.emerald : Palette.danger)
                    .frame(width: 6, height: 6)
            }
            Text(market.label)
                .font(.subheadline.weight(.bold))
                .foregroundStyle(Palette.text)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
            Text(market.isLive ? app.text("market.live") : (market.error ?? app.text("common.unavailable")))
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(market.isLive ? Palette.emerald : Palette.danger)
                .lineLimit(1)
            if let preview = market.assetPreview, !preview.isEmpty {
                Text(preview)
                    .font(.system(size: 9))
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard(padding: 13)
    }
}
