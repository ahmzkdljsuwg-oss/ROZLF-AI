/* API client: every request is authenticated with real Telegram initData. */
(function () {
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const initData = tg ? tg.initData || "" : "";
  const meta = document.querySelector('meta[name="rozlf-api-base"]');
  const base = ((window.ROZLF_API_BASE || (meta && meta.content) || "") + "").replace(/\/+$/, "");
  const TIMEOUT_MS = 25000;
  const RETRY_DELAYS = [700, 1800];

  class ApiError extends Error {
    constructor(message, code, status) {
      super(message);
      this.code = code || "API_ERROR";
      this.status = status || 0;
    }
  }

  function isRetryable(error) {
    return error && (error.code === "NETWORK" || error.code === "TIMEOUT" || error.status === 502 || error.status === 503 || error.status === 504);
  }

  function friendlyStatus(status, body) {
    if (body && body.message) return body.message;
    if (status === 401) return "انتهت جلسة Telegram. أغلق التطبيق وافتحه من جديد.";
    if (status === 403) return "هذه الجلسة غير مصرّح لها باستخدام المحرك.";
    if (status === 404) return "المسار المطلوب غير موجود على خادم ROZLF AI.";
    if (status === 429) return "طلبات كثيرة. انتظر لحظات ثم أعد المحاولة.";
    if (status === 503) return "محرك التحليل غير متاح حالياً. أعد المحاولة بعد قليل.";
    if (status >= 500) return "حدث خطأ في خادم ROZLF AI. أعد المحاولة.";
    return "تعذر إكمال الطلب.";
  }

  async function once(path, options) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    const headers = Object.assign(
      { "X-Telegram-Init-Data": initData, Accept: "application/json" },
      options && options.body ? { "Content-Type": "application/json" } : {}
    );
    let response;
    try {
      response = await fetch(base + path, Object.assign({ cache: "no-store" }, options, { headers, signal: controller.signal }));
    } catch (err) {
      const timeout = err && err.name === "AbortError";
      throw new ApiError(
        timeout ? "انتهت مهلة الاتصال بمحرك التحليل. تحقق من الشبكة وأعد المحاولة." : "تعذر الوصول إلى خادم ROZLF AI. تحقق من اتصال الإنترنت.",
        timeout ? "TIMEOUT" : "NETWORK",
        0
      );
    } finally {
      clearTimeout(timer);
    }
    let body = null;
    try {
      body = await response.json();
    } catch (err) {
      body = null;
    }
    if (!response.ok) {
      throw new ApiError(friendlyStatus(response.status, body), (body && body.error) || "HTTP_" + response.status, response.status);
    }
    return body;
  }

  async function request(path, options) {
    if (!initData) {
      throw new ApiError("افتح التطبيق من داخل Telegram حتى يتم التحقق من هويتك.", "NO_TELEGRAM_INIT_DATA", 401);
    }
    const method = (options && options.method) || "GET";
    const attempts = method === "GET" ? RETRY_DELAYS.length + 1 : 1;
    let lastError = null;
    for (let i = 0; i < attempts; i += 1) {
      try {
        return await once(path, options);
      } catch (error) {
        lastError = error;
        if (i === attempts - 1 || !isRetryable(error)) break;
        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAYS[i]));
      }
    }
    throw lastError;
  }

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtPrice(value) {
    const n = Number(value);
    if (!isFinite(n)) return "—";
    if (Math.abs(n) >= 500) return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
    if (Math.abs(n) >= 20) return n.toFixed(3);
    return n.toFixed(5);
  }

  function fmtTime(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (isNaN(date.getTime())) return "—";
    return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  }

  window.RozlfApi = {
    tg,
    initData,
    base,
    get bootstrap() { return request("/api/mini/bootstrap"); },
    get health() { return request("/api/mini/health"); },
    get markets() { return request("/api/mini/markets"); },
    market(key) { return request("/api/mini/market/" + encodeURIComponent(key)); },
    analyse(payload) {
      return request("/api/mini/analyse", { method: "POST", body: JSON.stringify(payload) });
    },
    get recommendations() { return request("/api/mini/recommendations"); },
    get history() { return request("/api/mini/history"); },
    get settings() { return request("/api/mini/settings"); },
    saveSettings(payload) {
      return request("/api/mini/settings", { method: "POST", body: JSON.stringify(payload) });
    },
    get status() { return request("/api/mini/status"); },
    esc,
    fmtPrice,
    fmtTime,
    ApiError,
  };
})();
