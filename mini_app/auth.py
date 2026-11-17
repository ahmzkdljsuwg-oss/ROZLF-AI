"""Validate the Telegram-signed identity, never an ID supplied by the client."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def telegram_user(raw: str, token: str) -> int:
    if not raw or not token or len(raw) > 8192:
        raise ValueError("missing Telegram session")
    pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=32)
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError("duplicate field")
    received = values.pop("hash", "")
    if len(received) != 64 or any(c not in "0123456789abcdef" for c in received):
        raise ValueError("invalid hash")
    text = "\n".join(f"{k}={v}" for k, v in sorted(values.items()))
    secret = hmac.digest(b"WebAppData", token.encode(), hashlib.sha256)
    expected = hmac.new(secret, text.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise ValueError("invalid signature")
    stamp = int(values.get("auth_date", "0"))
    if not -60 <= time.time() - stamp <= 21600:
        raise ValueError("expired Telegram session")
    user = json.loads(values.get("user", "null"))
    if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0:
        raise ValueError("invalid Telegram identity")
    return user["id"]
