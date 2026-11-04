import unittest
from unittest.mock import AsyncMock

from modules.chronos_predictions import _void_market_if_roster_changed


class PredictionRosterGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_unchanged_active_roster_keeps_market_open(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [{"user_id": 11}, {"user_id": 22}],
            [{"user_id": 22}, {"user_id": 11}],
        ]
        changed = await _void_market_if_roster_changed(
            conn, {"bot_event_id": 7, "market_id": 3}
        )
        self.assertFalse(changed)
        conn.execute.assert_not_awaited()

    async def test_changed_roster_voids_market_and_refunds_pending_forecasts(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [{"user_id": 11}, {"user_id": 33}],
            [{"user_id": 11}, {"user_id": 22}],
            [{"bet_id": 101, "bettor_user_id": 44}],
        ]
        changed = await _void_market_if_roster_changed(
            conn, {"bot_event_id": 7, "market_id": 3}
        )
        self.assertTrue(changed)
        self.assertEqual(conn.execute.await_count, 2)
        self.assertIn("status='void'", conn.execute.await_args_list[0].args[0])
        self.assertIn("status='refunded'", conn.execute.await_args_list[1].args[0])

    async def test_inactive_users_are_excluded_from_roster_comparison(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [{"user_id": 11}],
            [{"user_id": 11}],
        ]
        changed = await _void_market_if_roster_changed(
            conn, {"bot_event_id": 7, "market_id": 3}
        )
        self.assertFalse(changed)
        roster_query = conn.fetch.await_args_list[0].args[0]
        self.assertIn("u.is_active=1", roster_query)


if __name__ == "__main__":
    unittest.main()
