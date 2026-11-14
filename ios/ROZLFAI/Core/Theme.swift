import SwiftUI

enum Palette {
    static let background = Color(red: 0.016, green: 0.031, blue: 0.027)
    static let surface = Color(red: 0.043, green: 0.075, blue: 0.067)
    static let surfaceHigh = Color(red: 0.063, green: 0.106, blue: 0.094)
    static let emerald = Color(red: 0.086, green: 0.839, blue: 0.639)
    static let emeraldDeep = Color(red: 0.024, green: 0.286, blue: 0.220)
    static let gold = Color(red: 0.914, green: 0.769, blue: 0.416)
    static let danger = Color(red: 1.0, green: 0.365, blue: 0.451)
    static let text = Color(red: 0.925, green: 0.957, blue: 0.945)
    static let muted = Color(red: 0.514, green: 0.588, blue: 0.561)
    static let hairline = Color.white.opacity(0.08)
}

struct GlassCard: ViewModifier {
    var padding: CGFloat = 18
    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .fill(Palette.surface.opacity(0.82))
                    .overlay(
                        RoundedRectangle(cornerRadius: 22, style: .continuous)
                            .stroke(Palette.hairline, lineWidth: 1)
                    )
            )
    }
}

struct GlassSheet: ViewModifier {
    var corner: CGFloat = 30
    func body(content: Content) -> some View {
        content
            .background(.ultraThinMaterial)
            .overlay(
                RoundedRectangle(cornerRadius: corner, style: .continuous)
                    .stroke(Palette.emerald.opacity(0.18), lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: corner, style: .continuous))
    }
}

extension View {
    func glassCard(padding: CGFloat = 18) -> some View {
        modifier(GlassCard(padding: padding))
    }
    func glassSheet() -> some View {
        modifier(GlassSheet())
    }
}

struct PrimaryButton: View {
    let title: String
    var icon: String? = nil
    var loading: Bool = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                if loading {
                    ProgressView().tint(Palette.background)
                } else if let icon {
                    Image(systemName: icon)
                }
                Text(title).fontWeight(.semibold)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 15)
            .foregroundStyle(Palette.background)
            .background(
                LinearGradient(colors: [Palette.emerald, Palette.gold.opacity(0.92)],
                               startPoint: .leading, endPoint: .trailing)
            )
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(loading)
    }
}

struct Pill: View {
    let text: String
    var color: Color = Palette.emerald
    var body: some View {
        Text(text)
            .font(.caption2.weight(.bold))
            .padding(.horizontal, 9)
            .padding(.vertical, 5)
            .foregroundStyle(color)
            .background(color.opacity(0.12))
            .clipShape(Capsule())
    }
}
