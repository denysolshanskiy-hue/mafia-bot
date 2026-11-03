"""CHRONOS Prediction Exchange API."""

import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import asyncpg
from aiohttp import web

from modules.chronos_common import (
    active_season_id, audit, check_player_achievements, json_response, json_value, ledger_balance, notify_user, require_admin, award_ledger
)
from modules.chronos_logic import plackett_luce_probabilities


def _iso_datetime(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("closes_at must include a timezone")
    return parsed.astimezone(timezone.utc)


async def list_predictions(request):
    user_id = request["telegram_user"]["id"]
    from database import get_connection
    conn = await get_connection()
    try:
        await conn.execute(
            """
            UPDATE chronos.prediction_markets SET status='locked'
            WHERE status='open' AND closes_at<=NOW()
            """
        )
        active_config = await conn.fetchrow(
            "SELECT platform_settings FROM chronos.seasons WHERE status IN ('draft','active','paused') ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,season_id DESC LIMIT 1"
        )
        active_settings = json_value(active_config["platform_settings"], {}) if active_config else {}
        rules_status = (active_settings or {}).get("predictions", {}).get("status", "draft")
        markets = await conn.fetch(
            """
            SELECT m.market_id,m.bot_event_id,m.market_type,m.status,m.opened_at,m.closes_at,
                   e.title AS event_title,e.event_date,e.event_time
            FROM chronos.prediction_markets m
            JOIN public.events e ON e.event_id=m.bot_event_id
            WHERE m.status IN ('open','locked') AND e.status='active'
            ORDER BY e.event_date,m.market_type
            """
        )
        out=[]
        for market in markets:
            candidates=await conn.fetch(
                """
                SELECT c.user_id,u.display_name,c.probability,c.odds
                FROM chronos.prediction_candidates c
                JOIN public.users u ON u.user_id=c.user_id
                WHERE c.market_id=$1 ORDER BY c.odds DESC,u.display_name
                """,
                market["market_id"],
            )
            mine=await conn.fetchrow(
                """
                SELECT bet_id,candidate_user_id,stake,odds,potential_return,status
                FROM chronos.prediction_bets
                WHERE market_id=$1 AND bettor_user_id=$2
                """,
                market["market_id"],user_id,
            )
            out.append({
                "market_id":market["market_id"],
                "event_id":market["bot_event_id"],
                "event_title":market["event_title"],
                "event_date":market["event_date"],
                "event_time":market["event_time"],
                "market_type":market["market_type"],
                "status":market["status"],
                "closes_at":market["closes_at"],
                "candidates":[dict(row) for row in candidates],
                "my_bet":dict(mine) if mine else None,
            })
        return json_response({
            "balance_ex":await ledger_balance(conn,user_id,"EX"),
            "markets":out,
            "rules_status":rules_status,
            "currency_notice":"EX — ігрова валюта без грошової вартості. Її не можна купити, передати або вивести.",
        })
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def open_prediction_markets(request):
    actor_id=request["telegram_user"]["id"]
    try:
        payload=await request.json()
        event_id=int(payload["event_id"])
        closes_at=_iso_datetime(payload["closes_at"])
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return json_response({"error":"event_id_and_timezone_aware_closes_at_required"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        admin_error=await require_admin(request,conn)
        if admin_error:
            return admin_error
        async with conn.transaction():
            season=await conn.fetchrow(
                "SELECT season_id,platform_settings FROM chronos.seasons WHERE status='active' ORDER BY season_id DESC LIMIT 1"
            )
            if not season:
                return json_response({"error":"season_not_active"},409)
            season_settings=json_value(season["platform_settings"], {}) or {}
            settings=season_settings.get("predictions",{})
            if settings.get("status")!="approved":
                return json_response({"error":"prediction_rules_not_approved","message":"Правила прогнозів ще не затверджені."},409)
            event=await conn.fetchrow(
                """
                SELECT event_id,title,event_date,event_time FROM public.events
                WHERE event_id=$1 AND event_type='chronos' AND status='active'
                """,
                event_id,
            )
            if not event:
                return json_response({"error":"chronos_event_not_active"},404)
            if closes_at<=datetime.now(timezone.utc):
                return json_response({"error":"market_close_must_be_future"},400)
            roster=await conn.fetch(
                """
                SELECT u.user_id,u.display_name
                FROM public.registrations r JOIN public.users u ON u.user_id=r.user_id
                WHERE r.event_id=$1 AND r.status='active' AND u.is_active=1
                ORDER BY u.display_name
                """,
                event_id,
            )
            if len(roster)<2:
                return json_response({"error":"need_at_least_two_registered_players"},409)
            snapshot=await conn.fetchrow(
                """
                SELECT snapshot_id FROM chronos.ranking_snapshots
                WHERE season_id=$1 ORDER BY captured_at DESC,snapshot_id DESC LIMIT 1
                """,
                season["season_id"],
            )
            if not snapshot:
                return json_response({"error":"no_confirmed_ranking_snapshot"},409)
            player_ids=[row["user_id"] for row in roster]
            stats=await conn.fetch(
                """
                SELECT rp.user_id,rp.rank_position,rp.points,rp.games_played,rp.wins,rp.bonus_points
                FROM chronos.ranking_players rp
                WHERE rp.snapshot_id=$1 AND rp.user_id=ANY($2::bigint[])
                """,
                snapshot["snapshot_id"],player_ids,
            )
            stats_by_id={row["user_id"]:dict(row) for row in stats}
            missing=[row["display_name"] for row in roster if row["user_id"] not in stats_by_id]
            if missing:
                return json_response({"error":"incomplete_player_statistics","missing_players":missing},409)
            odds_data=plackett_luce_probabilities(
                [stats_by_id[user_id] for user_id in player_ids],
                simulations=12000,
                seed=int(event_id),
                house_margin=float(settings.get("house_margin",0.05)),
            )
            created=[]
            for place,market_type in ((1,"TOP1"),(2,"TOP2"),(3,"TOP3")):
                market=await conn.fetchrow(
                    """
                    INSERT INTO chronos.prediction_markets
                      (season_id,bot_event_id,market_type,status,opened_at,closes_at,created_by)
                    VALUES($1,$2,$3,'open',NOW(),$4,$5)
                    ON CONFLICT(bot_event_id,market_type) DO NOTHING
                    RETURNING market_id
                    """,
                    season["season_id"],event_id,market_type,closes_at,actor_id,
                )
                if not market:
                    return json_response({"error":"markets_already_created","market_type":market_type},409)
                for candidate_id in player_ids:
                    data=odds_data.get(place,{}).get(str(candidate_id))
                    if not data:
                        continue
                    await conn.execute(
                        """
                        INSERT INTO chronos.prediction_candidates(market_id,user_id,probability,odds)
                        VALUES($1,$2,$3,$4)
                        """,
                        market["market_id"],candidate_id,data["probability"],data["odds"],
                    )
                created.append({"market_id":market["market_id"],"market_type":market_type})
            await audit(conn,actor_id,"prediction_markets_opened","event",event_id,{"markets":created,"closes_at":closes_at.isoformat()})
        return json_response({"opened":created,"closes_at":closes_at.isoformat()},201)
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def place_bet(request):
    user_id=request["telegram_user"]["id"]
    market_id=int(request.match_info["market_id"])
    try:
        payload=await request.json()
        candidate_id=int(payload["candidate_user_id"])
        stake=int(payload["stake"])
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return json_response({"error":"invalid_bet_payload"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        async with conn.transaction():
            market=await conn.fetchrow(
                """
                SELECT m.*,e.status AS event_status
                FROM chronos.prediction_markets m
                JOIN public.events e ON e.event_id=m.bot_event_id
                WHERE m.market_id=$1 FOR UPDATE
                """,
                market_id,
            )
            if not market or market["event_status"]!="active":
                return json_response({"error":"market_not_found"},404)
            if market["status"]!="open" or market["closes_at"]<=datetime.now(timezone.utc):
                if market["status"]=="open":
                    await conn.execute("UPDATE chronos.prediction_markets SET status='locked' WHERE market_id=$1",market_id)
                return json_response({"error":"market_closed"},409)
            season=await conn.fetchrow(
                "SELECT platform_settings FROM chronos.seasons WHERE season_id=$1",
                market["season_id"],
            )
            season_settings=json_value(season["platform_settings"], {}) if season else {}
            rules=season_settings.get("predictions",{}) if season_settings else {}
            if rules.get("status")!="approved":
                return json_response({"error":"prediction_rules_not_approved"},409)
            min_stake=int(rules.get("min_stake",10))
            max_stake=int(rules.get("max_stake",200))
            max_evening=int(rules.get("max_per_evening",500))
            max_bets=int(rules.get("max_bets_per_evening",3))
            if stake<min_stake or stake>max_stake:
                return json_response({"error":"stake_out_of_range","min":min_stake,"max":max_stake},400)
            if not await conn.fetchval(
                """
                SELECT EXISTS(SELECT 1 FROM chronos.prediction_candidates WHERE market_id=$1 AND user_id=$2)
                """,
                market_id,candidate_id,
            ):
                return json_response({"error":"candidate_not_available"},404)
            playing=await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM public.registrations WHERE event_id=$1 AND user_id=$2 AND status='active')",
                market["bot_event_id"],user_id,
            )
            if playing:
                return json_response({"error":"registered_players_cannot_bet"},403)
            existing_bets=await conn.fetchrow(
                """
                SELECT COUNT(*) AS count,COALESCE(SUM(b.stake),0) AS total
                FROM chronos.prediction_bets b
                JOIN chronos.prediction_markets m ON m.market_id=b.market_id
                WHERE m.bot_event_id=$1 AND b.bettor_user_id=$2
                """,
                market["bot_event_id"],user_id,
            )
            if int(existing_bets["count"])>=max_bets:
                return json_response({"error":"evening_bet_count_limit","limit":max_bets},409)
            if int(existing_bets["total"])+stake>max_evening:
                return json_response({"error":"evening_stake_limit","limit":max_evening},409)
            balance=await ledger_balance(conn,user_id,"EX")
            if balance<stake:
                return json_response({"error":"insufficient_ex","balance":balance},409)
            odds=await conn.fetchval(
                "SELECT odds FROM chronos.prediction_candidates WHERE market_id=$1 AND user_id=$2",
                market_id,candidate_id,
            )
            potential_return=int((Decimal(stake)*Decimal(odds)).quantize(Decimal("1"),rounding=ROUND_HALF_UP))
            bet=await conn.fetchrow(
                """
                INSERT INTO chronos.prediction_bets
                  (market_id,bettor_user_id,candidate_user_id,stake,odds,potential_return)
                VALUES($1,$2,$3,$4,$5,$6)
                RETURNING bet_id
                """,
                market_id,user_id,candidate_id,stake,odds,potential_return,
            )
            await award_ledger(
                conn,user_id,"EX",-stake,"prediction_stake",
                f"prediction:stake:{bet['bet_id']}",str(bet["bet_id"]),
            )
            await check_player_achievements(conn,market["season_id"],user_id)
            await conn.execute(
                """
                INSERT INTO chronos.activity_events(season_id,user_id,action_code,score_value,source_key,verified,metadata)
                VALUES($1,$2,'prediction_placed',1,$3,TRUE,$4::jsonb)
                ON CONFLICT(source_key) DO NOTHING
                """,
                market["season_id"],user_id,f"prediction:{bet['bet_id']}",json.dumps({"market_id":market_id}),
            )
        return json_response({"accepted":True,"bet_id":bet["bet_id"],"odds":float(odds),"potential_return":potential_return},201)
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def settle_market(request):
    actor_id=request["telegram_user"]["id"]
    market_id=int(request.match_info["market_id"])
    try:
        payload=await request.json()
        result=payload.get("result","settled")
        winner=int(payload["winning_user_id"]) if result=="settled" else None
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return json_response({"error":"invalid_settlement_payload"},400)
    if result not in ("settled","void"):
        return json_response({"error":"invalid_result"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        admin_error=await require_admin(request,conn)
        if admin_error:
            return admin_error
        async with conn.transaction():
            market=await conn.fetchrow(
                "SELECT * FROM chronos.prediction_markets WHERE market_id=$1 FOR UPDATE",
                market_id,
            )
            if not market or market["status"] not in ("open","locked"):
                return json_response({"error":"market_not_settleable"},409)
            if market["status"]=="open" and market["closes_at"]>datetime.now(timezone.utc):
                return json_response({"error":"market_still_open"},409)
            if result=="settled":
                candidate=await conn.fetchval(
                    "SELECT 1 FROM chronos.prediction_candidates WHERE market_id=$1 AND user_id=$2",
                    market_id,winner,
                )
                if not candidate:
                    return json_response({"error":"winner_not_a_candidate"},400)
            bets=await conn.fetch(
                "SELECT * FROM chronos.prediction_bets WHERE market_id=$1 AND status='pending' FOR UPDATE",
                market_id,
            )
            for bet in bets:
                if result=="void":
                    await conn.execute(
                        "UPDATE chronos.prediction_bets SET status='refunded',settled_at=NOW() WHERE bet_id=$1",
                        bet["bet_id"],
                    )
                    await award_ledger(conn,bet["bettor_user_id"],"EX",bet["stake"],"prediction_refund",f"prediction:refund:{bet['bet_id']}",str(bet["bet_id"]))
                    await notify_user(conn,bet["bettor_user_id"],"predictions","Ринок скасовано","Ставку повернено на баланс EX.")
                elif bet["candidate_user_id"]==winner:
                    await conn.execute("UPDATE chronos.prediction_bets SET status='won',settled_at=NOW() WHERE bet_id=$1",bet["bet_id"])
                    await award_ledger(conn,bet["bettor_user_id"],"EX",bet["potential_return"],"prediction_win",f"prediction:payout:{bet['bet_id']}",str(bet["bet_id"]))
                    await notify_user(conn,bet["bettor_user_id"],"predictions","Прогноз влучив!",f"На баланс зараховано {bet['potential_return']} EX.")
                else:
                    await conn.execute("UPDATE chronos.prediction_bets SET status='lost',settled_at=NOW() WHERE bet_id=$1",bet["bet_id"])
            await conn.execute(
                """
                UPDATE chronos.prediction_markets
                SET status=$2,winning_user_id=$3,settled_at=NOW()
                WHERE market_id=$1
                """,
                market_id,"void" if result=="void" else "settled",winner,
            )
            await audit(conn,actor_id,"prediction_market_settled","market",market_id,{"result":result,"winner":winner})
        return json_response({"settled":True,"result":result,"winning_user_id":winner})
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def admin_markets(request):
    from database import get_connection
    conn=await get_connection()
    try:
        admin_error=await require_admin(request,conn)
        if admin_error:
            return admin_error
        rows=await conn.fetch(
            """
            SELECT m.market_id,m.bot_event_id,m.market_type,m.status,m.closes_at,e.title,
                   COUNT(b.bet_id) AS bets,COALESCE(SUM(b.stake),0) AS total_stake
            FROM chronos.prediction_markets m
            JOIN public.events e ON e.event_id=m.bot_event_id
            LEFT JOIN chronos.prediction_bets b ON b.market_id=m.market_id
            GROUP BY m.market_id,e.title ORDER BY m.market_id DESC LIMIT 100
            """
        )
        return json_response({"markets":[dict(row) for row in rows]})
    finally:
        await conn.close()


def register_prediction_routes(app):
    app.router.add_get("/api/chronos/predictions", list_predictions)
    app.router.add_post("/api/chronos/predictions/markets/open", open_prediction_markets)
    app.router.add_post("/api/chronos/predictions/markets/{market_id:\\d+}/bet", place_bet)
    app.router.add_post("/api/chronos/predictions/markets/{market_id:\\d+}/settle", settle_market)
    app.router.add_get("/api/chronos/admin/markets", admin_markets)
