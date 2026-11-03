"""CHRONOS Prediction Exchange API."""

import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import asyncpg
from aiohttp import web

from modules.chronos_common import (
    active_season_id, audit, check_player_achievements, json_response, json_value, ledger_balance, notify_user, require_admin, award_ledger
)
from modules.chronos_economy import prediction_reward_ex
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
                SELECT c.user_id,u.display_name,c.probability,c.odds,c.reward_ex
                FROM chronos.prediction_candidates c
                JOIN public.users u ON u.user_id=c.user_id
                WHERE c.market_id=$1 AND c.user_id<>$2
                ORDER BY c.odds DESC,u.display_name
                """,
                market["market_id"],user_id,
            )
            mine=await conn.fetchrow(
                """
                SELECT bet_id,candidate_user_id,odds,potential_return AS reward_ex,status
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
            "currency_notice":"EX — лише косметична ігрова валюта. Прогноз безкоштовний: за помилку немає штрафу, за правильний прогноз нараховується 25–100 EX. Себе обирати не можна.",
            "rules_notice":"Очікувана винагорода за один прогноз близько 5 EX; фактична залежить від імовірності кандидата. Ліміт заробітку — 500 EX за сезон.",
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
            economy_settings=season_settings.get("economy",{})
            if settings.get("status")!="approved" or economy_settings.get("status")!="approved":
                return json_response({"error":"economy_rules_not_approved","message":"Економіка та правила прогнозів ще не затверджені."},409)
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
                house_margin=0.0,
            )
            existing_markets=await conn.fetchval(
                "SELECT COUNT(*) FROM chronos.prediction_markets WHERE bot_event_id=$1",
                event_id,
            )
            if int(existing_markets or 0)>0:
                return json_response({"error":"markets_already_created","existing_count":int(existing_markets or 0)},409)
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
                    reward_ex=prediction_reward_ex(
                        data["probability"],
                        expected_reward=int(settings.get("expected_reward_ex",5)),
                        minimum=int(settings.get("min_reward_ex",25)),
                        maximum=int(settings.get("max_reward_ex",100)),
                    )
                    await conn.execute(
                        """
                        INSERT INTO chronos.prediction_candidates
                          (market_id,user_id,probability,odds,reward_ex)
                        VALUES($1,$2,$3,$4,$5)
                        """,
                        market["market_id"],candidate_id,data["probability"],data["odds"],reward_ex,
                    )
                created.append({"market_id":market["market_id"],"market_type":market_type})
            await audit(conn,actor_id,"prediction_markets_opened","event",event_id,{"markets":created,"closes_at":closes_at.isoformat()})
        return json_response({"opened":created,"closes_at":closes_at.isoformat()},201)
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def _void_market_if_roster_changed(conn, market):
    current_rows=await conn.fetch(
        """
        SELECT user_id FROM public.registrations
        WHERE event_id=$1 AND status='active'
        """,
        market["bot_event_id"],
    )
    candidate_rows=await conn.fetch(
        "SELECT user_id FROM chronos.prediction_candidates WHERE market_id=$1",
        market["market_id"],
    )
    current={int(row["user_id"]) for row in current_rows}
    frozen={int(row["user_id"]) for row in candidate_rows}
    if current==frozen:
        return False
    await conn.execute(
        "UPDATE chronos.prediction_markets SET status='void',settled_at=NOW() WHERE market_id=$1",
        market["market_id"],
    )
    bets=await conn.fetch(
        "SELECT * FROM chronos.prediction_bets WHERE market_id=$1 AND status='pending' FOR UPDATE",
        market["market_id"],
    )
    for bet in bets:
        await conn.execute(
            "UPDATE chronos.prediction_bets SET status='refunded',settled_at=NOW() WHERE bet_id=$1",
            bet["bet_id"],
        )
        await notify_user(
            conn,bet["bettor_user_id"],"predictions","Прогноз анульовано",
            "Склад вечора змінився після відкриття ринку. EX не списувалися, штрафу немає.",
        )
    return True


async def place_bet(request):
    """Submit a free forecast. No EX is debited; only correct forecasts earn EX."""
    user_id=request["telegram_user"]["id"]
    market_id=int(request.match_info["market_id"])
    try:
        payload=await request.json()
        candidate_id=int(payload["candidate_user_id"])
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return json_response({"error":"candidate_user_id_required"},400)
    if candidate_id==user_id:
        return json_response({"error":"self_prediction_not_allowed"},403)

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
            if await _void_market_if_roster_changed(conn,market):
                return json_response({
                    "error":"roster_changed_market_voided",
                    "message":"Склад вечора змінився. Прогноз анульовано без втрати EX.",
                },409)

            season=await conn.fetchrow(
                "SELECT platform_settings FROM chronos.seasons WHERE season_id=$1",
                market["season_id"],
            )
            season_settings=json_value(season["platform_settings"],{}) if season else {}
            rules=(season_settings or {}).get("predictions",{})
            economy=(season_settings or {}).get("economy",{})
            if rules.get("status")!="approved" or economy.get("status")!="approved":
                return json_response({"error":"economy_rules_not_approved"},409)

            candidate=await conn.fetchrow(
                """
                SELECT probability,odds,reward_ex FROM chronos.prediction_candidates
                WHERE market_id=$1 AND user_id=$2
                """,
                market_id,candidate_id,
            )
            if not candidate:
                return json_response({"error":"candidate_not_available"},404)
            duplicate=await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM chronos.prediction_bets WHERE market_id=$1 AND bettor_user_id=$2)",
                market_id,user_id,
            )
            if duplicate:
                return json_response({"error":"already_predicted_on_this_market"},409)
            count=await conn.fetchval(
                """
                SELECT COUNT(*) FROM chronos.prediction_bets b
                JOIN chronos.prediction_markets m ON m.market_id=b.market_id
                WHERE m.bot_event_id=$1 AND b.bettor_user_id=$2 AND b.status<>'refunded'
                """,
                market["bot_event_id"],user_id,
            )
            max_per_event=int(rules.get("max_predictions_per_event",3))
            if int(count or 0)>=max_per_event:
                return json_response({"error":"event_forecast_limit","limit":max_per_event},409)

            bet=await conn.fetchrow(
                """
                INSERT INTO chronos.prediction_bets
                  (market_id,bettor_user_id,candidate_user_id,stake,odds,potential_return)
                VALUES($1,$2,$3,0,$4,$5)
                RETURNING bet_id
                """,
                market_id,user_id,candidate_id,candidate["odds"],candidate["reward_ex"],
            )
            await check_player_achievements(conn,market["season_id"],user_id)
            await conn.execute(
                """
                INSERT INTO chronos.activity_events
                  (season_id,user_id,action_code,score_value,source_key,verified,metadata)
                VALUES($1,$2,'prediction_placed',1,$3,$4,$5::jsonb)
                ON CONFLICT(source_key) DO NOTHING
                """,
                market["season_id"],user_id,f"prediction:{bet['bet_id']}",True,
                json.dumps({"market_id":market_id,"event_id":market["bot_event_id"]}),
            )
        return json_response({
            "accepted":True,
            "bet_id":bet["bet_id"],
            "probability":float(candidate["probability"]),
            "estimated_reward_ex":int(candidate["reward_ex"]),
            "stake_ex":0,
            "loss_on_wrong_prediction":0,
        },201)
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

            season=await conn.fetchrow(
                "SELECT platform_settings FROM chronos.seasons WHERE season_id=$1",
                market["season_id"],
            )
            settings=json_value(season["platform_settings"],{}) if season else {}
            prediction_rules=(settings or {}).get("predictions",{})
            ex_cap=int(prediction_rules.get("ex_season_cap",500))
            bets=await conn.fetch(
                "SELECT * FROM chronos.prediction_bets WHERE market_id=$1 AND status='pending' FOR UPDATE",
                market_id,
            )
            settlements=[]
            for bet in bets:
                if result=="void":
                    await conn.execute(
                        "UPDATE chronos.prediction_bets SET status='refunded',settled_at=NOW() WHERE bet_id=$1",
                        bet["bet_id"],
                    )
                    await notify_user(
                        conn,bet["bettor_user_id"],"predictions","Прогноз анульовано",
                        "Склад учасників змінився. Прогноз закрито без списання чи повернення EX.",
                    )
                    settlements.append({"bet_id":bet["bet_id"],"status":"refunded","reward_ex":0})
                elif bet["candidate_user_id"]==winner:
                    already_earned=await conn.fetchval(
                        """
                        SELECT COALESCE(SUM(amount),0) FROM chronos.ledger
                        WHERE user_id=$1 AND currency='EX' AND reason_code='prediction_win'
                          AND metadata->>'season_id'=$2
                        """,
                        bet["bettor_user_id"],str(market["season_id"]),
                    )
                    reward=min(
                        int(bet["potential_return"]),
                        max(0,ex_cap-int(already_earned or 0)),
                    )
                    await conn.execute(
                        "UPDATE chronos.prediction_bets SET status='won',settled_at=NOW() WHERE bet_id=$1",
                        bet["bet_id"],
                    )
                    if reward:
                        await award_ledger(
                            conn,bet["bettor_user_id"],"EX",reward,"prediction_win",
                            f"prediction:payout:{bet['bet_id']}",str(bet["bet_id"]),
                            metadata={"season_id":market["season_id"],"market_id":market_id,"bet_id":bet["bet_id"]},
                        )
                    await notify_user(
                        conn,bet["bettor_user_id"],"predictions","Прогноз влучив!",
                        f"Нараховано {reward} EX. Неправильний прогноз не списує валюту.",
                    )
                    settlements.append({"bet_id":bet["bet_id"],"status":"won","reward_ex":reward})
                else:
                    await conn.execute(
                        "UPDATE chronos.prediction_bets SET status='lost',settled_at=NOW() WHERE bet_id=$1",
                        bet["bet_id"],
                    )
                    await notify_user(
                        conn,bet["bettor_user_id"],"predictions","Прогноз не справдився",
                        "EX не списано. Наступний прогноз можна зробити на іншому ринку.",
                    )
                    settlements.append({"bet_id":bet["bet_id"],"status":"lost","reward_ex":0})

            await conn.execute(
                """
                UPDATE chronos.prediction_markets
                SET status=$2,winning_user_id=$3,settled_at=NOW()
                WHERE market_id=$1
                """,
                market_id,"void" if result=="void" else "settled",winner,
            )
            await audit(
                conn,actor_id,"prediction_market_settled","market",market_id,
                {"result":result,"winner":winner,"settlements":settlements},
            )
        return json_response({
            "settled":True,"result":result,"winning_user_id":winner,
            "settlements":settlements,
            "no_stakes":True,
        })
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
                   COUNT(b.bet_id) AS forecasts
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
