# ROZLF / NEXUS AI — Subscriptions

Two independent aiogram bots share one database:

- **Customer bot** (`main.py`): NEXUS AI analysis, `/activate`, `/status`.
- **Owner bot** (`start_admin.py`): codes, customers, revocation, activation notifications.

## Tables

- `subscription_codes`: unique code, duration, status (`AVAILABLE`/`USED`/`DISABLED`), creator, used_by/used_at.
- `subscriptions`: one row per Telegram ID, plan days, activation/expiry, status (`ACTIVE`/`EXPIRED`/`REVOKED`).
- `subscription_notifications`: durable queue for owner notifications.

## Activation guarantees

`Repository.activate_code()` performs a conditional `UPDATE subscription_codes SET status='USED' WHERE code=:code AND status='AVAILABLE'`.
Only the request that changes one row proceeds; a concurrent request receives `USED`.
The subscription is then upserted for the Telegram ID. The owner notification is appended in the same transaction.

## Expiry

`is_subscribed()` and `subscription_for()` evaluate `expires_at` on every call and persist `EXPIRED`.
No cron job is required for correctness; the middleware blocks expired users immediately.
Signal scanner notifications are also skipped for expired users.

## Failure isolation

- If the admin bot is down, activation still succeeds and the notification waits in the queue.
- If the customer bot restarts, subscriptions are re-read from PostgreSQL.
- No in-memory subscription state is used.

## Deployment

See README section 10. Use `railway.admin.json` for the admin service and keep one replica per bot.
