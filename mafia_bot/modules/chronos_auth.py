"""Telegram Mini App initData verification (stdlib only)."""

import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl


_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int = 86400,
    now: int | None = None,
) -> dict:
    """Validate Telegram.WebApp.initData and return its signed user object.

    Raises ValueError for malformed, expired, or incorrectly signed data.
    Never trust Telegram.WebApp.initDataUnsafe on the client.
    """
    if not isinstance(init_data, str) or not init_data or len(init_data) > 16384:
        raise ValueError("Invalid initData")
    if not bot_token:
        raise ValueError("Bot token is not configured")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise ValueError("Malformed initData") from exc

    if not pairs or len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("Duplicate or missing initData fields")

    fields = dict(pairs)
    received_hash = fields.pop("hash", None)
    if not received_hash or not _HASH_RE.fullmatch(received_hash):
        raise ValueError("Missing or invalid initData hash")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items())
    )
    # Telegram's documented bot-token validation:
    # HMAC_SHA256(key=WebAppData, message=bot_token), then sign data_check_string.
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash.lower()):
        raise ValueError("Invalid initData signature")

    try:
        auth_date = int(fields["auth_date"])
        user = json.loads(fields["user"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Missing auth_date or user") from exc

    current_time = int(time.time()) if now is None else int(now)
    if auth_date > current_time + 60:
        raise ValueError("initData timestamp is in the future")
    if max_age_seconds <= 0 or current_time - auth_date > max_age_seconds:
        raise ValueError("initData has expired")

    if not isinstance(user, dict):
        raise ValueError("Invalid Telegram user")
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid Telegram user id") from exc
    if user_id <= 0:
        raise ValueError("Invalid Telegram user id")

    return {"id": user_id, "username": user.get("username"), "first_name": user.get("first_name")}
