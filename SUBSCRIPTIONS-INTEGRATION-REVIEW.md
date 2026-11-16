# Subscription integration review

This branch is isolated from production `main`.

The supplied `NEXUS-AI-SUBSCRIPTIONS-STAGING.zip` contains a standalone `subscriptions/` package (`store.py`, `customer.py`, `admin_bot.py`) and `start_subscription_admin.py`.

**Do not deploy this ZIP directly.** Its database schema and activation-code implementation have not been verified against the currently deployed `NEXUS-ADMIN` on branch `lemon/subscriptions`.

Required before deployment:
1. Reuse the existing subscription schema and code issuance/activation implementation from `lemon/subscriptions`.
2. Ensure `ROZLF-AI` blocks analysis, callbacks, scans, and recommendations for unlicensed Telegram user IDs, while allowing `/start`, `/activate`, and `/status`.
3. Ensure both services use the same Postgres database, and only the owner can issue or revoke codes.
4. Test issuance in NEXUS-ADMIN, activation in ROZLF-AI, reuse rejection, expiration, and fail-closed behavior on database errors.
5. Deploy the customer bot only after tests pass, then set `SUBSCRIPTIONS_ENABLED=true`.

No application code is changed by this review commit.
