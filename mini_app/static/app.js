/* ROZLF AI Mini App controller — cached navigation, real engine data only. */
(function () {
  const api = window.RozlfApi;
  const tg = api.tg;
  const view = document.getElementById("view");
  const pill = document.getElementById("connection-pill");
  const sheet = document.getElementById("sheet");
  const sheetBody = document.getElementById("sheet-body");
  const backdrop = document.getElementById("sheet-backdrop");
  const toastEl = document.getElementById("toast");

  const cache = { bootstrap: null, markets: null, recommendations: null, history: null, settings: null, market: new Map() };
  const seenAt = {};
  const inflight = {};
  const state = {
    route: "home",
    marketKey: null,
    selectedAsset: null,
    selectedDuration: null,
    analyzing: false,
  };

  if (tg) {
    tg.ready();
    tg.expand();
    if (tg.setHeaderColor) tg.setHeaderColor("#05080b");
    if (tg.setBackgroundColor) tg.setBackgroundColor("#05080b");
    if (tg.setBottomBarColor) tg.setBottomBarColor("#05080b");
    if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();
  }

  function haptic() {
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
  }
  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove("show"), 2600);
  }
  function setPill(mode, text) {
    pill.className = "signal-pill " + (mode || "");
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
  backdrop.addEventListener("click", closeSheet);
  sheet.addEventListener("click", (event) => {
    if (event.target.closest("[data-close]")) closeSheet();
  });

  async function cached(key, loader, maxAge) {
    const fresh = cache[key] && Date.now() - (seenAt[key] || 0) < (maxAge == null ? 45000 : maxAge);
    if (fresh) return cache[key];
    if (inflight[key]) return inflight[key];
    inflight[key] = loader()
      .then((data) => {
        cache[key] = data;
        seenAt[key] = Date.now();
        return data;
      })
      .finally(() => {
        delete inflight[key];
      });
    return inflight[key];
  }

  function liveMarkets(data) {
    return (data && data.markets ? data.markets : []).filter((market) => market.status === "LIVE").length;
  }
  function engineLive(data, liveCount) {
    return Boolean(data && data.api && data.api.telegram && liveCount > 0);
  }
  function skeleton(type) {
    if (type === "market") {
      return '<div class="skeleton"><div class="sk-block sk-market"></div><div class="sk-block sk-chart"></div><div class="sk-row"><span class="sk-block sk-chip"></span><span class="sk-block sk-chip"></span><span class="sk-block sk-chip"></span></div></div>';
    }
    return '<div class="skeleton"><div class="sk-block sk-hero"></div><div class="sk-row"><span class="sk-block sk-gem"></span><span class="sk-block sk-gem"></span><span class="sk-block sk-gem"></span></div><div class="sk-block sk-card"></div><div class="sk-block sk-card"></div></div>';
  }

  function errorView(error) {
    const noAuth = error && error.code === "NO_TELEGRAM_INIT_DATA";
    setPill("down", noAuth ? "TELEGRAM ONLY" : "API OFFLINE");
    view.innerHTML =
      '<section class="error-card"><div class="eyebrow">ROZLF AI · SECURE ACCESS</div>' +
      "<h1>" + (noAuth ? "افتح التطبيق<br><span>من داخل Telegram</span>" : "المحرك غير متاح<br><span>مؤقتاً</span>") + "</h1>" +
      "<p>" + api.esc((error && error.message) || "تعذر الوصول إلى خادم ROZLF AI.") + "</p>" +
      '<button class="btn block" data-retry="1">إعادة المحاولة</button></section>';
    view.querySelector("[data-retry]").addEventListener("click", () => navigate(state.route, true));
  }

  function empty(text, sub) {
    return '<div class="empty"><strong>' + text + "</strong>" + (sub ? "<small>" + sub + "</small>" : "") + "</div>";
  }

  function assetCount(market) {
    if (Array.isArray(market.assets)) return market.assets.length;
    return Number(market.assets || 0);
  }

  function marketCard(market) {
    const live = market.status === "LIVE";
    return (
      '<button class="market-card ' + (market.key === "LUXURY" ? "is-gold" : "") + (live ? " is-live" : "") + '" data-market="' + api.esc(market.key) + '">' +
      '<span class="card-top"><span class="market-icon">' + api.esc(market.icon) + '</span><span class="status-dot ' + (live ? "live" : "down") + '">' + (live ? "LIVE" : "OFFLINE") + "</span></span>" +
      "<h3>" + api.esc(market.label) + "</h3>" +
      "<small>" + assetCount(market) + " أصول · " + api.esc(market.source || "لا يوجد مصدر متاح") + "</small>" +
      '<span class="card-cta">' + (live ? "افتح السوق" : "عرض الحالة") + " ‹</span></button>"
    );
  }

  function metric(label, value) {
    return '<div class="metric"><small>' + label + "</small><strong>" + api.esc(value) + "</strong></div>";
  }

  function resultHtml(result) {
    const tradeable = result.direction === "UP" || result.direction === "DOWN";
    const name = result.direction === "UP" ? "شراء · UP" : result.direction === "DOWN" ? "بيع · DOWN" : "لا توجد فرصة";
    const nameClass = result.direction === "UP" ? "up" : result.direction === "DOWN" ? "down" : "wait";
    const confidence = result.confidence == null ? "—" : Math.round(result.confidence) + "%";
    const pct = result.confidence == null ? 0 : Math.max(0, Math.min(100, result.confidence));
    const reasons = (result.reasons || []).map((reason) => "<li>" + api.esc(reason) + "</li>").join("");
    return (
      '<div class="result-card' + (tradeable ? "" : " no-trade") + '">' +
      '<div class="result-top"><div><div class="eyebrow">ROZLF AI SIGNAL</div><div class="signal-name ' + nameClass + '">' + api.esc(name) + "</div></div>" +
      (tradeable ? '<div class="conf-ring" style="--pct:' + pct + '%"><span>' + confidence + "</span></div>" : "") + "</div>" +
      '<div class="result-grid">' +
      metric("السوق", result.market_label || "—") + metric("الأصل", result.asset || "—") +
      metric("المدة", result.duration_label || "—") + metric("السعر", result.price_display || "—") +
      metric("الاتجاه", result.trend || "—") + metric("الزخم", result.momentum || "—") +
      metric("المصدر", result.source || "—") + metric("الفريم", result.timeframe || "—") +
      "</div>" +
      (reasons ? '<div class="eyebrow">أسباب الإشارة</div><ul class="reasons">' + reasons + "</ul>" : "") +
      (result.direction === "NO TRADE" ? '<div class="note">' + api.esc(result.note || result.no_trade_reason || "لا توجد أدلة كافية، ولم تُفرض إشارة.") + "</div>" : "") +
      "</div>"
    );
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
        drawMarket(cache.market.get(state.marketKey));
      });
    });
    root.querySelectorAll("[data-duration]").forEach((element) => {
      element.addEventListener("click", () => {
        state.selectedDuration = Number(element.dataset.duration);
        drawMarket(cache.market.get(state.marketKey));
      });
    });
    root.querySelectorAll("[data-retry]").forEach((element) => {
      element.addEventListener("click", () => navigate(state.route, true, state.marketKey));
    });
  }

  function paintHome(data, recs, history) {
    const liveCount = liveMarkets(data);
    const live = engineLive(data, liveCount);
    setPill(liveCount ? "live" : "down", liveCount ? "DATA LIVE" : "API OFFLINE");
    const aiOnline = data.api && data.api.ai;
    const opportunities = recs && recs.items && recs.items.length
      ? recs.items.map((item) => (
          '<div class="feed-row"><div class="feed-main"><strong>' + api.esc(item.icon + " " + item.asset) + "</strong><small>" +
          api.esc(item.market_label + " · " + item.duration_label) + '</small></div><span class="feed-tag ' +
          (item.direction === "UP" ? "live" : "down") + '">' + api.esc(item.direction) + " · " + Math.round(item.confidence) + "%</span></div>"
        )).join("")
      : empty("NO VALID RECOMMENDATIONS RIGHT NOW.", "لن تظهر إشارة بدون أدلة حقيقية.");
    const latest = history && history.signals && history.signals.length
      ? history.signals.slice(0, 4).map((signal) => (
          '<div class="feed-row"><div class="feed-main"><strong>' + api.esc(signal.asset) + "</strong><small>" +
          api.esc(signal.market_label + " · " + signal.duration_label + " · " + signal.status) + '</small></div><span class="feed-tag gold">' +
          Math.round(signal.confidence) + "%</span></div>"
        )).join("")
      : empty("لا توجد إشارات مسجلة بعد.", "ستظهر النتائج المتحققة هنا فقط.");

    view.innerHTML =
      '<section class="hero-deck">' +
      '<div class="hero-orbit" aria-hidden="true"><span></span><i></i></div>' +
      '<div class="eyebrow">ADVANCED TRADING INTELLIGENCE</div>' +
      '<h1>ROZLF <span>AI</span></h1>' +
      '<p class="hero-line">ستة أسواق مستقلة · محرك تحليل واحد · بيانات حقيقية فقط</p>' +
      '<div class="metric-rail">' +
      '<div class="rail-item"><small>ENGINE</small><strong class="' + (live ? "up" : "wait") + '">' + (live ? "LIVE" : "OFFLINE") + "</strong></div>" +
      '<div class="rail-item"><small>MARKETS</small><strong>' + liveCount + "<span>/" + (data.total_markets || 6) + "</span></strong></div>" +
      '<div class="rail-item"><small>UPDATED</small><strong>' + api.fmtTime(data.last_update) + "</strong></div>" +
      "</div>" +
      '<div class="hero-actions"><button class="btn primary" data-route="analysis">◎ ابدأ التحليل</button><button class="btn ghost" data-route="recommendations">✦ الفرص</button></div>' +
      "</section>" +
      '<section class="strip"><span class="strip-label">SYSTEM</span>' +
      '<span class="strip-item"><i class="' + (live ? "on" : "") + '"></i>ENGINE ' + (live ? "CONNECTED" : "OFFLINE") + "</span>" +
      '<span class="strip-item"><i class="' + (aiOnline ? "on" : "") + '"></i>MISTRAL ' + (aiOnline ? "ONLINE" : "OFFLINE") + "</span>" +
      "</section>" +
      '<section class="block"><div class="block-head"><h2>الأسواق</h2><span class="count">' + liveCount + "/" + (data.total_markets || 6) + ' LIVE</span></div><div class="market-grid">' +
      (data.markets || []).map(marketCard).join("") + "</div></section>" +
      '<section class="block"><div class="block-head"><h2>أفضل الفرص</h2><button class="link-btn" data-route="recommendations">الكل ‹</button></div><div class="feed">' + opportunities + "</div></section>" +
      '<section class="block"><div class="block-head"><h2>آخر التحليلات</h2><button class="link-btn" data-route="history">السجل ‹</button></div><div class="feed">' + latest + "</div></section>";
    bind(view);
  }

  async function loadFeed(key, loader, force) {
    try {
      return await cached(key, loader, force ? 0 : 45000);
    } catch (error) {
      return cache[key] || null;
    }
  }

  async function renderHome(force) {
    const hadData = Boolean(cache.bootstrap);
    if (!hadData) view.innerHTML = skeleton();
    const boot = await cached("bootstrap", () => api.bootstrap, force ? 0 : 45000).catch((error) => {
      if (!hadData) errorView(error);
      return null;
    });
    if (!boot) {
      if (hadData) paintHome(cache.bootstrap, cache.recommendations, cache.history);
      return;
    }
    paintHome(boot, cache.recommendations, cache.history);
    const [recs, history] = await Promise.all([
      loadFeed("recommendations", () => api.recommendations, force),
      loadFeed("history", () => api.history, force),
    ]);
    if (state.route === "home") paintHome(cache.bootstrap || boot, recs, history);
  }

  async function renderMarkets(force) {
    const hadData = Boolean(cache.markets);
    if (!hadData) view.innerHTML = skeleton();
    const data = await cached("markets", () => api.markets, force ? 0 : 45000).catch((error) => {
      if (!hadData) errorView(error);
      return null;
    });
    if (!data) {
      if (hadData) renderMarketsFrom(cache.markets);
      return;
    }
    renderMarketsFrom(data);
  }

  function renderMarketsFrom(data) {
    const count = liveMarkets(data);
    const cards = (data.markets || []).map(marketCard).join("");
    setPill(count ? "live" : "down", count ? "DATA LIVE" : "API OFFLINE");
    view.innerHTML =
      '<div class="page-head"><div class="eyebrow">SIX INDEPENDENT MARKETS</div><h1>الأسواق</h1>' +
      "<p>" + count + " من " + (data.total_markets || 6) + " أسواق متصلة بمصادر بيانات حقيقية.</p></div>" +
      '<div class="market-grid wide">' + cards + "</div>" +
      '<div class="info-card"><strong>كل سوق بمحركه الخاص</strong><span>لا تُستخدم مؤشرات سوق على سوق آخر، وعند غياب البيانات يتوقف التحليل بدل اختلاق نتيجة.</span></div>';
    bind(view);
  }

  async function renderAnalysisPicker() {
    if (!cache.markets) {
      view.innerHTML = skeleton();
      await cached("markets", () => api.markets, 45000).catch((error) => {
        errorView(error);
        return null;
      });
    }
    const data = cache.markets;
    if (!data) return;
    view.innerHTML =
      '<div class="page-head"><div class="eyebrow">ANALYSE INDEPENDENTLY</div><h1>تحليل سوق</h1>' +
      "<p>اختر السوق، ثم الأصل ومدة الصفقة. القرار يعتمد على الأدلة الحقيقية فقط.</p></div>" +
      '<div class="market-grid">' + (data.markets || []).map(marketCard).join("") + "</div>" +
      '<div class="info-card gold"><strong>NO TRADE قرار صحيح</strong><span>عند نقص البيانات أو تعارض الأدلة لن تُفرض إشارة.</span></div>';
    bind(view);
  }

  async function renderMarket(key, force) {
    state.marketKey = key;
    const saved = cache.market.get(key);
    if (saved) {
      drawMarket(saved);
    } else {
      view.innerHTML = skeleton("market");
    }
    try {
      const market = await cached("m:" + key, () => api.market(key), force ? 0 : 30000);
      cache.market.set(key, market);
      if (!saved) {
        state.selectedAsset = market.assets && market.assets.length ? market.assets[0].key : null;
        state.selectedDuration = market.durations && market.durations.length ? market.durations[0] : null;
      }
      if (state.route === "market" && state.marketKey === key) drawMarket(market);
    } catch (error) {
      if (!saved) {
        view.innerHTML = '<div class="error-card"><h1>تعذر فتح السوق</h1><p>' + api.esc(error.message) +
          '</p><button class="btn block" data-route="markets">رجوع للأسواق</button></div>';
        bind(view);
      } else {
        toast("تعذر تحديث بيانات السوق — تُعرض آخر بيانات متاحة");
      }
    }
  }

  function durationLabel(seconds) {
    const map = { 30: "30 SEC", 60: "1 MIN", 120: "2 MIN", 180: "3 MIN", 300: "5 MIN" };
    return map[seconds] || seconds + " SEC";
  }

  function drawMarket(market) {
    if (!market) return;
    const assets = market.assets || [];
    const durations = market.durations || [];
    const live = market.status === "LIVE";
    const assetChips = assets.slice(0, 16).map((asset) => (
      '<button class="chip ' + (asset.key === state.selectedAsset ? "active" : "") + '" data-asset="' + api.esc(asset.key) + '">' + api.esc(asset.display) + "</button>"
    )).join("");
    const durationChips = durations.map((seconds) => (
      '<button class="chip gold ' + (seconds === state.selectedDuration ? "active" : "") + '" data-duration="' + seconds + '">' + durationLabel(seconds) + "</button>"
    )).join("");
    view.innerHTML =
      '<section class="market-head">' +
      '<div class="market-head-top"><div><div class="eyebrow">' + api.esc(market.icon + " " + market.label) + "</div>" +
      '<h1 class="price-hero">' + api.esc(market.price_display || "—") + "</h1>" +
      '<div class="price-meta">' + api.esc(live ? (market.source || "LIVE SOURCE") : "DATA UNAVAILABLE") +
      " · " + api.fmtTime(market.last_time) + '</div></div><span class="status-dot ' + (live ? "live" : "down") + '">' + (live ? "LIVE" : "OFFLINE") + "</span></div>" +
      '<div class="chart-frame"><canvas id="market-chart"></canvas><span class="chart-tag">' + (market.bars || 0) + " BARS · " + api.esc(market.timeframe || "—") + "</span></div>" +
      "</section>" +
      (!live ? '<div class="notice">هذا السوق غير متصل بمصدر بيانات موثوق. التحليل معطّل حتى تعود البيانات، ولا تُعرض أي إشارة تجريبية.</div>' : "") +
      '<section class="block"><div class="block-head"><h2>الأصول</h2><span class="count">' + assets.length + "</span></div>" +
      (assetChips ? '<div class="chip-row">' + assetChips + "</div>" : empty("لا توجد أصول حقيقية متاحة.", "سيظهر السوق عند توفر مصدره.")) + "</section>" +
      '<section class="block"><div class="block-head"><h2>مدة الصفقة</h2><span class="count">EXPIRY</span></div>' +
      (durationChips ? '<div class="chip-row">' + durationChips + "</div>" : "") +
      '<div class="action-stack"><button class="btn primary" id="analyse-btn"' + (live && assets.length && durations.length ? "" : " disabled") + ">◎ بدء التحليل</button>" +
      '<button class="btn ghost" id="smart-btn"' + (live && assets.length ? "" : " disabled") + ">🧠 ANALYZE TRADE TIME</button></div></section>" +
      '<section id="result-zone"></section>';
    bind(view);
    const canvas = document.getElementById("market-chart");
    if (canvas) window.RozlfChart.draw(canvas, market.candles || []);
    const analyse = document.getElementById("analyse-btn");
    if (analyse) analyse.addEventListener("click", () => runAnalysis(false, analyse));
    const smart = document.getElementById("smart-btn");
    if (smart) smart.addEventListener("click", () => runAnalysis(true, smart));
  }

  function loadingButton(button, text) {
    if (!button) return;
    button.dataset.label = button.textContent;
    button.textContent = text;
    button.classList.add("is-loading");
    button.disabled = true;
  }
  function restoreButton(button) {
    if (!button) return;
    button.textContent = button.dataset.label || button.textContent;
    button.classList.remove("is-loading");
    button.disabled = false;
  }

  async function runAnalysis(smart, button) {
    if (state.analyzing) return;
    const market = cache.market.get(state.marketKey);
    if (!market) return;
    const duration = smart ? null : state.selectedDuration;
    if (!smart && !duration) {
      toast("اختر مدة صفقة مدعومة أولاً");
      return;
    }
    state.analyzing = true;
    loadingButton(button, smart ? "يختار أفضل مدة…" : "جارٍ التحليل…");
    const zone = document.getElementById("result-zone");
    zone.innerHTML = '<div class="result-skeleton"><span></span><span></span><span></span><span></span></div>';
    try {
      const result = await api.analyse({ market: market.key, asset: state.selectedAsset, duration: duration });
      if (result.error) {
        zone.innerHTML = '<div class="notice red">' + api.esc(result.message || result.error) + '</div><button class="btn ghost block" id="retry-analysis">إعادة المحاولة</button>';
        const retry = document.getElementById("retry-analysis");
        if (retry) retry.addEventListener("click", () => runAnalysis(smart, button));
      } else {
        zone.innerHTML = '<div class="block-head"><h2>نتيجة التحليل</h2><span class="count">' + api.esc(result.direction) + "</span></div>" + resultHtml(result);
        haptic();
        zone.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } catch (error) {
      zone.innerHTML = '<div class="notice red">' + api.esc(error.message) + '</div><button class="btn ghost block" id="retry-analysis">إعادة المحاولة</button>';
      const retry = document.getElementById("retry-analysis");
      if (retry) retry.addEventListener("click", () => runAnalysis(smart, button));
      toast(error.message);
    } finally {
      state.analyzing = false;
      restoreButton(button);
    }
  }

  async function renderRecommendations(force) {
    const hadData = Boolean(cache.recommendations);
    if (!hadData) view.innerHTML = skeleton();
    const data = await loadFeed("recommendations", () => api.recommendations, force);
    if (!data) {
      if (!hadData) {
        view.innerHTML = '<div class="error-card"><h1>تعذر فحص الفرص</h1><p>المحرك غير متاح حالياً.</p><button class="btn block" data-retry="1">إعادة المحاولة</button></div>';
        bind(view);
      }
      return;
    }
    const items = data.items || [];
    setPill(items.length ? "live" : "", items.length ? "OPPORTUNITIES" : "SCANNED");
    view.innerHTML =
      '<div class="page-head"><div class="eyebrow">EVIDENCE-RANKED ONLY</div><h1>أفضل الفرص</h1>' +
      "<p>مرتبة حسب جودة الأدلة. الحد الأدنى للثقة " + api.esc(data.threshold) + "%.</p></div>" +
      (items.length ? '<div class="opportunity-list">' + items.map((item) => (
        '<article class="opportunity"><div class="opp-top"><span class="opp-icon">' + api.esc(item.icon) + "</span><div><strong>" + api.esc(item.asset) +
        "</strong><small>" + api.esc(item.market_label + " · " + item.duration_label) + '</small></div><span class="opp-dir ' +
        (item.direction === "UP" ? "up" : "down") + '">' + api.esc(item.direction) + "</span></div>" +
        '<p>' + api.esc(item.reason) + "</p>" +
        '<div class="opp-foot"><span>' + api.esc(item.source) + "</span><strong>" + Math.round(item.confidence) + "%</strong></div></article>"
      )).join("") + "</div>" : '<div class="feed">' + empty("NO VALID RECOMMENDATIONS RIGHT NOW.", "لا توجد فرصة مستوفية للأدلة والثقة حالياً.") + "</div>");
  }

  async function renderHistory(force) {
    const hadData = Boolean(cache.history);
    if (!hadData) view.innerHTML = skeleton();
    const data = await loadFeed("history", () => api.history, force);
    if (!data) {
      if (!hadData) {
        view.innerHTML = '<div class="error-card"><h1>تعذر تحميل السجل</h1><p>قاعدة البيانات غير متاحة حالياً.</p><button class="btn block" data-retry="1">إعادة المحاولة</button></div>';
        bind(view);
      }
      return;
    }
    const stats = data.stats || {};
    const rows = (data.signals || []).map((signal) => (
      '<div class="feed-row"><div class="feed-main"><strong>' + api.esc(signal.asset) + "</strong><small>" +
      api.esc(signal.market_label + " · " + signal.duration_label + " · " + api.fmtTime(signal.created_at)) + '</small></div><span class="feed-tag ' +
      (signal.status === "LOSS" ? "down" : signal.status === "WIN" ? "live" : "gold") + '">' + api.esc(signal.status) + "</span></div>"
    )).join("");
    view.innerHTML =
      '<div class="page-head"><div class="eyebrow">VERIFIED OUTCOMES ONLY</div><h1>السجل والأداء</h1><p>الإحصائيات من الإشارات المتحققة فقط.</p></div>' +
      '<div class="stat-grid">' +
      statBox("WIN RATE", stats.accuracy == null ? "—" : stats.accuracy + "%") + statBox("VERIFIED", stats.verified || 0) +
      statBox("WINS", stats.wins || 0) + statBox("LOSSES", stats.losses || 0) +
      statBox("PROFIT FACTOR", stats.profit_factor == null ? "—" : stats.profit_factor) + statBox("ACTIVE", stats.active || 0) +
      "</div>" +
      '<section class="block"><div class="block-head"><h2>آخر الإشارات</h2><span class="count">' + (data.signals || []).length + "</span></div><div class=\"feed\">" +
      (rows || empty("لا توجد إشارات مسجلة بعد.", "لن تُضاف نتيجة غير متحققة.")) + "</div></section>";
  }

  function statBox(label, value) {
    return '<div class="stat-box"><small>' + label + "</small><strong>" + api.esc(value) + "</strong></div>";
  }

  async function renderSettings(force) {
    const hadData = Boolean(cache.settings);
    if (!hadData) view.innerHTML = skeleton();
    const data = await loadFeed("settings", () => api.settings, force);
    if (!data) {
      view.innerHTML = '<div class="error-card"><h1>تعذر تحميل الإعدادات</h1><p>أعد المحاولة بعد قليل.</p><button class="btn block" data-retry="1">إعادة المحاولة</button></div>';
      bind(view);
      return;
    }
    const current = Number(data.settings.min_confidence || 0);
    const chips = (data.allowed || [50, 60, 70, 80, 90]).map((value) => (
      '<button class="chip gold ' + (value === current ? "active" : "") + '" data-min="' + value + '">' + value + "%</button>"
    )).join("");
    view.innerHTML =
      '<div class="page-head"><div class="eyebrow">ACCOUNT SETTINGS</div><h1>الإعدادات</h1><p>محفوظة في قاعدة البيانات ويستخدمها البوت والتطبيق معاً.</p></div>' +
      '<div class="panel"><div class="setting-row"><div><strong>الحد الأدنى لثقة الإشارة</strong><small>لا تُرفع الثقة قسراً ولا تظهر إشارة أقل من الحد.</small></div><span class="badge">' + current + "%</span></div>" +
      '<div class="chip-row">' + chips + '</div><button class="btn primary block" id="save-settings">حفظ الإعدادات</button></div>' +
      '<div class="panel"><div class="setting-row"><div><strong>محرك التحليل</strong><small>نفس محرك البوت ونفس المصادر.</small></div><span class="badge live">SHARED</span></div>' +
      '<div class="setting-row"><div><strong>الأسواق</strong><small>SMARTY · FOOTBALL · LUXURY · AI · CRICKET · FOREX</small></div><span class="badge">6</span></div></div>' +
      '<button class="btn ghost block" id="open-status">🖥️ حالة النظام والمصادر</button>';
    let selected = current;
    view.querySelectorAll("[data-min]").forEach((button) => {
      button.addEventListener("click", () => {
        selected = Number(button.dataset.min);
        view.querySelectorAll("[data-min]").forEach((item) => item.classList.toggle("active", item === button));
      });
    });
    document.getElementById("save-settings").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      loadingButton(button, "جارٍ الحفظ…");
      try {
        await api.saveSettings({ min_confidence: selected });
        cache.settings.settings.min_confidence = selected;
        toast("تم حفظ الإعدادات");
        haptic();
      } catch (error) {
        toast(error.message);
      } finally {
        restoreButton(button);
      }
    });
    document.getElementById("open-status").addEventListener("click", showStatus);
  }

  async function showStatus() {
    openSheet('<div class="sheet-head"><div><div class="eyebrow">SYSTEM HEALTH</div><h2>حالة النظام</h2></div><button class="icon-btn" data-close="1">✕</button></div>' + skeleton());
    let data;
    try {
      data = await api.status;
    } catch (error) {
      sheetBody.innerHTML = '<div class="sheet-head"><div><div class="eyebrow">SYSTEM HEALTH</div><h2>حالة النظام</h2></div><button class="icon-btn" data-close="1">✕</button></div>' +
        '<div class="notice red">' + api.esc(error.message) + "</div>";
      return;
    }
    const ai = data.ai || {};
    const sources = data.sources || {};
    const rows = Object.keys(sources).map((name) => {
      const source = sources[name] || {};
      const ok = source.ok === true || source.state === "ok" || source.status === "ok" || source.connected === true;
      return '<div class="feed-row"><div class="feed-main"><strong>' + api.esc(name) + "</strong><small>" +
        api.esc(source.detail || source.note || source.error || (ok ? "متصل" : "غير متاح")) + '</small></div><span class="feed-tag ' +
        (ok ? "live" : "down") + '">' + (ok ? "ONLINE" : "OFFLINE") + "</span></div>";
    }).join("");
    sheetBody.innerHTML =
      '<div class="sheet-head"><div><div class="eyebrow">SYSTEM HEALTH</div><h2>حالة النظام</h2></div><button class="icon-btn" data-close="1">✕</button></div>' +
      '<div class="stat-grid">' +
      statBox("TELEGRAM", data.telegram_configured ? "READY" : "MISSING") +
      statBox("AI ENGINE", ai.ok || ai.configured ? "ONLINE" : "OFFLINE") +
      statBox("BRIDGE", data.bridge_configured ? "READY" : "MISSING") +
      statBox("DATABASE", data.database || "—") +
      "</div>" +
      '<div class="eyebrow">DATA SOURCES</div>' +
      '<div class="feed">' + (rows || empty("لا توجد مصادر مسجلة.", "ستظهر هنا عند تهيئة المحرك.")) + "</div>";
    sheetBody.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", closeSheet));
  }

  function navigate(route, force, marketKey) {
    const allowed = { home: 1, markets: 1, analysis: 1, recommendations: 1, history: 1, settings: 1, market: 1 };
    if (!allowed[route]) route = "home";
    const changed = state.route !== route || (route === "market" && state.marketKey !== marketKey);
    state.route = route;
    setActiveTab(route);
    haptic();
    if (route === "home") return renderHome(force);
    if (route === "markets") return renderMarkets(force);
    if (route === "analysis") return renderAnalysisPicker();
    if (route === "recommendations") return renderRecommendations(force);
    if (route === "history") return renderHistory(force);
    if (route === "settings") return renderSettings(force);
    if (route === "market") return renderMarket(marketKey || state.marketKey, force || changed);
  }

  document.querySelectorAll("#tabbar button").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.route));
  });
  const settingsBtn = document.getElementById("settings-btn");
  if (settingsBtn) settingsBtn.addEventListener("click", () => navigate("settings"));

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (state.route === "home" && cache.bootstrap && Date.now() - (seenAt.bootstrap || 0) > 60000) {
      renderHome(false);
    }
  });

  const startRoute = (location.hash || "").replace("#", "");
  navigate(["markets", "recommendations", "history", "settings"].indexOf(startRoute) >= 0 ? startRoute : "home");
})();
