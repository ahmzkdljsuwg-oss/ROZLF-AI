"use strict";

const tg = window.Telegram?.WebApp;
const $ = (id) => document.getElementById(id);
const state = { markets: [], active: "", mode: "fast", serial: 0, busy: false, last: null };
const modes = {
  fast: ["الشمعة الجاية، قبل افتتاحها", "يقرأ الشموع المغلقة ويختار إطارًا مناسبًا للشمعة القادمة."],
  minute: ["تحليل شمعة الدقيقة", "إطار 60 ثانية، والاتجاه يطلع فقط إذا اجتاز شروط المعايرة."],
};
const localeTime = (ms) => new Intl.DateTimeFormat("ar-KW", {
  timeZone: "Asia/Kuwait", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
}).format(ms);
const label = (tag, klass, value) => {
  const node = document.createElement(tag);
  if (klass) node.className = klass;
  if (value !== undefined) node.textContent = value;
  return node;
};

try {
  tg?.ready();
  tg?.expand();
  tg?.setHeaderColor?.("#080c0b");
  tg?.setBackgroundColor?.("#080c0b");
} catch (_) { /* Older Telegram clients may ignore theme methods. */ }

function connection(kind, message) {
  $("status").dataset.state = kind;
  $("status").lastElementChild.textContent = message;
}

function info(message, retry = false) {
  $("feedback").hidden = !message;
  $("feedback").textContent = message || "";
  $("reload").hidden = !retry;
}

async function call(path, body) {
  if (!tg?.initData) throw new Error("افتح الـMini App من زر البوت داخل تيليجرام.");
  const started = performance.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 23000);
  try {
    const response = await fetch("/api/nexus-mini/v1/" + path, {
      method: body ? "POST" : "GET",
      headers: { "X-Telegram-Init-Data": tg.initData, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
      cache: "no-store",
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "تعذّر إكمال الطلب.");
    return { payload, rtt: performance.now() - started };
  } catch (error) {
    if (error.name === "AbortError") throw new Error("انتهت مهلة الاتصال. حاول مرة ثانية.");
    if (error instanceof TypeError || error instanceof SyntaxError) throw new Error("الخادم ما رد بالشكل المتوقع. حاول مرة ثانية.");
    throw error;
  } finally { clearTimeout(timeout); }
}

function renderMarkets() {
  const root = $("markets");
  root.replaceChildren();
  for (const market of state.markets) {
    const button = label("button", "", market.icon + " " + market.label);
    button.type = "button";
    button.setAttribute("aria-pressed", String(state.active === market.key));
    button.addEventListener("click", () => { state.active = market.key; renderMarkets(); });
    root.append(button);
  }
  $("market-count").textContent = state.markets.length ? state.markets.length + " أسواق" : "—";
  const market = state.markets.find((entry) => entry.key === state.active);
  const assets = $("assets");
  assets.replaceChildren();
  if (!market) return;
  market.assets.forEach((asset, index) => {
    const button = label("button", index === 0 ? "asset featured" : "asset");
    button.type = "button";
    const row = label("span", "asset-inner");
    const copy = label("span", "asset-copy");
    copy.append(label("b", "", asset.label), label("small", "", market.label + " · " + asset.symbol));
    row.append(label("span", "asset-icon", market.icon), copy, label("span", "chev", "‹"));
    button.append(row, label("span", "asset-cta", "حلّل الشمعة القادمة"));
    button.addEventListener("click", () => analyze(market, asset));
    assets.append(button);
  });
}

async function loadMarkets() {
  connection("pending", "يتحقق من الاتصال");
  info("جاري تحميل أسواق البوت…");
  try {
    const { payload } = await call("markets");
    state.markets = payload.markets;
    if (!state.markets.some((market) => state.active === market.key)) state.active = state.markets[0]?.key || "";
    renderMarkets();
    connection("ok", "المحرك متصل");
    info(state.markets.length ? "" : "ما فيه مصدر متاح حالياً.", !state.markets.length);
  } catch (error) {
    connection("error", tg?.initData ? "تعذّر الاتصال" : "داخل تيليجرام فقط");
    info(error.message, Boolean(tg?.initData));
  }
}

function chart(canvas, candles) {
  if (!candles.length) { canvas.hidden = true; return; }
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const width = canvas.width, height = canvas.height;
  const max = Math.max(...candles.map((bar) => bar.high));
  const min = Math.min(...candles.map((bar) => bar.low));
  const y = (value) => height - 18 - ((value - min) / Math.max(max - min, 1e-10)) * (height - 36);
  ctx.strokeStyle = "#213a2b";
  ctx.lineWidth = 1;
  for (let i = 1; i < 6; i++) {
    ctx.beginPath(); ctx.moveTo(0, i * height / 6); ctx.lineTo(width, i * height / 6); ctx.stroke();
  }
  const step = width / candles.length;
  candles.forEach((bar, index) => {
    const x = (index + 0.5) * step, half = step * 0.26;
    ctx.fillStyle = bar.close >= bar.open ? "#47d99a" : "#ee857f";
    ctx.fillRect(x - 1, y(bar.high), 2, Math.max(2, y(bar.low) - y(bar.high)));
    ctx.fillRect(x - half, y(Math.max(bar.open, bar.close)), half * 2, Math.max(2, Math.abs(y(bar.close) - y(bar.open))));
  });
}

function renderResult(root, snapshot) {
  root.classList.remove("notice");
  const result = snapshot.payload;
  root.replaceChildren($("result-template").content.cloneNode(true));
  const field = (name) => root.querySelector('[data-field="' + name + '"]');
  const directional = result.direction === "UP" || result.direction === "DOWN";
  const serverNow = () => snapshot.serverAtReceipt + performance.now() - snapshot.received;
  function tick() {
    const beforeOpen = directional && Number.isFinite(result.target_ms) && serverNow() < result.target_ms;
    const dir = field("direction");
    dir.dataset.direction = beforeOpen ? result.direction : "NO TRADE";
    dir.textContent = beforeOpen ? (result.direction === "UP" ? "↗ ميل للصعود" : "↘ ميل للهبوط")
      : directional ? "انتهت نافذة التوقع" : "لا إشارة";
    field("confidence").textContent = beforeOpen
      ? (result.confidence === null ? "غير معايرة" : Math.round(result.confidence) + "%") : "—";
    field("target").hidden = !beforeOpen;
    if (beforeOpen) {
      field("clock").textContent = localeTime(result.target_ms) + " الكويت";
      field("countdown").textContent = "بعد " + Math.ceil((result.target_ms - serverNow()) / 1000) + " ث";
    }
    if (beforeOpen && root.isConnected) setTimeout(() => {
      if (root.firstElementChild === article) tick();
    }, 250);
  }
  const article = root.firstElementChild;
  field("frame").textContent = result.seconds === 60 ? "دقيقة واحدة" : result.seconds + " ثوانٍ";
  field("source").textContent = result.asset + " · " + result.source;
  field("trend").textContent = ({ UP: "صاعد", DOWN: "هابط", RANGE: "عرضي" })[result.trend] || "—";
  field("volatility").textContent = ({ LOW: "منخفض", NORMAL: "طبيعي", HIGH: "عالٍ" })[result.volatility] || "—";
  field("reason").textContent = directional && serverNow() >= result.target_ms
    ? "الشمعة بدأت قبل وصول الرد، لذلك ما عُرض الاتجاه." : (result.reasons || []).join(" · ");
  field("bars").textContent = result.closed_count + " شمعة للتحليل";
  chart(field("chart"), result.candles);
  const price = (value) => new Intl.NumberFormat("en", { maximumFractionDigits: 8 }).format(value);
  for (const bar of result.candles.slice(-12).reverse()) {
    const row = label("div", "candle-row", localeTime(bar.at) + " · فتح " + price(bar.open)
      + " · أعلى " + price(bar.high) + " · أدنى " + price(bar.low) + " · قفل " + price(bar.close));
    field("candles").append(row);
  }
  tick();
}

function closeSheet() {
  if ($("sheet").open) $("sheet").close();
}

async function analyze(market, asset) {
  if (state.busy) return;
  state.busy = true;
  const requestId = ++state.serial;
  const sheet = $("sheet"), body = $("sheet-content");
  $("sheet-title").textContent = asset.label;
  const loading = label("div", "wait");
  loading.setAttribute("role", "status");
  loading.append(label("span", "mark", "✦"), label("strong", "", "جاري قراءة الشموع…"),
    label("p", "", "الترند والتذبذب وتوقيت الشمعة القادمة"), label("div", "track"));
  body.replaceChildren(loading);
  sheet.showModal();
  try { tg?.BackButton?.show(); } catch (_) {}
  try {
    const { payload, rtt } = await call("analyze", { market: market.key, asset: asset.key, mode: state.mode });
    if (requestId !== state.serial) return;
    const transit = Math.max(0, rtt - (payload.processing_ms || 0));
    const snapshot = { payload, serverAtReceipt: payload.server_ms + transit, received: performance.now() };
    state.last = snapshot;
    renderResult($("last-content"), snapshot);
    if (sheet.open) renderResult(body, snapshot);
  } catch (error) {
    if (requestId === state.serial && sheet.open) body.replaceChildren(label("p", "notice", error.message));
  } finally {
    if (requestId === state.serial) state.busy = false;
  }
}

$("close").addEventListener("click", closeSheet);
$("sheet").addEventListener("close", () => {
  try { tg?.BackButton?.hide(); } catch (_) {}
});
tg?.BackButton?.onClick?.(closeSheet);
$("reload").addEventListener("click", loadMarkets);
document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
  state.mode = b.dataset.mode;
  document.querySelectorAll("[data-mode]").forEach((item) => item.setAttribute("aria-pressed", String(item === b)));
  const [title, note] = modes[state.mode];
  $("mode-title").textContent = title;
  $("mode-note").textContent = note;
}));
document.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll("[data-tab]").forEach((item) => {
    item.removeAttribute("aria-current");
    $("view-" + item.dataset.tab).hidden = item !== b;
  });
  b.setAttribute("aria-current", "page");
  if (b.dataset.tab === "last" && state.last) renderResult($("last-content"), state.last);
  window.scrollTo(0, 0);
}));
loadMarkets();
