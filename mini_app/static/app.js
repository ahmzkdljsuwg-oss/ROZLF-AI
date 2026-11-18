"use strict";
const $ = (id) => document.getElementById(id);
const webapp = window.Telegram?.WebApp;
const auth = webapp?.initData || "";
const api = "/api/nexus-mini/v1";
const state = {data: null, page: "home", request: null, busy: false, failed: null};
const initialText = new WeakMap();
const strings = {
  "محطة التحليل":"Analysis terminal","نظرة عامة":"Overview","الملف":"Profile",
  "أبدا ي وحش 😪":"Let’s go 😪","القراءة تبدأ بعد اختيار السوق.":"Choose a market to begin.",
  "بانتظار التحليل":"Waiting for analysis","قراءات الشموع":"Candle readings","مصدر غير مفحوص":"Source not checked",
  "فحص الشموع المغلقة":"Checking closed candles","جارٍ طلب بيانات المصدر وتحليلها.":"Fetching the source snapshot and computing readings.",
  "القراءات المتاحة":"Readings available","تعذّر التحليل":"Analysis unavailable","تعذر جلب القراءات":"Readings could not be fetched",
  "الاتجاه":"Trend","الزخم":"Momentum","التذبذب":"Volatility","الدعم":"Support","المقاومة":"Resistance",
  "صاعد":"Rising","هابط":"Falling","عرضي":"Range","محايد":"Neutral","مرتفع":"High","متوسط":"Normal","منخفض":"Low",
  "غير متاح":"Unavailable","بيانات آخر إغلاق":"Last closed-candle data",
  "مختبر الشموع":"Candle lab","البيانات أولاً.":"Data first.",
  "افحص جسم الشمعة وذيولها وتوقيتها من بيانات المصدر.":"Inspect candle bodies, wicks and timing from the source.",
  "افتح مختبر الشموع":"Open candle lab",
  "اضغط على أي شمعة لعرض الافتتاح والأعلى والأدنى والإغلاق. الأوقات بتوقيت الكويت.":"Select a candle for its open, high, low and close. All times are Kuwait time.",
  "وقت استلام البيانات":"Data received","شمعة مغلقة":"Closed candle","وقت الشمعة":"Candle time",
  "الافتتاح":"Open","الأعلى":"High","الأدنى":"Low","الإغلاق":"Close","نسبة الجسم":"Body ratio",
  "شمعة سابقة":"Previous candle","شمعة تالية":"Next candle","اختيار الشمعة":"Select candle",
  "دوجي":"Doji","ذيل طويل":"Long wick","شمعة داخلية":"Inside bar","ابتلاع":"Engulfing",
  "جسم ممتد":"Extended body","حركة مختلطة":"Mixed body","ثابتة":"Flat",
  "اختبار تاريخي فقط":"Historical test only","مطابقة الاتجاه":"Directions matched",
  "لا يثبت أفضلية للتوقع.":"No forecasting edge established.",
  "قراءة الاستراتيجيات":"Strategy readings","قراءة فنية وليست توصية أو نسبة ثقة.":"Technical observations, not a signal or confidence score.",
  "الترند":"Trend","الانعكاس":"Reversal","هيكل السعر":"Price structure","حركة الشموع":"Price action","متعارض":"Conflicting",
  "قراءة فقط":"Read only","فجوة قبل هذه الشمعة":"Gap before this candle",
  "الوقت المتبقي للعرض غير كافٍ.":"Insufficient time to display this forecast.",
  "الفريم أقصر من مهلة العرض اللازمة. الشموع معروضة للقراءة فقط.":"This frame is shorter than the delivery window. Candles are read-only.",
  "اختبار SMARTY التاريخي لم يثبت دقة التوقع. هذا الفريم للقراءة الفنية، وليس إشارة.":"Historical results did not establish a SMARTY forecasting edge. This is a technical reading, not a signal.",
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
    if (button.dataset.go === page || (button.dataset.go === "settings" && ["home","signals","performance"].includes(page))) button.setAttribute("aria-current", "page");
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
  button.addEventListener("click",() => { show("analysis"); $("market").value=m.key; resetTerminal(); assets(); });
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
  options($("frame"), [["auto",t("تلقائي")],...frames.map(f=>[f, f.replace("sec"," s").replace("min"," min")+(f==="5sec"?" · "+t("قراءة فقط"):"")])]);
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
  const slice=candles.filter(c=>[c.open,c.close,c.low,c.high].every(Number.isFinite)).slice(-40);
  if (!slice.length) return null;
  const svgName="http://www.w3.org/2000/svg";
  const make=(tag,attrs)=> {const n=document.createElementNS(svgName,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);return n;};
  const width=402,height=210,left=12,right=322,top=17,bottom=176;
  const lo=Math.min(...slice.map(c=>c.low)),hi=Math.max(...slice.map(c=>c.high)),spread=(hi-lo||Math.max(hi*.0001,1e-6));
  const min=lo-spread*.09,max=hi+spread*.09;
  const y=p=>bottom-(p-min)/(max-min)*(bottom-top);
  const price=new Intl.NumberFormat("en-US",{maximumFractionDigits:8,minimumFractionDigits:4,useGrouping:false});
  const svg=make("svg",{viewBox:"0 0 "+width+" "+height,class:"chart",role:"img","aria-label":t("شمعة مغلقة"),direction:"ltr"});
  const step=(right-left)/slice.length;
  const hitboxes=[];
  const label=(x,y,text,cls="axis-label")=>{const node=make("text",{x,y,class:cls});node.textContent=text;return node;};
  for(let i=0;i<5;i++){
    const at=top+i*(bottom-top)/4;
    svg.append(make("line",{x1:left,x2:right,y1:at,y2:at,class:"grid"}),label(right+5,at+3,price.format(max-i*(max-min)/4)));
  }
  const timeMarks=[0,Math.floor(slice.length/2),slice.length-1].filter((n,i,all)=>all.indexOf(n)===i);
  const tickFormat=new Intl.DateTimeFormat(lang==="en"?"en-GB":"ar-KW",{timeZone:"Asia/Kuwait",hour:"2-digit",minute:"2-digit",second:"2-digit",hourCycle:"h23"});
  timeMarks.forEach(i=>svg.append(label(left+i/Math.max(1,slice.length-1)*(right-left-46),197,tickFormat.format(new Date(slice[i].at)))));
  const read=el("section",null,"candle-inspector");
  const inspectorTitle=el("div",null,"inspector-title"), badge=el("span",null,"badge");
  const details=el("dl",null,"ohlc-values");
  const control=el("div",null,"candle-controls");
  const back=el("button","‹","candle-step"), next=el("button","›","candle-step"), range=el("input");
  for(const [button,title] of [[back,"شمعة سابقة"],[next,"شمعة تالية"]]){
    button.type="button";button.setAttribute("aria-label",t(title));
  }
  range.type="range";range.min="0";range.max=String(slice.length-1);
  range.setAttribute("aria-label",t("اختيار الشمعة"));
  control.append(back,range,next);
  function select(index){
    const i=Math.max(0,Math.min(slice.length-1,index)), bar=slice[i];
    range.value=String(i);
    range.setAttribute("aria-valuetext",clock(bar.at)+" – "+clock(bar.close_at));
    back.disabled=i===0;next.disabled=i===slice.length-1;
    hitboxes.forEach((box,j)=>box.classList.toggle("selected",i===j));
    const shape=({DOJI:"دوجي",WICK:"ذيل طويل",INSIDE:"شمعة داخلية",ENGULFING:"ابتلاع",BODY:"جسم ممتد",MIXED:"حركة مختلطة",FLAT:"ثابتة"})[bar.shape];
    badge.textContent=shape?t(shape):t("شمعة مغلقة");
    badge.className="badge "+(bar.movement==="UP"?"positive":bar.movement==="DOWN"?"negative":"flat");
    const heading=el("div");
    heading.append(el("strong",t("شمعة مغلقة")),el("small",clock(bar.at)+" – "+clock(bar.close_at)+(bar.gap_before?" · "+t("فجوة قبل هذه الشمعة"):"")));
    inspectorTitle.replaceChildren(heading,badge);
    details.replaceChildren(...[["الافتتاح",bar.open],["الأعلى",bar.high],["الأدنى",bar.low],["الإغلاق",bar.close],["نسبة الجسم",bar.body_pct]]
      .map(([k,v])=>{const data=el("div");data.append(el("dt",t(k)),el("dd",k==="نسبة الجسم"?number(v)+"%":price.format(v)));return data;}));
  }
  slice.forEach((c,i)=>{
    const x=left+(i+.5)*step, cls=c.close>c.open?"up":c.close<c.open?"down":"neutral";
    const lane=make("rect",{x:x-step/2,y:top,width:step,height:bottom-top,class:"candle-lane"});
    hitboxes.push(lane);
    lane.addEventListener("click",()=>select(i));
    svg.append(lane,make("line",{x1:x,x2:x,y1:y(c.high),y2:y(c.low),class:"plot-mark "+cls}),
      make("rect",{x:x-step*.29,y:Math.min(y(c.open),y(c.close)),width:step*.58,height:Math.max(1,Math.abs(y(c.open)-y(c.close))),class:"plot-mark "+cls}));
  });
  range.addEventListener("input",()=>select(Number(range.value)));
  back.addEventListener("click",()=>select(Number(range.value)-1));
  next.addEventListener("click",()=>select(Number(range.value)+1));
  read.append(inspectorTitle,details,control);
  const panel=el("div",null,"chart-module");
  panel.append(svg,read);
  select(slice.length-1);
  return panel;
}
const readingTiles=[
  ["trend","الاتجاه","↗"],["ema","EMA 50/200","∿"],["momentum","الزخم","ϟ"],["rsi","RSI 14","⊙"],
  ["volatility","التذبذب","≈"],["support","الدعم","⌊"],["resistance","المقاومة","⌈"],["candle","شمعة مغلقة","◫"]
];
let terminalPhase="idle", terminalError="";
function formatReading(row){
  if(row?.value==null)return [t("غير متاح"),"neutral"];
  const v=row.value;
  const words={UP:"صاعد",DOWN:"هابط",RANGE:"عرضي",FLAT:"ثابتة",BULLISH:"صاعد",BEARISH:"هابط",NEUTRAL:"محايد",
    HIGH:"مرتفع",NORMAL:"متوسط",LOW:"منخفض",DOJI:"دوجي",WICK:"ذيل طويل",INSIDE:"شمعة داخلية",ENGULFING:"ابتلاع",BODY:"جسم ممتد",MIXED:"حركة مختلطة"};
  const tone=["UP","BULLISH"].includes(v)?"positive":["DOWN","BEARISH"].includes(v)?"negative":"neutral";
  if(row.key==="volatility" && row.state in words)return [t(words[row.state])+" · ATR "+formatPrecise(v),tone];
  if(row.key==="candle")return [t(words[v]||v)+" · "+number(row.body_pct)+"%",row.movement==="UP"?"positive":row.movement==="DOWN"?"negative":"neutral"];
  return [typeof v==="number"?formatPrecise(v):t(words[v]||v),tone];
}
function formatPrecise(v){
  return new Intl.NumberFormat(lang==="en"?"en":"ar-KW",{maximumFractionDigits:8,useGrouping:false}).format(v);
}
function renderReadings(phase,result=null,direction=null,message=""){
  terminalPhase=phase;
  terminalError=message;
  const hero=$("terminal-hero"), grid=$("reading-grid"), progress=$("terminal-progress");
  hero.dataset.phase=phase==="done"?(direction==="UP"?"up":direction==="DOWN"?"down":"hold"):phase;
  progress.dataset.phase=phase;
  grid.setAttribute("aria-busy",String(phase==="loading"));
  $("terminal-kicker").textContent=phase==="done"?(result.mode.toUpperCase()+" · "+result.frame):"CLOSED CANDLES";
  $("terminal-title").textContent=phase==="done"?resultLabel(direction):
    phase==="loading"?t("فحص الشموع المغلقة"):phase==="error"?t("تعذّر التحليل"):t("أبدا ي وحش 😪");
  $("terminal-detail").textContent=phase==="done"?result.asset+" · "+t("بيانات آخر إغلاق"):
    phase==="loading"?t("جارٍ طلب بيانات المصدر وتحليلها."):phase==="error"?message:t("القراءة تبدأ بعد اختيار السوق.");
  const available=phase==="done"?(result.readings || []).filter(r=>r.value!=null).length:0;
  $("progress-count").textContent=phase==="done"||phase==="loading"?String(available)+" / 8":"— / 8";
  $("progress-label").textContent=t(phase==="done"?"القراءات المتاحة":phase==="loading"?"فحص الشموع المغلقة":
    phase==="error"?"تعذر جلب القراءات":"بانتظار التحليل");
  $("reading-source").textContent=result?.source || t("مصدر غير مفحوص");
  $("reading-source").title=result?.source || "";
  progress.querySelectorAll(".phase-track i").forEach((bar,i)=>bar.classList.toggle("lit",i<available));
  const readings=result?.readings || [];
  grid.replaceChildren(...readingTiles.map(([key,title,icon])=>{
    const tile=el("div",null,"reading-tile"), glyph=el("span",icon,"tile-icon"), copy=el("div");
    glyph.setAttribute("aria-hidden","true");
    const [value,tone]=phase==="done"?formatReading(readings.find(r=>r.key===key)):
      phase==="loading"?["• • •","pending"]:["—","neutral"];
    const caption=phase==="done"&&key==="trend"?t(title)+" · "+result.frame:t(title);
    tile.dataset.tone=tone;
    copy.append(el("b",caption),el("small",value));
    tile.append(glyph,copy);return tile;
  }));
  const trace=$("terminal-trace");
  trace.replaceChildren();
  const series=(result?.candles || []).slice(-36).map(c=>c.close).filter(Number.isFinite);
  if(series.length>1){
    const min=Math.min(...series),max=Math.max(...series),span=max-min;
    const path=document.createElementNS("http://www.w3.org/2000/svg","polyline");
    path.setAttribute("points",series.map((v,i)=>[2+i*236/(series.length-1),span?40-36*(v-min)/span:23].join(",")).join(" "));
    trace.append(path);
  }
}
let lastResult=null;
let expiryTimer=null;
function effectiveTime(result) {
  return result.server_ms + (result._wireMs || 0) + Math.max(0,performance.now() - (result._received || performance.now()));
}
function strategyPanel(groups) {
  if (!groups?.length) return null;
  const titles={trend:"الترند", momentum:"الزخم", reversal:"الانعكاس", structure:"هيكل السعر", price_action:"حركة الشموع"};
  const labels={UP:"صاعد", DOWN:"هابط", MIXED:"متعارض", NEUTRAL:"محايد", UNAVAILABLE:"غير متاح"};
  const panel=el("details",null,"strategy-panel");
  panel.append(el("summary",t("قراءة الاستراتيجيات")),el("p",t("قراءة فنية وليست توصية أو نسبة ثقة.")));
  for (const group of groups) {
    const details=el("details",null,"strategy-family");
    const summary=el("summary",t(titles[group.key] || group.key));
    summary.append(el("b",t(labels[group.state] || "غير متاح"),"strategy-state"));
    summary.lastChild.dataset.state=group.state;
    const rules=el("ul");
    for (const rule of group.rules || []) {
      const line=el("li");
      const label=el("span",rule.name);
      label.dir="ltr";
      line.append(label,el("span",t(labels[rule.state] || "غير متاح")));
      rules.append(line);
    }
    details.append(summary,rules);
    panel.append(details);
  }
  return panel;
}
function displayAnalysis(result) {
  if(expiryTimer!==null){clearTimeout(expiryTimer);expiryTimer=null;}
  const card=el("article",null,"panel result"), top=el("div",null,"signal-line"), dl=el("dl");
  const market=state.data.markets.find(m=>m.key===result.market)?.label || result.market;
  const remaining=result.target_ms == null?null:result.target_ms-effectiveTime(result)-(result.min_view_lead_ms||5000);
  const timely=remaining==null || remaining>0;
  const direction=timely?result.direction:"NO TRADE";
  renderReadings("done",result,direction);
  const title=el("div");
  title.append(el("span",result.mode.toUpperCase()+" · "+result.frame,"overline"),el("h2",result.asset));
  top.append(title,el("span",resultLabel(direction),"badge "+(direction==="UP"?"positive":direction==="DOWN"?"negative":"flat")));
  for (const [name,value] of [[t("السوق"),market],[t("المدة"),duration(result.seconds)],[t("المصدر"),result.source],[t("الشمعة المستهدفة"), timely&&result.target_ms?clock(result.target_ms)+" → "+clock(result.end_ms):"—"],[t("الثقة"),direction==="NO TRADE"||result.confidence==null?t("غير متحقق"):number(result.confidence)+"%"],[t("آخر إغلاق"),clock(result.last_closed_ms)],[t("وقت استلام البيانات"),clock(result.captured_ms)],[t("زمن المعالجة"),number(result.processing_ms)+" ms"]]) {
    dl.append(el("dt",name),el("dd",value));
  }
  const reasons=el("ul",null,"result-reasons");
  for(const reason of (timely?(result.reasons||[]):["الوقت المتبقي للعرض غير كافٍ."]))reasons.append(el("li",t(reason)));
  card.append(top,reasons);
  const chart=candleChart(result.candles || []);
  if(chart) card.append(chart);
  const lab=strategyPanel(result.strategy_readings);
  if(lab) card.append(lab);
  if(result.historical_audit){
    const audit=result.historical_audit, info=el("div",null,"result-audit");
    const date=new Intl.DateTimeFormat(lang==="en"?"en-GB":"ar-KW",{timeZone:"Asia/Kuwait",month:"short",day:"numeric"}).format(new Date(audit.through_ms));
    info.append(el("strong",t("اختبار تاريخي فقط")+" · "+audit.mode.toUpperCase()),
      el("small",t("مطابقة الاتجاه")+" "+number(audit.wins)+" / "+number(audit.samples)+" · "+date+
        (audit.established_edge?"":" · "+t("لا يثبت أفضلية للتوقع."))));
    card.append(info);
  }
  card.append(dl);
  $("analysis-result").replaceChildren(card);
  if(remaining!=null&&remaining>0&&lastResult===result) expiryTimer=setTimeout(()=>{
    if(lastResult===result) displayAnalysis(result);
  },remaining+5);
}

document.addEventListener("click", event=>{
  const action=event.target.closest("[data-go]");
  if(action)show(action.dataset.go);
});
function resetTerminal(){
  if(state.request && state.busy)state.request.abort();
  lastResult=null;
  if(expiryTimer!==null){clearTimeout(expiryTimer);expiryTimer=null;}
  $("analysis-result").replaceChildren();
  renderReadings("idle");
}
$("market").addEventListener("change",()=>{resetTerminal();assets();});
$("asset").addEventListener("change",resetTerminal);
$("frame").addEventListener("change",resetTerminal);
for(const control of document.querySelectorAll('input[name="mode"]'))control.addEventListener("change",resetTerminal);
$("connection").addEventListener("click",refresh);
$("lang").addEventListener("change",()=>{
  lang=$("lang").value;
  try{localStorage.setItem("nexus-language",lang);}catch(_){}
  applyLanguage();
  if(state.failed)showFailure(state.failed);else if(state.data)setConnection("ok","متصل بالخادم");
  render();
  if(lastResult && !state.busy)displayAnalysis(lastResult);
  else renderReadings(terminalPhase,null,null,terminalError);
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
  $("analysis-result").replaceChildren();
  renderReadings("loading");
  try {
    const requestedAt=performance.now();
    const result=await request("/analyze",{market:$("market").value,asset:$("asset").value,
      frame:$("frame").value,mode:new FormData(event.currentTarget).get("mode")},state.request.signal);
    const receivedAt=performance.now();
    result._wireMs=Math.max(0,receivedAt-requestedAt-result.processing_ms);
    result._received=receivedAt;
    lastResult=result;
    displayAnalysis(result);
    void refresh();
    try{webapp?.HapticFeedback?.selectionChanged();}catch(_){}
  } catch(error){
    renderReadings(error.name==="AbortError"?"idle":"error",null,null,error.message);
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
try {webapp?.ready();webapp?.expand();webapp?.setHeaderColor("#0a0f19");webapp?.setBackgroundColor("#0a0f19");} catch (_) {}
applyLanguage();
show("analysis");
renderReadings("idle");
void refresh();
setInterval(()=>{if(!document.hidden && auth && !state.busy && !saving)void refresh();},30000);
