from database import get_connection


async def get_active_event():
    conn = await get_connection()
    try:
        event = await conn.fetchrow(
            """
            SELECT event_id, title
            FROM events
            WHERE status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        return event
    finally:
        await conn.close()


async def get_event_players(event_id):
    conn = await get_connection()
    try:
        players = await conn.fetch(
            """
            SELECT u.user_id, u.display_name
            FROM registrations r
            JOIN users u ON u.user_id = r.user_id
            WHERE r.event_id = $1
              AND r.status = 'active'
            """
            ,
            event_id
        )
        return players
    finally:
        await conn.close()
