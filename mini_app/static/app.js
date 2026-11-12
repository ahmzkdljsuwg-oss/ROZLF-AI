/* ROZLF AI Mini App controller. All data comes from /api/mini (real engine). */
(function () {
  const api = window.RozlfApi;
  const tg = api.tg;
  const view = document.getElementById("view");
  const pill = document.getElementById("connection-pill");
  const loading = document.getElementById("loading");
  const loadingText = document.getElementById("loading-text");
  const sheet = document.getElementById("sheet");
  const sheetBody = document.getElementById("sheet-body");
  const backdrop = document.getElementById("sheet-backdrop");
  const toastEl = document.getElementById("toast");
  const state = {
    bootstrap: null,
    markets: [],
    market: null,
    selectedAsset: null,
    selectedDuration: null,
    lastResult: null,
    route: "home",
  };

  if (tg) {
    tg.ready();
    tg.expand();
    if (tg.setHeaderColor) tg.setHeaderColor("#04070a");
    if (tg.setBackgroundColor) tg.setBackgroundColor("#04070a");
    if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();
    if (tg.setBottomBarColor) tg.setBottomBarColor("#04070a");
    if (tg.enableClosingConfirmation) tg.enableClosingConfirmation();
  }

  function showLoading(text) {
    loadingText.textContent = text || "جارٍ الاتصال بالمحرك…";
    loading.classList.add("show");
  }
  function hideLoading() {
    loading.classList.remove("show");
  }
  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove("show"), 2600);
  }
  function setPill(mode, text) {
    pill.className = "status-pill " + (mode || "");
    pill.querySelector("span").textContent = text;
  }
  function setActiveTab(route) {
    const map = { market: "markets", status: "home" };
    const active = map[route] || route;
    document.querySelectorAll("#tabbar button").forEach((button) => {
      button.classList.toggle("active", button.dataset.route === active);
    });
  }
  function openSheet(html) {
    sheetBody.innerHTML = html;
    sheet.classList.add("open");
    backdrop.classList.add("open");
    sheet.setAttribute("aria-hidden", "false");
    sheet.scrollTop = 0;
  }
  function closeSheet() {
    sheet.classList.remove("open");
    backdrop.classList.remove("open");
    sheet.setAttribute("aria-hidden", "true");
  }
  function closeBtn() {
    return '<div class="sheet-title"><h3></h3><button data-close="1">×</button></div>';
  }
  backdrop.addEventListener("click", closeSheet);
  sheet.addEventListener("click", (event) => {
    if (event.target.closest("[data-close]")) closeSheet();
  });

  function errorView(error) {
    const noAuth = error && error.code === "NO_TELEGRAM_INIT_DATA";
    setPill("down", noAuth ? "TELEGRAM ONLY" : "OFFLINE");
    view.innerHTML =
      '<section class="hero fade-in"><div class="eyebrow">ROZLF AI · SECURE ACCESS</div>' +
      "<h1>" + (noAuth ? "افتح التطبيق<br><span>من داخل Telegram</span>" : "تعذر الاتصال<br><span>بمحرك التحليل</span>") + "</h1>" +
      "<p>" + api.esc((error && error.message) || "حدث خطأ غير متوقع.") + "</p>" +
      '<div class="analysis-actions"><button class="btn block" data-retry="1">إعادة المحاولة</button></div></section>';
    view.querySelector("[data-retry]").addEventListener("click", () => navigate(state.route, true));
  }

  function marketCard(market) {
    const live = market.status === "LIVE";
    return (
      '<button class="market-card ' + (market.key === "LUXURY" ? "gold" : "") + ' fade-in" data-market="' + api.esc(market.key) + '">' +
      '<span class="market-badge ' + (live ? "live" : "down") + '">' + (live ? "LIVE" : "UNAVAILABLE") + "</span>" +
      '<span class="market-icon">' + api.esc(market.icon) + "</span>" +
      "<h3>" + api.esc(market.label) + "</h3>" +
      "<small>" + (market.assets || 0) + " أصول متاحة · " + api.esc(market.source || "بيانات غير متاحة الآن") + "</small>" +
      "</button>"
    );
  }

  function liveMarkets(data) {
    return (data && data.markets ? data.markets : []).filter((m) => m.status === "LIVE").length;
  }

  function engineLive(data, liveCount) {
    return Boolean(data && data.api && data.api.telegram && liveCount > 0);
  }

  function signalBadge(direction) {
    if (direction === "UP") return '<span class="badge live">UP · شراء</span>';
    if (direction === "DOWN") return '<span class="badge down">DOWN · بيع</span>';
    return '<span class="badge">NO TRADE</span>';
  }

  function resultHtml(result) {
    if (!result) return "";
    const tradeable = result.direction === "UP" || result.direction === "DOWN";
    const cls = tradeable ? "" : " no-trade";
    const name = result.direction === "UP" ? "شراء · UP" : result.direction === "DOWN" ? "بيع · DOWN" : "لا توجد فرصة تداول";
    const nameClass = result.direction === "UP" ? "up" : result.direction === "DOWN" ? "down" : "wait";
    const confidence = result.confidence == null ? "—" : Math.round(result.confidence) + "%";
    const pct = result.confidence == null ? 0 : Math.max(0, Math.min(100, result.confidence));
    const reasons = (result.reasons || []).map((reason) => "<li>" + api.esc(reason) + "</li>").join("");
    return (
      '<div class="result-card' + cls + ' fade-in">' +
      '<div class="result-top"><div><div class="eyebrow">ROZLF AI SIGNAL</div>' +
      '<div class="signal-name ' + nameClass + '">' + api.esc(name) + "</div></div>" +
      (tradeable ? '<div class="conf-ring" style="--pct:' + pct + '%"><span>' + confidence + "</span></div>" : "") +
      "</div>" +
      '<div class="result-grid">' +
      metric("السوق", result.market_label || "—") +
      metric("الأصل", result.asset || "—") +
      metric("المدة", result.duration_label || "—") +
      metric("السعر", result.price_display || "—") +
      metric("الاتجاه", result.trend || "—") +
      metric("الزخم", result.momentum || "—") +
      metric("المصدر", result.source || "—") +
      metric("الفريم", result.timeframe || "—") +
      "</div>" +
      (reasons ? "<div class=\"eyebrow\">أسباب الإشارة</div><ul class=\"reasons\">" + reasons + "</ul>" : "") +
      (result.direction === "NO TRADE" ? '<div class="note">' + api.esc(result.note || result.no_trade_reason || "لا توجد أدلة كافية، ولم يتم فرض إشارة.") + "</div>" : "") +
      "</div>"
    );
  }

  function metric(label, value) {
    return '<div class="metric"><small>' + label + "</small><strong>" + api.esc(value) + "</strong></div>";
  }

  async function loadBootstrap() {
    const data = await api.bootstrap;
    state.bootstrap = data;
    state.markets = data.markets || [];
    const live = data.available_markets || 0;
    setPill(live ? "live" : "down", live ? "DATA LIVE" : "DATA OFFLINE");
    return data;
  }

  async function renderHome() {
    showLoading("جارٍ فحص الأسواق والمصادر…");
    try {
      const [data, recs, history] = await Promise.all([
        state.bootstrap ? Promise.resolve(state.bootstrap) : loadBootstrap(),
        api.recommendations.catch(() => ({ items: [] })),
        api.history.catch(() => ({ signals: [], stats: {} })),
      ]);
      const aiOnline = data.api && data.api.ai;
      const liveCount = liveMarkets(data);
      const live = engineLive(data, liveCount);
      setPill(liveCount ? "live" : "down", liveCount ? "DATA LIVE" : "DATA OFFLINE");
      const cards = (data.markets || []).map(marketCard).join("");
      const opportunities = (recs.items || []).length
        ? recs.items.map((item) => (
            '<div class="row"><div class="row-main"><strong>' + api.esc(item.icon + " " + item.asset) +
            "</strong><small>" + api.esc(item.market_label + " · " + item.duration_label + " · " + item.source) +
            '</small></div><div class="row-value">' + api.esc(item.direction === "UP" ? "UP" : "DOWN") + "</div></div>"
          )).join("")
        : '<div class="empty">NO VALID RECOMMENDATIONS RIGHT NOW.<br>لن تظهر إشارة بدون أدلة حقيقية.</div>';
      const latest = (history.signals || []).slice(0, 4).length
        ? history.signals.slice(0, 4).map((signal) => (
            '<div class="row"><div class="row-main"><strong>' + api.esc(signal.asset) +
            "</strong><small>" + api.esc(signal.market_label + " · " + signal.duration_label + " · " + signal.status) +
            '</small></div><div class="row-value ' + (signal.direction === "DOWN" ? "down" : "") + '">' +
            (signal.direction === "UP" ? "UP" : "DOWN") + " · " + Math.round(signal.confidence) + "%</div></div>"
          )).join("")
        : '<div class="empty">لا توجد إشارات مسجلة بعد.</div>';
      view.innerHTML =
        '<section class="hero fade-in"><div class="eyebrow">ADVANCED TRADING INTELLIGENCE</div>' +
        '<h1>ROZLF <span>AI</span><br>لوحة تحليل<br>احترافية</h1>' +
        "<p>ستة أسواق · محرك تحليل واحد · بيانات حقيقية فقط.<br><small>" +
        api.esc(data.brand.tagline) + " · " + api.esc(data.user ? data.user.name : "") + "</small></p>" +
        '<div class="hero-grid">' +
        '<div class="hero-stat"><small>ENGINE</small><strong>' + (live ? "LIVE" : "OFFLINE") + "</strong></div>" +
        '<div class="hero-stat"><small>MARKETS LIVE</small><strong>' + liveCount + "/" + (data.total_markets || 6) + "</strong></div>" +
        '<div class="hero-stat gold"><small>LAST UPDATE</small><strong>' + api.fmtTime(data.last_update) + "</strong></div>" +
        "</div>" +
        '<div class="analysis-actions"><button class="btn block" data-route="analysis">◎ بدء التحليل الآن</button></div>' +
        '<div class="row" style="margin-top:8px"><div class="row-main"><strong>SHARED ANALYSIS ENGINE</strong><small>نفس محرك البوت · نفس المصادر · نفس النتائج</small></div><span class="badge ' + (live ? "live" : "down") + '">' + (live ? "CONNECTED" : "DISCONNECTED") + "</span></div>" +
        '<div class="row"><div class="row-main"><strong>MISTRAL AI</strong><small>' + api.esc((data.api && data.api.ai_detail && data.api.ai_detail.model) || "technical engine only") + "</small></div><span class=\"badge " + (aiOnline ? "live" : "down") + '">' + (aiOnline ? "ONLINE" : "OFFLINE") + "</span></div>" +
        "</section>" +
        '<section class="section"><div class="section-head"><h2>الأسواق الستة</h2><button data-route="markets">الكل ›</button></div><div class="cards">' + cards + "</div></section>" +
        '<section class="section"><div class="section-head"><h2>أفضل الفرص الحالية</h2><button data-route="recommendations">الكل ›</button></div><div class="panel">' + opportunities + "</div></section>" +
        '<section class="section"><div class="section-head"><h2>آخر التحليلات</h2><button data-route="history">السجل ›</button></div><div class="panel">' + latest + "</div></section>";
      bind(view);
    } catch (error) {
      errorView(error);
    } finally {
      hideLoading();
    }
  }

  async function renderMarkets() {
    showLoading("جارٍ اكتشاف الأصول الحقيقية…");
    try {
      const data = await api.markets;
      state.markets = data.markets || [];
      const liveCount = liveMarkets(data);
      setPill(liveCount ? "live" : "down", liveCount ? "DATA LIVE" : "DATA OFFLINE");
      view.innerHTML =
        '<div class="page-head fade-in"><div class="eyebrow">SIX INDEPENDENT MARKETS</div><h1>الأسواق</h1>' +
        "<p>" + liveCount + " من " + (data.total_markets || 6) + " أسواق متصلة الآن بمصادر بيانات حقيقية.</p></div>" +
        '<div class="cards">' + state.markets.map(marketCard).join("") + "</div>";
      bind(view);
    } catch (error) {
      errorView(error);
    } finally {
      hideLoading();
    }
  }

  async function renderAnalysisPicker() {
    try {
      if (!state.markets.length) await loadBootstrap();
      view.innerHTML =
        '<div class="page-head fade-in"><div class="eyebrow">ANALYSE INDEPENDENTLY</div><h1>تحليل سوق</h1>' +
        "<p>اختر السوق ثم الأصل ومدة الصفقة. كل سوق يُحلَّل بمحركه الخاص، دون خلط بيانات.</p></div>" +
        '<div class="cards">' + state.markets.map(marketCard).join("") + "</div>" +
        '<div class="panel" style="margin-top:14px"><div class="row"><div class="row-main"><strong>NO TRADE هو قرار صحيح</strong><small>عندما لا توجد أدلة كافية لن تُفرض إشارة.</small></div><span class="badge">ENGINE RULE</span></div></div>';
      bind(view);
    } catch (error) {
      errorView(error);
    }
  }

  async function renderMarket(key) {
    showLoading("جارٍ تحميل الشارت والبيانات…");
    try {
      const market = await api.market(key);
      state.market = market;
      state.selectedAsset = market.assets && market.assets.length ? market.assets[0].key : null;
      state.selectedDuration = market.durations && market.durations.length ? market.durations[0] : null;
      state.lastResult = null;
      drawMarket();
    } catch (error) {
      view.innerHTML = '<div class="panel"><div class="empty">' + api.esc(error.message) + '</div><button class="btn ghost block" data-route="markets">رجوع</button></div>';
      bind(view);
    } finally {
      hideLoading();
    }
  }

  function drawMarket() {
    const market = state.market;
    const assets = market.assets || [];
    const durations = market.durations || [];
    const assetChips = assets.slice(0, 12).map((asset) => (
      '<button class="chip ' + (asset.key === state.selectedAsset ? "active" : "") + '" data-asset="' + api.esc(asset.key) + '">' + api.esc(asset.display) + "</button>"
    )).join("");
    const durationChips = durations.map((seconds) => (
      '<button class="chip gold ' + (seconds === state.selectedDuration ? "active" : "") + '" data-duration="' + seconds + '">' + durationLabel(seconds) + "</button>"
    )).join("");
    const live = market.status === "LIVE";
    view.innerHTML =
      '<div class="market-hero fade-in"><div class="market-hero-top"><div><div class="eyebrow">' + api.esc(market.icon + " " + market.label) + "</div>" +
      "<h1>" + api.esc(market.price_display || "DATA UNAVAILABLE") + "</h1>" +
      "<div class=\"price\"><small>" + api.esc(live ? "LAST PRICE · " + (market.source || "") : "المصدر غير متاح الآن — لن تُصدر إشارة بدون بيانات موثوقة") + "</small></div></div>" +
      '<span class="badge ' + (live ? "live" : "down") + '">' + (live ? "LIVE" : "UNAVAILABLE") + "</span></div>" +
      '<div class="chart-wrap"><canvas id="market-chart"></canvas></div>' +
      '<div class="row"><div class="row-main"><strong>مدة تحديث آخر شمعة</strong><small>' + api.esc(market.timeframe || "—") + " · " + api.fmtTime(market.last_time) + "</small></div>" +
      '<span class="badge">' + (market.bars || 0) + " BARS</span></div></div>" +
      '<section class="section"><div class="section-head"><h2>الأصول المتاحة</h2><span class="badge">' + assets.length + "</span></div>" +
      (assetChips ? '<div class="chip-row">' + assetChips + "</div>" : '<div class="panel"><div class="empty">لا توجد أصول حقيقية متاحة في هذا السوق.</div></div>') + "</section>" +
      '<section class="section"><div class="section-head"><h2>مدة الصفقة</h2><span class="badge">EXPIRY</span></div>' +
      (durationChips ? '<div class="chip-row">' + durationChips + "</div>" : "") +
      '<div class="analysis-actions"><button class="btn block" id="analyse-btn"' + (live && assets.length && durations.length ? "" : " disabled") + ">بدء التحليل</button>" +
      '<button class="btn ghost block" id="smart-btn"' + (live && assets.length ? "" : " disabled") + ">🧠 ANALYZE TRADE TIME</button></div>" +
      (!live ? '<div class="note" style="margin-top:10px">هذا السوق غير متصل بمصدر بيانات موثوق حالياً. التحليل معطّل حتى تعود البيانات، ولا تُعرض أي إشارة تجريبية.</div>' : "") +
      "</section>" +
      '<section id="result-zone"></section>';
    bind(view);
    const canvas = document.getElementById("market-chart");
    if (canvas) window.RozlfChart.draw(canvas, market.candles || []);
    const analyse = document.getElementById("analyse-btn");
    if (analyse) analyse.addEventListener("click", () => runAnalysis(false));
    const smart = document.getElementById("smart-btn");
    if (smart) smart.addEventListener("click", () => runAnalysis(true));
  }

  function durationLabel(seconds) {
    const map = { 30: "30 SEC", 60: "1 MIN", 120: "2 MIN", 180: "3 MIN", 300: "5 MIN" };
    return map[seconds] || seconds + " SEC";
  }

  async function runAnalysis(smart) {
    if (!state.market) return;
    const duration = smart ? null : state.selectedDuration;
    if (!smart && !duration) {
      toast("اختر مدة صفقة مدعومة أولاً");
      return;
    }
    showLoading(smart ? "🧠 يختار المحرك أفضل مدة…" : "🧠 المحرك يحلل الشموع الحقيقية…");
    try {
      const result = await api.analyse({ market: state.market.key, asset: state.selectedAsset, duration: duration });
      state.lastResult = result;
      const zone = document.getElementById("result-zone");
      if (result.error) {
        zone.innerHTML = '<div class="panel" style="margin-top:16px"><div class="empty">' + api.esc(result.message || result.error) + "</div></div>";
      } else {
        zone.innerHTML = '<section class="section"><div class="section-head"><h2>نتيجة التحليل</h2><span class="badge ' + (result.direction === "NO TRADE" ? "" : "live") + '">' + api.esc(result.direction) + "</span></div>" + resultHtml(result) + "</section>";
      }
      if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
      document.getElementById("result-zone").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      toast(error.message);
    } finally {
      hideLoading();
    }
  }

  async function renderRecommendations() {
    showLoading("🏆 فحص الأسواق الستة…");
    try {
      const data = await api.recommendations;
      setPill(data.items.length ? "live" : "", data.items.length ? "OPPORTUNITIES" : "SCANNED");
      const items = data.items || [];
      view.innerHTML =
        '<div class="page-head fade-in"><div class="eyebrow">EVIDENCE-RANKED ONLY</div><h1>أفضل الفرص</h1>' +
        "<p>مرتبة حسب جودة الأدلة والسوق. الحد الأدنى للثقة: " + api.esc(data.threshold) + "%.</p></div>" +
        (items.length ? items.map((item) => (
          '<div class="panel fade-in" style="margin-bottom:10px"><div class="row"><div class="row-main"><strong>' +
          api.esc(item.icon + " " + item.asset) + "</strong><small>" + api.esc(item.market_label + " · " + item.duration_label + " · " + item.source) +
          '</small></div><div class="row-value">' + Math.round(item.confidence) + "%</div></div>" +
          "<div class=\"row\"><div class=\"row-main\"><strong>" + (item.direction === "UP" ? "شراء · UP" : "بيع · DOWN") +
          "</strong><small>" + api.esc(item.reason) + "</small></div><span class=\"badge " + (item.direction === "UP" ? "live" : "down") + "\">" +
          api.esc(item.direction) + "</span></div></div>"
        )).join("") : '<div class="panel"><div class="empty">NO VALID RECOMMENDATIONS RIGHT NOW.<br>لا توجد فرصة مستوفية للأدلة والثقة حالياً.</div></div>');
      bind(view);
    } catch (error) {
      errorView(error);
    } finally {
      hideLoading();
    }
  }

  async function renderHistory() {
    showLoading("جارٍ تحميل السجل والإحصائيات…");
    try {
      const data = await api.history;
      const stats = data.stats || {};
      const rows = (data.signals || []).map((signal) => (
        '<div class="row"><div class="row-main"><strong>' + api.esc(signal.asset) + "</strong><small>" +
        api.esc(signal.market_label + " · " + signal.duration_label + " · " + api.fmtTime(signal.created_at)) +
        '</small></div><div class="row-value ' + (signal.status === "LOSS" ? "down" : signal.status === "WIN" ? "" : "gold") + '">' +
        api.esc(signal.status) + "</div></div>"
      )).join("");
      view.innerHTML =
        '<div class="page-head fade-in"><div class="eyebrow">VERIFIED OUTCOMES ONLY</div><h1>سجل الإشارات</h1>' +
        "<p>الإحصائيات تُحسب من النتائج المتحققة فقط، ولا تُحتسب الإشارات المفتوحة.</p></div>" +
        '<div class="panel"><div class="stat-grid">' +
        statBox("WIN RATE", stats.accuracy == null ? "—" : stats.accuracy + "%") +
        statBox("VERIFIED", stats.verified || 0) +
        statBox("WINS", stats.wins || 0) +
        statBox("LOSSES", stats.losses || 0) +
        statBox("PROFIT FACTOR", stats.profit_factor == null ? "—" : stats.profit_factor) +
        statBox("ACTIVE", stats.active || 0) +
        "</div></div>" +
        '<section class="section"><div class="section-head"><h2>آخر الإشارات</h2><span class="badge">' + (data.signals || []).length + "</span></div>" +
        '<div class="panel">' + (rows || '<div class="empty">لا توجد إشارات مسجلة بعد.</div>') + "</div></section>";
      bind(view);
    } catch (error) {
      errorView(error);
    } finally {
      hideLoading();
    }
  }

  function statBox(label, value) {
    return '<div class="stat-box"><small>' + label + "</small><strong>" + api.esc(value) + "</strong></div>";
  }

  async function renderSettings() {
    showLoading("جارٍ تحميل الإعدادات…");
    try {
      const data = await api.settings;
      const current = Number(data.settings.min_confidence || 0);
      const chips = (data.allowed || [50, 60, 70, 80, 90]).map((value) => (
        '<button class="chip gold ' + (value === current ? "active" : "") + '" data-min="' + value + '">' + value + "%</button>"
      )).join("");
      view.innerHTML =
        '<div class="page-head fade-in"><div class="eyebrow">ACCOUNT SETTINGS</div><h1>الإعدادات</h1>' +
        "<p>نفس إعداد البوت محفوظ في قاعدة البيانات ويُطبَّق على التطبيق أيضاً.</p></div>" +
        '<div class="panel"><div class="setting-row"><div><strong>الحد الأدنى لثقة الإشارة</strong><small>لن تظهر أي إشارة أقل من هذا الحد، ولن تُرفع الثقة قسراً.</small></div><span class="badge">' + current + "%</span></div>" +
        '<div class="chip-row" style="margin-top:12px">' + chips + "</div>" +
        '<button class="btn block" id="save-settings" style="margin-top:16px">حفظ الإعدادات</button></div>' +
        '<div class="panel" style="margin-top:12px"><div class="setting-row"><div><strong>محرك التحليل</strong><small>هذا التطبيق يستخدم محرك البوت نفسه مباشرة.</small></div><span class="badge live">SHARED</span></div>' +
        '<div class="setting-row"><div><strong>الأسواق</strong><small>SMARTY · FOOTBALL · LUXURY · AI · CRICKET · FOREX</small></div><span class="badge">6</span></div></div>' +
        '<button class="btn ghost block" id="open-status" style="margin-top:12px">🖥️ حالة النظام</button>';
      let selected = current;
      view.querySelectorAll("[data-min]").forEach((button) => {
        button.addEventListener("click", () => {
          selected = Number(button.dataset.min);
          view.querySelectorAll("[data-min]").forEach((item) => item.classList.toggle("active", item === button));
        });
      });
      document.getElementById("save-settings").addEventListener("click", async () => {
        showLoading("جارٍ حفظ الإعدادات…");
        try {
          await api.saveSettings({ min_confidence: selected });
          toast("تم حفظ الإعدادات");
        } catch (error) {
          toast(error.message);
        } finally {
          hideLoading();
        }
      });
      document.getElementById("open-status").addEventListener("click", showStatus);
      bind(view);
    } catch (error) {
      errorView(error);
    } finally {
      hideLoading();
    }
  }

  async function showStatus() {
    showLoading("جارٍ فحص حالة النظام…");
    try {
      const data = await api.status;
      const sources = (data.sources || []).map((source) => (
        '<div class="source-row"><div><strong>' + api.esc(source.name) + "</strong><small>" + api.esc((source.markets || []).join(", ")) +
        "</small></div><span class=\"badge " + (source.configured ? "live" : "down") + '">' + (source.configured ? "CONFIGURED" : "OFF") + "</span></div>"
      )).join("");
      openSheet(
        '<div class="sheet-title"><h3>حالة النظام</h3><button data-close="1">×</button></div>' +
        '<div class="panel"><div class="row"><div class="row-main"><strong>Telegram</strong><small>initData validation</small></div><span class="badge ' + (data.telegram_configured ? "live" : "down") + '">' + (data.telegram_configured ? "READY" : "MISSING") + "</span></div>" +
        '<div class="row"><div class="row-main"><strong>EO Bridge</strong><small>ExpertOption market data</small></div><span class="badge ' + (data.bridge_configured ? "live" : "down") + '">' + (data.bridge_configured ? "READY" : "MISSING") + "</span></div>" +
        '<div class="row"><div class="row-main"><strong>Mistral AI</strong><small>' + api.esc(data.ai.model || "") + "</small></div><span class=\"badge " + (data.ai.online ? "live" : "down") + '">' + (data.ai.online ? "ONLINE" : "OFFLINE") + "</span></div>" +
        '<div class="row"><div class="row-main"><strong>Database</strong><small>verified outcomes</small></div><span class="badge">' + api.esc((data.database || "").toUpperCase()) + "</span></div></div>" +
        '<section class="section"><div class="section-head"><h2>مصادر البيانات</h2></div><div class="source-list">' + sources + "</div></section>"
      );
    } catch (error) {
      toast(error.message);
    } finally {
      hideLoading();
    }
  }

  function bind(root) {
    root.querySelectorAll("[data-route]").forEach((element) => {
      element.addEventListener("click", () => navigate(element.dataset.route));
    });
    root.querySelectorAll("[data-market]").forEach((element) => {
      element.addEventListener("click", () => navigate("market", false, element.dataset.market));
    });
    root.querySelectorAll("[data-asset]").forEach((element) => {
      element.addEventListener("click", () => {
        state.selectedAsset = element.dataset.asset;
        drawMarket();
      });
    });
    root.querySelectorAll("[data-duration]").forEach((element) => {
      element.addEventListener("click", () => {
        state.selectedDuration = Number(element.dataset.duration);
        drawMarket();
      });
    });
  }

  async function navigate(route, force, key) {
    state.route = route;
    setActiveTab(route);
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (route === "home") return renderHome();
    if (route === "markets") return renderMarkets();
    if (route === "analysis") return renderAnalysisPicker();
    if (route === "market") return renderMarket(key || state.market.key);
    if (route === "recommendations") return renderRecommendations();
    if (route === "history") return renderHistory();
    if (route === "settings") return renderSettings();
    if (route === "status") return showStatus();
    return renderHome();
  }

  document.querySelectorAll("#tabbar button").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.route));
  });
  pill.addEventListener("click", () => navigate("home", true));
  const settingsBtn = document.getElementById("settings-btn");
  if (settingsBtn) settingsBtn.addEventListener("click", () => navigate("settings"));

  window.addEventListener("online", () => toast("عاد الاتصال بالإنترنت"));
  window.addEventListener("offline", () => {
    setPill("down", "NO NETWORK");
    toast("لا يوجد اتصال بالإنترنت");
  });

  if (!api.initData) {
    errorView(new api.ApiError("افتح التطبيق من داخل Telegram حتى يتم التحقق من هويتك.", "NO_TELEGRAM_INIT_DATA", 401));
    return;
  }
  navigate("home");
  window.addEventListener("resize", () => {
    const canvas = document.getElementById("market-chart");
    if (canvas && state.market) window.RozlfChart.draw(canvas, state.market.candles || []);
  });
  setInterval(() => {
    if (state.route === "home" && document.visibilityState === "visible") loadBootstrap().catch(() => {});
  }, 60000);
})();
