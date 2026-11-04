import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

try:
    from modules import chronos_api
except ModuleNotFoundError:
    from mafia_bot.modules import chronos_api


class FakeConnection:
    def __init__(self, account):
        self.account = account
        self.close = AsyncMock()

    async def fetchrow(self, query, user_id):
        return self.account


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
        self.validate = self.auth.start()\n        self.test_admin_env = patch.dict("os.environ", {"CHRONOS_TEST_ADMIN_ID": "424242"})\n        self.test_admin_env.start()
        app = web.Application(middlewares=[chronos_api.telegram_auth_middleware])
        app.router.add_get("/api/chronos/private-test", self.private_endpoint)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        if self.client:
            await self.client.close()
        self.get_connection.stop()
        self.auth.stop()\n        self.test_admin_env.stop()

    async def private_endpoint(self, request):
        return web.json_response({"season_data": "visible"})

    async def test_active_admin_can_access_api(self):
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {"season_data": "visible"})
        self.conn.close.assert_awaited_once()

    async def test_player_is_denied(self):
        self.account.update(role="player")
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 403)
        self.assertEqual((await response.json())["error"], "admin_test_access_only")

    async def test_other_admin_is_denied_even_with_admin_role(self):
        self.validate.return_value = {"id": 854716579, "username": "other_admin"}
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 403)
        self.assertEqual((await response.json())["error"], "admin_test_access_only")

    async def test_inactive_admin_is_denied(self):
        self.account.update(is_active=0)
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma signed"}
        )
        self.assertEqual(response.status, 403)

    async def test_invalid_telegram_session_is_denied_before_role_lookup(self):
        self.validate.side_effect = ValueError("invalid init data")
        response = await self.client.get(
            "/api/chronos/private-test", headers={"Authorization": "tma invalid"}
        )
        self.assertEqual(response.status, 401)
        self.db_connect.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
