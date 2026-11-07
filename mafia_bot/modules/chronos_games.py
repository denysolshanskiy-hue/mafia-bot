"""Server-authoritative CHRONOS mini-games."""

import json
import random
import uuid
from datetime import timedelta

import asyncpg
from aiohttp import web

from modules.chronos_common import active_season_id, award_ledger, check_player_achievements, json_response, json_value, notify_user, require_admin


def _public_state(game_code, state, session):
    remaining = max(0, int((session["expires_at"] - session["now"]).total_seconds()))
    if game_code == "CODE_BREAKER":
        return {
            "attempts_used": len(state["guesses"]),
            "attempts_left": max(0, 6 - len(state["guesses"])),
            "guesses": state["guesses"],
            "seconds_left": remaining,
            "status": session["status"],
        }
    revealed = set(state["matched"]) | set(state["flipped"])
    return {
        "cells": [
            {"index": index, "value": card if index in revealed else None,
             "matched": index in state["matched"], "flipped": index in state["flipped"]}
            for index, card in enumerate(state["cards"])
        ],
        "pairs_found": len(state["matched"]) // 2,
        "moves": state["moves"],
        "seconds_left": remaining,
        "status": session["status"],
        "pending_hide": bool(state.get("pending_hide")),
    }


async def _award_minigame_xp(conn, season_id, user_id, game_code, session_id):
    # Serialize first-clear and repeat-cap checks across concurrent sessions.
    await conn.fetchval(
        "SELECT user_id FROM public.users WHERE user_id=$1 FOR UPDATE",
        user_id,
    )
    row=await conn.fetchrow(
        "SELECT platform_settings FROM chronos.seasons WHERE season_id=$1",
        season_id,
    )
    platform=json_value(row["platform_settings"],{}) if row else {}
    economy=(platform or {}).get("economy",{})
    if economy.get("status")!="approved":
        return 0
    first_xp=max(0,int(economy.get("minigame_first_clear_xp",20)))
    repeat_xp=max(0,int(economy.get("minigame_repeat_xp",5)))
    repeat_cap=max(0,int(economy.get("minigame_repeat_cap",10)))
    first_key = f"minigame:first:{season_id}:{user_id}:{game_code}"
    first_awarded = await award_ledger(
        conn,user_id,"XP",first_xp,"minigame_first",first_key,
        reference_key=str(session_id),metadata={"game_code":game_code,"season_id":season_id},
    )
    if first_awarded:
        return first_xp
    repeat_count = await conn.fetchval(
        """
        SELECT COUNT(*) FROM chronos.ledger
        WHERE user_id=$1 AND currency='XP' AND reason_code='minigame_repeat'
          AND metadata->>'season_id'=$2
        """,
        user_id,str(season_id),
    )
    if int(repeat_count or 0) >= repeat_cap:
        return 0
    repeat_key = f"minigame:repeat:{season_id}:{user_id}:{session_id}"
    created = await award_ledger(
        conn,user_id,"XP",repeat_xp,"minigame_repeat",repeat_key,
        reference_key=f"{season_id}:{session_id}",
        metadata={"game_code":game_code,"season_id":season_id},
    )
    return repeat_xp if created else 0


async def start_game(request):
    user_id = request["telegram_user"]["id"]
    game_code = request.match_info["game_code"].upper()
    if game_code not in ("CODE_BREAKER","MEMORY"):
        return json_response({"error":"unknown_game"},404)
    from database import get_chronos_connection as get_connection
    conn = await get_connection()
    try:
        async with conn.transaction():
            admin_access = await require_admin(request, conn)
            is_admin_test = admin_access is None
            season_id = await active_season_id(conn)
            if not season_id and is_admin_test:
                # Admin preview uses the latest configured season record without activating it.
                season_id = await conn.fetchval(
                    "SELECT season_id FROM chronos.seasons ORDER BY season_id DESC LIMIT 1"
                )
            if not season_id:
                return json_response({"error":"season_not_configured"},409)
            season_row=await conn.fetchrow(
                "SELECT platform_settings FROM chronos.seasons WHERE season_id=$1",
                season_id,
            )
            platform=json_value(season_row["platform_settings"],{}) if season_row else {}
            economy=(platform or {}).get("economy",{})
            if not is_admin_test and economy.get("status")!="approved":
                return json_response({"error":"economy_not_approved"},409)
            # Lock the player row so parallel starts cannot exceed the daily cap.
            user = await conn.fetchrow(
                "SELECT display_name,is_active FROM public.users WHERE user_id=$1 FOR UPDATE",
                user_id,
            )
            if not user or not user["display_name"]:
                return json_response({"error":"profile_incomplete"},409)
            if user["is_active"] != 1:
                return json_response({"error":"account_disabled"},403)

            daily_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM chronos.minigame_sessions
                WHERE user_id=$1 AND game_code=$2
                  AND started_at >= ((NOW() AT TIME ZONE 'Europe/Kyiv')::date::timestamp AT TIME ZONE 'Europe/Kyiv')
                  AND started_at < ((((NOW() AT TIME ZONE 'Europe/Kyiv')::date + 1)::timestamp) AT TIME ZONE 'Europe/Kyiv')
                """,
                user_id,game_code,
            )
            if int(daily_count or 0) >= 3:
                return json_response({"error":"daily_limit","limit":3},429)

            session_id = uuid.uuid4()
            rng = random.SystemRandom()
            if game_code == "CODE_BREAKER":
                state = {"secret":"".join(rng.sample("0123456789",4)),"guesses":[],"admin_test":is_admin_test}
            else:
                symbols = ["ATOM","NOVA","PULSE","FLUX","ECHO","CORE"]
                cards = symbols * 2
                rng.shuffle(cards)
                state = {"cards":cards,"matched":[],"flipped":[],"moves":0,"pending_hide":False,"admin_test":is_admin_test}

            row = await conn.fetchrow(
                """
                INSERT INTO chronos.minigame_sessions
                  (session_id,season_id,user_id,game_code,state,expires_at)
                VALUES($1,$2,$3,$4,$5::jsonb,NOW()+($6 * INTERVAL '1 second'))
                RETURNING session_id,expires_at,status
                """,
                session_id,season_id,user_id,game_code,json.dumps(state),
                180 if game_code == "CODE_BREAKER" else 150,
            )
        return json_response({
            "session_id":str(session_id),
            "game_code":game_code,
            "instructions":(
                {"attempts":10,"digits":4,"unique_digits":True,"seconds":180}
                if game_code=="CODE_BREAKER"
                else {"cards":12,"pairs":6,"symbols":["ATOM","NOVA","PULSE","FLUX","ECHO","CORE"],"seconds":150}
            ),
            "state":_public_state(game_code,state,{"expires_at":row["expires_at"],"now":row["expires_at"]-timedelta(seconds=(180 if game_code=="CODE_BREAKER" else 150)),"status":"running"}),
        },201)
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def game_action(request):
    user_id = request["telegram_user"]["id"]
    try:
        session_id = uuid.UUID(request.match_info["session_id"])
        payload = await request.json()
    except (ValueError,json.JSONDecodeError):
        return json_response({"error":"invalid_request"},400)
    if not isinstance(payload,dict):
        return json_response({"error":"invalid_request"},400)
    action = payload.get("action")
    value = payload.get("value")
    from database import get_chronos_connection as get_connection
    conn = await get_connection()
    try:
        async with conn.transaction():
            session = await conn.fetchrow(
                """
                SELECT session_id,season_id,user_id,game_code,status,state,expires_at
                FROM chronos.minigame_sessions
                WHERE session_id=$1 AND user_id=$2 FOR UPDATE
                """,
                session_id,user_id,
            )
            if not session:
                return json_response({"error":"session_not_found"},404)
            if session["status"] != "running":
                return json_response({"error":"session_finished","status":session["status"]},409)

            state = session["state"]
            if not isinstance(state,dict):
                state = json.loads(state)
            game_code = session["game_code"]
            if session["expires_at"].timestamp() <= __import__("time").time():
                await conn.execute(
                    "UPDATE chronos.minigame_sessions SET status='expired',completed_at=NOW() WHERE session_id=$1",
                    session_id,
                )
                return json_response({"error":"time_expired","status":"expired"},409)

            if game_code == "CODE_BREAKER":
                if action != "guess" or not isinstance(value,str) or len(value)!=4 or not value.isdigit() or len(set(value))!=4:
                    return json_response({"error":"guess_must_be_four_unique_digits"},400)
                exact=sum(a==b for a,b in zip(value,state["secret"]))
                common=sum(min(value.count(d),state["secret"].count(d)) for d in set(value))
                misplaced=common-exact
                state["guesses"].append({"guess":value,"exact":exact,"misplaced":misplaced})
                status = "running"
                if exact==4:
                    status="completed"
                elif len(state["guesses"])>=10:
                    status="failed"
                await conn.execute(
                    """
                    UPDATE chronos.minigame_sessions
                    SET state=$2::jsonb,actions_count=actions_count+1,status=$3,
                        score=$4,completed_at=CASE WHEN $3='running' THEN NULL ELSE NOW() END
                    WHERE session_id=$1
                    """,
                    session_id,json.dumps(state),status,exact*100+max(0,10-len(state["guesses"]))*10 if status=="completed" else 0,
                )
                xp=0
                if status=="completed" and not state.get("admin_test"):
                    xp=await _award_minigame_xp(conn,session["season_id"],user_id,game_code,session_id)
                    await conn.execute("UPDATE chronos.minigame_sessions SET xp_awarded=$2 WHERE session_id=$1",session_id,xp)
                    await check_player_achievements(conn,session["season_id"],user_id)
                    await notify_user(conn,user_id,"rewards","Симуляцію завершено",f"CODE BREAKER: +{xp} XP.")
                return json_response({
                    "status":status,"feedback":state["guesses"][-1],
                    "attempts_left":10-len(state["guesses"]),"xp_awarded":xp,
                })

            if action == "hide":
                if not state.get("pending_hide"):
                    return json_response({"error":"nothing_to_hide"},409)
                state["flipped"]=[]
                state["pending_hide"]=False
            elif action == "flip":
                try:
                    index=int(value)
                except (TypeError,ValueError):
                    return json_response({"error":"invalid_card_index"},400)
                if index<0 or index>=12:
                    return json_response({"error":"invalid_card_index"},400)
                if state.get("pending_hide"):
                    return json_response({"error":"hide_mismatched_cards_first"},409)
                if index in state["matched"] or index in state["flipped"]:
                    return json_response({"error":"card_already_open"},409)
                state["flipped"].append(index)
                state["moves"]+=1
                if len(state["flipped"])==2:
                    a,b=state["flipped"]
                    if state["cards"][a]==state["cards"][b]:
                        state["matched"].extend([a,b])
                        state["flipped"]=[]
                    else:
                        state["pending_hide"]=True
            else:
                return json_response({"error":"unknown_action"},400)

            status="completed" if len(state["matched"])==12 else "running"
            await conn.execute(
                """
                UPDATE chronos.minigame_sessions
                SET state=$2::jsonb,actions_count=actions_count+1,status=$3,
                    score=$4,completed_at=CASE WHEN $3='running' THEN NULL ELSE NOW() END
                WHERE session_id=$1
                """,
                session_id,json.dumps(state),status,max(0,1000-state["moves"]*10) if status=="completed" else 0,
            )
            xp=0
            if status=="completed" and not state.get("admin_test"):
                xp=await _award_minigame_xp(conn,session["season_id"],user_id,game_code,session_id)
                await conn.execute("UPDATE chronos.minigame_sessions SET xp_awarded=$2 WHERE session_id=$1",session_id,xp)
                await check_player_achievements(conn,session["season_id"],user_id)
                await notify_user(conn,user_id,"rewards","Симуляцію завершено",f"MEMORY: +{xp} XP.")
            return json_response({
                "status":status,
                "state":_public_state(game_code,state,{"expires_at":session["expires_at"],"now":__import__("datetime").datetime.now(__import__("datetime").timezone.utc),"status":status}),
                "xp_awarded":xp,
            })
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def games_status(request):
    user_id = request["telegram_user"]["id"]
    from database import get_chronos_connection as get_connection
    conn = await get_connection()
    try:
        admin_access = await require_admin(request, conn)
        is_admin = admin_access is None
        season_id = await active_season_id(conn)
        if not season_id and is_admin:
            season_id = await conn.fetchval(
                "SELECT season_id FROM chronos.seasons ORDER BY season_id DESC LIMIT 1"
            )
        if not season_id:
            return json_response({"season_active":False,"admin_preview":False,"games":[]})
        rows = await conn.fetch(
            """
            SELECT game_code,COUNT(*) FILTER (
                       WHERE started_at >= ((NOW() AT TIME ZONE 'Europe/Kyiv')::date::timestamp AT TIME ZONE 'Europe/Kyiv')
                         AND started_at < ((((NOW() AT TIME ZONE 'Europe/Kyiv')::date + 1)::timestamp) AT TIME ZONE 'Europe/Kyiv')
                   ) AS attempts_today,
                   COUNT(*) FILTER (WHERE status='completed') AS completed,
                   COALESCE(SUM(xp_awarded),0) AS xp_total
            FROM chronos.minigame_sessions
            WHERE user_id=$1 AND season_id=$2
            GROUP BY game_code
            """,
            user_id,season_id,
        )
        stats={r["game_code"]:dict(r) for r in rows}
        active = await active_season_id(conn)
        return json_response({
            "season_active":bool(active) or is_admin,
            "admin_preview":bool(is_admin and not active),
            "daily_limit":3,
            "games":[
                {"game_code":code,"title":title,"description":desc,"attempts_today":int(stats.get(code,{}).get("attempts_today",0)),
                 "completed":int(stats.get(code,{}).get("completed",0)),"xp_total":int(stats.get(code,{}).get("xp_total",0))}
                for code,title,desc in (
                    ("CODE_BREAKER","CODE BREAKER","Знайди 4 унікальні цифри за 6 спроб. 90 секунд."),
                    ("MEMORY","MEMORY","Знайди 6 пар серед 12 карток. 90 секунд.")
                )
            ],
        })
    finally:
        await conn.close()


def register_game_routes(app):
    app.router.add_get("/api/chronos/games", games_status)
    app.router.add_post("/api/chronos/games/{game_code}", start_game)
    app.router.add_post("/api/chronos/games/sessions/{session_id}/action", game_action)
