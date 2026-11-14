import SwiftUI

struct MarketDetailView: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.dismiss) private var dismiss
    let marketKey: String

    @State private var snapshot: MarketSnapshot?
    @State private var analysis: AnalysisResponse?
    @State private var loading = true
    @State private var analysing = false
    @State private var error: String?
    @State private var autoMode = true
    @State private var duration = 60
    @State private var assetKey: String?

    private let fallbackDurations = [30, 60, 120, 300]

    var body: some View {
        NavigationStack {
            ZStack {
                Palette.background.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        priceHeader
                        controls
                        if let error {
                            errorCard(error)
                        }
                        if let analysis {
                            resultSection(analysis)
                        }
                        if let snapshot, !snapshot.candles.isEmpty {
                            chartSection(snapshot)
                        }
                    }
                    .padding(.horizontal, 18)
                    .padding(.bottom, 28)
                }
            }
            .navigationTitle(snapshot?.label ?? marketKey.uppercased())
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(app.text("common.close")) { dismiss() }
                        .foregroundStyle(Palette.emerald)
                }
                ToolbarItem(placement: .topBarLeading) {
                    ConnectionBadge()
                }
            }
            .task { await load() }
        }
        .preferredColorScheme(.dark)
    }

    private var priceHeader: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(snapshot?.icon ?? "chart.line.uptrend.xyaxis")
                    .font(.system(size: 20))
                    .foregroundStyle(Palette.gold)
                Text(snapshot?.source ?? "—")
                    .font(.caption2).foregroundStyle(Palette.muted)
                Spacer()
                if let snapshot {
                    Pill(text: snapshot.status == "LIVE" ? app.text("common.live") : (snapshot.error ?? app.text("common.unavailable")),
                         color: snapshot.status == "LIVE" ? Palette.emerald : Palette.danger)
                }
            }
            Text(snapshot?.priceDisplay ?? (snapshot?.price).map { String(format: "%.5f", $0) } ?? "—")
                .font(.system(size: 40, weight: .heavy, design: .rounded))
                .foregroundStyle(Palette.text)
            HStack(spacing: 16) {
                Text("TF \(snapshot?.timeframe ?? "—")")
                Text(app.text("home.updated") + " " + AppState.pretty(snapshot?.lastTime))
            }
            .font(.caption2).foregroundStyle(Palette.muted)
        }
        .glassCard()
    }

    private var controls: some View {
        VStack(alignment: .leading, spacing: 14) {
            if let assets = snapshot?.assets, assets.count > 1 {
                Picker("Asset", selection: Binding(get: { assetKey ?? assets[0].key }, set: { assetKey = $0 })) {
                    ForEach(assets) { asset in Text(asset.display).tag(asset.key) }
                }
                .pickerStyle(.menu)
                .tint(Palette.emerald)
            }

            HStack(spacing: 6) {
                modeButton(app.text("market.auto"), active: autoMode) { autoMode = true }
                modeButton(app.text("market.manual"), active: !autoMode) { autoMode = false }
            }
            .padding(4)
            .background(Palette.surface)
            .clipShape(RoundedRectangle(cornerRadius: 13, style: .continuous))

            if autoMode {
                Label(app.text("market.auto"), systemImage: "wand.and.stars")
                    .font(.footnote)
                    .foregroundStyle(Palette.muted)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(durations, id: \.self) { value in
                            Button { duration = value } label: {
                                Text(durationLabel(value))
                                    .font(.caption2.weight(.bold))
                                    .padding(.horizontal, 12).padding(.vertical, 8)
                                    .foregroundStyle(duration == value ? Palette.background : Palette.muted)
                                    .background(duration == value ? Palette.emerald : Palette.surface)
                                    .clipShape(Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }

            PrimaryButton(title: app.text("market.analysis"), icon: "bolt.fill", loading: analysing) {
                Task { await analyse() }
            }
            .accessibilityIdentifier("analyseButton")
        }
        .glassCard(padding: 16)
    }

    private func resultSection(_ result: AnalysisResponse) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text(result.asset ?? "—").font(.headline).foregroundStyle(Palette.text)
                Spacer()
                DirectionBadge(direction: result.direction ?? "NO TRADE")
            }
            HStack(spacing: 14) {
                meta(app.text("analysis.confidence"), result.confidence.map { String(format: "%.0f%%", $0) } ?? "—", Palette.emerald)
                meta(app.text("card.expiry"), result.durationLabel ?? app.text("market.auto"), Palette.gold)
                meta(app.text("card.entry"), result.priceDisplay ?? "—", Palette.text)
            }
            if let reasons = result.reasons, !reasons.isEmpty {
                Text(app.text("analysis.reasons")).font(.caption2.weight(.bold)).foregroundStyle(Palette.muted)
                ForEach(reasons.prefix(6), id: \.self) { reason in
                    Label(reason, systemImage: "checkmark.seal")
                        .font(.caption)
                        .foregroundStyle(Palette.text.opacity(0.9))
                }
            }
            if let summary = result.candleAnalysis?.summary, !summary.isEmpty {
                Text(summary)
                    .font(.caption2)
                    .foregroundStyle(Palette.muted)
                    .lineSpacing(3)
            }
            if let mode = result.durationMode, let why = result.durationReason {
                Text("\(mode.uppercased()) · \(why)")
                    .font(.caption2)
                    .foregroundStyle(Palette.gold.opacity(0.9))
            }
            if let entry = result.entry {
                VStack(alignment: .leading, spacing: 5) {
                    Text(app.text("analysis.entry")).font(.caption2.weight(.bold)).foregroundStyle(Palette.muted)
                    Text(entry.ready ? "\(entry.condition) · \(entry.priceDisplay ?? "")" : app.text("analysis.noEntry"))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(entry.ready ? Palette.emerald : Palette.gold)
                    if let until = entry.validUntil {
                        Text("Valid until \(AppState.pretty(until))")
                            .font(.caption2).foregroundStyle(Palette.muted)
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Palette.surfaceHigh)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            if let text = result.noTradeReason ?? result.note, !text.isEmpty {
                Text(text).font(.caption2).foregroundStyle(Palette.muted)
            }
            ForEach(result.invalidation ?? [], id: \.self) { line in
                Label(line, systemImage: "xmark.octagon")
                    .font(.caption2).foregroundStyle(Palette.danger.opacity(0.9))
            }
            if let warnings = result.warnings, !warnings.isEmpty {
                ForEach(warnings, id: \.self) { line in
                    Label(line, systemImage: "exclamationmark.triangle")
                        .font(.caption2).foregroundStyle(Palette.gold)
                }
            }
        }
        .glassCard()
        .transition(.opacity.combined(with: .move(edge: .bottom)))
    }

    private func chartSection(_ snap: MarketSnapshot) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(app.text("analysis.candles")).font(.caption2.weight(.bold)).foregroundStyle(Palette.muted)
            HStack(alignment: .bottom, spacing: 4) {
                ForEach(snap.candles.suffix(22)) { candle in
                    let up = candle.c >= candle.o
                    VStack(spacing: 1) {
                        Rectangle().fill((up ? Palette.emerald : Palette.danger).opacity(0.6))
                            .frame(width: 3, height: 10)
                        RoundedRectangle(cornerRadius: 1)
                            .fill(up ? Palette.emerald : Palette.danger)
                            .frame(width: 7, height: 26)
                        Rectangle().fill((up ? Palette.emerald : Palette.danger).opacity(0.6))
                            .frame(width: 3, height: 8)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .glassCard()
    }

    private func errorCard(_ text: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(app.text("error.title"), systemImage: "wifi.exclamationmark")
                .font(.subheadline.weight(.semibold)).foregroundStyle(Palette.gold)
            Text(text).font(.caption).foregroundStyle(Palette.muted)
            Button(app.text("common.retry")) { Task { await load() } }
                .font(.caption.weight(.bold)).foregroundStyle(Palette.emerald)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private var durations: [Int] {
        let values = snapshot?.durations ?? []
        return values.isEmpty ? fallbackDurations : values
    }

    private func modeButton(_ title: String, active: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.caption2.weight(.bold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 9)
                .foregroundStyle(active ? Palette.background : Palette.muted)
                .background(active ? Palette.emerald : .clear)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .buttonStyle(.plain)
    }

    private func meta(_ title: String, _ value: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.system(size: 9)).foregroundStyle(Palette.muted)
            Text(value).font(.caption.weight(.bold)).foregroundStyle(color)
        }
    }

    private func durationLabel(_ seconds: Int) -> String {
        if seconds < 60 { return "\(seconds)s" }
        if seconds < 3600 { return "\(seconds / 60)m" }
        return "\(seconds / 3600)h"
    }

    private func load() async {
        guard let client = app.client else { return }
        loading = true
        error = nil
        do {
            let snap = try await client.market(marketKey)
            snapshot = snap
            if assetKey == nil { assetKey = snap.assets.first?.key }
            if let first = snap.durations.first, !snap.durations.contains(duration) { duration = first }
            if snap.status != "LIVE" {
                error = snap.error ?? app.text("error.data")
            }
        } catch {
            self.error = error.localizedDescription
        }
        loading = false
    }

    private func analyse() async {
        guard let client = app.client else { return }
        analysing = true
        error = nil
        do {
            analysis = try await client.analyse(
                market: marketKey,
                asset: assetKey,
                duration: autoMode ? nil : duration
            )
        } catch {
            self.error = error.localizedDescription
        }
        analysing = false
    }
}
