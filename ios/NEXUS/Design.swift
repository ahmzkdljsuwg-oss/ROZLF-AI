import SwiftUI

enum Ink {
    static let paper = Color(red: 0.953, green: 0.960, blue: 0.980)
    static let navy = Color(red: 0.055, green: 0.078, blue: 0.137)
    static let mute = Color(red: 0.37, green: 0.41, blue: 0.50)
    static let rim = Color(red: 0.88, green: 0.90, blue: 0.94)
    static let gold = Color(red: 1, green: 0.70, blue: 0.0)
    static let honey = Color(red: 1, green: 0.81, blue: 0.31)
    static let leaf = Color(red: 0.09, green: 0.48, blue: 0.33)
    static let aqua = Color(red: 0.47, green: 0.83, blue: 0.95)
    static let fern = Color(red: 0.06, green: 0.16, blue: 0.13)
}

extension View {
    func nexusCard(_ padding: CGFloat = 18) -> some View {
        self.padding(padding).frame(maxWidth: .infinity, alignment: .leading)
            .background(.white, in: RoundedRectangle(cornerRadius: 23))
            .overlay { RoundedRectangle(cornerRadius: 23).strokeBorder(Ink.rim, lineWidth: 0.75) }
    }
}

struct GoldButton: View {
    let label, icon: String
    var busy = false
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if busy { ProgressView().tint(Ink.navy) } else { Image(systemName: icon) }
                Text(label).fontWeight(.bold)
            }
            .frame(maxWidth: .infinity, minHeight: 50)
            .foregroundStyle(Ink.navy)
            .background(LinearGradient(colors: [Ink.gold, Ink.honey], startPoint: .trailing, endPoint: .leading),
                        in: RoundedRectangle(cornerRadius: 15))
        }
        .buttonStyle(.plain)
        .disabled(busy)
    }
}

struct BadgeIcon: View {
    let icon: String
    var color = Ink.gold
    var size: CGFloat = 46
    var body: some View {
        Image(systemName: icon).font(.system(size: size * 0.45, weight: .semibold))
            .foregroundStyle(color == Ink.gold ? Ink.navy : color)
            .frame(width: size, height: size)
            .background(color.opacity(0.20), in: Circle())
    }
}

struct NexusLogo: View {
    var size: CGFloat
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.27).fill(Ink.navy)
            RoundedRectangle(cornerRadius: size * 0.27).strokeBorder(Ink.gold, lineWidth: size * 0.034)
            HStack(alignment: .center, spacing: size * 0.047) {
                ForEach(0..<3) { i in
                    let h = size * [0.22, 0.36, 0.28][i]
                    let c = i == 2 ? Ink.honey : Color(red: 0.27, green: 0.94, blue: 0.68)
                    ZStack {
                        Capsule().fill(c).frame(width: size * 0.025, height: h + size * 0.14)
                        RoundedRectangle(cornerRadius: size * 0.026).fill(c).frame(width: size * 0.11, height: h)
                    }.offset(y: size * [0.09, 0.00, -0.09][i])
                }
            }.rotationEffect(.degrees(-10))
        }.frame(width: size, height: size).accessibilityHidden(true)
    }
}

struct SplashScreen: View {
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    @State private var sweep = false

    var body: some View {
        GeometryReader { geo in
            ZStack {
                LinearGradient(colors: [Color.black, Ink.navy, .black], startPoint: .top, endPoint: .bottom)
                Canvas { context, size in
                    for i in 1..<10 {
                        let y = size.height * CGFloat(i) / 10
                        var line = Path()
                        line.move(to: CGPoint(x: 0, y: y + 48))
                        line.addLine(to: CGPoint(x: size.width, y: y - 48))
                        context.stroke(line, with: .color(Ink.honey.opacity(0.11)), lineWidth: 1)
                    }
                    for i in 0..<25 {
                        let x = size.width * (CGFloat(i) + 0.5) / 25
                        let y = size.height * (0.77 - CGFloat(i) * 0.022 + sin(CGFloat(i) * 1.19) * 0.07)
                        let h = CGFloat(17 + (i * 17) % 45)
                        let tone = i % 4 == 1 ? Color.orange : Ink.honey
                        let wick = CGRect(x: x, y: y - h, width: 1.5, height: h * 2)
                        let body = CGRect(x: x - 3, y: y - h / 2, width: 7, height: h)
                        context.fill(Path(wick), with: .color(tone.opacity(0.24)))
                        context.fill(Path(body), with: .color(tone.opacity(0.30)))
                    }
                }
                RadialGradient(colors: [Ink.navy.opacity(0.05), .black.opacity(0.75)], center: .center, startRadius: 20, endRadius: geo.size.height * 0.70)
                VStack(spacing: 12) {
                    Spacer()
                    NexusLogo(size: 110)
                    Text("NEXUS AI").font(.system(size: 39, weight: .black, design: .rounded)).tracking(2)
                    Text("محلّل الأسواق").font(.title3.bold())
                    Text("الأسواق · الشموع · الرادار").font(.footnote).foregroundStyle(.white.opacity(0.63))
                    Spacer()
                    Capsule().fill(.white.opacity(0.24)).frame(width: 135, height: 3)
                        .overlay(alignment: .leading) {
                            Capsule().fill(Ink.gold).frame(width: reduceMotion || sweep ? 135 : 12, height: 3)
                        }
                        .padding(.bottom, 60)
                }.foregroundStyle(.white).frame(maxWidth: .infinity)
            }.ignoresSafeArea()
        }
        .onAppear { withAnimation(.easeOut(duration: 0.75)) { sweep = true } }
        .accessibilityElement(children: .combine)
    }
}

struct CandleCanvas: View {
    let candles: [NexusCandle]
    var body: some View {
        Canvas { context, size in
            let rows = Array(candles.suffix(36))
            guard let lo = rows.map(\.low).min(), let hi = rows.map(\.high).max() else { return }
            let step = size.width / CGFloat(rows.count)
            let span = max(hi - lo, 1e-12)
            func position(_ value: Double) -> CGFloat { 12 + CGFloat((hi - value) / span) * (size.height - 24) }
            for level in 1..<5 {
                let y = size.height * CGFloat(level) / 5
                var line = Path()
                line.move(to: CGPoint(x: 0, y: y))
                line.addLine(to: CGPoint(x: size.width, y: y))
                context.stroke(line, with: .color(Ink.rim), lineWidth: 0.7)
            }
            for (i, c) in rows.enumerated() {
                let x = step * (CGFloat(i) + 0.5)
                let color: Color = c.close >= c.open ? Ink.leaf : .red
                let width = max(2, step * 0.58)
                let top = min(position(c.open), position(c.close))
                let h = max(1.5, abs(position(c.open) - position(c.close)))
                context.fill(Path(CGRect(x: x, y: position(c.high), width: 1, height: max(1, position(c.low) - position(c.high)))), with: .color(color))
                context.fill(Path(CGRect(x: x - width / 2, y: top, width: width, height: h)), with: .color(color))
            }
        }
        .frame(height: 150).environment(\.layoutDirection, .leftToRight)
        .accessibilityLabel("رسم الشموع المغلقة")
    }
}
