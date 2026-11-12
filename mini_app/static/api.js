/* API client: every request is authenticated with real Telegram initData. */
(function () {
  const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  const initData = tg ? tg.initData || "" : "";

  class ApiError extends Error {
    constructor(message, code, status) {
      super(message);
      this.code = code || "API_ERROR";
      this.status = status || 0;
    }
  }

  async function request(path, options) {
    if (!initData) {
      throw new ApiError("افتح التطبيق من داخل Telegram حتى يتم التحقق من هويتك.", "NO_TELEGRAM_INIT_DATA", 401);
    }
    const headers = Object.assign(
      { "X-Telegram-Init-Data": initData, Accept: "application/json" },
      options && options.body ? { "Content-Type": "application/json" } : {}
    );
    let response;
    try {
      response = await fetch(path, Object.assign({}, options, { headers }));
    } catch (err) {
      throw new ApiError("تعذر الوصول إلى خادم ROZLF AI.", "NETWORK", 0);
    }
    let body = null;
    try {
      body = await response.json();
    } catch (err) {
      body = null;
    }
    if (!response.ok) {
      throw new ApiError(
        (body && body.message) || "HTTP " + response.status,
        (body && body.error) || "HTTP_" + response.status,
        response.status
      );
    }
    return body;
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
    get bootstrap() { return request("/api/mini/bootstrap"); },
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
