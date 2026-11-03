"""Shared CHRONOS API helpers."""

import asyncpg
from aiohttp import web
from datetime import date, datetime
from decimal import Decimal
import json


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, asyncpg.Record):
        return json_safe(dict(value))
    return value


def json_value(value, fallback=None):
    if value is None:
        return fallback
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return fallback
    return value


def json_response(payload, status=200):
    return web.json_response(json_safe(payload), status=status, headers={"Cache-Control": "no-store"})


async def active_season_id(conn):
    return await conn.fetchval(
        "SELECT season_id FROM chronos.seasons WHERE status = 'active' ORDER BY season_id DESC LIMIT 1"
    )


async def current_season(conn):
    return await conn.fetchrow(
        """
        SELECT season_id, season_code, title, status, target_sync_units, platform_settings
        FROM chronos.seasons
        WHERE status IN ('draft','active','paused')
        ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END, season_id DESC
        LIMIT 1
        """
    )


async def require_admin(request, conn):
    user_id = request["telegram_user"]["id"]
    row = await conn.fetchrow(
        "SELECT role, is_active FROM public.users WHERE user_id = $1",
        user_id,
    )
    if not row or row["is_active"] != 1 or row["role"] != "admin":
        return json_response({"error": "admin_required"}, 403)
    return None


async def ledger_balance(conn, user_id: int, currency: str) -> int:
    return int(await conn.fetchval(
        "SELECT COALESCE(SUM(amount),0) FROM chronos.ledger WHERE user_id=$1 AND currency=$2",
        user_id, currency,
    ) or 0)


async def notify_user(conn, user_id, category, title, body, action_type=None, action_payload=None):
    await conn.execute(
        """
        INSERT INTO chronos.notifications
          (user_id,category,title,body,action_type,action_payload)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb)
        """,
        user_id, category, title, body, action_type,
        __import__("json").dumps(action_payload or {}),
    )


async def audit(conn, actor_id, action_code, target_type, target_id=None, details=None):
    await conn.execute(
        """
        INSERT INTO chronos.audit_log(actor_user_id,action_code,target_type,target_id,details)
        VALUES($1,$2,$3,$4,$5::jsonb)
        """,
        actor_id, action_code, target_type,
        None if target_id is None else str(target_id),
        __import__("json").dumps(details or {}),
    )


async def award_ledger(conn, user_id, currency, amount, reason_code, idempotency_key, reference_key=None, metadata=None, created_by=None):
    """Idempotent journal write. Returns whether a row was created."""
    row = await conn.fetchval(
        """
        INSERT INTO chronos.ledger
          (user_id,currency,amount,reason_code,reference_key,idempotency_key,metadata,created_by)
        VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8)
        ON CONFLICT (idempotency_key) DO NOTHING
        RETURNING ledger_id
        """,
        user_id, currency, int(amount), reason_code, reference_key, idempotency_key,
        __import__("json").dumps(metadata or {}), created_by,
    )
    return row is not None


async def award_achievement(conn, user_id, achievement_code, source_key=None):
    row = await conn.fetchrow(
        "SELECT achievement_id,name,reward_cr,reward_xp FROM chronos.achievement_definitions WHERE achievement_code=$1 AND is_enabled=TRUE",
        achievement_code,
    )
    if not row:
        return False
    inserted = await conn.fetchval(
        """
        INSERT INTO chronos.user_achievements(user_id,achievement_id,source_key)
        VALUES($1,$2,$3) ON CONFLICT DO NOTHING RETURNING achievement_id
        """,
        user_id,row["achievement_id"],source_key,
    )
    if not inserted:
        return False
    if row["reward_cr"]:
        await award_ledger(
            conn,user_id,"CR",int(row["reward_cr"]),"achievement_reward",
            f"achievement:cr:{user_id}:{achievement_code}",metadata={"achievement":achievement_code},
        )
    if row["reward_xp"]:
        await award_ledger(
            conn,user_id,"XP",int(row["reward_xp"]),"achievement_reward",
            f"achievement:xp:{user_id}:{achievement_code}",metadata={"achievement":achievement_code},
        )
    await notify_user(conn,user_id,"rewards","Нове досягнення",f"Отримано: {row['name']}.")
    return True


async def check_player_achievements(conn, season_id, user_id):
    games = await conn.fetchval(
        """
        SELECT COUNT(*) FROM chronos.game_players gp
        JOIN chronos.games g ON g.game_id=gp.game_id
        WHERE gp.user_id=$1 AND g.season_id=$2 AND g.status='confirmed' AND g.counts_for_sync=TRUE
        """,
        user_id,season_id,
    )
    if games >= 1:
        await award_achievement(conn,user_id,"FIRST_SYNC",f"first-sync:{season_id}:{user_id}")
    if games >= 10:
        await award_achievement(conn,user_id,"TEN_GAMES",f"ten-games:{season_id}:{user_id}")

    for game_code, achievement_code in (("MEMORY","FIRST_MEMORY"),("CODE_BREAKER","FIRST_CODE")):
        played = await conn.fetchval(
            """
            SELECT EXISTS(
              SELECT 1 FROM chronos.minigame_sessions
              WHERE season_id=$1 AND user_id=$2 AND game_code=$3 AND status='completed'
            )
            """,
            season_id,user_id,game_code,
        )
        if played:
            await award_achievement(conn,user_id,achievement_code,f"minigame:{season_id}:{user_id}:{game_code}")

    bets = await conn.fetchval(
        """
        SELECT COUNT(*) FROM chronos.prediction_bets b
        JOIN chronos.prediction_markets m ON m.market_id=b.market_id
        WHERE m.season_id=$1 AND b.bettor_user_id=$2 AND b.status<>'refunded'
        """,
        season_id,user_id,
    )
    if bets >= 6:
        await award_achievement(conn,user_id,"SIX_PREDICTIONS",f"six-predictions:{season_id}:{user_id}")

    finals = await conn.fetchval(
        """
        SELECT COUNT(DISTINCT s.slot_id)
        FROM chronos.event_slots s
        JOIN chronos.games g ON g.bot_event_id=s.bot_event_id AND g.status='confirmed'
        JOIN chronos.game_players gp ON gp.game_id=g.game_id AND gp.user_id=$2
        WHERE s.season_id=$1 AND s.slot_type='intermediate_final'
        """,
        season_id,user_id,
    )
    if finals >= 3:
        await award_achievement(conn,user_id,"THREE_FINALS",f"three-finals:{season_id}:{user_id}")
