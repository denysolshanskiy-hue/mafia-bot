import unittest
import os
from unittest.mock import AsyncMock, patch
from datetime import date, datetime, timedelta, timezone
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from modules.chronos_admin import _invitation_deadline
from modules import chronos_admin


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class StagingFakeConnection:
    def __init__(self, role="admin", linked=False):
        self.role = role
        self.linked = linked
        self.calls = []
        self.close = AsyncMock()

    def transaction(self):
        return FakeTransaction()

    async def fetchrow(self, query, *args):
        self.calls.append(("fetchrow", query, args))
        if "FROM public.users" in query:
            return {"role": self.role, "is_active": 1}
        if "FROM chronos.event_slots" in query:
            return {"slot_id": 7, "title": "Chronos night", "planned_date": date(2026, 12, 1),
                    "status": "planned", "bot_event_id": 55 if self.linked else None}
        if "FROM public.events" in query:
            return {"event_id": 55, "event_type": "chronos"}
        raise AssertionError("Unexpected query")

    async def fetchval(self, query, *args):
        self.calls.append(("fetchval", query, args))
        if "INSERT INTO public.events" in query:
            return 55
        raise AssertionError("Unexpected query")

    async def execute(self, query, *args):
        self.calls.append(("execute", query, args))
        return "UPDATE 1"


class ChronosAdminEventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = StagingFakeConnection()
        self.staging_connect = AsyncMock(return_value=self.conn)
        self.prod_connect = AsyncMock(side_effect=AssertionError("production connection must not be used"))
        self.db = patch("database.get_chronos_connection", new=self.staging_connect)
        self.db.start()
        self.prod = patch("database.get_connection", new=self.prod_connect)
        self.prod.start()

        @web.middleware
        async def telegram_user(request, handler):
            request["telegram_user"] = {"id": 424242}
            return await handler(request)

        app = web.Application(middlewares=[telegram_user])
        chronos_admin.register_admin_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.db.stop()
        self.prod.stop()

    async def test_admin_creates_event_in_staging_and_binds_it_to_slot(self):
        response = await self.client.post("/api/chronos/admin/slots/7/event", json={
            "title": "Test night", "event_date": "2026-12-02", "event_time": "18:30",
        })
        self.assertEqual(response.status, 201)
        self.assertEqual((await response.json())["event_id"], 55)
        insert = next(call for call in self.conn.calls if call[0] == "fetchval")
        self.assertIn("INSERT INTO public.events", insert[1])
        self.assertEqual(insert[2][-2:], ("18:30", 424242))
        slot_update = next(call for call in self.conn.calls if call[0] == "execute" and "UPDATE chronos.event_slots" in call[1])
        self.assertEqual(slot_update[2][:2], (7, 55))
        self.staging_connect.assert_awaited_once()
        self.prod_connect.assert_not_awaited()

    async def test_missing_chronos_database_blocks_without_production_fallback(self):
        import database
        self.db.stop()
        try:
            with patch.dict(os.environ, {"CHRONOS_DATABASE_URL": ""}), patch(
                "database.get_chronos_connection", new=database.get_chronos_connection
            ):
                response = await self.client.post("/api/chronos/admin/slots/7/event", json={
                    "title": "Test", "event_date": "2026-12-02", "event_time": "18:30",
                })
        finally:
            self.db.start()
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["error"], "chronos_database_not_configured")
        self.staging_connect.assert_not_awaited()
        self.prod_connect.assert_not_awaited()

    async def test_player_cannot_create_event(self):
        self.conn.role = "player"
        response = await self.client.post("/api/chronos/admin/slots/7/event", json={
            "title": "Test", "event_date": "2026-12-02", "event_time": "18:30",
        })
        self.assertEqual(response.status, 403)
        self.assertFalse(any("INSERT INTO public.events" in call[1] for call in self.conn.calls))
        self.assertFalse(any("UPDATE chronos.event_slots" in call[1] for call in self.conn.calls))

    async def test_slot_binding_and_linked_event_edit_status_work(self):
        self.conn.linked = True
        response = await self.client.post("/api/chronos/admin/slots/7/event/update", json={
            "title": "Updated", "event_date": "2026-12-03", "event_time": "19:00", "status": "closed",
        })
        self.assertEqual(response.status, 200)
        event_update = next(call for call in self.conn.calls if call[0] == "execute" and "UPDATE public.events" in call[1])
        self.assertEqual(event_update[2], (55, "Updated", date(2026, 12, 3), "19:00", "closed"))

    def test_ordinary_event_creation_remains_on_legacy_production_path(self):
        from pathlib import Path
        source = Path(__file__).parents[1].joinpath("bot.py").read_text(encoding="utf-8")
        creator = source[source.index("async def create_event_time"):source.index("async def confirm_event_start")]
        self.assertIn("get_connection()", creator)
        self.assertIn("INSERT INTO events", creator)
        self.assertNotIn("get_chronos_connection", creator)


class InvitationDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    def test_deadline_is_at_most_seven_days_when_final_is_far_away(self):
        deadline = _invitation_deadline(date(2026, 11, 20), self.now)
        self.assertEqual(deadline, self.now + timedelta(days=7))

    def test_deadline_is_48_hours_when_final_is_less_than_seven_days_away(self):
        deadline = _invitation_deadline(date(2026, 11, 10), self.now)
        self.assertEqual(deadline, self.now + timedelta(hours=48))

    def test_exactly_seven_calendar_days_uses_seven_day_limit(self):
        deadline = _invitation_deadline(date(2026, 11, 11), self.now)
        self.assertEqual(deadline, self.now + timedelta(days=7))


if __name__ == "__main__":
    unittest.main()
