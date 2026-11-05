"""Authenticated CHRONOS Mini App API, mounted on the existing aiohttp server."""

import json
import logging
import os
from pathlib import Path

import asyncpg
from aiohttp import web

try:
    from database import ChronosDatabaseNotConfigured, get_chronos_connection as get_connection
except ModuleNotFoundError:
    from mafia_bot.database import ChronosDatabaseNotConfigured, get_chronos_connection as get_connection

try:
    from modules.chronos_auth import validate_init_data
except ModuleNotFoundError:
    from mafia_bot.modules.chronos_auth import validate_init_data


logger = logging.getLogger(__name__)

API_PREFIX = "/api/chronos"
MINIAPP_DIR = Path(__file__).resolve().parents[1] / "miniapp"


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

    # CHRONOS_ACCESS_MODE defaults to a closed test with one admin. The optional
    # open mode is intended for later player access after an explicit config change.
    access_mode = os.getenv("CHRONOS_ACCESS_MODE", "closed").strip().lower()
    if access_mode not in {"closed", "open"}:
        return _json({"error": "chronos_access_mode_invalid"}, 503)

    # Keep the test administrator configured and valid in staging in either mode.
    configured_admin = os.getenv("CHRONOS_TEST_ADMIN_ID", "").strip()
    try:
        if not configured_admin.isascii() or not configured_admin.isdigit():
            raise ValueError("invalid test admin id")
        test_admin_id = int(configured_admin)
    except ValueError:
        return _json({"error": "closed_test_admin_not_configured"}, 503)
    if test_admin_id <= 0:
        return _json({"error": "closed_test_admin_not_configured"}, 503)

    user_id = request["telegram_user"]["id"]
    if access_mode == "closed" and user_id != test_admin_id:
        return _json({"error": "admin_test_access_only"}, 403)

    conn = None
    access_check_stage = "database_connect"
    try:
        conn = await get_connection()
        access_check_stage = "admin_lookup"
        test_admin = await conn.fetchrow(
            """
            SELECT role, is_active
            FROM public.users
            WHERE user_id = $1
            """,
            test_admin_id,
        )
        if not test_admin or test_admin["is_active"] != 1 or test_admin["role"] != "admin":
            return _json({"error": "closed_test_admin_not_configured"}, 503)

        if user_id == test_admin_id:
            account = test_admin
        elif access_mode == "open":
            account = await conn.fetchrow(
                "SELECT role, is_active FROM public.users WHERE user_id = $1",
                user_id,
            )
        else:
            return _json({"error": "admin_test_access_only"}, 403)

        if not account or account["is_active"] != 1:
            return _json({
                "error": "admin_test_access_only",
                "message": "CHRONOS зараз доступний лише призначеному адміністратору під час тестування.",
            }, 403)
        if access_mode == "closed" and account["role"] != "admin":
            return _json({"error": "admin_test_access_only"}, 403)
    except ChronosDatabaseNotConfigured:
        return _json({"error": "chronos_database_not_configured"}, 503)
    except asyncpg.UndefinedTableError:
        return _json({"error": "database_not_ready"}, 503)
    except Exception as exc:
        # Log only safe diagnostics: never include exception text, DSN, or credentials.
        logger.error(
            "CHRONOS access check failed: stage=%s error_type=%s",
            access_check_stage,
            type(exc).__name__,
        )
        # Fail closed: database/auth lookup failures must never expose season data.
        return _json({"error": "access_check_unavailable"}, 503)
    finally:
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass

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

        sync_units = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM chronos.game_players gp
            JOIN chronos.games g ON g.game_id=gp.game_id
            WHERE g.season_id=$1 AND g.status='confirmed' AND g.counts_for_sync=TRUE
            """,
            season["season_id"],
        )
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
                "sync_units": int(sync_units or 0),
                "sync_percent": min(100, round(100*int(sync_units or 0)/max(1,season["target_sync_units"]),1)),
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

        # One unique, verified Mini App interaction per active bot player/event.
        # Reopening the same event detail does not farm additional Activity Score.
        player_active=await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM public.users WHERE user_id=$1 AND is_active=1)",
            tg_user["id"],
        )
        if player_active:
            await conn.execute(
                """
                INSERT INTO chronos.activity_events
                  (season_id,user_id,action_code,score_value,source_key,verified,metadata)
                SELECT season_id,$1,'event_detail_view',1,$2,TRUE,$3::jsonb
                FROM chronos.seasons
                WHERE status='active'
                ON CONFLICT(source_key) DO NOTHING
                """,
                tg_user["id"],
                f"miniapp-event-view:{event_id}:{tg_user['id']}",
                json.dumps({"event_id":event_id,"interaction":"event_detail_view"}),
            )

        roster = await conn.fetch(
            """
            SELECT u.display_name, p.avatar_base, r.created_at
            FROM public.registrations r
            JOIN public.users u ON u.user_id = r.user_id
            LEFT JOIN chronos.profiles p ON p.user_id = u.user_id
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
                    "avatar_base": row["avatar_base"] or "european_male",
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

            await conn.execute(
                """
                INSERT INTO chronos.activity_events
                  (season_id,user_id,action_code,score_value,source_key,verified,metadata)
                SELECT s.season_id,$1,'event_registration',1,$2,TRUE,$3::jsonb
                FROM chronos.seasons s
                WHERE s.status='active'
                ON CONFLICT(source_key) DO NOTHING
                """,
                tg_user["id"],
                f"miniapp-registration:{event_id}:{tg_user['id']}",
                json.dumps({"event_id":event_id}),
            )
        return _json({
            "registered": True,
            "event_id": event_id,
            "message": "Реєстрацію підтверджено.",
        }, 201)
    except asyncpg.UndefinedTableError:
        return _json({"error": "database_not_ready"}, 503)
    finally:
        await conn.close()


async def miniapp_index(request):
    """Serve the CHRONOS Telegram Mini App shell."""
    index_file = MINIAPP_DIR / "index.html"
    if not index_file.is_file():
        raise web.HTTPServiceUnavailable(text="CHRONOS Mini App assets are not installed.")
    return web.FileResponse(
        index_file,
        headers={"Cache-Control": "no-cache"},
    )



async def cancel_event_registration(request):
    event_id=int(request.match_info["event_id"])
    user_id=request["telegram_user"]["id"]
    from database import get_chronos_connection as get_connection
    conn=await get_connection()
    try:
        async with conn.transaction():
            event=await conn.fetchrow(
                "SELECT event_id,status,event_type FROM public.events WHERE event_id=$1",
                event_id,
            )
            if not event or event["event_type"]!="chronos" or event["status"]!="active":
                return _json({"error":"event_not_available"},409)
            registration=await conn.fetchrow(
                """
                UPDATE public.registrations SET status='cancelled',updated_at=NOW()
                WHERE event_id=$1 AND user_id=$2 AND status='active'
                RETURNING registration_id
                """,
                event_id,user_id,
            )
            if not registration:
                return _json({"error":"active_registration_not_found"},404)
            await conn.execute(
                """
                INSERT INTO chronos.activity_events
                  (season_id,user_id,action_code,score_value,source_key,verified,metadata)
                SELECT season_id,$1,'event_cancellation',0,$2,TRUE,$3::jsonb
                FROM chronos.seasons WHERE status='active'
                ON CONFLICT(source_key) DO NOTHING
                """,
                user_id,f"miniapp-cancel:{event_id}:{user_id}",json.dumps({"event_id":event_id}),
            )
        return _json({"cancelled":True,"event_id":event_id})
    finally:
        await conn.close()

def register_chronos_routes(app):
    """Mount authenticated API routes and the static Mini App on the bot server."""
    app.router.add_get("/miniapp", miniapp_index)
    app.router.add_get("/miniapp/", miniapp_index)
    app.router.add_static(
        "/miniapp/assets/",
        str(MINIAPP_DIR / "assets"),
        name="chronos-miniapp-assets",
        show_index=False,
    )
    app.router.add_get(API_PREFIX + "/me", get_me)
    app.router.add_get(API_PREFIX + "/events", list_events)
    app.router.add_get(API_PREFIX + "/events/{event_id:\\d+}", get_event)
    app.router.add_post(
        API_PREFIX + "/events/{event_id:\\d+}/register",
        register_for_event,
    )
    app.router.add_post(
        API_PREFIX + "/events/{event_id:\\d+}/cancel",
        cancel_event_registration,
    )

    from modules.chronos_identity import register_identity_routes
    from modules.chronos_games import register_game_routes
    from modules.chronos_predictions import register_prediction_routes
    from modules.chronos_admin import register_admin_routes

    register_identity_routes(app)
    register_game_routes(app)
    register_prediction_routes(app)
    register_admin_routes(app)
