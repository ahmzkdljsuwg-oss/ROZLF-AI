import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var app: AppState
    @State private var server = ""
    @State private var testing = false
    @State private var testResult: String?
    @State private var testOK = false

    private let levels = [50.0, 60.0, 70.0, 80.0, 90.0]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text(app.text("settings.title"))
                        .font(.system(size: 28, weight: .heavy, design: .rounded))
                        .foregroundStyle(Palette.text)
                    Spacer()
                    ConnectionBadge()
                }

                serverSection
                languageSection
                confidenceSection
                aboutCard
            }
            .padding(.horizontal, 18)
            .padding(.top, 14)
            .padding(.bottom, 24)
        }
        .scrollIndicators(.hidden)
        .onAppear { server = app.baseURLString }
    }

    private var serverSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(app.text("settings.server"))
                .font(.caption.weight(.bold)).foregroundStyle(Palette.muted)
            TextField(app.text("setup.placeholder"), text: $server)
                .textInputAutocapitalization(.never)
                .keyboardType(.URL)
                .autocorrectionDisabled()
                .padding(12)
                .background(Palette.surfaceHigh)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .foregroundStyle(Palette.text)
                .accessibilityIdentifier("settingsServer")
            Text(app.text("settings.serverNote"))
                .font(.caption2).foregroundStyle(Palette.muted)
            HStack(spacing: 10) {
                Button(app.text("settings.test")) { test() }
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Palette.emerald)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 11)
                    .background(Palette.surfaceHigh)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                Button(app.text("settings.reconnect")) { save() }
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Palette.background)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 11)
                    .background(Palette.emerald)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            }
            if let testResult {
                Label(testResult, systemImage: testOK ? "checkmark.circle.fill" : "xmark.octagon.fill")
                    .font(.caption2)
                    .foregroundStyle(testOK ? Palette.emerald : Palette.danger)
            }
        }
        .glassCard()
    }

    private var languageSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(app.text("settings.language")).font(.caption.weight(.bold)).foregroundStyle(Palette.muted)
            HStack(spacing: 8) {
                ForEach(Language.allCases) { lang in
                    Button {
                        withAnimation(.easeInOut(duration: 0.2)) { app.setLanguage(lang) }
                    } label: {
                        Text(lang.title)
                            .font(.caption.weight(.semibold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                            .foregroundStyle(app.language == lang ? Palette.background : Palette.text)
                            .background(app.language == lang ? Palette.emerald : Palette.surfaceHigh)
                            .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .glassCard()
    }

    private var confidenceSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(app.text("settings.threshold")).font(.caption.weight(.bold)).foregroundStyle(Palette.muted)
                Spacer()
                Text(String(format: "%.0f%%", app.minConfidence)).font(.caption.weight(.bold)).foregroundStyle(Palette.emerald)
            }
            HStack(spacing: 6) {
                ForEach(levels, id: \.self) { value in
                    Button {
                        Task { await app.saveThreshold(value) }
                    } label: {
                        Text("\(Int(value))")
                            .font(.caption2.weight(.bold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 9)
                            .foregroundStyle(app.minConfidence == value ? Palette.background : Palette.muted)
                            .background(app.minConfidence == value ? Palette.emerald : Palette.surfaceHigh)
                            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .glassCard()
    }

    private var aboutCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "lock.shield.fill").foregroundStyle(Palette.gold)
                Text("ROZLF AI · v1.0.0").font(.caption.weight(.bold)).foregroundStyle(Palette.text)
            }
            Text(app.text("settings.about"))
                .font(.caption2).foregroundStyle(Palette.muted).lineSpacing(3)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }

    private func test() {
        guard let url = URL.validateServer(server) else {
            testOK = false
            testResult = app.text("setup.invalid")
            return
        }
        testing = true
        Task {
            do {
                let health = try await APIClient(baseURL: url).health()
                testOK = health.engine == "ONLINE"
                testResult = "engine \(health.engine) · database \(health.database ?? "—")"
            } catch {
                testOK = false
                testResult = error.localizedDescription
            }
            testing = false
        }
    }

    private func save() {
        guard URL.validateServer(server) != nil else {
            testOK = false
            testResult = app.text("setup.invalid")
            return
        }
        app.saveServer(server)
        Task {
            let ok = await app.connect()
            testOK = ok
            testResult = ok ? app.text("section.connection.online") : app.connectionDetail
        }
    }
}
