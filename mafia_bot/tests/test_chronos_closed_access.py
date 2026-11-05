import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

try:
    from modules import chronos_api
    from modules.chronos_common import require_admin
except ModuleNotFoundError:
    from mafia_bot.modules import chronos_api
    from mafia_bot.modules.chronos_common import require_admin


class FakeConnection:
    def __init__(self, account):
        self.account = account
        self.other_account = {"role": "player", "is_active": 1}
        self.close = AsyncMock()

    async def fetchrow(self, query, user_id):
        return self.account if user_id == 424242 else self.other_account


class ChronosClosedAccessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = None
        self.account = {"role": "admin", "is_active": 1}
        self.conn = FakeConnection(self.account)
        self.db_connect = AsyncMock(return_value=self.conn)
        self.get_connection = patch.object(
            chronos_api, "get_connection", new=self.db_connect
        )
        self.get_connection.start()
        self.auth = patch.object(
            chronos_api, "validate_init_data",
            return_value={"id": 424242, "username": "tester"},
        )
        self.validate = self.auth.start()
        self.test_admin_env = patch.dict("os.environ", {"CHRONOS_TEST_ADMIN_ID": "424242"})
        self.test_admin_env.start()
        app = web.Application(middlewares=[chronos_api.telegram_auth_middleware])
        app.router.add_get("/api/chronos/private-test", self.private_endpoint)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        if self.client:
            await self.client.close()
        self.get_connection.stop()
        self.auth.stop()
        self.test_admin_env.stop()

    async def private_endpoint(self, request):
        return web.json_response({"season_data": "visible"})

    async def test_active_admin_can_access_api(self):
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {"season_data": "visible"})
        self.conn.close.assert_awaited_once()

    async def test_configured_test_admin_must_be_an_active_admin(self):
        self.account.update(role="player")
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "closed_test_admin_not_configured")

    async def test_other_admin_is_denied_even_with_admin_role(self):
        self.validate.return_value = {"id": 854716579, "username": "other_admin"}
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 403)
        self.assertEqual((await response.json())["error"], "admin_test_access_only")
        self.db_connect.assert_not_awaited()

    async def test_non_test_account_is_denied_without_database_lookup(self):
        self.validate.return_value = {"id": 2, "username": "player"}
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 403)
        self.assertEqual((await response.json())["error"], "admin_test_access_only")
        self.db_connect.assert_not_awaited()

    async def test_open_mode_allows_active_player_but_admin_guard_still_denies_admin_action(self):
        self.validate.return_value = {"id": 2, "username": "player"}
        with patch.dict("os.environ", {"CHRONOS_ACCESS_MODE": "open"}):
            response = await self.client.get(
                "/api/chronos/private-test", headers={"Authorization": "tma signed"}
            )
        self.assertEqual(response.status, 200)
        admin_error = await require_admin({"telegram_user": {"id": 2}}, self.conn)
        self.assertEqual(admin_error.status, 403)

    async def test_open_mode_still_requires_configured_test_admin(self):
        self.validate.return_value = {"id": 2, "username": "player"}
        with patch.dict("os.environ", {
            "CHRONOS_ACCESS_MODE": "open",
            "CHRONOS_TEST_ADMIN_ID": "",
        }):
            response = await self.client.get(
                "/api/chronos/private-test", headers={"Authorization": "tma signed"}
            )
        self.assertEqual(response.status, 503)
        self.db_connect.assert_not_awaited()

    async def test_invalid_access_mode_fails_closed(self):
        with patch.dict("os.environ", {"CHRONOS_ACCESS_MODE": "unsupported"}):
            response = await self.client.get(
                "/api/chronos/private-test", headers={"Authorization": "tma signed"}
            )
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "chronos_access_mode_invalid")
        self.db_connect.assert_not_awaited()

    async def test_inactive_admin_is_denied(self):
        self.account.update(is_active=0)
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "closed_test_admin_not_configured")

    async def test_missing_staging_admin_is_denied(self):
        self.conn.account = None
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "closed_test_admin_not_configured")

    async def test_missing_chronos_database_fails_closed(self):
        self.db_connect.side_effect = chronos_api.ChronosDatabaseNotConfigured(
            "CHRONOS_DATABASE_URL is not configured"
        )
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "chronos_database_not_configured")

    async def test_missing_test_admin_configuration_fails_closed(self):
        with patch.dict("os.environ", {"CHRONOS_TEST_ADMIN_ID": ""}):
            response = await self.client.get(
                "/api/chronos/private-test", headers={"Authorization": "tma signed"}
            )
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "closed_test_admin_not_configured")
        self.db_connect.assert_not_awaited()

    async def test_malformed_test_admin_configuration_fails_closed(self):
        with patch.dict("os.environ", {"CHRONOS_TEST_ADMIN_ID": "9" * 5000}):
            response = await self.client.get(
                "/api/chronos/private-test", headers={"Authorization": "tma signed"}
            )
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "closed_test_admin_not_configured")
        self.db_connect.assert_not_awaited()

    async def test_database_lookup_failure_fails_closed(self):
        self.db_connect.side_effect = RuntimeError("database unavailable")
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "access_check_unavailable")

    async def test_invalid_telegram_session_is_denied_before_role_lookup(self):
        self.validate.side_effect = ValueError("invalid init data")
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma invalid"}
        )
        self.assertEqual(response.status, 401)
        self.db_connect.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
