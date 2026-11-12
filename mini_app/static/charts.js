/* Minimal dependency-free candlestick renderer for real API candles. */
(function () {
  function resize(canvas) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(rect.width, 200);
    const height = Math.max(rect.height, 120);
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, width, height };
  }

  function draw(canvas, candles) {
    const { ctx, width, height } = resize(canvas);
    ctx.clearRect(0, 0, width, height);
    const pad = { top: 14, right: 8, bottom: 18, left: 8 };
    const w = width - pad.left - pad.right;
    const h = height - pad.top - pad.bottom;

    const grad = ctx.createLinearGradient(0, 0, 0, height);
    grad.addColorStop(0, "rgba(22,245,160,.08)");
    grad.addColorStop(1, "rgba(22,245,160,0)");
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, width, height);

    if (!Array.isArray(candles) || candles.length < 2) {
      ctx.fillStyle = "rgba(143,167,156,.8)";
      ctx.font = "11px -apple-system, Tahoma, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("NO CHART DATA", width / 2, height / 2);
      return;
    }

    const highs = candles.map((c) => Number(c.h));
    const lows = candles.map((c) => Number(c.l));
    let max = Math.max(...highs);
    let min = Math.min(...lows);
    const range = max - min || Math.max(max * 0.001, 0.0001);
    max += range * 0.08;
    min -= range * 0.08;
    const y = (value) => pad.top + ((max - value) / (max - min)) * h;

    ctx.strokeStyle = "rgba(255,255,255,.045)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i += 1) {
      const yy = pad.top + (h / 3) * i;
      ctx.beginPath();
      ctx.moveTo(pad.left, yy);
      ctx.lineTo(width - pad.right, yy);
      ctx.stroke();
    }

    const step = w / candles.length;
    const body = Math.max(1.4, Math.min(step * 0.58, 7));
    candles.forEach((c, i) => {
      const x = pad.left + step * i + step / 2;
      const open = Number(c.o);
      const close = Number(c.c);
      const up = close >= open;
      const color = up ? "#16f5a0" : "#ff5d72";
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, y(Number(c.h)));
      ctx.lineTo(x, y(Number(c.l)));
      ctx.stroke();
      const bodyTop = y(Math.max(open, close));
      const bodyHeight = Math.max(1.2, Math.abs(y(open) - y(close)));
      if (up) {
        ctx.fillRect(x - body / 2, bodyTop, body, bodyHeight);
      } else {
        ctx.fillRect(x - body / 2, bodyTop, body, bodyHeight);
      }
    });

    const avg = candles.reduce((sum, c) => sum + Number(c.c), 0) / candles.length;
    ctx.strokeStyle = "rgba(226,195,122,.55)";
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.left, y(avg));
    ctx.lineTo(width - pad.right, y(avg));
    ctx.stroke();
    ctx.setLineDash([]);

    const last = Number(candles[candles.length - 1].c);
    ctx.fillStyle = last >= Number(candles[candles.length - 1].o) ? "#16f5a0" : "#ff5d72";
    ctx.font = "600 9px -apple-system, Tahoma, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(last.toFixed(5), pad.left, height - 5);
    ctx.textAlign = "right";
    ctx.fillStyle = "rgba(143,167,156,.7)";
    ctx.fillText(candles.length + " BARS · LIVE", width - pad.right, height - 5);
  }

  window.RozlfChart = { draw };
})();
