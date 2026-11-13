/* ROZLF AI Mini App controller — real engine data, four-state connection, EN/AR. */
(function () {
  const api = window.RozlfApi;
  const i18n = window.RozlfI18n;
  const t = (key, params) => i18n.t(key, params);
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
    connection: "CONNECTING",
  };

  if (tg) {
    tg.ready();
    tg.expand();
    if (tg.setHeaderColor) tg.setHeaderColor("#04070c");
    if (tg.setBackgroundColor) tg.setBackgroundColor("#04070c");
    if (tg.setBottomBarColor) tg.setBottomBarColor("#04070c");
    if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();
  }

  function haptic() {
    if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
  }
  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove("show"), 2800);
  }
  function setConnection(mode) {
    state.connection = mode;
    const key = "state." + mode.toLowerCase();
    pill.className = "signal-pill " + mode.toLowerCase();
    pill.querySelector("span").textContent = t(key);
    pill.setAttribute("aria-label", t(key));
  }
  function setActiveTab(route) {
    const map = { market: "markets" };
    const active = map[route] || route;
    document.querySelectorAll("#tabbar button").forEach((button) => {
      const on = button.dataset.route === active;
      button.classList.toggle("active", on);
      if (on) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
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
  function connectionFor(data) {
    if (!data) return "OFFLINE";
    const conn = data.connection || {};
    if (conn.service === "OFFLINE" || conn.api === "OFFLINE") return "OFFLINE";
    const live = liveMarkets(data);
    const total = Number(data.total_markets || (data.markets || []).length || 0);
    if (live === 0) return "OFFLINE";
    if (conn.engine === "OFFLINE") return "DEGRADED";
    return live === total ? "ONLINE" : "DEGRADED";
  }
  function skeleton(type) {
    if (type === "market") {
      return '<div class="skeleton"><div class="sk-block sk-market"></div><div class="sk-block sk-chart"></div><div class="sk-row"><span class="sk-block sk-chip"></span><span class="sk-block sk-chip"></span><span class="sk-block sk-chip"></span></div></div>';
    }
    return '<div class="skeleton"><div class="sk-block sk-hero"></div><div class="sk-row"><span class="sk-block sk-gem"></span><span class="sk-block sk-gem"></span><span class="sk-block sk-gem"></span></div><div class="sk-block sk-card"></div><div class="sk-block sk-card"></div></div>';
  }

  function errorView(error) {
    const noAuth = error && error.code === "NO_TELEGRAM_INIT_DATA";
    setConnection(noAuth ? "DEGRADED" : "OFFLINE");
    const heading = noAuth ? t("common.telegram_only") : t("common.engine_down");
    view.innerHTML =
      '<section class="error-card"><div class="eyebrow">' + api.esc(t("common.secure")) + "</div>" +
      "<h1>" + api.esc(heading) + "</h1>" +
      "<p>" + api.esc((error && error.message) || t("common.network")) + "</p>" +
      '<button class="btn block" data-retry="1">' + api.esc(t("common.retry")) + "</button></section>";
    view.querySelector("[data-retry]").addEventListener("click", () => navigate(state.route, true, state.marketKey));
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
      '<button class="market-card ' + (market.key === "LUXURY" ? "is-gold " : "") + (live ? "is-live" : "") + '" data-market="' + api.esc(market.key) + '">' +
      '<span class="card-top"><span class="market-icon">' + api.esc(market.icon) + '</span><span class="status-dot ' + (live ? "live" : "down") + '">' + (live ? "LIVE" : "UNAVAILABLE") + "</span></span>" +
      "<h3>" + api.esc(market.label) + "</h3>" +
      "<small>" + assetCount(market) + " · " + api.esc(market.source || t("market.no_assets_sub")) + "</small>" +
      '<span class="card-cta">' + api.esc(live ? t("market.open") : t("market.view_status")) + ' <span class="chev">›</span></span></button>'
    );
  }

  function metric(label, value) {
    return '<div class="metric"><small>' + api.esc(label) + "</small><strong>" + api.esc(value) + "</strong></div>";
  }

  function resultHtml(result) {
    const tradeable = result.direction === "UP" || result.direction === "DOWN";
    const name = result.direction === "UP" ? t("result.buy") : result.direction === "DOWN" ? t("result.sell") : t("result.no_trade");
    const nameClass = result.direction === "UP" ? "up" : result.direction === "DOWN" ? "down" : "wait";
    const confidence = result.confidence == null ? "—" : Math.round(result.confidence) + "%";
    const pct = result.confidence == null ? 0 : Math.max(0, Math.min(100, result.confidence));
    const reasons = (result.reasons || []).map((reason) => "<li>" + api.esc(reason) + "</li>").join("");
    return (
      '<div class="result-card' + (tradeable ? "" : " no-trade") + '">' +
      '<div class="result-top"><div><div class="eyebrow">' + api.esc(t("result.eyebrow")) + '</div><div class="signal-name ' + nameClass + '">' + api.esc(name) + "</div></div>" +
      (tradeable ? '<div class="conf-ring" style="--pct:' + pct + '%"><span>' + confidence + "</span></div>" : "") + "</div>" +
      '<div class="result-grid">' +
      metric(t("result.market"), result.market_label || "—") + metric(t("result.asset"), result.asset || "—") +
      metric(t("result.duration"), result.duration_label || "—") + metric(t("result.price"), result.price_display || "—") +
      metric(t("result.trend"), result.trend || "—") + metric(t("result.momentum"), result.momentum || "—") +
      metric(t("result.source"), result.source || "—") + metric(t("result.frame"), result.timeframe || "—") +
      "</div>" +
      (reasons ? '<div class="eyebrow">' + api.esc(t("result.reasons")) + '</div><ul class="reasons">' + reasons + "</ul>" : "") +
      (result.direction === "NO TRADE" ? '<div class="note">' + api.esc(result.note || result.no_trade_reason || t("result.no_evidence")) + "</div>" : "") +
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
    const total = Number(data.total_markets || 6);
    const engine = (data.connection && data.connection.engine) || (data.api && data.api.telegram ? "ONLINE" : "OFFLINE");
    const opportunities = recs && recs.items && recs.items.length
      ? recs.items.slice(0, 4).map((item) => (
          '<div class="feed-row"><div class="feed-main"><strong>' + api.esc(item.icon + " " + item.asset) + "</strong><small>" +
          api.esc((item.market_label || item.market || "—") + " · " + (item.duration_label || "—")) + '</small></div><span class="feed-tag ' +
          (item.direction === "UP" ? "live" : "down") + '">' + api.esc(item.direction) + " · " + Math.round(item.confidence) + "%</span></div>"
        )).join("")
      : empty(api.esc(t("home.no_recs")), api.esc(t("home.no_recs_sub")));
    const latest = history && history.signals && history.signals.length
      ? history.signals.slice(0, 4).map((signal) => (
          '<div class="feed-row"><div class="feed-main"><strong>' + api.esc(signal.asset) + "</strong><small>" +
          api.esc((signal.market_label || signal.market || "—") + " · " + (signal.duration_label || "—") + " · " + signal.status) + '</small></div><span class="feed-tag gold">' +
          Math.round(signal.confidence) + "%</span></div>"
        )).join("")
      : empty(api.esc(t("home.no_signals")), api.esc(t("home.no_signals_sub")));

    view.innerHTML =
      '<section class="hero">' +
      '<div class="hero-top"><div><div class="eyebrow">' + api.esc(t("home.eyebrow")) + '</div><h1 class="wordmark">ROZLF <span>AI</span></h1><p class="tagline">' + api.esc(t("brand.tagline")) + "</p></div>" +
      '<div class="hero-orb" aria-hidden="true"><span></span></div></div>' +
      '<p class="hero-copy">' + api.esc(t("home.subtitle")) + "</p>" +
      '<div class="rail">' +
      '<div class="rail-cell"><small>' + api.esc(t("home.engine")) + '</small><strong class="' + (engine === "ONLINE" ? "ok" : "warn") + '">' + api.esc(engine) + "</strong></div>" +
      '<div class="rail-cell"><small>' + api.esc(t("home.markets")) + '</small><strong>' + liveCount + " / " + total + "</strong></div>" +
      '<div class="rail-cell"><small>' + api.esc(t("home.updated")) + '</small><strong class="time">' + api.esc(api.fmtTime(data.last_update)) + "</strong></div>" +
      "</div>" +
      '<div class="hero-actions"><button class="btn" data-route="analysis">◎ ' + api.esc(t("home.start")) + '</button>' +
      '<button class="btn ghost" data-route="opportunities">✦ ' + api.esc(t("home.opportunities")) + "</button></div>" +
      "</section>" +
      '<section class="section"><div class="section-head"><h2>' + api.esc(t("home.markets_title")) + '</h2><button class="link" data-route="markets">' + api.esc(t("home.all")) + " ›</button></div>" +
      '<div class="market-grid">' + (data.markets || []).map(marketCard).join("") + "</div></section>" +
      '<section class="section"><div class="section-head"><h2>' + api.esc(t("home.top_opportunities")) + '</h2><button class="link" data-route="opportunities">' + api.esc(t("home.all")) + " ›</button></div>" +
      '<div class="glass-list">' + opportunities + "</div></section>" +
      '<section class="section"><div class="section-head"><h2>' + api.esc(t("home.recent")) + '</h2><button class="link" data-route="history">' + api.esc(t("home.log")) + " ›</button></div>" +
      '<div class="glass-list">' + latest + "</div></section>";
    bind(view);
  }

  async function drawHome(force) {
    setActiveTab("home");
    if (!cache.bootstrap || force) view.innerHTML = skeleton("home");
    try {
      const data = await cached("bootstrap", () => api.once("/api/mini/bootstrap"), force ? 0 : 45000);
      setConnection(connectionFor(data));
      let recs = cache.recommendations;
      let history = cache.history;
      const [recsResult, historyResult] = await Promise.allSettled([
        cached("recommendations", () => api.once("/api/mini/recommendations"), force ? 0 : 60000),
        cached("history", () => api.once("/api/mini/history?limit=8"), force ? 0 : 45000),
      ]);
      if (recsResult.status === "fulfilled") recs = recsResult.value;
      if (historyResult.status === "fulfilled") history = historyResult.value;
      if (state.route !== "home") return;
      paintHome(data, recs, history);
    } catch (error) {
      if (state.route === "home") errorView(error);
    }
  }

  async function drawMarkets() {
    setActiveTab("markets");
    if (!cache.bootstrap) view.innerHTML = skeleton();
    try {
      const data = await cached("bootstrap", () => api.once("/api/mini/bootstrap"), 45000);
      setConnection(connectionFor(data));
      if (state.route !== "markets") return;
      view.innerHTML =
        '<section class="page-head"><div class="eyebrow">' + api.esc(t("markets.eyebrow")) + '</div><h1>' + api.esc(t("markets.title")) + "</h1>" +
        "<p>" + api.esc(t("markets.subtitle", { live: liveMarkets(data), total: data.total_markets || 6 })) + "</p></section>" +
        '<div class="market-grid wide">' + (data.markets || []).map(marketCard).join("") + "</div>" +
        '<section class="glass note-card"><strong>' + api.esc(t("markets.footer_title")) + "</strong><p>" + api.esc(t("markets.footer_text")) + "</p></section>";
      bind(view);
    } catch (error) {
      if (state.route === "markets") errorView(error);
    }
  }

  async function drawAnalysis() {
    setActiveTab("analysis");
    view.innerHTML = skeleton();
    try {
      const data = await cached("bootstrap", () => api.once("/api/mini/bootstrap"), 45000);
      setConnection(connectionFor(data));
      if (state.route !== "analysis") return;
      view.innerHTML =
        '<section class="page-head"><div class="eyebrow">' + api.esc(t("analysis.eyebrow")) + '</div><h1>' + api.esc(t("analysis.title")) + "</h1><p>" + api.esc(t("analysis.subtitle")) + "</p></section>" +
        '<div class="market-grid wide">' + (data.markets || []).map(marketCard).join("") + "</div>" +
        '<section class="glass note-card"><strong>' + api.esc(t("analysis.no_trade_title")) + "</strong><p>" + api.esc(t("analysis.no_trade_text")) + "</p></section>";
      bind(view);
    } catch (error) {
      if (state.route === "analysis") errorView(error);
    }
  }
  function durationLabel(seconds) {
    if (seconds == null) return "—";
    if (seconds < 60) return seconds + " SEC";
    return Math.round(seconds / 60) + " MIN";
  }

  function drawChart(market) {
    const canvas = view.querySelector("#price-chart");
    if (!canvas || !window.RozlfChart) return;
    if (Array.isArray(market.candles) && market.candles.length > 1) {
      window.RozlfChart.draw(canvas, market.candles);
    }
  }

  function paintMarket(market) {
    const live = market.available && market.status === "LIVE";
    if (state.selectedDuration && !(market.durations || []).includes(state.selectedDuration)) {
      state.selectedDuration = null;
    }
    const assets = market.assets || [];
    if (!state.selectedAsset || !assets.some((asset) => asset.key === state.selectedAsset)) {
      state.selectedAsset = assets.length ? assets[0].key : null;
    }
    if (!state.selectedDuration && market.durations && market.durations.length) {
      state.selectedDuration = market.durations.includes(60) ? 60 : market.durations[0];
    }
    const assetChips = assets.length
      ? assets.map((asset) => (
          '<button class="chip ' + (asset.key === state.selectedAsset ? "active" : "") + '" data-asset="' + api.esc(asset.key) + '">' +
          api.esc(asset.display) + "</button>"
        )).join("")
      : empty(api.esc(t("market.no_assets")), api.esc(t("market.no_assets_sub")));
    const durationChips = (market.durations || []).map((seconds) => (
      '<button class="chip gold ' + (Number(seconds) === state.selectedDuration ? "active" : "") + '" data-duration="' + seconds + '">' +
      api.esc(durationLabel(seconds)) + "</button>"
    )).join("");
    const price = market.price_display || t("market.unavailable_price");
    view.innerHTML =
      '<section class="page-head market-head"><button class="back" data-route="markets" aria-label="' + api.esc(t("common.back_markets")) + '">‹</button>' +
      '<div><div class="eyebrow">' + api.esc(market.label) + '</div><h1><span class="market-icon">' + api.esc(market.icon) + "</span> " + api.esc(market.label) + "</h1>" +
      '<p><span class="status-dot ' + (live ? "live" : "down") + '">' + (live ? "LIVE" : "DATA UNAVAILABLE") + "</span> " +
      api.esc(market.source || "—") + " · " + api.esc(api.fmtTime(market.last_time)) + "</p></div></section>" +
      '<section class="price-card ' + (live ? "" : "is-down") + '"><small>' + api.esc(t("result.price")) + '</small><strong class="price">' + api.esc(price) + '</strong>' +
      '<span class="price-meta">' + (market.bars ? market.bars + " " + api.esc(t("market.chart_tag")) + " · " + api.esc(market.timeframe || "—") : "—") + "</span>" +
      (live ? '<canvas id="price-chart" class="chart" aria-label="Price chart"></canvas>' : '<div class="note">' + api.esc(market.error || t("market.unavailable")) + "</div>") +
      "</section>" +
      (live ? '<section class="section"><div class="section-head"><h2>' + api.esc(t("market.assets")) + '</h2></div><div class="chips">' + assetChips + "</div></section>" +
      '<section class="section"><div class="section-head"><h2>' + api.esc(t("market.expiry")) + '</h2></div><div class="chips">' + durationChips + "</div></section>" +
      '<div class="action-stack"><button class="btn block" id="analyse-btn">◎ ' + api.esc(t("market.start")) + '</button>' +
      '<button class="btn ghost block" id="smart-btn">' + api.esc(t("market.smart")) + "</button></div>" : "") +
      '<div id="result-slot"></div>';
    bind(view);
    if (live) {
      drawChart(market);
      view.querySelector("#analyse-btn").addEventListener("click", () => runAnalysis(market, false));
      view.querySelector("#smart-btn").addEventListener("click", () => runAnalysis(market, true));
    }
  }

  async function drawMarket(key) {
    setActiveTab("market");
    state.selectedAsset = null;
    view.innerHTML = skeleton("market");
    try {
      const market = await api.once("/api/mini/market/" + encodeURIComponent(key));
      cache.market.set(key, market);
      setConnection(connectionFor(cache.bootstrap));
      if (state.route !== "market" || state.marketKey !== key) return;
      paintMarket(market);
    } catch (error) {
      if (state.route === "market") errorView(error);
    }
  }

  async function runAnalysis(market, smart) {
    if (state.analyzing) return;
    if (!smart && !state.selectedDuration) {
      toast(t("common.select_duration"));
      return;
    }
    const slot = view.querySelector("#result-slot");
    const buttons = view.querySelectorAll("#analyse-btn, #smart-btn");
    state.analyzing = true;
    buttons.forEach((button) => { button.disabled = true; });
    slot.innerHTML = '<div class="glass loading-card"><span class="spinner"></span><strong>' + api.esc(smart ? t("result.choosing") : t("result.analyzing")) + "</strong></div>";
    try {
      const payload = await api.once("/api/mini/analyse", {
        method: "POST",
        body: JSON.stringify({
          market: market.key,
          asset: state.selectedAsset,
          duration: smart ? null : state.selectedDuration,
        }),
      });
      if (payload && payload.status === "UNAVAILABLE") {
        slot.innerHTML = '<div class="glass note-card"><strong>DATA UNAVAILABLE</strong><p>' + api.esc(payload.message || payload.error || t("market.unavailable")) + "</p></div>";
      } else {
        slot.innerHTML = resultHtml(payload);
      }
      haptic();
    } catch (error) {
      slot.innerHTML = '<div class="glass note-card"><strong>' + api.esc(t("common.engine_down")) + '</strong><p>' + api.esc(error.message || "") + "</p></div>";
      setConnection("DEGRADED");
    } finally {
      state.analyzing = false;
      buttons.forEach((button) => { button.disabled = false; });
    }
  }
  async function drawOpportunities(force) {
    setActiveTab("opportunities");
    view.innerHTML = skeleton();
    try {
      const data = await cached("recommendations", () => api.once("/api/mini/recommendations"), force ? 0 : 60000);
      if (state.route !== "opportunities") return;
      const items = data.items || [];
      const rows = items.length
        ? items.map((item) => (
            '<button class="opp-card" data-market="' + api.esc(item.market) + '">' +
            '<span class="opp-left"><span class="market-icon">' + api.esc(item.icon) + "</span><span><strong>" + api.esc(item.asset) + "</strong><small>" +
            api.esc((item.market_label || item.market || "—") + " · " + (item.duration_label || "—")) + "</small></span></span>" +
            '<span class="opp-right"><span class="feed-tag ' + (item.direction === "UP" ? "live" : "down") + '">' +
            api.esc(item.direction) + '</span><strong class="gold-text">' + Math.round(item.confidence) + "%</strong></span></button>"
          )).join("")
        : empty(api.esc(t("recs.empty")), api.esc(t("recs.empty_sub")));
      view.innerHTML =
        '<section class="page-head"><div class="eyebrow">' + api.esc(t("recs.eyebrow")) + '</div><h1>' + api.esc(t("recs.title")) + "</h1>" +
        "<p>" + api.esc(t("recs.subtitle", { threshold: Math.round(data.threshold || 60) })) + "</p></section>" +
        '<div class="glass-list">' + rows + "</div>" +
        '<button class="btn ghost block wide-action" data-retry="1">↻ ' + api.esc(t("common.retry")) + "</button>";
      bind(view);
    } catch (error) {
      if (state.route !== "opportunities") return;
      view.innerHTML = '<section class="error-card"><div class="eyebrow">' + api.esc(t("recs.eyebrow")) + '</div><h1>' + api.esc(t("recs.error")) + "</h1><p>" +
        api.esc(t("recs.error_sub")) + '</p><button class="btn block" data-retry="1">' + api.esc(t("common.retry")) + "</button></section>";
      bind(view);
    }
  }

  async function drawHistory(force) {
    setActiveTab("history");
    view.innerHTML = skeleton();
    try {
      const data = await cached("history", () => api.once("/api/mini/history?limit=50"), force ? 0 : 45000);
      if (state.route !== "history") return;
      const stats = data.stats || {};
      const rate = stats.accuracy == null ? "—" : stats.accuracy + "%";
      const rows = data.signals && data.signals.length
        ? data.signals.map((signal) => (
            '<div class="feed-row"><div class="feed-main"><strong>' + api.esc(signal.asset) + "</strong><small>" +
            api.esc((signal.market_label || signal.market || "—") + " · " + (signal.duration_label || "—") + " · " + api.fmtTime(signal.created_at)) + '</small></div>' +
            '<span class="feed-tag ' + (signal.status === "WIN" ? "live" : signal.status === "LOSS" ? "down" : "gold") + '">' +
            api.esc(signal.status) + "</span></div>"
          )).join("")
        : empty(api.esc(t("history.empty")), api.esc(t("history.empty_sub")));
      view.innerHTML =
        '<section class="page-head"><div class="eyebrow">' + api.esc(t("history.eyebrow")) + '</div><h1>' + api.esc(t("history.title")) + "</h1><p>" + api.esc(t("history.subtitle")) + "</p></section>" +
        '<div class="stat-grid">' +
        '<div class="stat"><small>' + api.esc(t("history.win_rate")) + '</small><strong class="gold-text">' + api.esc(rate) + "</strong></div>" +
        '<div class="stat"><small>' + api.esc(t("history.verified")) + "</small><strong>" + api.esc(String(stats.verified || 0)) + "</strong></div>" +
        '<div class="stat"><small>' + api.esc(t("history.wins")) + "</small><strong>" + api.esc(String(stats.wins || 0)) + "</strong></div>" +
        '<div class="stat"><small>' + api.esc(t("history.losses")) + "</small><strong>" + api.esc(String(stats.losses || 0)) + "</strong></div>" +
        '<div class="stat"><small>' + api.esc(t("history.profit_factor")) + "</small><strong>" + api.esc(stats.profit_factor == null ? "—" : String(stats.profit_factor)) + "</strong></div>" +
        '<div class="stat"><small>' + api.esc(t("history.active")) + "</small><strong>" + api.esc(String(stats.active || 0)) + "</strong></div>" +
        "</div>" +
        '<section class="section"><div class="section-head"><h2>' + api.esc(t("history.latest")) + "</h2></div><div class=\"glass-list\">" + rows + "</div></section>";
      bind(view);
    } catch (error) {
      if (state.route !== "history") return;
      view.innerHTML = '<section class="error-card"><h1>' + api.esc(t("history.error")) + '</h1><p>' + api.esc(t("error.history")) +
        '</p><button class="btn block" data-retry="1">' + api.esc(t("common.retry")) + "</button></section>";
      bind(view);
    }
  }

  function paintSettings(settings, allowed, status) {
    const current = Number(settings.min_confidence || 60);
    const values = Array.from(new Set([...(allowed || [50, 60, 70, 80, 90]), current])).sort((a, b) => a - b);
    const chips = values.map((value) => (
      '<button class="chip gold ' + (value === current ? "active" : "") + '" data-confidence="' + value + '">' + value + "%</button>"
    )).join("");
    const sources = status && status.sources && status.sources.length
      ? status.sources.map((source) => (
          '<div class="source-row"><span><strong>' + api.esc(source.name || source.id || "source") + "</strong><small>" +
          api.esc(source.id || "") + '</small></span><span class="feed-tag ' + (source.configured ? "live" : "gold") + '">' +
          api.esc(source.configured ? t("status.ready") : t("status.missing")) + "</span></div>"
        )).join("")
      : empty(api.esc(t("status.no_sources")), api.esc(t("status.no_sources_sub")));
    view.innerHTML =
      '<section class="page-head"><div class="eyebrow">' + api.esc(t("settings.eyebrow")) + '</div><h1>' + api.esc(t("settings.title")) + "</h1><p>" + api.esc(t("settings.subtitle")) + "</p></section>" +
      '<section class="glass settings-block"><div class="settings-head"><h2>' + api.esc(t("settings.language")) + '</h2><span class="mini-tag">EN · AR</span></div>' +
      '<p class="muted">' + api.esc(t("settings.language_note")) + '</p><div class="chips">' +
      '<button class="chip ' + (i18n.language === "en" ? "active" : "") + '" data-lang="en">' + api.esc(t("settings.english")) + "</button>" +
      '<button class="chip ' + (i18n.language === "ar" ? "active" : "") + '" data-lang="ar">' + api.esc(t("settings.arabic")) + "</button></div></section>" +
      '<section class="glass settings-block"><div class="settings-head"><h2>' + api.esc(t("settings.min_conf")) + '</h2><span class="mini-tag gold-text">' + current + '%</span></div>' +
      '<div class="chips" id="confidence-chips">' + chips + '</div><p class="muted">' + api.esc(t("settings.min_conf_note")) + "</p>" +
      '<button class="btn block" id="save-settings">' + api.esc(t("settings.save")) + "</button></section>" +
      '<section class="glass settings-block"><div class="settings-head"><h2>' + api.esc(t("settings.engine")) + '</h2><span class="mini-tag">' + api.esc(t("settings.shared")) + "</span></div>" +
      '<p class="muted">' + api.esc(t("settings.engine_note")) + " · " + api.esc(t("settings.markets_note")) + "</p></section>" +
      '<section class="glass settings-block"><div class="settings-head"><h2>' + api.esc(t("status.sources")) + '</h2><span class="mini-tag">' +
      (status && status.database ? api.esc(String(status.database)) : "—") + '</span></div><div class="source-list">' + sources + "</div></section>" +
      '<button class="btn ghost block wide-action" data-route="status">◎ ' + api.esc(t("settings.status")) + "</button>";
    bind(view);
    view.querySelectorAll("[data-lang]").forEach((button) => {
      button.addEventListener("click", () => {
        i18n.setLanguage(button.dataset.lang);
        drawSettings(true);
      });
    });
    view.querySelectorAll("[data-confidence]").forEach((button) => {
      button.addEventListener("click", () => {
        view.querySelectorAll("[data-confidence]").forEach((chip) => chip.classList.toggle("active", chip === button));
        view.querySelector("#save-settings").dataset.confidence = button.dataset.confidence;
      });
    });
    const save = view.querySelector("#save-settings");
    save.dataset.confidence = String(current);
    save.addEventListener("click", async () => {
      save.disabled = true;
      try {
        const payload = await api.once("/api/mini/settings", {
          method: "POST",
          body: JSON.stringify({ min_confidence: Number(save.dataset.confidence) }),
        });
        cache.settings = payload.settings;
        cache.bootstrap = null;
        toast(t("settings.saved"));
      } catch (error) {
        toast(t("error.settings"));
      } finally {
        save.disabled = false;
      }
    });
  }

  async function drawSettings(force) {
    if (!cache.settings || force) view.innerHTML = skeleton();
    try {
      const [settingsResult, statusResult] = await Promise.allSettled([
        cached("settings", () => api.once("/api/mini/settings"), force ? 0 : 45000),
        api.once("/api/mini/status"),
      ]);
      if (state.route !== "settings") return;
      const settingsPayload = settingsResult.status === "fulfilled" ? settingsResult.value : { settings: { min_confidence: 60 }, allowed: [50, 60, 70, 80, 90] };
      const status = statusResult.status === "fulfilled" ? statusResult.value : null;
      paintSettings(settingsPayload.settings, settingsPayload.allowed, status);
    } catch (error) {
      if (state.route === "settings") errorView(error);
    }
  }

  async function drawStatus() {
    view.innerHTML = skeleton();
    try {
      const status = await api.once("/api/mini/status");
      if (state.route !== "status") return;
      const sources = (status.sources || []).map((source) => (
        '<div class="source-row"><span><strong>' + api.esc(source.name || source.id || "source") + "</strong><small>" +
        api.esc(source.id || "") + '</small></span><span class="feed-tag ' + (source.configured ? "live" : "gold") + '">' +
        api.esc(source.configured ? t("status.ready") : t("status.missing")) + "</span></div>"
      )).join("");
      view.innerHTML =
        '<section class="page-head"><div class="eyebrow">' + api.esc(t("status.eyebrow")) + '</div><h1>' + api.esc(t("status.title")) + "</h1></section>" +
        '<section class="glass settings-block"><div class="source-list">' + (sources || empty(api.esc(t("status.no_sources")), api.esc(t("status.no_sources_sub")))) + "</div></section>" +
        '<button class="btn ghost block wide-action" data-route="settings">‹ ' + api.esc(t("settings.title")) + "</button>";
      bind(view);
    } catch (error) {
      if (state.route === "status") errorView(error);
    }
  }

  function navigate(route, force, marketKey) {
    const next = route;
    state.route = next;
    if (next === "market") state.marketKey = marketKey || state.marketKey;
    closeSheet();
    setActiveTab(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
    if (next === "home") drawHome(force);
    else if (next === "markets") drawMarkets();
    else if (next === "analysis") drawAnalysis();
    else if (next === "opportunities") drawOpportunities(force);
    else if (next === "history") drawHistory(force);
    else if (next === "settings") drawSettings(force);
    else if (next === "status") drawStatus();
    else if (next === "market") drawMarket(state.marketKey);
  }

  document.querySelectorAll("#tabbar button, [data-nav], .topbar [data-route]").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.route));
  });
  const langButton = document.getElementById("lang-btn");
  if (langButton) {
    langButton.addEventListener("click", () => {
      i18n.setLanguage(i18n.language === "en" ? "ar" : "en");
      navigate(state.route, false, state.marketKey);
    });
  }
  if (tg && tg.onEvent) {
    tg.onEvent("themeChanged", () => i18n.apply());
  }
  setConnection("CONNECTING");
  i18n.apply();
  navigate("home", true);

  let refreshing = false;
  async function refreshStatus() {
    if (refreshing || document.hidden) return;
    refreshing = true;
    try {
      const data = await api.once("/api/mini/bootstrap");
      cache.bootstrap = data;
      seenAt.bootstrap = Date.now();
      setConnection(connectionFor(data));
      if (state.route === "home" || state.route === "markets") {
        if (state.route === "home") drawHome(false);
        else drawMarkets();
      }
    } catch (error) {
      setConnection("OFFLINE");
    } finally {
      refreshing = false;
    }
  }
  setInterval(refreshStatus, 30000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshStatus();
  });
})();
