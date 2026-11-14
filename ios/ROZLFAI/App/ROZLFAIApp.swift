import SwiftUI

@main
struct ROZLFAIApp: App {
    @StateObject private var app = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(app)
                .environment(\.layoutDirection, app.language.layout)
                .preferredColorScheme(.dark)
                .tint(Palette.emerald)
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        ZStack {
            Palette.background.ignoresSafeArea()
            if app.isConfigured {
                MainShell()
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
            } else {
                SetupView()
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.35), value: app.isConfigured)
        .task {
            if app.isConfigured && app.connection == .notConfigured {
                _ = await app.connect()
            }
        }
    }
}
