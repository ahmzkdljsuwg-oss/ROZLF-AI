import SwiftUI

struct MainShell: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        ZStack(alignment: .bottom) {
            Group {
                switch app.selectedTab {
                case 0: HomeView()
                case 1: RecommendationsView()
                case 2: HistoryView()
                default: SettingsView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.bottom, 84)
            .transition(.opacity)

            TabBar()
        }
        .background(Palette.background.ignoresSafeArea())
        .animation(.easeInOut(duration: 0.22), value: app.selectedTab)
    }
}

private struct TabBar: View {
    @EnvironmentObject private var app: AppState
    private let tabs: [(icon: String, key: String)] = [
        ("square.grid.2x2.fill", "nav.home"),
        ("sparkles", "nav.signals"),
        ("clock.arrow.circlepath", "nav.history"),
        ("gearshape.fill", "nav.settings"),
    ]

    var body: some View {
        HStack(spacing: 4) {
            ForEach(Array(tabs.enumerated()), id: \.offset) { index, tab in
                Button {
                    app.selectedTab = index
                } label: {
                    VStack(spacing: 5) {
                        Image(systemName: tab.icon)
                            .font(.system(size: 18, weight: .semibold))
                        Text(app.text(tab.key))
                            .font(.system(size: 10, weight: .semibold))
                            .lineLimit(1)
                            .minimumScaleFactor(0.8)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                    .foregroundStyle(app.selectedTab == index ? Palette.emerald : Palette.muted)
                    .background(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .fill(app.selectedTab == index ? Palette.emerald.opacity(0.10) : .clear)
                    )
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("tab.\(index)")
            }
        }
        .padding(.horizontal, 12)
        .padding(.top, 8)
        .padding(.bottom, 10)
        .background(.ultraThinMaterial)
        .overlay(alignment: .top) {
            Rectangle().fill(Palette.hairline).frame(height: 1)
        }
        .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
        .padding(.horizontal, 18)
        .padding(.bottom, 8)
    }
}
