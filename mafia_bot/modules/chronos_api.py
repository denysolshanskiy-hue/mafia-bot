"""Authenticated CHRONOS Mini App API, mounted on the existing aiohttp server."""

import json
import os

import asyncpg
from aiohttp import web

try:
    from database import get_connection
except ModuleNotFoundError:
    from mafia_bot.database import get_connection

try:
    from modules.chronos_auth import validate_init_data
except ModuleNotFoundError:
    from mafia_bot.modules.chronos_auth import validate_init_data


API_PREFIX = "/api/chronos"


def _json(data, status=200):
    return web.json_response(
        data,
        status=status,
        headers={"Cache-Control": "no-store"},
    )


def _date(value):
    return value.isoformat() if value is not None else None


def _auth_max_age():
    try:
        return int(os.getenv("TELEGRAM_INIT_DATA_MAX_AGE", "86400"))
    except ValueError:
        return 86400


@web.middleware
async def telegram_auth_middleware(request, handler):
    if not request.path.startswith(API_PREFIX + "/"):
        return await handler(request)

    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("tma "):
        init_data = authorization[4:].strip()
    else:
        init_data = request.headers.get("X-Telegram-Init-Data", "").strip()

    try:
        request["telegram_user"] = validate_init_data(
            init_data,
            os.getenv("BOT_TOKEN", ""),
            max_age_seconds=_auth_max_age(),
        )
    except ValueError:
        return _json({"error": "unauthorized", "message": "Telegram-сесію не підтверджено."}, 401)

    return await handler(request)


async def get_me(request):
    tg_user = request["telegram_user"]
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT display_name, role, is_active
            FROM public.users
            WHERE user_id = $1
            """,
            tg_user["id"],
        )
        if not row:
            return _json({
                "profile_complete": False,
                "message": "Спочатку відкрийте бота та пройдіть /start.",
            }, 200)

        if row["is_active"] != 1:
            return _json({"error": "account_disabled"}, 403)

        return _json({
            "profile_complete": bool(row["display_name"]),
            "display_name": row["display_name"],
            "role": row["role"],
        })
    except asyncpg.UndefinedTableError:
        return _json({"error": "database_not_ready"}, 503)
    finally:
        await conn.close()


async def list_events(request):
    tg_user = request["telegram_user"]
    conn = await get_connection()
    try:
        season = await conn.fetchrow(
            """
            SELECT season_id, season_code, title, status, target_sync_units
            FROM chronos.seasons
            WHERE status IN ('draft', 'active', 'paused')
            ORDER BY CASE WHEN status = 'active' THEN 0 WHEN status = 'paused' THEN 1 ELSE 2 END, season_id DESC
            LIMIT 1
            """
        )
        if not season:
            return _json({"season": None, "events": [], "planned_slots": []})

        events = await conn.fetch(
            """
            SELECT
                e.event_id,
                e.title,
                e.event_date,
                e.event_time,
                s.slot_code,
                s.sequence_no,
                s.slot_type,
                (
                    SELECT COUNT(*)
                    FROM public.registrations r
                    JOIN public.users u ON u.user_id = r.user_id
                    WHERE r.event_id = e.event_id
                      AND r.status = 'active'
                      AND u.is_active = 1
                ) AS active_count,
                EXISTS (
                    SELECT 1
                    FROM public.registrations r
                    WHERE r.event_id = e.event_id
                      AND r.user_id = $2
                      AND r.status = 'active'
                ) AS is_registered
            FROM public.events e
            LEFT JOIN chronos.event_slots s
              ON s.bot_event_id = e.event_id
             AND s.season_id = $1
            WHERE e.status = 'active'
              AND e.event_type = 'chronos'
            ORDER BY e.event_date ASC, e.created_at ASC
            """,
            season["season_id"],
            tg_user["id"],
        )

        planned_slots = await conn.fetch(
            """
            SELECT slot_id, slot_code, sequence_no, slot_type, title, planned_date
            FROM chronos.event_slots
            WHERE season_id = $1
              AND status = 'planned'
              AND bot_event_id IS NULL
            ORDER BY sequence_no
            """,
            season["season_id"],
        )

        return _json({
            "season": {
                "season_code": season["season_code"],
                "title": season["title"],
                "status": season["status"],
                "target_sync_units": season["target_sync_units"],
            },
            "events": [
                {
                    "event_id": row["event_id"],
                    "title": row["title"],
                    "event_date": _date(row["event_date"]),
                    "event_time": row["event_time"],
                    "slot_code": row["slot_code"],
                    "sequence_no": row["sequence_no"],
                    "slot_type": row["slot_type"],
                    "active_count": row["active_count"],
                    "is_registered": row["is_registered"],
                }
                for row in events
            ],
            "planned_slots": [
                {
                    "slot_id": row["slot_id"],
                    "slot_code": row["slot_code"],
                    "sequence_no": row["sequence_no"],
                    "slot_type": row["slot_type"],
                    "title": row["title"],
                    "planned_date": _date(row["planned_date"]),
                }
                for row in planned_slots
            ],
        })
    except asyncpg.UndefinedTableError:
        return _json({"error": "database_not_ready"}, 503)
    finally:
        await conn.close()


async def get_event(request):
    event_id = int(request.match_info["event_id"])
    tg_user = request["telegram_user"]
    conn = await get_connection()
    try:
        event = await conn.fetchrow(
            """
            SELECT event_id, title, event_date, event_time
            FROM public.events
            WHERE event_id = $1
              AND event_type = 'chronos'
              AND status = 'active'
            """,
            event_id,
        )
        if not event:
            return _json({"error": "event_not_found"}, 404)

        roster = await conn.fetch(
            """
            SELECT u.display_name, r.created_at
            FROM public.registrations r
            JOIN public.users u ON u.user_id = r.user_id
            WHERE r.event_id = $1
              AND r.status = 'active'
              AND u.is_active = 1
            ORDER BY r.created_at, u.display_name
            """,
            event_id,
        )
        is_registered = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM public.registrations
                WHERE event_id = $1
                  AND user_id = $2
                  AND status = 'active'
            )
            """,
            event_id,
            tg_user["id"],
        )
        return _json({
            "event": {
                "event_id": event["event_id"],
                "title": event["title"],
                "event_date": _date(event["event_date"]),
                "event_time": event["event_time"],
                "is_registered": is_registered,
                "active_count": len(roster),
            },
            "roster": [
                {
                    "display_name": row["display_name"],
                    "registered_at": row["created_at"].isoformat(),
                }
                for row in roster
            ],
        })
    except asyncpg.UndefinedTableError:
        return _json({"error": "database_not_ready"}, 503)
    finally:
        await conn.close()


async def register_for_event(request):
    event_id = int(request.match_info["event_id"])
    tg_user = request["telegram_user"]

    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        return _json({"error": "invalid_json"}, 400)
    if not isinstance(payload, dict):
        return _json({"error": "invalid_json"}, 400)

    comment = payload.get("comment")
    if comment is not None:
        if not isinstance(comment, str):
            return _json({"error": "invalid_comment"}, 400)
        comment = comment.strip() or None
        if comment and len(comment) > 500:
            return _json({"error": "comment_too_long", "max_length": 500}, 400)

    conn = await get_connection()
    try:
        async with conn.transaction():
            season_is_active = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1 FROM chronos.seasons WHERE status = 'active'
                )
                """
            )
            if not season_is_active:
                return _json({"error": "season_not_active"}, 409)

            event = await conn.fetchrow(
                """
                SELECT event_id, title
                FROM public.events
                WHERE event_id = $1
                  AND event_type = 'chronos'
                  AND status = 'active'
                FOR SHARE
                """,
                event_id,
            )
            if not event:
                return _json({"error": "event_not_available"}, 409)

            user = await conn.fetchrow(
                """
                SELECT display_name, is_active
                FROM public.users
                WHERE user_id = $1
                FOR SHARE
                """,
                tg_user["id"],
            )
            if not user or not user["display_name"]:
                return _json({
                    "error": "profile_incomplete",
                    "message": "Спочатку відкрийте бота та вкажіть ігровий нік через /start.",
                }, 409)
            if user["is_active"] != 1:
                return _json({"error": "account_disabled"}, 403)

            inserted = await conn.fetchval(
                """
                INSERT INTO public.registrations (event_id, user_id, comment, status)
                VALUES ($1, $2, $3, 'active')
                ON CONFLICT DO NOTHING
                RETURNING registration_id
                """,
                event_id,
                tg_user["id"],
                comment,
            )
            if inserted is None:
                return _json({
                    "error": "already_registered",
                    "message": "Ви вже записані на цей вечір.",
                }, 409)

        return _json({
            "registered": True,
            "event_id": event_id,
            "message": "Реєстрацію підтверджено.",
        }, 201)
    except asyncpg.UndefinedTableError:
        return _json({"error": "database_not_ready"}, 503)
    finally:
        await conn.close()


def register_chronos_routes(app):
    """Mount authenticated API routes on the bot's existing aiohttp application."""
    app.router.add_get(API_PREFIX + "/me", get_me)
    app.router.add_get(API_PREFIX + "/events", list_events)
    app.router.add_get(API_PREFIX + "/events/{event_id:\\d+}", get_event)
    app.router.add_post(
        API_PREFIX + "/events/{event_id:\\d+}/register",
        register_for_event,
    )
