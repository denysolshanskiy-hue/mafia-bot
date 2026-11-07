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


async def award_game_and_evening_rewards(conn, season_id, event_id, game_id, user_id, economy):
    """Issue CR/XP once per confirmed game and once per attended evening."""
    if (economy or {}).get("status") != "approved":
        return {"CR":0,"XP":0}
    cr_game=int((economy or {}).get("cr_per_confirmed_game",5))
    xp_game=int((economy or {}).get("xp_per_confirmed_game",10))
    cr_evening=int((economy or {}).get("cr_per_attended_evening",10))
    xp_evening=int((economy or {}).get("xp_per_attended_evening",5))
    metadata={"season_id":int(season_id),"event_id":int(event_id),"game_id":int(game_id)}
    minted={"CR":0,"XP":0}
    if cr_game:
        created=await award_ledger(
            conn,user_id,"CR",cr_game,"game_participation",
            f"chronos:{season_id}:cr:game:{game_id}:{user_id}",
            reference_key=str(game_id),metadata=metadata,
        )
        minted["CR"]+=cr_game if created else 0
    if xp_game:
        created=await award_ledger(
            conn,user_id,"XP",xp_game,"game_participation",
            f"chronos:{season_id}:xp:game:{game_id}:{user_id}",
            reference_key=str(game_id),metadata=metadata,
        )
        minted["XP"]+=xp_game if created else 0

    # The evening bonus is keyed by event + user and therefore is granted once,
    # even if the player appeared in all 5 or 8 games of that evening.
    if cr_evening:
        created=await award_ledger(
            conn,user_id,"CR",cr_evening,"evening_attendance",
            f"chronos:{season_id}:cr:event:{event_id}:{user_id}",
            reference_key=str(event_id),metadata=metadata,
        )
        minted["CR"]+=cr_evening if created else 0
    if xp_evening:
        created=await award_ledger(
            conn,user_id,"XP",xp_evening,"evening_attendance",
            f"chronos:{season_id}:xp:event:{event_id}:{user_id}",
            reference_key=str(event_id),metadata=metadata,
        )
        minted["XP"]+=xp_evening if created else 0
    return minted


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
    # CHRONOS season milestones (all checks are idempotent through award_achievement).
    accepted_finals = await conn.fetch(
        """
        SELECT s.slot_id,s.slot_type
        FROM chronos.final_invitations fi
        JOIN chronos.event_slots s ON s.slot_id=fi.slot_id
        WHERE fi.user_id=$1 AND s.season_id=$2
          AND s.slot_type IN ('intermediate_final','main_final')
          AND fi.status='accepted'
        ORDER BY fi.responded_at NULLS LAST,fi.invitation_id
        """,
        user_id,season_id,
    )
    if any(row["slot_type"] == "intermediate_final" for row in accepted_finals):
        await award_achievement(conn,user_id,"FIRST_INTERMEDIATE_FINAL",f"first-intermediate-final:{season_id}:{user_id}")
    if any(row["slot_type"] == "main_final" for row in accepted_finals):
        await award_achievement(conn,user_id,"FIRST_GRAND_FINAL",f"first-grand-final:{season_id}:{user_id}")

    first_purchase = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM chronos.ledger WHERE user_id=$1 AND reason_code='store_purchase' AND amount<0)",
        user_id,
    )
    if first_purchase:
        await award_achievement(conn,user_id,"FIRST_PURCHASE",f"first-purchase:{user_id}")

    minigame_seconds = await conn.fetchval(
        """
        SELECT COALESCE(SUM(LEAST(
            GREATEST(EXTRACT(EPOCH FROM (completed_at-started_at)),0),
            GREATEST(EXTRACT(EPOCH FROM (expires_at-started_at)),0),
            300
        )),0)
        FROM chronos.minigame_sessions
        WHERE user_id=$1 AND actions_count>0
          AND status IN ('completed','failed','expired') AND completed_at IS NOT NULL
        """,
        user_id,
    )
    if float(minigame_seconds or 0) > 18000:
        await award_achievement(conn,user_id,"MINIGAME_FIVE_HOURS",f"minigame-five-hours:{user_id}")

    # A slot counts only with an active registration (regular event) or an accepted
    # invitation (intermediate/Grand Final). Opened cards and declined invitations do not count.
    registered_slots = await conn.fetchval(
        """
        SELECT COUNT(DISTINCT s.slot_id)
        FROM chronos.event_slots s
        WHERE s.season_id=$1 AND (
          (s.slot_type='regular' AND EXISTS(
            SELECT 1 FROM public.registrations r
            WHERE r.event_id=s.bot_event_id AND r.user_id=$2 AND r.status='active'
          ))
          OR EXISTS(
            SELECT 1 FROM chronos.final_invitations fi
            WHERE fi.slot_id=s.slot_id AND fi.user_id=$2 AND fi.status='accepted'
          )
        )
        """,
        season_id,user_id,
    )
    season_slots = await conn.fetchval(
        "SELECT COUNT(*) FROM chronos.event_slots WHERE season_id=$1 AND slot_type IN ('regular','intermediate_final')",
        season_id,
    )
    grand_final_slots = await conn.fetchval(
        "SELECT COUNT(*) FROM chronos.event_slots WHERE season_id=$1 AND slot_type='main_final'",
        season_id,
    )
    if int(season_slots or 0) == 12 and int(registered_slots or 0) >= 12:
        await award_achievement(conn,user_id,"ALL_SEASON_EVENTS",f"all-season-events:{season_id}:{user_id}")
    if int(season_slots or 0) == 12 and int(grand_final_slots or 0) == 1 and int(registered_slots or 0) >= 13:
        await award_achievement(conn,user_id,"ALL_EVENTS_AND_GRAND_FINAL",f"all-events-grand-final:{season_id}:{user_id}")

    top_rank = await conn.fetchval(
        """
        SELECT MIN(rp.rank_position)
        FROM chronos.ranking_players rp
        JOIN chronos.ranking_snapshots rs ON rs.snapshot_id=rp.snapshot_id
        WHERE rs.season_id=$1 AND rp.user_id=$2
        """,
        season_id,user_id,
    )
    if top_rank is not None and int(top_rank) <= 3:
        await award_achievement(conn,user_id,"FIRST_TOP_THREE",f"first-top-three:{season_id}:{user_id}")
    if top_rank is not None and int(top_rank) == 1:
        await award_achievement(conn,user_id,"FIRST_TOP_ONE",f"first-top-one:{season_id}:{user_id}")

    # Tower completion uses the existing ten-floor progression gates:
    # participation, profile/collection, simulations, prediction access,
    # three intermediate finals and the season's full sync target.
    tower_state = await conn.fetchrow(
        """
        SELECT
          COALESCE((SELECT COUNT(*) FROM chronos.game_players gp
            JOIN chronos.games g ON g.game_id=gp.game_id
            WHERE gp.user_id=$2 AND g.season_id=$1 AND g.status='confirmed' AND g.counts_for_sync=TRUE),0) AS sync_units,
          COALESCE((SELECT COUNT(*) FROM chronos.prediction_bets b
            JOIN chronos.prediction_markets m ON m.market_id=b.market_id
            WHERE b.bettor_user_id=$2 AND m.season_id=$1 AND b.status<>'refunded'),0) AS bets,
          COALESCE((SELECT COUNT(DISTINCT s.slot_id) FROM chronos.event_slots s
            JOIN chronos.games g ON g.bot_event_id=s.bot_event_id AND g.status='confirmed'
            JOIN chronos.game_players gp ON gp.game_id=g.game_id AND gp.user_id=$2
            WHERE s.season_id=$1 AND s.slot_type='intermediate_final'),0) AS finals,
          (SELECT target_sync_units FROM chronos.seasons WHERE season_id=$1) AS target_sync_units
        """,
        season_id,user_id,
    )
    if (tower_state and int(tower_state["sync_units"] or 0) >= int(tower_state["target_sync_units"] or 0)
        and int(tower_state["bets"] or 0) >= 6
        and int(tower_state["finals"] or 0) >= 3):
        await award_achievement(conn,user_id,"TOWER_ALL_FLOORS",f"tower-all-floors:{season_id}:{user_id}")

