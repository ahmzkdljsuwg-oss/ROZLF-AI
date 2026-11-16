import SwiftUI
import PhotosUI
import UIKit

enum NexusTab: String, CaseIterable {
    case home, markets, scan, results, services, settings
    var title: String {
        switch self {
        case .home: return "الرئيسية"
        case .markets: return "الأسواق"
        case .scan: return "التحليل التلقائي"
        case .results: return "النتائج"
        case .services: return "الخدمات"
        case .settings: return "الإعدادات"
        }
    }
    var symbol: String {
        switch self {
        case .home: return "house.fill"
        case .markets: return "chart.xyaxis.line"
        case .scan: return "waveform.path"
        case .results: return "chart.bar.xaxis"
        case .services: return "square.grid.2x2.fill"
        case .settings: return "gearshape.fill"
        }
    }
}
enum NexusSheet: String, Identifiable {
    case chart, guide
    var id: String { rawValue }
}

@main struct NEXUSApp: App {
    @StateObject private var store = NexusStore()
    var body: some Scene {
        WindowGroup {
            NexusRoot().environmentObject(store)
                .environment(\.layoutDirection, .rightToLeft)
                .preferredColorScheme(.light).tint(Ink.navy)
        }
    }
}

struct NexusRoot: View {
    @EnvironmentObject private var store: NexusStore
    @Environment(\.accessibilityReduceMotion) var reduceMotion
    @State private var showLaunch = true
    @State private var sheet: NexusSheet?

    var body: some View {
        ZStack {
            Ink.paper.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 15) {
                    switch store.tab {
                    case .home: home
                    case .markets: MarketPage()
                    case .scan: ScanPage()
                    case .results: ResultsPage()
                    case .services: services
                    case .settings: SettingsPage()
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 7).padding(.bottom, 18)
                .frame(maxWidth: 530)
                .frame(maxWidth: .infinity)
                .foregroundStyle(Ink.navy)
            }
            .id(store.tab)
            .safeAreaInset(edge: .bottom, spacing: 0) { tabBar }
            .accessibilityHidden(showLaunch)
            if showLaunch { SplashScreen().transition(.opacity).zIndex(2) }
        }
        .task {
            try? await Task.sleep(nanoseconds: reduceMotion ? 220_000_000 : 850_000_000)
            withAnimation(.easeOut(duration: reduceMotion ? 0 : 0.24)) { showLaunch = false }
            if store.api != nil { await store.connect() }
        }
        .sheet(item: $sheet) { item in
            NavigationStack {
                ScrollView {
                    if item == .chart { ChartPhotoPage() }
                    else { guide }
                }
                .padding(16).background(Ink.paper.ignoresSafeArea())
                .navigationTitle(item == .chart ? "تحليل الشارت" : "كيف يعمل المحلّل؟")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .navigationBarTrailing) { Button("تم") { sheet = nil } } }
            }
            .environment(\.layoutDirection, .rightToLeft)
        }
    }

    private var tabBar: some View {
        HStack(spacing: 0) {
            ForEach(NexusTab.allCases, id: \.self) { tab in
                Button {
                    withAnimation(.easeInOut(duration: reduceMotion ? 0 : 0.16)) { store.tab = tab }
                } label: {
                    VStack(spacing: 5) {
                        Image(systemName: tab.symbol)
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundStyle(store.tab == tab ? Color(red: 0.72, green: 0.42, blue: 0) : Ink.mute)
                        Text(tab.title).font(.system(size: 10, weight: store.tab == tab ? .bold : .medium))
                            .minimumScaleFactor(0.70).lineLimit(2).multilineTextAlignment(.center)
                    }.frame(maxWidth: .infinity, minHeight: 53)
                }
                .buttonStyle(.plain).accessibilityIdentifier("nexus.tab." + tab.rawValue)
                .accessibilityAddTraits(store.tab == tab ? .isSelected : [])
            }
        }
        .padding(.horizontal, 9).padding(.vertical, 4)
        .background(.regularMaterial, in: Capsule())
        .overlay { Capsule().strokeBorder(Ink.mute.opacity(0.35), lineWidth: 0.7) }
        .shadow(color: .black.opacity(0.13), radius: 20, x: 0, y: 6)
        .padding(.horizontal, 15).padding(.vertical, 6)
    }

    private var home: some View {
        Group {
            HStack {
                NexusLogo(size: 43)
                Text("NEXUS AI").font(.system(size: 20, weight: .black, design: .rounded)).tracking(1.4)
                    .environment(\.layoutDirection, .leftToRight)
                Spacer()
                Button { store.tab = .settings } label: {
                    BadgeIcon(icon: "gearshape", color: Ink.mute, size: 42)
                }.accessibilityLabel("الإعدادات")
            }.padding(.vertical, 8)
            VStack(alignment: .leading, spacing: 9) {
                Text(store.name.isEmpty ? "أهلاً بك في NEXUS" : "أهلاً، \(store.name)")
                    .font(.system(size: 29, weight: .black))
                Text("من آخر شمعة إلى التوقّع الجاي").font(.headline).foregroundStyle(Ink.mute)
                Text(Date.now.formatted(.dateTime.day().month(.wide).weekday(.wide).locale(Locale(identifier: "ar_KW"))))
                    .font(.footnote.bold()).foregroundStyle(Ink.mute).padding(.vertical, 7).padding(.horizontal, 11)
                    .background(Ink.paper, in: Capsule())
            }.nexusCard()
                .overlay(alignment: .leading) { Capsule().fill(Ink.gold).frame(width: 3, height: 47) }
            FeatureBanner(title: "رادار NEXUS", caption: "تحليل الشمعة القادمة في الأسواق المتوفرة", button: "افتح الرادار",
                          icon: "dot.radiowaves.left.and.right", tint: Ink.honey, fill: Ink.navy, light: true) { store.tab = .scan }
            HStack(spacing: 10) {
                Metric(title: "مصادر متاحة", value: store.connected ? String(store.markets.count) : "—",
                       icon: "antenna.radiowaves.left.and.right", tone: Ink.leaf)
                Metric(title: "حالة الخادم", value: store.connected ? "متصل" : "غير متصل",
                       icon: "bolt.horizontal.circle", tone: store.connected ? Ink.leaf : Ink.mute)
            }
            HStack(spacing: 10) {
                mini("الأسواق", "chart.line.uptrend.xyaxis") { store.tab = .markets }
                mini("تحليل الشارت", "viewfinder") { sheet = .chart }
            }
        }
    }

    private func mini(_ title: String, _ icon: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 10) {
                BadgeIcon(icon: icon, size: 42)
                Text(title).font(.subheadline.bold())
            }.frame(maxWidth: .infinity).nexusCard(13)
        }.buttonStyle(.plain)
    }

    private var services: some View {
        Group {
            Text("الخدمات").font(.largeTitle.bold())
            Text("أدوات NEXUS AI للتحليل في مكان واحد").foregroundStyle(Ink.mute)
            FeatureBanner(title: "تحليل الرسم البياني", caption: "ارفع صورة الشارت واقرأ تحليلها", button: "افتح الآن",
                          icon: "sparkles", tint: Ink.navy, fill: Ink.aqua, light: false) { sheet = .chart }
            FeatureBanner(title: "رادار الأسواق", caption: "افحص أحدث الشموع من المصادر المتاحة", button: "افتح الآن",
                          icon: "dot.radiowaves.left.and.right", tint: Ink.aqua, fill: Ink.navy, light: true) { store.tab = .scan }
            FeatureBanner(title: "دليل الاستراتيجيات", caption: "كيف يقرأ المحرك الترند والتذبذب والشموع", button: "اقرأ الدليل",
                          icon: "wrench.and.screwdriver.fill", tint: Color(red: 0.34, green: 0.87, blue: 0.59),
                          fill: Ink.fern, light: true) { sheet = .guide }
            Text("المزيد من الأدوات").font(.title2.bold())
            HStack(spacing: 10) {
                mini("سجل التحليل", "clock.arrow.circlepath") { store.tab = .results }
                mini("حالة المصادر", "network") { store.tab = .settings }
            }
        }
    }

    private var guide: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("قراءة الشمعة القادمة").font(.title2.bold())
            Text("المحرك يقرأ الشموع المغلقة ويقارن اتجاه المتوسطات، الزخم، التذبذب وموقع السعر. التوقّع لا ينفّذ أي صفقة.")
            Divider()
            Text("الوضع المعاير").font(.headline)
            Text("تُرفض الإشارة إذا ما اجتاز السوق والفريم معايير المحرك.")
            Text("وضع LO").font(.headline)
            Text("اتجاه فني تجريبي. لا يعرض نسبة ثقة إذا ما كانت معايرة.")
        }.foregroundStyle(Ink.navy).nexusCard()
    }
}

struct FeatureBanner: View {
    let title, caption, button, icon: String
    let tint, fill: Color
    let light: Bool
    let action: () -> Void
    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 9) {
                Text(title).font(.title3.bold())
                Text(caption).font(.subheadline).foregroundStyle((light ? Color.white : Ink.navy).opacity(0.77))
                Button(action: action) {
                    Text(button).font(.subheadline.bold())
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .foregroundStyle(light ? Ink.navy : .white).background(tint, in: Capsule())
                }.buttonStyle(.plain)
            }
            Spacer(minLength: 0)
            ZStack {
                Circle().strokeBorder((light ? tint : Ink.navy).opacity(0.18), lineWidth: 1).frame(width: 85, height: 85)
                Circle().fill((light ? tint : Ink.navy).opacity(0.15)).frame(width: 70, height: 70)
                Image(systemName: icon).font(.system(size: 31, weight: .semibold)).foregroundStyle(light ? tint : Ink.navy)
            }.accessibilityHidden(true)
        }.padding(17).frame(maxWidth: .infinity)
            .foregroundStyle(light ? .white : Ink.navy)
            .background(fill, in: RoundedRectangle(cornerRadius: 23))
    }
}

struct Metric: View {
    let title, value, icon: String
    let tone: Color
    var body: some View {
        VStack(spacing: 7) {
            Image(systemName: icon).foregroundStyle(tone)
            Text(value).font(.title3.bold()).monospacedDigit()
            Text(title).font(.caption).foregroundStyle(Ink.mute).multilineTextAlignment(.center)
        }.frame(maxWidth: .infinity).nexusCard(12)
    }
}

struct MarketPage: View {
    @EnvironmentObject private var store: NexusStore
    @State private var selected: NexusMarket?
    var body: some View {
        Group {
            Text("الأسواق").font(.largeTitle.bold())
            Text("اختر السوق وبعده اختر الأصل").foregroundStyle(Ink.mute)
            ModeSelector()
            if store.markets.isEmpty {
                VStack(alignment: .leading, spacing: 9) {
                    Text(store.connected ? "ما فيه مصدر متاح حالياً" : "محرك التحليل غير متصل").font(.headline)
                    Text(store.message ?? "اضبط عنوان الخادم والرمز من الإعدادات.").font(.footnote).foregroundStyle(Ink.mute)
                    Button("الإعدادات") { store.tab = .settings }.font(.footnote.bold())
                }.nexusCard()
            } else {
                ForEach(store.markets) { market in
                    Button {
                        selected = market
                    } label: {
                        HStack {
                            Text(market.icon).font(.title2)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(market.label).font(.headline)
                                Text("\(market.assets.count) أصل").font(.caption).foregroundStyle(Ink.mute)
                            }
                            Spacer()
                            Image(systemName: "chevron.left").font(.footnote).foregroundStyle(Ink.mute)
                        }.nexusCard(13)
                    }.buttonStyle(.plain)
                }
            }
        }.sheet(item: $selected) { market in
            MarketSheet(market: market).environment(\.layoutDirection, .rightToLeft)
        }
    }
}

struct MarketSheet: View {
    @EnvironmentObject private var store: NexusStore
    @Environment(\.dismiss) private var dismiss
    let market: NexusMarket
    @State private var asset: String = ""
    @State private var result: NexusResult?
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Picker("الأصل", selection: $asset) {
                        Text("اختر الأصل").tag("")
                        ForEach(market.assets) { item in Text(item.display).tag(item.key) }
                    }.pickerStyle(.menu).nexusCard()
                    GoldButton(label: "حلّل الشمعة القادمة", icon: "waveform.path", busy: store.busy) {
                        let key = asset
                        result = nil
                        Task { result = await store.analyze(market: market.key, asset: key) }
                    }.disabled(asset.isEmpty).opacity(asset.isEmpty ? 0.6 : 1)
                    if let result { ResultCard(result: result, showChart: true) }
                    else if let message = store.message { Text(message).font(.footnote).foregroundStyle(.red).nexusCard() }
                }.padding(16)
            }.background(Ink.paper.ignoresSafeArea()).navigationTitle(market.label).navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .navigationBarTrailing) { Button("تم") { dismiss() } } }
        }
    }
}

struct ModeSelector: View {
    @EnvironmentObject private var store: NexusStore
    var body: some View {
        HStack(spacing: 5) {
            option("معاير", "strong")
            option("LO · تجريبي", "lo")
        }.padding(4).background(Ink.rim.opacity(0.6), in: Capsule())
    }
    private func option(_ title: String, _ value: String) -> some View {
        Button { store.mode = value } label: {
            Text(title).font(.subheadline.bold()).frame(maxWidth: .infinity, minHeight: 41)
                .foregroundStyle(store.mode == value ? Ink.navy : Ink.mute)
                .background(store.mode == value ? Ink.gold : .clear, in: Capsule())
        }.buttonStyle(.plain).disabled(store.busy)
    }
}

struct ScanPage: View {
    @EnvironmentObject private var store: NexusStore
    var body: some View {
        Group {
            Text("التحليل التلقائي").font(.largeTitle.bold())
            ModeSelector()
            VStack(spacing: 11) {
                BadgeIcon(icon: "scope", size: 62)
                Text("افحص الأسواق المتاحة").font(.title3.bold())
                Text("يفحص كل سوق له مصدر، ويعرض نتائج الشموع الحقيقية فقط.")
                    .font(.subheadline).multilineTextAlignment(.center).foregroundStyle(Ink.mute)
                GoldButton(label: "افحص الآن", icon: "dot.radiowaves.left.and.right", busy: store.busy) {
                    Task { await store.runScan() }
                }.accessibilityIdentifier("nexus.scan.now")
            }.nexusCard(19)
            if let message = store.message {
                Text(message).font(.footnote).foregroundStyle(Ink.mute).nexusCard()
            }
            if let scan = store.scan {
                HStack(spacing: 10) {
                    Metric(title: "أسواق فحصناها", value: String(scan.checked), icon: "scope", tone: Ink.leaf)
                    Metric(title: "نتائج ببيانات حقيقية", value: String(scan.items.count), icon: "checkmark.circle", tone: Ink.leaf)
                }
                if !scan.unavailable.isEmpty {
                    Text("لم تتوفر شموع حديثة: " + scan.unavailable.joined(separator: " · "))
                        .font(.footnote).foregroundStyle(Ink.mute).nexusCard(12)
                }
                ForEach(scan.items) { ResultCard(result: $0, showChart: false) }
            }
        }
    }
}

struct ResultCard: View {
    let result: NexusResult
    var showChart: Bool
    var direction: String {
        switch result.direction {
        case "UP": return "صعود ↑"
        case "DOWN": return "هبوط ↓"
        default: return "لا إشارة"
        }
    }
    var tone: Color { result.direction == "UP" ? Ink.leaf : result.direction == "DOWN" ? .red : Ink.mute }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(result.asset).font(.headline)
                    Text("\(result.source) · \(result.frame)").font(.caption).foregroundStyle(Ink.mute)
                }
                Spacer()
                Text(direction).font(.caption.bold()).padding(8).foregroundStyle(tone)
                    .background(tone.opacity(0.11), in: Capsule())
            }
            if let date = NexusResult.date(result.targetAt) {
                Text("افتتاح الشمعة المستهدفة " + date.formatted(date: .omitted, time: .standard))
                    .font(.footnote.bold())
            }
            if let confidence = result.confidence {
                Text("الثقة المعايرة \(Int(confidence.rounded()))٪").font(.caption).foregroundStyle(Ink.mute)
            } else if result.mode == "lo" {
                Text("LO · تقدير فني غير معاير").font(.caption).foregroundStyle(Ink.mute)
            }
            let trend = ["UP": "صاعد", "DOWN": "هابط", "RANGE": "عرضي"][result.trend ?? ""] ?? "—"
            let volatility = ["LOW": "منخفض", "NORMAL": "طبيعي", "HIGH": "عالٍ"][result.volatility ?? ""] ?? "—"
            Text("الترند " + trend + " · التذبذب " + volatility).font(.footnote).foregroundStyle(Ink.mute)
            if let reason = result.reasons.first { Text(reason).font(.caption).foregroundStyle(Ink.mute) }
            if showChart { CandleCanvas(candles: result.candles) }
        }.nexusCard(15)
    }
}

struct ResultsPage: View {
    @EnvironmentObject private var store: NexusStore
    @State private var selection = 0
    var body: some View {
        Group {
            Text("النتائج").font(.largeTitle.bold())
            HStack(spacing: 9) {
                Metric(title: "إجمالي التحليلات", value: String(store.history.count), icon: "chart.bar", tone: Ink.leaf)
                Metric(title: "نشطة الآن", value: String(store.history.filter(\.live).count), icon: "waveform.path", tone: Ink.leaf)
            }
            Picker("الفترة", selection: $selection) {
                Text("الكل").tag(0)
                Text("نشطة").tag(1)
                Text("منتهية").tag(2)
            }.pickerStyle(.segmented)
            let entries = store.history.filter { selection == 0 || (selection == 1 ? $0.live : !$0.live) }
            if entries.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("ما فيه نتائج هنا للحين").font(.headline)
                    Text("تظهر نتائج الفحص والتحليل على هذا الجهاز. انتهاء الإشارة لا يعني نتيجة صفقة.")
                        .font(.footnote).foregroundStyle(Ink.mute)
                }.nexusCard()
            }
            ForEach(entries) { ResultCard(result: $0, showChart: false) }
        }
    }
}

struct SettingsPage: View {
    @EnvironmentObject private var store: NexusStore
    var body: some View {
        Group {
            Text("الإعدادات").font(.largeTitle.bold())
            VStack(alignment: .leading, spacing: 13) {
                Text("تخصيص NEXUS").font(.headline)
                TextField("اسمك لبطاقة الترحيب", text: $store.name).textFieldStyle(.roundedBorder)
                Text("اتصال المحرك").font(.headline)
                TextField("https://…", text: $store.address).keyboardType(.URL)
                    .textInputAutocapitalization(.never).autocorrectionDisabled().textFieldStyle(.roundedBorder)
                    .environment(\.layoutDirection, .leftToRight)
                SecureField("رمز اتصال الخادم", text: $store.access).autocorrectionDisabled().textFieldStyle(.roundedBorder)
                    .textInputAutocapitalization(.never)
                GoldButton(label: "حفظ واختبار الاتصال", icon: "network", busy: store.busy) {
                    store.saveProfile()
                    Task { await store.connect() }
                }.accessibilityIdentifier("nexus.connect")
                Text(store.connected ? "اتصل المحرك بنجاح" : (store.message ?? "حالة الاتصال لم تتحقق بعد"))
                    .font(.footnote).foregroundStyle(store.connected ? Ink.leaf : Ink.mute)
            }.nexusCard()
        }
    }
}

struct ChartPhotoPage: View {
    @EnvironmentObject private var store: NexusStore
    @State private var selected: PhotosPickerItem?
    @State private var bytes: Data?
    @State private var result: String?
    @State private var camera = false
    @State private var localError: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            Text("صورة الشارت").font(.title2.bold())
            Text("اختر صورة واضحة ومتضمنة السعر والإطار، ثم اضغط تحليل لإرسالها للمحرك.")
                .font(.subheadline).foregroundStyle(Ink.mute)
            if let bytes, let image = UIImage(data: bytes) {
                Image(uiImage: image).resizable().scaledToFit().frame(maxHeight: 180).frame(maxWidth: .infinity)
            } else {
                BadgeIcon(icon: "icloud.and.arrow.up", size: 63).frame(maxWidth: .infinity, minHeight: 98)
            }
            HStack {
                PhotosPicker(selection: $selected, matching: .images) {
                    Label("المعرض", systemImage: "photo.on.rectangle").font(.subheadline.bold())
                        .frame(maxWidth: .infinity, minHeight: 44).background(Ink.paper, in: RoundedRectangle(cornerRadius: 12))
                }.buttonStyle(.plain)
                if UIImagePickerController.isSourceTypeAvailable(.camera) {
                    Button { camera = true } label: {
                        Label("الكاميرا", systemImage: "camera").font(.subheadline.bold())
                            .frame(maxWidth: .infinity, minHeight: 44).background(Ink.paper, in: RoundedRectangle(cornerRadius: 12))
                    }.buttonStyle(.plain)
                }
            }
            GoldButton(label: "حلّل الصورة", icon: "sparkles", busy: store.busy) {
                if let bytes { Task { result = await store.analyzeImage(bytes) } }
            }.disabled(bytes == nil || !store.vision).opacity(bytes == nil || !store.vision ? 0.56 : 1)
            if !store.vision { Text("تحليل الصور يحتاج اتصالاً بخادم فيه مزوّد صور مفعّل.").font(.footnote).foregroundStyle(Ink.mute) }
            if let localError { Text(localError).font(.footnote).foregroundStyle(.red) }
            if let result { Text(result).font(.subheadline).textSelection(.enabled) }
            else if let message = store.message { Text(message).font(.footnote).foregroundStyle(Ink.mute) }
        }.nexusCard()
            .task(id: selected) {
                guard let selected else { return }
                defer { self.selected = nil }
                guard let data = try? await selected.loadTransferable(type: Data.self), !Task.isCancelled,
                      let image = UIImage(data: data) else {
                    if !Task.isCancelled { localError = "تعذر فتح الصورة." }
                    return
                }
                prepare(image)
            }
            .sheet(isPresented: $camera) { CameraPicker { prepare($0) }.ignoresSafeArea() }
    }

    private func prepare(_ image: UIImage) {
        let scale = min(1, 1800 / max(1, max(image.size.width, image.size.height)))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let resized = UIGraphicsImageRenderer(size: size, format: format).image { _ in image.draw(in: CGRect(origin: .zero, size: size)) }
        bytes = resized.jpegData(compressionQuality: 0.85)
        result = nil
        localError = bytes == nil ? "تعذر تجهيز الصورة." : nil
    }
}

struct CameraPicker: UIViewControllerRepresentable {
    let completion: (UIImage) -> Void
    @Environment(\.dismiss) private var dismiss
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }
    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}
    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let parent: CameraPicker
        init(_ parent: CameraPicker) { self.parent = parent }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { parent.dismiss() }
        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let image = info[.originalImage] as? UIImage { parent.completion(image) }
            parent.dismiss()
        }
    }
}
