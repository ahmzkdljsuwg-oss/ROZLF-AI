"use strict";
const $ = (id) => document.getElementById(id);
const webapp = window.Telegram?.WebApp;
const auth = webapp?.initData || "";
const api = "/api/nexus-mini/v1";
const state = {data: null, page: "home", request: null, busy: false, failed: null};
const initialText = new WeakMap();
const strings = {
  "مرصد الأسواق":"Market observatory","جارٍ التحقق":"Checking","متصل بالخادم":"Backend online",
  "بدون اتصال":"Backend offline","افتح من Telegram":"Open in Telegram","غير مفعّل":"Access not active",
  "اقرأ السوق":"Read the market","شمعة بشمعة.":"One candle at a time.",
  "تحليل فني من بيانات السوق، مع توقيت واضح وسبب لكل قراءة.":"Technical readings with market data, timing and evidence.",
  "ابدأ التحليل":"Start analysis","الأسواق ببيانات حديثة":"Markets with fresh data","بانتظار التحقق":"Waiting for verification",
  "الماسح التلقائي":"Auto scanner","نبض الأسواق":"Market pulse","عرض الكل":"View all","آخر التنبيهات":"Recent alerts",
  "السجل":"Feed","الأسواق":"Markets","حالة الشموع من مصدرها. «لم يُفحص» لا تعني أن السوق مغلق.":"Freshness is checked at the source. Unchecked does not mean closed.",
  "مختبر التحليل":"Analysis lab","شموع أصلية مغلقة فقط. وقت الكويت.":"Native closed candles only. Kuwait time.",
  "وضع التحليل":"Analysis mode","تحليل سريع":"Quick technical reading","أدلة ومعايرة":"Evidence and calibration",
  "السوق":"Market","الأصل":"Asset","المدة":"Duration","حلّل الآن":"Analyze now","تحليل جارٍ":"Analyzing",
  "سجل التنبيهات":"Live alerts","تنبيهات حسابك التي أقرّ Telegram استلامها قبل بداية الشمعة.":"Your alerts acknowledged by Telegram before the target opened.",
  "الأداء المتحقق":"Verified performance","قياس اتجاه الشمعة، وليس ربح صفقة. لا تدخل الحالات المعلّقة أو التعادل في نسبة المطابقة.":"Directional accuracy, not profit. Pending and tied results are not counted.",
  "زمن جلب الشموع":"Candle fetch latency","الإعدادات":"Settings","التفضيلات مرتبطة بحسابك. التحليل لا ينفّذ أي صفقات.":"Preferences are account-specific. Analysis does not execute trades.",
  "تنبيهات الماسح":"Scanner alerts","تشغيل وإيقاف توصيات Telegram":"Enable or disable Telegram alerts",
  "الوضع الافتراضي":"Default mode","يتزامن مع وضع تحليل البوت":"Synced with the bot",
  "اللغة":"Language","تغيير لغة الواجهة على جهازك":"Change the language on this device",
  "الرئيسية":"Home","التحليل":"Analysis","الأداء":"Stats","انتقل للمحتوى":"Skip to content",
  "NEXUS AI · متابعة فنية فقط، لا تنفيذ للصفقات":"NEXUS AI · Technical analysis only. No orders executed.",
  "مُفعّل":"Enabled","متوقف":"Off","بانتظار الخدمة":"Service unavailable","لم يُفحص":"Unchecked",
  "شموع حديثة":"Fresh candles","آخر بيانات متقادمة":"Data is stale","آخر فحص":"Last scan",
  "لا توجد تنبيهات مؤكدة لهذا الحساب حتى الآن.":"No acknowledged alerts for this account yet.",
  "ما فيه نتائج مسجلة حتى الآن.":"No results yet.","لا توجد عينات زمنية كافية.":"No timed samples yet.",
  "صعود":"Up","هبوط":"Down","وافق الاتجاه":"Matched","خالف الاتجاه":"Missed","معلّق":"Pending","تعادل":"Tie",
  "غير متحقق":"Unverified","لا توجد أصول متاحة":"No assets available","تلقائي":"Auto","الثقة":"Confidence",
  "المصدر":"Source","الشمعة المستهدفة":"Target candle","آخر إغلاق":"Last close","زمن المعالجة":"Processing time",
  "جارٍ قراءة الشموع المغلقة…":"Reading closed candles…","أعد المحاولة":"Try again",
  "افتح Mini App من زر البوت داخل Telegram لعرض حسابك.":"Open this Mini App from the bot in Telegram.",
  "تعذر الوصول إلى خادم NEXUS الآن.":"The NEXUS backend could not be reached."
};
let lang = "ar";
try { lang = localStorage.getItem("nexus-language") === "en" ? "en" : "ar"; } catch (_) {}
const t = (msg) => lang === "en" ? (strings[msg] || msg) : msg;
function applyLanguage() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  $("lang").value = lang;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.parentElement.closest("#notice,#home-markets,#markets-list,#home-feed,#signals-list,#performance-list,#latency-list,#analysis-result,#connection-text,#scan-state,#scan-time,#market-count,#market-total,#pref-scanner-hint,#market,#asset,#frame")) continue;
    if (node.parentElement.closest("#analyze-button") && state.busy) continue;
    const original = initialText.get(node) || node.nodeValue.trim();
    if (strings[original]) { initialText.set(node, original); node.nodeValue = t(original); }
  }
}
function el(tag, content, cls) {
  const node = document.createElement(tag);
  if (content != null) node.textContent = content;
  if (cls) node.className = cls;
  return node;
}
const clock = (ms) => ms == null ? "—" : new Intl.DateTimeFormat(lang === "ar" ? "ar-KW" : "en-GB", {
  timeZone: "Asia/Kuwait", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"
}).format(new Date(ms));
const number = (n) => new Intl.NumberFormat(lang === "ar" ? "ar-KW" : "en", {maximumFractionDigits: 2}).format(n);
const duration = (n) => n == null ? "—" : n < 60 ? number(n) + (lang === "en" ? " sec" : " ث") :
  number(n / 60) + (lang === "en" ? " min" : " د");
const statusLabel = (s) => t(({ACTIVE:"معلّق",PENDING:"معلّق",WIN:"وافق الاتجاه",LOSS:"خالف الاتجاه",DRAW:"تعادل",UNVERIFIED:"غير متحقق"})[String(s).toUpperCase()] || "غير متحقق");
const resultLabel = (s) => s === "UP" ? t("صعود") : s === "DOWN" ? t("هبوط") : "NO TRADE";
const barsState = (s) => t(({online:"شموع حديثة",stale:"آخر بيانات متقادمة"})[s] || "لم يُفحص");

function setConnection(kind, label, banner = "") {
  $("connection").dataset.state = kind;
  $("connection-text").textContent = t(label);
  $("notice").textContent = t(banner);
  $("notice").hidden = !banner;
}
async function request(path, data = null, signal = null) {
  const own = new AbortController();
  const cancel = () => own.abort();
  if (signal?.aborted) cancel();
  signal?.addEventListener("abort", cancel, {once:true});
  const timeout = setTimeout(cancel, path === "/analyze" ? 42000 : 12000);
  try {
    const headers = {"X-Telegram-Init-Data": auth, "Accept":"application/json"};
    const params = {headers, signal: own.signal, cache:"no-store"};
    if (data !== null) { params.method = "POST"; headers["Content-Type"] = "application/json"; params.body = JSON.stringify(data); }
    const response = await fetch(api + path, params);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(payload.message || t("تعذر الوصول إلى خادم NEXUS الآن.")), {code: payload.code, http:response.status});
    return payload;
  } finally { clearTimeout(timeout); signal?.removeEventListener("abort", cancel); }
}
function show(page) {
  if (!document.querySelector(".page#" + CSS.escape(page))) return;
  if (state.page !== page && state.request && page !== "analysis") state.request.abort();
  state.page = page;
  for (const section of document.querySelectorAll(".page")) section.hidden = section.id !== page;
  for (const button of document.querySelectorAll(".nav button")) {
    if (button.dataset.go === page) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  window.scrollTo(0, 0);
}
function empty(msg) { return el("div",t(msg),"empty"); }
function marketCard(m) {
  const button = el("button",null,"panel market-card"), details = el("div");
  button.type = "button";
  button.append(el("span",m.icon || "◫"),details);
  details.append(el("b",m.label),el("small",barsState(m.state),"state-"+m.state));
  if (m.last_closed_ms) details.append(el("small",clock(m.last_closed_ms)));
  button.addEventListener("click",() => { show("analysis"); $("market").value=m.key; assets(); });
  return button;
}
function signalView(row, markets) {
  const card = el("div",null,"panel signal"), top = el("div",null,"signal-line");
  const label = markets.find(m => m.key === row.market)?.label || row.market;
  const text = el("div");
  text.append(el("strong",row.asset),el("small",label+" · "+duration(row.seconds)+" · "+clock(row.target_ms)+" – "+clock(row.end_ms)));
  top.append(text,el("span",statusLabel(row.status)+" · "+resultLabel(row.direction),"badge "+(row.direction==="UP"?"positive":"negative")));
  card.append(top);
  if (row.open != null && row.close != null) card.append(el("small",number(row.open)+" → "+number(row.close)));
  return card;
}
function performanceView(row, markets) {
  const card = el("div",null,"panel perf");
  card.append(el("strong",(markets.find(m => m.key===row.market)?.label || row.market)+" · "+row.frame+" · "+(row.mode || "").toUpperCase()));
  card.append(el("small",(row.accuracy==null?"—":number(row.accuracy)+"%")+" · N = "+number(row.decided)));
  card.append(el("small",Object.entries(row.counts).map(([key,value])=>statusLabel(key)+" "+number(value)).join(" · ")));
  return card;
}
function options(select, values) {
  const old = select.value;
  select.replaceChildren(...values.map(([value,label]) => {const option=el("option",label);option.value=value;return option;}));
  if(values.some(([value])=>value===old)) select.value=old;
}
function assets() {
  const market = state.data?.markets.find(m=>m.key===$("market").value);
  const rows = market?.assets || [];
  options($("asset"), rows.length ? rows.map(a=>[a.key,a.label]) : [["",t("لا توجد أصول متاحة")]]);
  const frames = market?.frames || [];
  options($("frame"), [["auto",t("تلقائي")],...frames.map(f=>[f, f.replace("sec"," s").replace("min"," min")])]);
  $("analyze-button").disabled = state.busy || !rows.length || !frames.length;
}
function render() {
  const data = state.data;
  if (!data) return;
  const indexed = data.markets || [], signals = data.signals || [], stats = data.performance || [];
  $("market-count").textContent = number(indexed.filter(m=>m.state==="online").length);
  $("market-total").textContent = " / " + number(indexed.length);
  $("scan-state").textContent = t(!data.scanner.enabled?"متوقف":data.scanner.running?"مُفعّل":"بانتظار الخدمة");
  $("scan-time").textContent = data.scanner.last_scan_ms ? t("آخر فحص")+" · "+clock(data.scanner.last_scan_ms) : "—";
  $("home-markets").removeAttribute("aria-busy");
  $("home-markets").replaceChildren(...indexed.slice(0,4).map(marketCard));
  $("markets-list").replaceChildren(...indexed.map(marketCard));
  $("home-feed").replaceChildren(...(signals.length?signals.slice(0,3).map(r=>signalView(r,indexed)):[empty("لا توجد تنبيهات مؤكدة لهذا الحساب حتى الآن.")]));
  $("signals-list").replaceChildren(...(signals.length?signals.map(r=>signalView(r,indexed)):[empty("لا توجد تنبيهات مؤكدة لهذا الحساب حتى الآن.")]));
  $("performance-list").replaceChildren(...(stats.length?stats.map(r=>performanceView(r,indexed)):[empty("ما فيه نتائج مسجلة حتى الآن.")]));
  const metrics = Object.entries(data.latency || {});
  $("latency-list").replaceChildren(...(metrics.length?metrics.map(([source,m])=>{
    const card=el("div",null,"panel perf");card.append(el("strong",source),el("small","p50 "+number(m.p50_ms)+" ms · p95 "+number(m.p95_ms)+" ms · N = "+number(m.n)));return card;
  }):[empty("لا توجد عينات زمنية كافية.")]));
  $("scanner-toggle").setAttribute("aria-checked",String(data.scanner.enabled));
  $("pref-scanner-hint").textContent = t(data.scanner.enabled && !data.scanner.running?"بانتظار الخدمة":"تشغيل وإيقاف توصيات Telegram");
  $("scanner-toggle").disabled = false;
  $("pref-mode").disabled = false;
  $("pref-mode").value = data.mode;
  options($("market"),indexed.map(m=>[m.key,m.label]));
  assets();
}
function showFailure(error) {
  state.failed=error;
  if (error.code==="TELEGRAM_REQUIRED" || !auth)
    setConnection("error","افتح من Telegram","افتح Mini App من زر البوت داخل Telegram لعرض حسابك.");
  else if (error.code==="NOT_AUTHORIZED") setConnection("error","غير مفعّل",error.message);
  else setConnection("error","بدون اتصال",error.message || "تعذر الوصول إلى خادم NEXUS الآن.");
  for (const id of ["home-markets","markets-list","home-feed","signals-list","performance-list"]) {
    $(id).setAttribute("aria-busy","false");
    if (!state.data) $(id).replaceChildren(empty(!auth?"افتح من Telegram":"أعد المحاولة"));
  }
}
let refreshing = false;
async function refresh() {
  if (refreshing) return;
  if (!auth) {showFailure({code:"TELEGRAM_REQUIRED"});return;}
  refreshing=true;
  try {
    const oldMode=state.data?.mode;
    state.data=await request("/dashboard");
    if (!oldMode && ["pro","strong"].includes(state.data.mode)) document.querySelector('[name="mode"][value="pro"]').checked=true;
    state.failed=null;
    setConnection("ok","متصل بالخادم");
    render();
  } catch (error) {showFailure(error);}
  finally {refreshing=false;}
}
function candleChart(candles) {
  const slice=candles.filter(c=>[c.open,c.close,c.low,c.high].every(Number.isFinite)).slice(-32);
  if (!slice.length) return null;
  const svgName="http://www.w3.org/2000/svg";
  const make=(tag,attrs)=> {const n=document.createElementNS(svgName,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;};
  const width=380,height=132,pad=10,min=Math.min(...slice.map(c=>c.low)),max=Math.max(...slice.map(c=>c.high));
  const y=p=>height-pad-(p-min)/(max-min||1)*(height-2*pad);
  const svg=make("svg",{viewBox:"0 0 380 132",class:"chart",role:"img","aria-label":lang==="en"?"Closed market candlesticks":"رسم آخر شموع مغلقة"});
  [26,52,78,104].forEach(v=>svg.append(make("line",{x1:0,x2:width,y1:v,y2:v,class:"grid"})));
  const step=(width-pad*2)/slice.length;
  slice.forEach((c,i)=>{
    const x=pad+(i+.5)*step, cls=c.close>=c.open?"up":"down";
    svg.append(make("line",{x1:x,x2:x,y1:y(c.high),y2:y(c.low),class:cls}),
      make("rect",{x:x-step*.27,y:Math.min(y(c.open),y(c.close)),width:step*.54,height:Math.max(1,Math.abs(y(c.open)-y(c.close))),class:cls}));
  });
  return svg;
}
let lastResult=null;
function displayAnalysis(result) {
  const card=el("article",null,"panel result"), top=el("div",null,"signal-line"), dl=el("dl");
  const market=state.data.markets.find(m=>m.key===result.market)?.label || result.market;
  const timely=result.target_ms == null || result.target_ms > Date.now();
  const direction=timely?result.direction:"NO TRADE";
  top.append(el("strong",result.asset),el("span",resultLabel(direction),"badge "+(direction==="UP"?"positive":direction==="DOWN"?"negative":"flat")));
  for (const [name,value] of [[t("السوق"),market],[t("المدة"),duration(result.seconds)],[t("المصدر"),result.source],[t("الشمعة المستهدفة"), timely&&result.target_ms?clock(result.target_ms)+" – "+clock(result.end_ms):"—"],[t("الثقة"),direction==="NO TRADE"||result.confidence==null?t("غير متحقق"):number(result.confidence)+"%"],[t("آخر إغلاق"),clock(result.last_closed_ms)],[t("زمن المعالجة"),number(result.processing_ms)+" ms"]]) {
    dl.append(el("dt",name),el("dd",value));
  }
  card.append(top,dl);
  const chart=candleChart(result.candles || []);
  if(chart) card.append(chart);
  const reasons=el("ul");
  for(const reason of (timely?(result.reasons||[]):[lang==="en"?"The target window elapsed.":"انتهت نافذة التوقع قبل عرضه."]))reasons.append(el("li",reason));
  card.append(reasons);
  $("analysis-result").replaceChildren(card);
}

document.addEventListener("click", event=>{
  const action=event.target.closest("[data-go]");
  if(action)show(action.dataset.go);
});
$("market").addEventListener("change",assets);
$("connection").addEventListener("click",refresh);
$("lang").addEventListener("change",()=>{
  lang=$("lang").value;
  try{localStorage.setItem("nexus-language",lang);}catch(_){}
  applyLanguage();
  if(state.failed)showFailure(state.failed);else if(state.data)setConnection("ok","متصل بالخادم");
  render();
  if(lastResult && !state.busy)displayAnalysis(lastResult);
});
$("form").addEventListener("submit", async event=>{
  event.preventDefault();
  if(state.busy || !state.data || !$("asset").value)return;
  lastResult=null;
  state.busy=true;
  state.request=new AbortController();
  const submit=$("analyze-button"), oldLabel=submit.firstChild;
  submit.disabled=true;
  oldLabel.nodeValue=t("تحليل جارٍ");
  $("analysis-result").replaceChildren(empty("جارٍ قراءة الشموع المغلقة…"),el("div",null,"skeleton"));
  try {
    const result=await request("/analyze",{market:$("market").value,asset:$("asset").value,
      frame:$("frame").value,mode:new FormData(event.currentTarget).get("mode")},state.request.signal);
    lastResult=result;
    displayAnalysis(result);
    void refresh();
    try{webapp?.HapticFeedback?.selectionChanged();}catch(_){}
  } catch(error){
    $("analysis-result").replaceChildren(empty(error.name==="AbortError"?"أعد المحاولة":error.message));
    if(error.http===401||error.http===403||(!error.http&&error.name!=="AbortError"))showFailure(error);
  } finally {state.busy=false;state.request=null;const native=initialText.get(oldLabel)||"حلّل الآن";initialText.set(oldLabel,native);oldLabel.nodeValue=t(native)+" ";assets();}
});
let saving=false;
async function save(payload){
  if(!state.data||saving)return;
  saving=true;
  $("scanner-toggle").disabled=true;
  $("pref-mode").disabled=true;
  try {
    const saved=await request("/preferences",payload);
    state.data.scanner.enabled=saved.scanner;
    state.data.mode=saved.mode;
    if(payload.mode) {
      const mode=["pro","strong"].includes(saved.mode)?"pro":"fast";
      document.querySelector('[name="mode"][value="'+mode+'"]').checked=true;
    }
  } catch(error){showFailure(error);}
  finally {saving=false;render();}
}
$("scanner-toggle").addEventListener("click",()=>save({scanner:!state.data.scanner.enabled}));
$("pref-mode").addEventListener("change",()=>save({mode:$("pref-mode").value}));
document.addEventListener("visibilitychange",()=>{if(!document.hidden)void refresh();});
try {webapp?.ready();webapp?.expand();webapp?.setHeaderColor("#080c17");webapp?.setBackgroundColor("#080c17");} catch (_) {}
applyLanguage();
void refresh();
setInterval(()=>{if(!document.hidden && auth && !state.busy && !saving)void refresh();},30000);
