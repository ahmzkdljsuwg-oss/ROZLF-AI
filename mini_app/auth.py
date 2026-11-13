"""Telegram Web App initData validation (HMAC-SHA256, no client-supplied identity)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

class AuthError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MiniAppUser:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""

    @property
    def display_name(self) -> str:
        name = " ".join(part for part in (self.first_name, self.last_name) if part).strip()
        return name or self.username or str(self.id)


def _secret(bot_token: str) -> bytes:
    return hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> MiniAppUser:
    if not init_data:
        raise AuthError("MISSING_INIT_DATA", "Telegram initData is required")
    if not bot_token:
        raise AuthError("NO_BOT_TOKEN", "Telegram bot token is not configured on the server")
    pairs = parse_qsl(init_data, keep_blank_values=True)
    values: dict[str, str] = {}
    for key, value in pairs:
        values[key] = value
    received = values.get("hash", "")
    if not received:
        raise AuthError("MISSING_HASH", "Telegram initData has no hash")
    # Bot-token HMAC covers every field except ``hash``, including the newer
    # ``signature`` field that Telegram adds for third-party Ed25519 validation.
    check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(values.items())
        if key != "hash"
    )
    expected = hmac.new(_secret(bot_token), check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise AuthError("BAD_SIGNATURE", "Telegram initData signature is invalid")

    try:
        auth_date = int(values.get("auth_date", "0"))
    except ValueError as exc:
        raise AuthError("BAD_AUTH_DATE", "Telegram auth_date is invalid") from exc
    if auth_date <= 0:
        raise AuthError("BAD_AUTH_DATE", "Telegram auth_date is missing")
    age = time.time() - auth_date
    if age > max_age_seconds:
        raise AuthError("EXPIRED_INIT_DATA", "Telegram initData has expired; reopen the Mini App")
    if age < -120:
        raise AuthError("BAD_AUTH_DATE", "Telegram auth_date is in the future")

    try:
        raw_user = json.loads(values.get("user", "{}"))
        user_id = int(raw_user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthError("NO_USER", "Telegram initData has no user") from exc
    return MiniAppUser(
        id=user_id,
        first_name=str(raw_user.get("first_name") or ""),
        last_name=str(raw_user.get("last_name") or ""),
        username=str(raw_user.get("username") or ""),
        language_code=str(raw_user.get("language_code") or ""),
    )


def init_data_from_request(request) -> str:
    header = request.headers.get("X-Telegram-Init-Data", "")
    if header:
        return header
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("tma "):
        return authorization[4:].strip()
    return request.query.get("initData", "")


def authenticate(request, bot_token: str) -> MiniAppUser:
    try:
        return validate_init_data(init_data_from_request(request), bot_token)
    except AuthError:
        raise
    except Exception as exc:  # malformed payloads must not leak a stack trace
        raise AuthError("INVALID_INIT_DATA", "Telegram initData is invalid") from exc

