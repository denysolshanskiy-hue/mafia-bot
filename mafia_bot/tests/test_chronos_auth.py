import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

try:
    from modules.chronos_auth import validate_init_data
except ModuleNotFoundError:
    from mafia_bot.modules.chronos_auth import validate_init_data


BOT_TOKEN = "123456:TEST_TOKEN_FOR_UNIT_TESTS_ONLY"


def make_init_data(user_id=123456789, auth_date=1_800_000_000):
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAEAAAE",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test", "username": "test_user"},
            separators=(",", ":"),
        ),
    }
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(fields.items())
    )
    secret_key = hmac.new(
        b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256
    ).digest()
    fields["hash"] = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return urlencode(fields)


class TelegramInitDataTests(unittest.TestCase):
    def test_valid_data_returns_signed_user(self):
        raw = make_init_data()
        user = validate_init_data(
            raw, BOT_TOKEN, max_age_seconds=3600, now=1_800_000_100
        )
        self.assertEqual(user["id"], 123456789)
        self.assertEqual(user["username"], "test_user")

    def test_modified_data_is_rejected(self):
        raw = make_init_data().replace("test_user", "attacker")
        with self.assertRaises(ValueError):
            validate_init_data(raw, BOT_TOKEN, now=1_800_000_100)

    def test_expired_data_is_rejected(self):
        raw = make_init_data(auth_date=1_700_000_000)
        with self.assertRaises(ValueError):
            validate_init_data(
                raw, BOT_TOKEN, max_age_seconds=3600, now=1_800_000_100
            )

    def test_future_timestamp_is_rejected(self):
        raw = make_init_data(auth_date=1_800_001_000)
        with self.assertRaises(ValueError):
            validate_init_data(raw, BOT_TOKEN, now=1_800_000_100)

    def test_duplicate_parameter_is_rejected(self):
        raw = make_init_data() + "&auth_date=1800000000"
        with self.assertRaises(ValueError):
            validate_init_data(raw, BOT_TOKEN, now=1_800_000_100)


if __name__ == "__main__":
    unittest.main()
