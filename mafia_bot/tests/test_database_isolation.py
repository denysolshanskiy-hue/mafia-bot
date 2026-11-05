import os
import unittest
from unittest.mock import AsyncMock, patch

try:
    import database
except ModuleNotFoundError:
    from mafia_bot import database


class ChronosDatabaseIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_chronos_url_never_uses_bot_database_url(self):
        connect = AsyncMock()
        with patch.dict(os.environ, {"DATABASE_URL": "production-url"}, clear=True):
            with patch.object(database.asyncpg, "connect", connect):
                with self.assertRaises(database.ChronosDatabaseNotConfigured):
                    await database.get_chronos_connection()
        connect.assert_not_awaited()

    async def test_chronos_connection_uses_only_chronos_database_url(self):
        connection = object()
        connect = AsyncMock(return_value=connection)
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "production-url",
                "CHRONOS_DATABASE_URL": "staging-url",
            },
            clear=True,
        ):
            with patch.object(database.asyncpg, "connect", connect):
                result = await database.get_chronos_connection()
        self.assertIs(result, connection)
        connect.assert_awaited_once_with("staging-url")


if __name__ == "__main__":
    unittest.main()
