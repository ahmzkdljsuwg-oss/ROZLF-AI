import SwiftUI

struct RecommendationsView: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                thresholdRow
                if app.recommendations.isEmpty {
                    emptyState
                } else {
                    ForEach(Array(app.recommendations.enumerated()), id: \.element.id) { index, item in
                        RecommendationCard(item: item)
                            .transition(.opacity.combined(with: .move(edge: .bottom)))
                            .animation(.easeInOut(duration: 0.25).delay(Double(index) * 0.04), value: app.recommendations.count)
                    }
                }
            }
            .padding(.horizontal, 18)
            .padding(.top, 14)
            .padding(.bottom, 20)
        }
        .refreshable { await app.refreshRecommendations() }
        .scrollIndicators(.hidden)
        .overlay(alignment: .top) {
            if app.isLoading {
                ProgressView().tint(Palette.emerald).padding(.top, 8)
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(app.text("signals.title"))
                    .font(.system(size: 28, weight: .heavy, design: .rounded))
                    .foregroundStyle(Palette.text)
                Spacer()
                ConnectionBadge()
            }
            Text(app.text("signals.best"))
                .font(.caption)
                .foregroundStyle(Palette.muted)
        }
    }

    private var thresholdRow: some View {
        HStack(spacing: 10) {
            Image(systemName: "slider.horizontal.3").foregroundStyle(Palette.gold)
            Text(app.text("signals.threshold"))
                .font(.caption2).foregroundStyle(Palette.muted)
            Spacer()
            Text(String(format: "%.0f%%", app.minConfidence))
                .font(.caption.weight(.bold)).foregroundStyle(Palette.emerald)
        }
        .glassCard(padding: 12)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "scope")
                .font(.system(size: 26))
                .foregroundStyle(Palette.emerald.opacity(0.8))
            Text(app.text("signals.empty"))
                .font(.footnote)
                .foregroundStyle(Palette.muted)
                .multilineTextAlignment(.center)
                .lineSpacing(4)
            Button(app.text("common.refresh")) {
                Task { await app.refreshRecommendations() }
            }
            .font(.caption.weight(.bold))
            .foregroundStyle(Palette.emerald)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 34)
        .glassCard()
    }
}
