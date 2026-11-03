"""CHRONOS identity, wardrobe, rewards, operations and notifications API."""

import json
import math

import asyncpg
from aiohttp import web

from modules.chronos_common import (
    active_season_id, audit, json_response, json_value, ledger_balance, require_admin
)
from modules.chronos_logic import AVATAR_BASES, level_for_xp


async def get_identity(request):
    user_id = request["telegram_user"]["id"]
    conn = await request.app["db_connection"]() if request.app.get("db_connection") else None
    if conn is None:
        from database import get_connection
        conn = await get_connection()
    try:
        user = await conn.fetchrow(
            "SELECT display_name,role,is_active FROM public.users WHERE user_id=$1",
            user_id,
        )
        if not user or user["is_active"] != 1:
            return json_response({"error": "profile_not_found"}, 404)

        await conn.execute(
            "INSERT INTO chronos.profiles(user_id) VALUES($1) ON CONFLICT DO NOTHING",
            user_id,
        )
        profile = await conn.fetchrow(
            "SELECT avatar_base,active_title,active_badge_1,active_badge_2 FROM chronos.profiles WHERE user_id=$1",
            user_id,
        )
        cr = await ledger_balance(conn, user_id, "CR")
        ex = await ledger_balance(conn, user_id, "EX")
        xp = await ledger_balance(conn, user_id, "XP")
        level, level_xp, next_level_xp = level_for_xp(xp)
        equipment = await conn.fetch(
            """
            SELECT e.equip_slot, c.item_code, c.name, c.visual_key
            FROM chronos.equipment e
            JOIN chronos.catalog_items c ON c.item_id=e.item_id
            WHERE e.user_id=$1
            """,
            user_id,
        )
        return json_response({
            "profile_complete": bool(user["display_name"]),
            "display_name": user["display_name"],
            "role": user["role"],
            "avatar_base": profile["avatar_base"],
            "active_title": profile["active_title"],
            "badges": [v for v in (profile["active_badge_1"], profile["active_badge_2"]) if v],
            "balances": {"CR": cr, "EX": ex, "XP": xp},
            "level": {"current": level, "xp_in_level": level_xp, "next_level_xp": next_level_xp},
            "equipment": [dict(row) for row in equipment],
        })
    except asyncpg.UndefinedTableError:
        return json_response({"error": "database_not_ready"}, 503)
    finally:
        await conn.close()


async def update_avatar(request):
    user_id = request["telegram_user"]["id"]
    try:
        payload = await request.json()
    except (ValueError, json.JSONDecodeError):
        return json_response({"error": "invalid_json"}, 400)
    avatar = payload.get("avatar_base") if isinstance(payload, dict) else None
    if avatar not in AVATAR_BASES:
        return json_response({"error": "invalid_avatar_base"}, 400)

    from database import get_connection
    conn = await get_connection()
    try:
        await conn.execute(
            """
            INSERT INTO chronos.profiles(user_id,avatar_base)
            VALUES($1,$2)
            ON CONFLICT(user_id) DO UPDATE SET avatar_base=EXCLUDED.avatar_base,updated_at=NOW()
            """,
            user_id, avatar,
        )
        return json_response({"avatar_base": avatar, "updated": True})
    finally:
        await conn.close()


async def store_catalog(request):
    user_id = request["telegram_user"]["id"]
    from database import get_connection
    conn = await get_connection()
    try:
        items = await conn.fetch(
            """
            SELECT c.item_id,c.item_code,c.name,c.description,c.currency,c.price,
                   c.equip_slot,c.rarity,c.visual_key,c.is_enabled,
                   (i.user_id IS NOT NULL) AS owned,
                   (e.item_id IS NOT NULL) AS equipped
            FROM chronos.catalog_items c
            LEFT JOIN chronos.inventory i ON i.item_id=c.item_id AND i.user_id=$1
            LEFT JOIN chronos.equipment e ON e.item_id=c.item_id AND e.user_id=$1
            ORDER BY c.currency,c.price,c.item_id
            """,
            user_id,
        )
        return json_response({
            "balances": {
                "CR": await ledger_balance(conn,user_id,"CR"),
                "EX": await ledger_balance(conn,user_id,"EX"),
            },
            "items": [dict(row) for row in items],
        })
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def buy_item(request):
    user_id = request["telegram_user"]["id"]
    item_id = int(request.match_info["item_id"])
    from database import get_connection
    conn = await get_connection()
    try:
        async with conn.transaction():
            item = await conn.fetchrow(
                "SELECT * FROM chronos.catalog_items WHERE item_id=$1 AND is_enabled=TRUE FOR UPDATE",
                item_id,
            )
            if not item:
                return json_response({"error":"item_unavailable"},404)
            already = await conn.fetchval(
                "SELECT 1 FROM chronos.inventory WHERE user_id=$1 AND item_id=$2",
                user_id,item_id,
            )
            if already:
                return json_response({"error":"already_owned"},409)
            balance = await ledger_balance(conn,user_id,item["currency"])
            if balance < item["price"]:
                return json_response({"error":"insufficient_funds","balance":balance},409)
            await conn.execute(
                "INSERT INTO chronos.inventory(user_id,item_id,acquisition_source) VALUES($1,$2,'store')",
                user_id,item_id,
            )
            await conn.execute(
                """
                INSERT INTO chronos.ledger(user_id,currency,amount,reason_code,reference_key,idempotency_key)
                VALUES($1,$2,$3,'store_purchase',$4,$5)
                """,
                user_id,item["currency"],-int(item["price"]),str(item_id),
                f"store:{user_id}:{item_id}",
            )
            await conn.execute(
                """
                INSERT INTO chronos.notifications(user_id,category,title,body,action_type,action_payload)
                VALUES($1,'rewards','Покупку підтверджено',$2,'inventory','{}'::jsonb)
                """,
                user_id,f"Предмет {item['name']} додано до колекції.",
            )
        return json_response({"purchased":True,"item_code":item["item_code"]},201)
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def equip_item(request):
    user_id = request["telegram_user"]["id"]
    item_id = int(request.match_info["item_id"])
    from database import get_connection
    conn = await get_connection()
    try:
        item = await conn.fetchrow(
            """
            SELECT c.item_id,c.equip_slot,c.item_code,c.name
            FROM chronos.catalog_items c
            JOIN chronos.inventory i ON i.item_id=c.item_id AND i.user_id=$1
            WHERE c.item_id=$2
            """,
            user_id,item_id,
        )
        if not item:
            return json_response({"error":"item_not_owned"},404)
        await conn.execute(
            """
            INSERT INTO chronos.equipment(user_id,equip_slot,item_id)
            VALUES($1,$2,$3)
            ON CONFLICT(user_id,equip_slot) DO UPDATE SET item_id=EXCLUDED.item_id,equipped_at=NOW()
            """,
            user_id,item["equip_slot"],item_id,
        )
        return json_response({"equipped":True,"slot":item["equip_slot"],"item_code":item["item_code"]})
    finally:
        await conn.close()


async def achievements(request):
    user_id = request["telegram_user"]["id"]
    from database import get_connection
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT a.achievement_code,a.name,a.description,a.tier,
                   ua.awarded_at,(ua.user_id IS NOT NULL) AS earned
            FROM chronos.achievement_definitions a
            LEFT JOIN chronos.user_achievements ua
              ON ua.achievement_id=a.achievement_id AND ua.user_id=$1
            WHERE a.is_enabled=TRUE
            ORDER BY earned DESC,a.tier,a.achievement_id
            """,
            user_id,
        )
        return json_response({"achievements":[dict(row) for row in rows]})
    finally:
        await conn.close()


async def notifications(request):
    user_id = request["telegram_user"]["id"]
    try:
        limit = max(1,min(100,int(request.query.get("limit","50"))))
    except ValueError:
        limit = 50
    from database import get_connection
    conn = await get_connection()
    try:
        rows = await conn.fetch(
            """
            SELECT notification_id,category,title,body,action_type,action_payload,read_at,created_at
            FROM chronos.notifications WHERE user_id=$1
            ORDER BY created_at DESC LIMIT $2
            """,
            user_id,limit,
        )
        unread = await conn.fetchval(
            "SELECT COUNT(*) FROM chronos.notifications WHERE user_id=$1 AND read_at IS NULL",
            user_id,
        )
        return json_response({"unread_count":unread,"items":[dict(row) for row in rows]})
    finally:
        await conn.close()


async def mark_notification_read(request):
    user_id = request["telegram_user"]["id"]
    notification_id = int(request.match_info["notification_id"])
    from database import get_connection
    conn = await get_connection()
    try:
        result = await conn.execute(
            """
            UPDATE chronos.notifications SET read_at=COALESCE(read_at,NOW())
            WHERE notification_id=$1 AND user_id=$2
            """,
            notification_id,user_id,
        )
        if result.endswith("0"):
            return json_response({"error":"notification_not_found"},404)
        return json_response({"read":True})
    finally:
        await conn.close()


async def operations(request):
    user_id = request["telegram_user"]["id"]
    from database import get_connection
    conn = await get_connection()
    try:
        season = await conn.fetchrow(
            """
            SELECT season_id,status,target_sync_units,platform_settings
            FROM chronos.seasons WHERE status IN ('active','paused','draft')
            ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,season_id DESC LIMIT 1
            """
        )
        if not season:
            return json_response({"season":None,"stats":{},"invitations":[]})
        season_id = season["season_id"]
        conducted_games = await conn.fetchval(
            "SELECT COUNT(*) FROM chronos.games WHERE season_id=$1 AND status='confirmed' AND counts_for_sync=TRUE",
            season_id,
        )
        played_games = await conn.fetchval(
            """
            SELECT COUNT(*) FROM chronos.game_players gp
            JOIN chronos.games g ON g.game_id=gp.game_id
            WHERE g.season_id=$1 AND g.status='confirmed' AND g.counts_for_sync=TRUE AND gp.user_id=$2
            """,
            season_id,user_id,
        )
        sync_units = await conn.fetchval(
            """
            SELECT COUNT(*) FROM chronos.game_players gp
            JOIN chronos.games g ON g.game_id=gp.game_id
            WHERE g.season_id=$1 AND g.status='confirmed' AND g.counts_for_sync=TRUE
            """,
            season_id,
        )
        eligible_regular = await conn.fetchval(
            """
            SELECT COUNT(*) FROM chronos.event_slots s
            WHERE s.season_id=$1 AND s.slot_type='regular'
              AND s.bot_event_id IS NOT NULL
              AND EXISTS(SELECT 1 FROM public.events e WHERE e.event_id=s.bot_event_id AND e.status='closed')
            """,
            season_id,
        )
        attended_regular = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT s.slot_id)
            FROM chronos.event_slots s
            JOIN chronos.games g ON g.bot_event_id=s.bot_event_id AND g.status='confirmed'
            JOIN chronos.game_players gp ON gp.game_id=g.game_id AND gp.user_id=$2
            WHERE s.season_id=$1 AND s.slot_type='regular'
            """,
            season_id,user_id,
        )
        invited_finals = await conn.fetchval(
            """
            SELECT COUNT(*) FROM chronos.final_invitations fi
            JOIN chronos.event_slots s ON s.slot_id=fi.slot_id
            WHERE s.season_id=$1 AND fi.user_id=$2
            """,
            season_id,user_id,
        )
        attended_finals = await conn.fetchval(
            """
            SELECT COUNT(*) FROM chronos.final_invitations fi
            JOIN chronos.event_slots s ON s.slot_id=fi.slot_id
            JOIN chronos.games g ON g.bot_event_id=s.bot_event_id AND g.status='confirmed'
            JOIN chronos.game_players gp ON gp.game_id=g.game_id AND gp.user_id=$2
            WHERE s.season_id=$1 AND fi.user_id=$2 AND s.slot_type IN ('intermediate_final','main_final')
            """,
            season_id,user_id,
        )
        invitations = await conn.fetch(
            """
            SELECT fi.invitation_id,fi.status,fi.rank_at_invite,fi.deadline_at,
                   s.title AS slot_title,s.planned_date,s.slot_type
            FROM chronos.final_invitations fi
            JOIN chronos.event_slots s ON s.slot_id=fi.slot_id
            WHERE s.season_id=$1 AND fi.user_id=$2
            ORDER BY fi.invited_at DESC
            """,
            season_id,user_id,
        )
        mini_game_count = await conn.fetchval(
            "SELECT COUNT(*) FROM chronos.minigame_sessions WHERE season_id=$1 AND user_id=$2 AND status='completed'",
            season_id,user_id,
        )
        app_actions = await conn.fetchval(
            "SELECT COUNT(*) FROM chronos.activity_events WHERE season_id=$1 AND user_id=$2 AND verified=TRUE",
            season_id,user_id,
        )
        settings = json_value(season["platform_settings"], {}) or {}
        weights = settings.get("activity_score", {})
        attendance_total = int(eligible_regular or 0) + int(invited_finals or 0)
        attendance_done = int(attended_regular or 0) + int(attended_finals or 0)
        attendance_pct = round(100*attendance_done/attendance_total,1) if attendance_total else 0.0
        qualifies = int(played_games or 0) >= math.ceil(0.3*int(conducted_games or 0)) if conducted_games else False
        return json_response({
            "season":{"status":season["status"]},
            "participation":{
                "games_played":int(played_games or 0),
                "games_conducted":int(conducted_games or 0),
                "qualification_minimum":math.ceil(0.3*int(conducted_games or 0)),
                "qualified":qualifies,
            },
            "attendance":{"eligible_evenings":attendance_total,"attended":attendance_done,"percent":attendance_pct},
            "mini_games_completed":int(mini_game_count or 0),
            "verified_app_actions":int(app_actions or 0),
            "activity_score_status":weights.get("status","draft"),
            "activity_score_weights":weights.get("weights",{"attendance":80,"app":15,"minigame":5}),
            "invitations":[dict(row) for row in invitations],
        })
    finally:
        await conn.close()


async def rankings(request):
    user_id = request["telegram_user"]["id"]
    from database import get_connection
    conn = await get_connection()
    try:
        season = await conn.fetchrow(
            "SELECT season_id,target_sync_units FROM chronos.seasons ORDER BY season_id DESC LIMIT 1"
        )
        if not season:
            return json_response({"snapshot":None,"players":[]})
        snapshot = await conn.fetchrow(
            """
            SELECT snapshot_id,captured_at FROM chronos.ranking_snapshots
            WHERE season_id=$1 ORDER BY captured_at DESC,snapshot_id DESC LIMIT 1
            """,
            season["season_id"],
        )
        if not snapshot:
            return json_response({"snapshot":None,"players":[],"sync_units":0,"target_sync_units":season["target_sync_units"]})
        rows = await conn.fetch(
            """
            SELECT rp.user_id,u.display_name,rp.rank_position,rp.points,rp.games_played,rp.wins,
                   rp.bonus_points,
                   CASE WHEN rp.games_played>0 THEN ROUND((rp.wins::numeric/rp.games_played)*100,1) ELSE 0 END AS win_rate,
                   (rp.user_id=$2) AS is_me
            FROM chronos.ranking_players rp
            JOIN public.users u ON u.user_id=rp.user_id
            WHERE rp.snapshot_id=$1 ORDER BY rp.rank_position
            """,
            snapshot["snapshot_id"],user_id,
        )
        sync_units = await conn.fetchval(
            """
            SELECT COUNT(*) FROM chronos.game_players gp
            JOIN chronos.games g ON g.game_id=gp.game_id
            WHERE g.season_id=$1 AND g.status='confirmed' AND g.counts_for_sync=TRUE
            """,
            season["season_id"],
        )
        total_games = await conn.fetchval(
            "SELECT COUNT(*) FROM chronos.games WHERE season_id=$1 AND status='confirmed' AND counts_for_sync=TRUE",
            season["season_id"],
        )
        played = await conn.fetchval(
            """
            SELECT COUNT(*) FROM chronos.game_players gp JOIN chronos.games g ON g.game_id=gp.game_id
            WHERE g.season_id=$1 AND g.status='confirmed' AND g.counts_for_sync=TRUE AND gp.user_id=$2
            """,
            season["season_id"],user_id,
        )
        return json_response({
            "snapshot":{"captured_at":snapshot["captured_at"].isoformat()},
            "players":[dict(row) for row in rows],
            "my_rank":next((dict(r) for r in rows if r["is_me"]),None),
            "sync_units":int(sync_units or 0),
            "target_sync_units":season["target_sync_units"],
            "qualification":{
                "games_played":int(played or 0),
                "games_conducted":int(total_games or 0),
                "minimum":math.ceil(0.3*int(total_games or 0)),
                "qualified":bool(total_games and int(played or 0)>=math.ceil(0.3*int(total_games or 0))),
            },
        })
    finally:
        await conn.close()


def register_identity_routes(app):
    app.router.add_get("/api/chronos/identity", get_identity)
    app.router.add_post("/api/chronos/identity/avatar", update_avatar)
    app.router.add_get("/api/chronos/store", store_catalog)
    app.router.add_post("/api/chronos/store/{item_id:\\d+}/buy", buy_item)
    app.router.add_post("/api/chronos/store/{item_id:\\d+}/equip", equip_item)
    app.router.add_get("/api/chronos/achievements", achievements)
    app.router.add_get("/api/chronos/notifications", notifications)
    app.router.add_post("/api/chronos/notifications/{notification_id:\\d+}/read", mark_notification_read)
    app.router.add_get("/api/chronos/operations", operations)
    app.router.add_get("/api/chronos/rankings", rankings)
