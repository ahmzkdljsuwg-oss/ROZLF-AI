# ROZLF AI — Bot Engine API (used by the Mini App web service)

The analysis engine runs only in the **ROZLF AI Bot** service. The Mini App web
service no longer tries to build a second engine: when its local context is not
initialized it proxies `/api/mini/*` to the bot service over HTTPS.

## Configuration

Set on the **web service only**:

```text
ENGINE_API_URL=https://<bot-service-public-domain>
```

- Base URL only (`https://host`); a trailing `/api/mini` is accepted and removed.
- Never put a token, API key or secret in this value.
- Railway private networking (`*.railway.internal`) only works inside one
  project. These two services are in separate Railway projects, so the bot
  service must expose a public HTTPS domain.
- A value that points at the web service's own host is discarded automatically;
  that self-reference caused recursive requests and 30s timeouts.
- For the `web-only` role the bot domain above is used as a last resort when the
  variable is missing or invalid. Never rely on this in a different deployment:
  set the real bot domain explicitly.

## Contract

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/mini/health` | none | Real engine readiness; no secret values |
| GET | `/api/mini/bootstrap` | Telegram initData | User + six markets |
| GET | `/api/mini/markets` | Telegram initData | Market list + real asset counts |
| GET | `/api/mini/market/{market}` | Telegram initData | Quote/candles/analysis support |
| POST | `/api/mini/analyse` | Telegram initData | Real engine result |
| GET | `/api/mini/recommendations` | Telegram initData | Real opportunities (no mock data) |
| GET | `/api/mini/history` | Telegram initData | Verified signals only |
| GET/POST | `/api/mini/settings` | Telegram initData | Minimum confidence |
| GET | `/api/mini/status` | Telegram initData | Source/AI/bridge flags |

## Security model

1. The proxy forwards `X-Telegram-Init-Data` unchanged; the web service never
   reads or stores the bot token.
2. The bot service validates the HMAC signature and `auth_date` against
   `TELEGRAM_BOT_TOKEN`; a forged or expired payload returns 401.
3. Only paths under `/api/mini/` are forwarded to the fixed upstream host.
4. CORS remains restricted to Telegram and ROZLF origins; responses use
   `Cache-Control: no-store`.
5. If the upstream is unreachable the proxy returns HTTP 503 with
   `ENGINE_UNREACHABLE`; it never fabricates data or reports success.

## Connectivity probe

`GET /api/mini/health?probe=1` runs a bounded check from the web service and
returns DNS addresses, TCP/TLS connect time, upstream HTTP status and the real
engine payload. It never contains tokens. Use it before opening the Mini App:

```bash
curl -sS "https://web-production-b044b.up.railway.app/api/mini/health?probe=1"
```

A healthy result has `"engine_ready": true`, `"mode": "proxy"` and an
`"http_status": 200` from `https://rozlf-ai-production.up.railway.app`.
