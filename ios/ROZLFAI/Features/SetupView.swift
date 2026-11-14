import SwiftUI

struct SetupView: View {
    @EnvironmentObject private var app: AppState
    @State private var server = ""
    @State private var busy = false
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                Spacer(minLength: 34)
                logo
                VStack(alignment: .leading, spacing: 10) {
                    Text(app.text("setup.title"))
                        .font(.system(size: 30, weight: .bold, design: .rounded))
                        .foregroundStyle(Palette.text)
                    Text(app.text("setup.body"))
                        .font(.subheadline)
                        .foregroundStyle(Palette.muted)
                        .lineSpacing(4)
                }
                VStack(alignment: .leading, spacing: 8) {
                    Text(app.text("settings.server"))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(Palette.muted)
                    TextField(app.text("setup.placeholder"), text: $server)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .padding(14)
                        .background(Palette.surfaceHigh)
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .foregroundStyle(Palette.text)
                        .accessibilityIdentifier("serverField")
                }
                if let error {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .font(.footnote)
                        .foregroundStyle(Palette.danger)
                }
                PrimaryButton(title: app.text("setup.connect"), icon: "bolt.horizontal.fill", loading: busy) {
                    submit()
                }
                .accessibilityIdentifier("connectButton")
                HStack(spacing: 8) {
                    Circle().fill(Palette.emerald).frame(width: 7, height: 7)
                    Text("HTTPS · RAILWAY READY · NO API KEYS IN APP")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(Palette.muted)
                }
                Spacer(minLength: 40)
            }
            .padding(24)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Palette.background.ignoresSafeArea())
        .onAppear { server = app.baseURLString }
    }

    private var logo: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                Image(systemName: "waveform.path.ecg.rectangle.fill")
                    .font(.system(size: 26, weight: .semibold))
                    .foregroundStyle(Palette.emerald)
                Text("ROZLF AI")
                    .font(.system(size: 34, weight: .heavy, design: .rounded))
                    .foregroundStyle(Palette.text)
            }
            Text(app.text("app.tagline"))
                .font(.caption.weight(.semibold))
                .tracking(2.4)
                .foregroundStyle(Palette.gold)
        }
    }

    private func submit() {
        guard URL.validateServer(server) != nil else {
            error = app.text("setup.invalid")
            return
        }
        busy = true
        error = nil
        app.saveServer(server)
        Task {
            let ok = await app.connect()
            busy = false
            if !ok {
                error = app.connectionDetail.isEmpty ? app.text("setup.failed") : app.connectionDetail
            }
        }
    }
}
