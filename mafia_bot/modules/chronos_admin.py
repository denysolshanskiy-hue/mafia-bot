"""CHRONOS administration: event mapping, iMafia imports, invitations, prizes and audit."""

import asyncio
import json
import shutil
from datetime import datetime, date, timedelta, time, timezone

import asyncpg
from aiohttp import web

from modules.chronos_common import (
    audit, award_game_and_evening_rewards, check_player_achievements, json_response, json_value, ledger_balance, notify_user, require_admin, award_ledger
)
from modules.chronos_economy import allocate_activity_bonus, calculate_activity_score, qualification_games_required
)


def _user_id_from_row(row):
    value=row.get("user_id") if isinstance(row,dict) else None
    return int(value) if value is not None else None


async def admin_overview(request):
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        season=await conn.fetchrow(
            """
            SELECT season_id,season_code,title,status,target_sync_units,platform_settings
            FROM chronos.seasons ORDER BY season_id DESC LIMIT 1
            """
        )
        if not season:
            return json_response({"season":None})
        season_id=season["season_id"]
        stats=await conn.fetchrow(
            """
            SELECT
              COUNT(DISTINCT g.game_id) FILTER(WHERE g.status='confirmed') AS confirmed_games,
              COUNT(gp.user_id) FILTER(WHERE g.status='confirmed' AND g.counts_for_sync=TRUE) AS sync_units,
              COUNT(DISTINCT gp.user_id) FILTER(WHERE g.status='confirmed') AS active_players
            FROM chronos.games g LEFT JOIN chronos.game_players gp ON gp.game_id=g.game_id
            WHERE g.season_id=$1
            """,
            season_id,
        )
        pending_imports=await conn.fetchval("SELECT COUNT(*) FROM chronos.import_batches WHERE status='needs_review'")
        open_markets=await conn.fetchval("SELECT COUNT(*) FROM chronos.prediction_markets WHERE status='open'")
        pending_invitations=await conn.fetchval("SELECT COUNT(*) FROM chronos.final_invitations WHERE status='pending'")
        return json_response({
            "season":{"season_code":season["season_code"],"title":season["title"],"status":season["status"],
                      "target_sync_units":season["target_sync_units"],
                      "platform_settings":json_value(season["platform_settings"], {})},
            "progress":{"games":int(stats["confirmed_games"] or 0),"sync_units":int(stats["sync_units"] or 0),
                        "percent":round(100*int(stats["sync_units"] or 0)/max(1,season["target_sync_units"]),1),
                        "players":int(stats["active_players"] or 0)},
            "pending_imports":int(pending_imports or 0),
            "open_markets":int(open_markets or 0),
            "pending_invitations":int(pending_invitations or 0),
        })
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def admin_slots(request):
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        season_id=await conn.fetchval("SELECT season_id FROM chronos.seasons ORDER BY season_id DESC LIMIT 1")
        rows=await conn.fetch(
            """
            SELECT s.slot_id,s.slot_code,s.sequence_no,s.slot_type,s.title,s.planned_date,s.status,
                   s.bot_event_id,e.title AS bot_event_title,e.event_date,e.event_time,e.status AS bot_status
            FROM chronos.event_slots s
            LEFT JOIN public.events e ON e.event_id=s.bot_event_id
            WHERE s.season_id=$1 ORDER BY s.sequence_no
            """,
            season_id,
        )
        available=await conn.fetch(
            """
            SELECT event_id,title,event_date,event_time
            FROM public.events
            WHERE status='active' AND event_type='chronos'
              AND event_id NOT IN (SELECT bot_event_id FROM chronos.event_slots WHERE bot_event_id IS NOT NULL)
            ORDER BY event_date
            """
        )
        return json_response({"slots":[dict(r) for r in rows],"available_bot_events":[dict(r) for r in available]})
    finally:
        await conn.close()


async def link_slot_to_bot_event(request):
    actor_id=request["telegram_user"]["id"]
    slot_id=int(request.match_info["slot_id"])
    try:
        payload=await request.json()
        event_id=int(payload["event_id"])
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return json_response({"error":"event_id_required"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        async with conn.transaction():
            slot=await conn.fetchrow("SELECT * FROM chronos.event_slots WHERE slot_id=$1 FOR UPDATE",slot_id)
            event=await conn.fetchrow(
                "SELECT event_id,title,event_type,status FROM public.events WHERE event_id=$1",
                event_id,
            )
            if not slot:
                return json_response({"error":"slot_not_found"},404)
            if not event or event["event_type"]!="chronos":
                return json_response({"error":"event_must_be_chronos"},400)
            if event["status"]!="active":
                return json_response({"error":"event_must_be_active"},409)
            await conn.execute(
                "UPDATE chronos.event_slots SET bot_event_id=$2,updated_at=NOW() WHERE slot_id=$1",
                slot_id,event_id,
            )
            await audit(conn,actor_id,"event_slot_linked","event_slot",slot_id,{"bot_event_id":event_id})
        return json_response({"linked":True,"slot_id":slot_id,"event_id":event_id})
    finally:
        await conn.close()


async def _run_tesseract(image_data: bytes):
    if not shutil.which("tesseract"):
        return "", "tesseract_not_installed"
    try:
        proc=await asyncio.create_subprocess_exec(
            "tesseract","stdin","stdout","-l","ukr+eng",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout,stderr=await asyncio.wait_for(proc.communicate(image_data),timeout=30)
        if proc.returncode!=0:
            return "",stderr.decode("utf-8","replace")[:500]
        return stdout.decode("utf-8","replace"),None
    except asyncio.TimeoutError:
        return "","ocr_timeout"
    except Exception as exc:
        return "",f"ocr_error:{type(exc).__name__}"


async def upload_import(request):
    actor_id=request["telegram_user"]["id"]
    reader=await request.multipart()
    import_type=None
    event_id=None
    file_name=None
    content_type=None
    image_data=None
    async for field in reader:
        if field.name=="import_type":
            import_type=(await field.text()).strip()
        elif field.name=="event_id":
            raw=(await field.text()).strip()
            event_id=int(raw) if raw else None
        elif field.name=="image":
            file_name=field.filename or "imafia.png"
            content_type=field.headers.get("Content-Type","application/octet-stream")
            image_data=await field.read(decode=False)
            if len(image_data)>8*1024*1024:
                return json_response({"error":"image_too_large","max_bytes":8388608},413)
    if import_type not in ("ranking","game_results") or not image_data or content_type not in ("image/png","image/jpeg","image/webp"):
        return json_response({"error":"ranking_or_game_results_image_required"},400)
    if import_type=="game_results" and not event_id:
        return json_response({"error":"event_id_required_for_game_results"},400)

    ocr_text,ocr_error=await _run_tesseract(image_data)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        season_id=await conn.fetchval("SELECT season_id FROM chronos.seasons ORDER BY season_id DESC LIMIT 1")
        if import_type=="game_results":
            event=await conn.fetchrow(
                "SELECT event_id,event_type FROM public.events WHERE event_id=$1",
                event_id,
            )
            if not event or event["event_type"]!="chronos":
                return json_response({"error":"event_must_be_chronos"},400)
        import_id=await conn.fetchval(
            """
            INSERT INTO chronos.import_batches
              (season_id,import_type,bot_event_id,file_name,content_type,source_image,ocr_text,uploaded_by)
            VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING import_id
            """,
            season_id,import_type,event_id,file_name,content_type,image_data,ocr_text,actor_id,
        )
        await audit(conn,actor_id,"import_uploaded","import",import_id,{"import_type":import_type,"file_name":file_name,"ocr_error":ocr_error})
        return json_response({
            "import_id":import_id,"status":"needs_review","import_type":import_type,
            "file_name":file_name,"ocr_text":ocr_text,"ocr_error":ocr_error,
            "message":"OCR — лише чернетка. Перевірте та вручну виправте кожен нік і показник перед підтвердженням.",
        },201)
    finally:
        await conn.close()


async def list_imports(request):
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        rows=await conn.fetch(
            """
            SELECT i.import_id,i.import_type,i.file_name,i.content_type,i.status,
                   i.uploaded_at,i.confirmed_at,e.title AS event_title,u.display_name AS uploaded_by_name
            FROM chronos.import_batches i
            LEFT JOIN public.events e ON e.event_id=i.bot_event_id
            LEFT JOIN public.users u ON u.user_id=i.uploaded_by
            ORDER BY i.uploaded_at DESC LIMIT 100
            """
        )
        return json_response({"imports":[dict(r) for r in rows]})
    finally:
        await conn.close()


async def import_detail(request):
    import_id=int(request.match_info["import_id"])
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        row=await conn.fetchrow(
            """
            SELECT import_id,import_type,bot_event_id,file_name,content_type,ocr_text,status,
                   review_payload,uploaded_at,confirmed_at
            FROM chronos.import_batches WHERE import_id=$1
            """,
            import_id,
        )
        if not row:
            return json_response({"error":"import_not_found"},404)
        return json_response(dict(row))
    finally:
        await conn.close()


async def import_image(request):
    import_id=int(request.match_info["import_id"])
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        row=await conn.fetchrow(
            "SELECT source_image,content_type,file_name FROM chronos.import_batches WHERE import_id=$1",
            import_id,
        )
        if not row:
            raise web.HTTPNotFound()
        return web.Response(
            body=bytes(row["source_image"]),
            content_type=row["content_type"],
            headers={"Content-Disposition":f'inline; filename="{row["file_name"].replace(chr(34),"")}"',"Cache-Control":"no-store"},
        )
    finally:
        await conn.close()


async def save_import_review(request):
    actor_id=request["telegram_user"]["id"]
    import_id=int(request.match_info["import_id"])
    try:
        payload=await request.json()
    except (ValueError,json.JSONDecodeError):
        return json_response({"error":"invalid_json"},400)
    if not isinstance(payload,dict):
        return json_response({"error":"invalid_review_payload"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        row=await conn.fetchrow("SELECT status,import_type FROM chronos.import_batches WHERE import_id=$1",import_id)
        if not row:
            return json_response({"error":"import_not_found"},404)
        if row["status"]!="needs_review":
            return json_response({"error":"import_not_editable"},409)
        expected="players" if row["import_type"]=="ranking" else "games"
        if not isinstance(payload.get(expected),list) or not payload[expected]:
            return json_response({"error":f"{expected}_array_required"},400)
        await conn.execute(
            "UPDATE chronos.import_batches SET review_payload=$2::jsonb WHERE import_id=$1",
            import_id,json.dumps(payload),
        )
        await audit(conn,actor_id,"import_review_saved","import",import_id,{"rows":len(payload[expected])})
        return json_response({"saved":True,"rows":len(payload[expected])})
    finally:
        await conn.close()


async def _resolve_import_user(conn, row):
    user_id=row.get("user_id")
    if user_id is not None:
        found=await conn.fetchrow(
            "SELECT user_id,display_name FROM public.users WHERE user_id=$1 AND is_active=1",
            int(user_id),
        )
    else:
        name=str(row.get("display_name","")).strip()
        if not name:
            return None
        found=await conn.fetchrow(
            """
            SELECT user_id,display_name FROM public.users
            WHERE is_active=1 AND LOWER(BTRIM(display_name))=LOWER(BTRIM($1))
            """,
            name,
        )
    return found


async def confirm_import(request):
    actor_id=request["telegram_user"]["id"]
    import_id=int(request.match_info["import_id"])
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        async with conn.transaction():
            batch=await conn.fetchrow(
                "SELECT * FROM chronos.import_batches WHERE import_id=$1 FOR UPDATE",
                import_id,
            )
            if not batch:
                return json_response({"error":"import_not_found"},404)
            if batch["status"]!="needs_review" or not batch["review_payload"]:
                return json_response({"error":"review_required_before_confirmation"},409)
            payload=batch["review_payload"]
            if isinstance(payload,str):
                payload=json.loads(payload)

            if batch["import_type"]=="ranking":
                players=payload.get("players",[])
                seen_users=set()
                seen_ranks=set()
                mapped=[]
                for player in players:
                    user=await _resolve_import_user(conn,player)
                    if not user:
                        return json_response({"error":"unmapped_player","display_name":player.get("display_name")},400)
                    uid=user["user_id"]
                    rank=int(player.get("rank_position",0))
                    games=int(player.get("games_played",0))
                    wins=int(player.get("wins",0))
                    points=float(player.get("points",0))
                    bonus=float(player.get("bonus_points",0))
                    if rank<=0 or games<0 or wins<0 or wins>games or uid in seen_users or rank in seen_ranks:
                        return json_response({"error":"invalid_or_duplicate_ranking_row","display_name":user["display_name"]},400)
                    seen_users.add(uid);seen_ranks.add(rank)
                    mapped.append((uid,rank,points,games,wins,bonus,player.get("extra_stats") or {}))
                snapshot_id=await conn.fetchval(
                    """
                    INSERT INTO chronos.ranking_snapshots(season_id,import_id,confirmed_by)
                    VALUES($1,$2,$3) RETURNING snapshot_id
                    """,
                    batch["season_id"],import_id,actor_id,
                )
                for uid,rank,points,games,wins,bonus,extra in mapped:
                    await conn.execute(
                        """
                        INSERT INTO chronos.ranking_players
                          (snapshot_id,user_id,rank_position,points,games_played,wins,bonus_points,extra_stats)
                        VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
                        """,
                        snapshot_id,uid,rank,points,games,wins,bonus,json.dumps(extra),
                    )
                summary={"snapshot_id":snapshot_id,"players":len(mapped)}
            else:
                event=await conn.fetchrow(
                    """
                    SELECT e.event_id,e.event_type,s.slot_type,s.slot_id
                    FROM public.events e
                    LEFT JOIN chronos.event_slots s ON s.bot_event_id=e.event_id
                    WHERE e.event_id=$1
                    """,
                    batch["bot_event_id"],
                )
                if not event or event["event_type"]!="chronos" or not event["slot_id"]:
                    return json_response({"error":"event_slot_must_be_linked_before_result_import"},409)
                counts_for_sync=event["slot_type"]!="main_final"
                game_rows=payload.get("games",[])
                if not game_rows:
                    return json_response({"error":"at_least_one_game_required"},400)
                inserted_games=0
                for game in game_rows:
                    external_id=str(game.get("external_game_id","")).strip()
                    players=game.get("players",[])
                    if not external_id or len(players)!=10:
                        return json_response({"error":"each_game_requires_external_id_and_exactly_10_players"},400)
                    mapped=[]
                    seen=set()
                    placements=set()
                    for player in players:
                        user=await _resolve_import_user(conn,player)
                        if not user:
                            return json_response({"error":"unmapped_player","display_name":player.get("display_name")},400)
                        uid=user["user_id"]
                        placement=int(player.get("placement",0))
                        if uid in seen or placement<1 or placement>10 or placement in placements:
                            return json_response({"error":"invalid_game_player_or_placement"},400)
                        seen.add(uid);placements.add(placement)
                        mapped.append((uid,placement,str(player.get("role_name") or ""),float(player.get("points",0)),float(player.get("bonus_points",0)),bool(player.get("is_winner",False)),player.get("stats") or {}))
                    played_at=game.get("played_at")
                    if played_at:
                        parsed=datetime.fromisoformat(str(played_at).replace("Z","+00:00"))
                    else:
                        parsed=None
                    game_id=await conn.fetchval(
                        """
                        INSERT INTO chronos.games
                          (season_id,bot_event_id,external_game_id,game_number,played_at,status,counts_for_sync,source_import_id)
                        VALUES($1,$2,$3,$4,$5,'confirmed',$6,$7)
                        RETURNING game_id
                        """,
                        batch["season_id"],batch["bot_event_id"],external_id,
                        int(game.get("game_number",inserted_games+1)),parsed,counts_for_sync,import_id,
                    )
                    for uid,placement,role,points,bonus,winner,stats in mapped:
                        await conn.execute(
                            """
                            INSERT INTO chronos.game_players
                              (game_id,user_id,placement,role_name,points,bonus_points,is_winner,stats)
                            VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
                            """,
                            game_id,uid,placement,role,points,bonus,winner,json.dumps(stats),
                        )
                    inserted_games+=1
                # Mark attendance automatically only for players who appeared in at least one imported game.
                await conn.execute(
                    """
                    INSERT INTO chronos.attendance(season_id,slot_id,user_id,invited,status,marked_by,marked_at)
                    SELECT DISTINCT $1,$2,gp.user_id,TRUE,'attended',$3,NOW()
                    FROM chronos.games g JOIN chronos.game_players gp ON gp.game_id=g.game_id
                    WHERE g.source_import_id=$4
                    ON CONFLICT(slot_id,user_id) DO UPDATE SET status='attended',marked_by=EXCLUDED.marked_by,marked_at=NOW()
                    """,
                    batch["season_id"],event["slot_id"],actor_id,import_id,
                )
                await conn.execute(
                    """
                    UPDATE chronos.final_invitations fi
                    SET status='accepted',responded_at=COALESCE(responded_at,NOW())
                    FROM chronos.game_players gp
                    JOIN chronos.games g ON g.game_id=gp.game_id
                    WHERE g.source_import_id=$1 AND fi.slot_id=$2 AND fi.user_id=gp.user_id
                    """,
                    import_id,event["slot_id"],
                )
                reward_rows=await conn.fetch(
                    """
                    SELECT g.game_id,g.bot_event_id,g.counts_for_sync,gp.user_id
                    FROM chronos.games g
                    JOIN chronos.game_players gp ON gp.game_id=g.game_id
                    WHERE g.source_import_id=$1 AND g.status='confirmed'
                    ORDER BY g.game_id,gp.user_id
                    """,
                    import_id,
                )
                season_settings=json_value(
                    await conn.fetchval(
                        "SELECT platform_settings FROM chronos.seasons WHERE season_id=$1",
                        batch["season_id"],
                    ),
                    {},
                ) or {}
                economy_settings=season_settings.get("economy",{})
                issued={"CR":0,"XP":0}
                for reward_row in reward_rows:
                    amounts=await award_game_and_evening_rewards(
                        conn,batch["season_id"],reward_row["bot_event_id"],
                        reward_row["game_id"],reward_row["user_id"],economy_settings,
                    )
                    issued["CR"]+=amounts["CR"]
                    issued["XP"]+=amounts["XP"]
                participants=sorted({row["user_id"] for row in reward_rows})
                for participant_id in participants:
                    await check_player_achievements(conn,batch["season_id"],participant_id)
                summary={
                    "games":inserted_games,
                    "counts_for_sync":counts_for_sync,
                    "currency_issued":issued,
                    "economy_rewards_pending":economy_settings.get("status")!="approved",
                }
            await conn.execute(
                """
                UPDATE chronos.import_batches
                SET status='confirmed',confirmed_by=$2,confirmed_at=NOW()
                WHERE import_id=$1
                """,
                import_id,actor_id,
            )
            await audit(conn,actor_id,"import_confirmed","import",import_id,summary)
        return json_response({"confirmed":True,**summary})
    except asyncpg.UniqueViolationError:
        return json_response({"error":"duplicate_game_or_snapshot","message":"Дубль external_game_id або вже підтверджений імпорт."},409)
    except (ValueError,TypeError) as exc:
        return json_response({"error":"invalid_review_data","details":str(exc)},400)
    finally:
        await conn.close()


async def admin_players(request):
    query=request.query.get("q","").strip()
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        rows=await conn.fetch(
            """
            SELECT u.user_id,u.username,u.display_name,u.role,u.is_active,
                   COALESCE(SUM(l.amount) FILTER(WHERE l.currency='CR'),0) AS cr,
                   COALESCE(SUM(l.amount) FILTER(WHERE l.currency='EX'),0) AS ex,
                   COALESCE(SUM(l.amount) FILTER(WHERE l.currency='XP'),0) AS xp
            FROM public.users u
            LEFT JOIN chronos.ledger l ON l.user_id=u.user_id
            WHERE ($1='' OR u.display_name ILIKE '%'||$1||'%' OR u.username ILIKE '%'||$1||'%')
            GROUP BY u.user_id ORDER BY u.display_name LIMIT 100
            """,
            query,
        )
        return json_response({"players":[dict(row) for row in rows]})
    finally:
        await conn.close()


async def admin_audit(request):
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        rows=await conn.fetch(
            """
            SELECT a.audit_id,a.action_code,a.target_type,a.target_id,a.details,a.created_at,
                   u.display_name AS actor_name
            FROM chronos.audit_log a
            LEFT JOIN public.users u ON u.user_id=a.actor_user_id
            ORDER BY a.created_at DESC LIMIT 200
            """
        )
        return json_response({"entries":[dict(row) for row in rows]})
    finally:
        await conn.close()


async def generate_invitations(request):
    actor_id=request["telegram_user"]["id"]
    slot_id=int(request.match_info["slot_id"])
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        async with conn.transaction():
            slot=await conn.fetchrow(
                "SELECT * FROM chronos.event_slots WHERE slot_id=$1 FOR UPDATE",
                slot_id,
            )
            if not slot or slot["slot_type"] not in ("intermediate_final","main_final"):
                return json_response({"error":"final_slot_required"},400)
            if not slot["planned_date"]:
                return json_response({"error":"set_planned_date_first"},409)
            existing=await conn.fetchval("SELECT COUNT(*) FROM chronos.final_invitations WHERE slot_id=$1",slot_id)
            if existing:
                return json_response({"error":"invitations_already_generated"},409)
            snapshot=await conn.fetchrow(
                """
                SELECT snapshot_id FROM chronos.ranking_snapshots
                WHERE season_id=$1 ORDER BY captured_at DESC,snapshot_id DESC LIMIT 1
                """,
                slot["season_id"],
            )
            if not snapshot:
                return json_response({"error":"confirmed_ranking_snapshot_required"},409)
            top=await conn.fetch(
                """
                SELECT rp.user_id,rp.rank_position
                FROM chronos.ranking_players rp
                WHERE rp.snapshot_id=$1
                  AND (SELECT COUNT(*)
                       FROM chronos.game_players gp
                       JOIN chronos.games g ON g.game_id=gp.game_id
                       WHERE gp.user_id=rp.user_id AND g.season_id=$2
                         AND g.status='confirmed' AND g.counts_for_sync=TRUE)
                      >= GREATEST(1,CEIL((SELECT COUNT(*) FROM chronos.games
                         WHERE season_id=$2 AND status='confirmed' AND counts_for_sync=TRUE)*0.30))
                ORDER BY rp.rank_position LIMIT 10
                """,
                snapshot["snapshot_id"],slot["season_id"],
            )
            if len(top)<10:
                return json_response({"error":"top10_not_complete"},409)
            now=datetime.now(timezone.utc)
            days=(slot["planned_date"]-date.today()).days
            deadline=(datetime.combine(slot["planned_date"],time.min,tzinfo=timezone.utc)-timedelta(days=7)) if days>=7 else now+timedelta(hours=48)
            for row in top:
                await conn.execute(
                    """
                    INSERT INTO chronos.final_invitations(slot_id,user_id,rank_at_invite,deadline_at)
                    VALUES($1,$2,$3,$4)
                    """,
                    slot_id,row["user_id"],row["rank_position"],deadline,
                )
                await conn.execute(
                    """
                    INSERT INTO chronos.attendance(season_id,slot_id,user_id,invited,status)
                    VALUES($1,$2,$3,TRUE,'pending')
                    ON CONFLICT(slot_id,user_id) DO NOTHING
                    """,
                    slot["season_id"],slot_id,row["user_id"],
                )
                await notify_user(conn,row["user_id"],"finals","Запрошення на фінал",f"Тебе запрошено: {slot['title']}. Підтверди участь до {deadline.isoformat()}.","invitation",{"slot_id":slot_id})
            await audit(conn,actor_id,"final_invitations_generated","event_slot",slot_id,{"count":len(top),"deadline":deadline.isoformat()})
        return json_response({"generated":len(top),"deadline_at":deadline.isoformat()},201)
    finally:
        await conn.close()


async def respond_invitation(request):
    user_id=request["telegram_user"]["id"]
    invitation_id=int(request.match_info["invitation_id"])
    try:
        payload=await request.json()
        response=payload.get("response")
    except (ValueError,json.JSONDecodeError):
        return json_response({"error":"invalid_json"},400)
    if response not in ("accepted","declined"):
        return json_response({"error":"response_must_be_accepted_or_declined"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        async with conn.transaction():
            invitation=await conn.fetchrow(
                """
                SELECT fi.*,s.season_id,s.title,s.slot_type,s.slot_id
                FROM chronos.final_invitations fi
                JOIN chronos.event_slots s ON s.slot_id=fi.slot_id
                WHERE fi.invitation_id=$1 AND fi.user_id=$2 FOR UPDATE
                """,
                invitation_id,user_id,
            )
            if not invitation:
                return json_response({"error":"invitation_not_found"},404)
            if invitation["status"]!="pending":
                return json_response({"error":"invitation_already_processed"},409)
            if invitation["deadline_at"]<=datetime.now(timezone.utc):
                await conn.execute(
                    "UPDATE chronos.final_invitations SET status='no_response' WHERE invitation_id=$1",
                    invitation_id,
                )
                await conn.execute(
                    "UPDATE chronos.attendance SET status='no_response' WHERE slot_id=$1 AND user_id=$2",
                    invitation["slot_id"],user_id,
                )
                await _invite_next_rank(conn,invitation["slot_id"],invitation["season_id"])
                return json_response({"error":"invitation_expired"},409)
            await conn.execute(
                "UPDATE chronos.final_invitations SET status=$2,responded_at=NOW() WHERE invitation_id=$1",
                invitation_id,response,
            )
            await conn.execute(
                "UPDATE chronos.attendance SET status=$3 WHERE slot_id=$1 AND user_id=$2",
                invitation["slot_id"],user_id,"pending" if response=="accepted" else "declined",
            )
            await notify_user(conn,user_id,"finals","Відповідь збережено",("Участь підтверджено." if response=="accepted" else "Ти відмовився від запрошення."))
            if response=="declined":
                await _invite_next_rank(conn,invitation["slot_id"],invitation["season_id"])
        return json_response({"saved":True,"status":response})
    finally:
        await conn.close()


async def _invite_next_rank(conn,slot_id,season_id):
    active_count=await conn.fetchval(
        "SELECT COUNT(*) FROM chronos.final_invitations WHERE slot_id=$1 AND status IN ('pending','accepted')",
        slot_id,
    )
    if int(active_count or 0)>=10:
        return
    snapshot=await conn.fetchrow(
        "SELECT snapshot_id FROM chronos.ranking_snapshots WHERE season_id=$1 ORDER BY captured_at DESC,snapshot_id DESC LIMIT 1",
        season_id,
    )
    if not snapshot:
        return
    next_player=await conn.fetchrow(
        """
        SELECT rp.user_id,rp.rank_position
        FROM chronos.ranking_players rp
        WHERE rp.snapshot_id=$1
          AND (SELECT COUNT(*)
               FROM chronos.game_players gp
               JOIN chronos.games g ON g.game_id=gp.game_id
               WHERE gp.user_id=rp.user_id AND g.season_id=$3
                 AND g.status='confirmed' AND g.counts_for_sync=TRUE)
              >= GREATEST(1,CEIL((SELECT COUNT(*) FROM chronos.games
                 WHERE season_id=$3 AND status='confirmed' AND counts_for_sync=TRUE)*0.30))
          AND NOT EXISTS(SELECT 1 FROM chronos.final_invitations fi WHERE fi.slot_id=$2 AND fi.user_id=rp.user_id)
        ORDER BY rp.rank_position LIMIT 1
        """,
        snapshot["snapshot_id"],slot_id,season_id,
    )
    if not next_player:
        return
    slot=await conn.fetchrow("SELECT title,planned_date FROM chronos.event_slots WHERE slot_id=$1",slot_id)
    days=(slot["planned_date"]-date.today()).days if slot["planned_date"] else 0
    now=datetime.now(timezone.utc)
    deadline=(datetime.combine(slot["planned_date"],time.min,tzinfo=timezone.utc)-timedelta(days=7)) if days>=7 else now+timedelta(hours=48)
    await conn.execute(
        "INSERT INTO chronos.final_invitations(slot_id,user_id,rank_at_invite,deadline_at) VALUES($1,$2,$3,$4)",
        slot_id,next_player["user_id"],next_player["rank_position"],deadline,
    )
    await conn.execute(
        """
        INSERT INTO chronos.attendance(season_id,slot_id,user_id,invited,status)
        VALUES($1,$2,$3,TRUE,'pending') ON CONFLICT(slot_id,user_id) DO NOTHING
        """,
        season_id,slot_id,next_player["user_id"],
    )
    await notify_user(conn,next_player["user_id"],"finals","Запрошення на фінал",f"Звільнилося місце. Тебе запрошено на {slot['title']}. Дедлайн: {deadline.isoformat()}.","invitation",{"slot_id":slot_id})


async def process_expired_invitations(request):
    actor_id=request["telegram_user"]["id"]
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        changed=0
        async with conn.transaction():
            expired=await conn.fetch(
                """
                SELECT fi.invitation_id,fi.slot_id,s.season_id,fi.user_id
                FROM chronos.final_invitations fi JOIN chronos.event_slots s ON s.slot_id=fi.slot_id
                WHERE fi.status='pending' AND fi.deadline_at<=NOW()
                FOR UPDATE
                """
            )
            affected=set()
            for row in expired:
                await conn.execute("UPDATE chronos.final_invitations SET status='no_response' WHERE invitation_id=$1",row["invitation_id"])
                await conn.execute("UPDATE chronos.attendance SET status='no_response' WHERE slot_id=$1 AND user_id=$2",row["slot_id"],row["user_id"])
                affected.add((row["slot_id"],row["season_id"]))
                changed+=1
            for slot_id,season_id in affected:
                # Refill all expired places in rank order; stop when the top-10 is full or no candidates remain.
                for _ in range(10):
                    active_count=await conn.fetchval(
                        "SELECT COUNT(*) FROM chronos.final_invitations WHERE slot_id=$1 AND status IN ('pending','accepted')",
                        slot_id,
                    )
                    if int(active_count or 0)>=10:
                        break
                    before=await conn.fetchval("SELECT COUNT(*) FROM chronos.final_invitations WHERE slot_id=$1",slot_id)
                    await _invite_next_rank(conn,slot_id,season_id)
                    after=await conn.fetchval("SELECT COUNT(*) FROM chronos.final_invitations WHERE slot_id=$1",slot_id)
                    if int(after or 0)==int(before or 0):
                        break
            if changed:
                await audit(conn,actor_id,"expired_invitations_processed","season",None,{"count":changed})
        return json_response({"processed":changed})
    finally:
        await conn.close()


async def calculate_season_activity_bonus(request):
    """Create a draft allocation of the fixed UAH 500 activity bonus pool."""
    actor_id=request["telegram_user"]["id"]
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        async with conn.transaction():
            season=await conn.fetchrow(
                """
                SELECT season_id,status,platform_settings
                FROM chronos.seasons ORDER BY season_id DESC LIMIT 1 FOR UPDATE
                """
            )
            if not season:
                return json_response({"error":"season_not_found"},404)
            if season["status"]!="completed":
                return json_response({"error":"season_must_be_completed"},409)
            platform=json_value(season["platform_settings"],{}) or {}
            activity_rules=platform.get("activity_score",{})
            economy=platform.get("economy",{})
            if activity_rules.get("status")!="approved" or economy.get("status")!="approved":
                return json_response({"error":"activity_economy_rules_not_approved"},409)

            main_slot=await conn.fetchrow(
                """
                SELECT slot_id,bot_event_id,title FROM chronos.event_slots
                WHERE season_id=$1 AND slot_type='main_final'
                """,
                season["season_id"],
            )
            if not main_slot or not main_slot["bot_event_id"]:
                return json_response({"error":"main_final_must_be_linked"},409)
            event_status=await conn.fetchval(
                "SELECT status FROM public.events WHERE event_id=$1",
                main_slot["bot_event_id"],
            )
            if event_status!="closed":
                return json_response({"error":"main_final_must_be_closed"},409)

            rule=await conn.fetchrow(
                """
                SELECT amount_uah,is_enabled FROM chronos.prize_rules
                WHERE season_id=$1 AND event_kind='legacy' AND place=1
                """,
                season["season_id"],
            )
            pool=int((economy or {}).get("season_activity_bonus_uah",500))
            if not rule or not rule["is_enabled"] or int(rule["amount_uah"])!=pool:
                return json_response({
                    "error":"activity_bonus_rule_not_enabled",
                    "configured_pool_uah":pool,
                },409)

            initial_top=await conn.fetch(
                """
                SELECT invitation_id,user_id,rank_at_invite
                FROM (
                  SELECT fi.invitation_id,fi.user_id,fi.rank_at_invite,
                         ROW_NUMBER() OVER(ORDER BY fi.invitation_id) AS invite_order
                  FROM chronos.final_invitations fi
                  WHERE fi.slot_id=$1
                ) ranked
                WHERE invite_order<=10
                ORDER BY invite_order
                """,
                main_slot["slot_id"],
            )
            if len(initial_top)!=10:
                return json_response({"error":"main_final_initial_top10_required","found":len(initial_top)},409)

            existing=await conn.fetchval(
                """
                SELECT COUNT(*) FROM chronos.season_bonus_allocations
                WHERE season_id=$1 AND status IN ('approved','paid')
                """,
                season["season_id"],
            )
            if int(existing or 0):
                return json_response({"error":"bonus_already_approved_or_paid"},409)

            conducted_games=int(await conn.fetchval(
                """
                SELECT COUNT(*) FROM chronos.games
                WHERE season_id=$1 AND status='confirmed' AND counts_for_sync=TRUE
                """,
                season["season_id"],
            ) or 0)
            required_games=qualification_games_required(conducted_games)
            eligible_regular=int(await conn.fetchval(
                """
                SELECT COUNT(*) FROM chronos.event_slots s
                JOIN public.events e ON e.event_id=s.bot_event_id
                WHERE s.season_id=$1 AND s.slot_type='regular' AND e.status='closed'
                """,
                season["season_id"],
            ) or 0)
            participants=[]
            snapshots=[]

            for invitee in initial_top:
                user_id=invitee["user_id"]
                games_played=int(await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM chronos.game_players gp
                    JOIN chronos.games g ON g.game_id=gp.game_id
                    WHERE g.season_id=$1 AND g.status='confirmed'
                      AND g.counts_for_sync=TRUE AND gp.user_id=$2
                    """,
                    season["season_id"],user_id,
                ) or 0)
                if games_played<required_games:
                    continue

                attended_regular=int(await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT s.slot_id)
                    FROM chronos.event_slots s
                    JOIN chronos.games g ON g.bot_event_id=s.bot_event_id AND g.status='confirmed'
                    JOIN chronos.game_players gp ON gp.game_id=g.game_id AND gp.user_id=$2
                    JOIN public.events e ON e.event_id=s.bot_event_id AND e.status='closed'
                    WHERE s.season_id=$1 AND s.slot_type='regular'
                    """,
                    season["season_id"],user_id,
                ) or 0)
                invited_finals=int(await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM chronos.final_invitations fi
                    JOIN chronos.event_slots s ON s.slot_id=fi.slot_id
                    WHERE s.season_id=$1 AND fi.user_id=$2
                      AND s.slot_type IN ('intermediate_final','main_final')
                    """,
                    season["season_id"],user_id,
                ) or 0)
                attended_finals=int(await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT s.slot_id)
                    FROM chronos.final_invitations fi
                    JOIN chronos.event_slots s ON s.slot_id=fi.slot_id
                    JOIN chronos.games g ON g.bot_event_id=s.bot_event_id AND g.status='confirmed'
                    JOIN chronos.game_players gp ON gp.game_id=g.game_id AND gp.user_id=$2
                    WHERE s.season_id=$1 AND fi.user_id=$2
                      AND s.slot_type IN ('intermediate_final','main_final')
                    """,
                    season["season_id"],user_id,
                ) or 0)
                eligible_slots=eligible_regular+invited_finals
                attended_slots=attended_regular+attended_finals
                app_actions=int(await conn.fetchval(
                    """
                    SELECT COUNT(DISTINCT metadata->>'event_id')
                    FROM chronos.activity_events
                    WHERE season_id=$1 AND user_id=$2 AND verified=TRUE
                      AND score_value>0 AND metadata ? 'event_id'
                    """,
                    season["season_id"],user_id,
                ) or 0)
                minigames=int(await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM chronos.minigame_sessions
                    WHERE season_id=$1 AND user_id=$2 AND status='completed'
                    """,
                    season["season_id"],user_id,
                ) or 0)
                score=calculate_activity_score(
                    attended_slots=attended_slots,
                    eligible_slots=eligible_slots,
                    verified_app_actions=app_actions,
                    completed_minigames=minigames,
                    weights=activity_rules.get("weights",{"attendance":80,"app":15,"minigame":5}),
                    app_actions_cap=int(activity_rules.get("app_actions_cap",13)),
                    minigame_completions_cap=int(activity_rules.get("minigame_completions_cap",5)),
                )
                participants.append({
                    "user_id":user_id,
                    "rank_position":int(invitee["rank_at_invite"]),
                    "activity_score":score["activity_score"],
                })
                snapshots.append({
                    "user_id":user_id,
                    "rank_position":int(invitee["rank_at_invite"]),
                    "games_played":games_played,
                    "attended_slots":attended_slots,
                    "eligible_slots":eligible_slots,
                    "verified_app_actions":app_actions,
                    "completed_minigames":minigames,
                    **score,
                })

            if not participants:
                return json_response({"error":"no_qualified_top10_players"},409)
            try:
                allocations=allocate_activity_bonus(participants,pool)
            except (ValueError,ArithmeticError) as exc:
                return json_response({"error":"activity_bonus_allocation_failed","details":str(exc)},409)

            await conn.execute(
                """
                DELETE FROM chronos.season_bonus_allocations
                WHERE season_id=$1 AND status IN ('draft','void')
                """,
                season["season_id"],
            )
            for snapshot in snapshots:
                await conn.execute(
                    """
                    INSERT INTO chronos.season_bonus_allocations
                      (season_id,slot_id,user_id,rank_at_lock,games_played,games_conducted,
                       attended_slots,eligible_slots,verified_app_actions,completed_minigames,
                       attendance_points,app_points,minigame_points,activity_score,activity_coefficient,
                       pool_amount_uah,allocation_amount_uah,status)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,'draft')
                    """,
                    season["season_id"],main_slot["slot_id"],snapshot["user_id"],
                    snapshot["rank_position"],snapshot["games_played"],conducted_games,
                    snapshot["attended_slots"],snapshot["eligible_slots"],
                    snapshot["verified_app_actions"],snapshot["completed_minigames"],
                    snapshot["attendance_points"],snapshot["app_points"],snapshot["minigame_points"],
                    snapshot["activity_score"],snapshot["activity_coefficient"],pool,
                    allocations[snapshot["user_id"]],
                )
            await audit(
                conn,actor_id,"season_activity_bonus_calculated","season",season["season_id"],
                {"pool_uah":pool,"eligible_players":len(snapshots),"distributed_uah":sum(allocations.values()),
                 "required_games":required_games},
            )
        return json_response({
            "calculated":True,
            "pool_uah":pool,
            "eligible_players":len(snapshots),
            "distributed_uah":sum(allocations.values()),
            "required_games":required_games,
            "allocations":sorted(
                [{**row,"allocation_amount_uah":allocations[row["user_id"]]} for row in snapshots],
                key=lambda row:row["rank_position"],
            ),
            "status":"draft",
        },201)
    except asyncpg.UndefinedTableError:
        return json_response({"error":"database_not_ready"},503)
    finally:
        await conn.close()


async def update_activity_bonus_status(request):
    actor_id=request["telegram_user"]["id"]
    allocation_id=int(request.match_info["allocation_id"])
    try:
        payload=await request.json()
        status=payload.get("status")
    except (ValueError,json.JSONDecodeError):
        return json_response({"error":"invalid_json"},400)
    if status not in ("approved","paid","void"):
        return json_response({"error":"invalid_bonus_status"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        row=await conn.fetchrow(
            "SELECT status FROM chronos.season_bonus_allocations WHERE allocation_id=$1 FOR UPDATE",
            allocation_id,
        )
        if not row:
            return json_response({"error":"bonus_allocation_not_found"},404)
        if status=="paid" and row["status"]!="approved":
            return json_response({"error":"approve_bonus_before_marking_paid"},409)
        await conn.execute(
            """
            UPDATE chronos.season_bonus_allocations
            SET status=$2,
                approved_by=CASE WHEN $2='approved' THEN $3 ELSE approved_by END,
                approved_at=CASE WHEN $2='approved' THEN NOW() ELSE approved_at END,
                paid_at=CASE WHEN $2='paid' THEN NOW() ELSE paid_at END,
                updated_at=NOW()
            WHERE allocation_id=$1
            """,
            allocation_id,status,actor_id,
        )
        await audit(conn,actor_id,"activity_bonus_status_changed","season_bonus",allocation_id,{"status":status})
        return json_response({"updated":True,"status":status})
    finally:
        await conn.close()


async def reconcile_economy_ledger(request):
    """Backfill missed CR/XP grants safely after the economy rules are approved."""
    from modules.chronos_games import _award_minigame_xp
    actor_id=request["telegram_user"]["id"]
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        async with conn.transaction():
            season=await conn.fetchrow(
                """
                SELECT season_id,platform_settings FROM chronos.seasons
                ORDER BY season_id DESC LIMIT 1 FOR UPDATE
                """
            )
            if not season:
                return json_response({"error":"season_not_found"},404)
            platform=json_value(season["platform_settings"],{}) or {}
            economy=platform.get("economy",{})
            if economy.get("status")!="approved":
                return json_response({"error":"economy_not_approved"},409)
            rows=await conn.fetch(
                """
                SELECT g.game_id,g.bot_event_id,gp.user_id
                FROM chronos.games g
                JOIN chronos.game_players gp ON gp.game_id=g.game_id
                WHERE g.season_id=$1 AND g.status='confirmed'
                ORDER BY g.game_id,gp.user_id
                """,
                season["season_id"],
            )
            minted={"CR":0,"XP":0}
            participants=set()
            for row in rows:
                amounts=await award_game_and_evening_rewards(
                    conn,season["season_id"],row["bot_event_id"],row["game_id"],row["user_id"],economy
                )
                minted["CR"]+=amounts["CR"]
                minted["XP"]+=amounts["XP"]
                participants.add(row["user_id"])
            # Reconcile completed minigame sessions in chronological order; ledger
            # idempotency keys and the season cap prevent duplicate XP.
            sessions=await conn.fetch(
                """
                SELECT session_id,user_id,game_code FROM chronos.minigame_sessions
                WHERE season_id=$1 AND status='completed' AND xp_awarded=0
                ORDER BY started_at,session_id
                FOR UPDATE
                """,
                season["season_id"],
            )
            minigame_xp=0
            for session in sessions:
                amount=await _award_minigame_xp(
                    conn,season["season_id"],session["user_id"],session["game_code"],session["session_id"]
                )
                await conn.execute(
                    "UPDATE chronos.minigame_sessions SET xp_awarded=$2 WHERE session_id=$1",
                    session["session_id"],amount,
                )
                minigame_xp+=amount
                participants.add(session["user_id"])
            await audit(
                conn,actor_id,"economy_ledger_reconciled","season",season["season_id"],
                {"games":len(rows),"participants":len(participants),"currency_minted":minted,"minigame_xp":minigame_xp},
            )
        return json_response({
            "reconciled":True,"games":len(rows),"participants":len(participants),
            "currency_minted":minted,"minigame_xp":minigame_xp,
        })
    finally:
        await conn.close()



async def create_prize_awards(request):
    actor_id=request["telegram_user"]["id"]
    try:
        payload=await request.json()
        slot_id=int(payload["slot_id"])
        event_kind=payload["event_kind"]
        awards=payload["awards"]
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return json_response({"error":"invalid_awards_payload"},400)
    if event_kind not in ("intermediate_final","main_final") or not isinstance(awards,list) or not awards:
        return json_response({"error":"fixed_place_awards_only"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        slot=await conn.fetchrow("SELECT season_id,slot_type FROM chronos.event_slots WHERE slot_id=$1",slot_id)
        if not slot:
            return json_response({"error":"slot_not_found"},404)
        if event_kind=="intermediate_final" and slot["slot_type"]!="intermediate_final":
            return json_response({"error":"wrong_slot_type"},400)
        if event_kind=="main_final" and slot["slot_type"]!="main_final":
            return json_response({"error":"wrong_slot_type"},400)
        created=[]
        seen_users=set()
        seen_places=set()
        for award in awards:
            try:
                user_id=int(award["user_id"])
                place=int(award["place"])
                base=int(award["base_amount_uah"])
                coefficient=float(award.get("activity_coefficient",1.0))
            except (ValueError,KeyError,TypeError):
                return json_response({"error":"invalid_award_row"},400)
            if user_id in seen_users or place in seen_places or place not in (1,2,3):
                return json_response({"error":"duplicate_player_or_place","place":place},400)
            if base<0 or coefficient!=1.0:
                return json_response({"error":"fixed_competition_prizes_are_not_reduced_by_activity_score"},400)
            seen_users.add(user_id)
            seen_places.add(place)
        async with conn.transaction():
            for award in awards:
                user_id=int(award["user_id"])
                place=int(award["place"])
                base=int(award["base_amount_uah"])
                coefficient=float(award.get("activity_coefficient",1.0))
                rule=await conn.fetchrow(
                    """
                    SELECT amount_uah,is_enabled FROM chronos.prize_rules
                    WHERE season_id=$1 AND event_kind=$2 AND place=$3
                    """,
                    slot["season_id"],event_kind,place,
                )
                if place<1 or not rule or not rule["is_enabled"] or base!=int(rule["amount_uah"]):
                    return json_response({"error":"award_must_match_enabled_fixed_prize_rule","place":place},409)
                if coefficient!=1.0:
                    return json_response({"error":"fixed_competition_prizes_are_not_reduced_by_activity_score"},400)
                final=base
                award_id=await conn.fetchval(
                    """
                    INSERT INTO chronos.prize_awards
                      (season_id,slot_id,event_kind,user_id,place,base_amount_uah,activity_coefficient,final_amount_uah,status)
                    VALUES($1,$2,$3,$4,$5,$6,$7,$8,'draft')
                    ON CONFLICT(slot_id,event_kind,user_id) DO UPDATE
                      SET place=EXCLUDED.place,base_amount_uah=EXCLUDED.base_amount_uah,
                          activity_coefficient=EXCLUDED.activity_coefficient,final_amount_uah=EXCLUDED.final_amount_uah,status='draft'
                    RETURNING award_id
                    """,
                    slot["season_id"],slot_id,event_kind,user_id,place,base,coefficient,final,
                )
                created.append(award_id)
            await audit(conn,actor_id,"prize_awards_drafted","event_slot",slot_id,{"award_ids":created})
        return json_response({"drafted":len(created),"award_ids":created})
    finally:
        await conn.close()


async def update_prize_status(request):
    actor_id=request["telegram_user"]["id"]
    award_id=int(request.match_info["award_id"])
    try:
        payload=await request.json()
        status=payload.get("status")
    except (ValueError,json.JSONDecodeError):
        return json_response({"error":"invalid_json"},400)
    if status not in ("approved","paid","void"):
        return json_response({"error":"invalid_prize_status"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        if status=="paid":
            prior=await conn.fetchval("SELECT status FROM chronos.prize_awards WHERE award_id=$1",award_id)
            if prior!="approved":
                return json_response({"error":"approve_before_marking_paid"},409)
        result=await conn.execute(
            """
            UPDATE chronos.prize_awards SET status=$2,approved_by=CASE WHEN $2='approved' THEN $3 ELSE approved_by END,
                approved_at=CASE WHEN $2='approved' THEN NOW() ELSE approved_at END
            WHERE award_id=$1
            """,
            award_id,status,actor_id,
        )
        if result.endswith("0"):
            return json_response({"error":"award_not_found"},404)
        await audit(conn,actor_id,"prize_status_changed","prize_award",award_id,{"status":status})
        return json_response({"updated":True,"status":status})
    finally:
        await conn.close()


async def admin_prizes(request):
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        rows=await conn.fetch(
            """
            SELECT a.award_id,a.event_kind,a.place,a.base_amount_uah,a.activity_coefficient,a.final_amount_uah,a.status,
                   u.display_name,s.title AS slot_title
            FROM chronos.prize_awards a
            JOIN public.users u ON u.user_id=a.user_id
            LEFT JOIN chronos.event_slots s ON s.slot_id=a.slot_id
            ORDER BY a.created_at DESC LIMIT 100
            """
        )
        rules=await conn.fetch("SELECT event_kind,place,amount_uah,is_enabled,rule_note FROM chronos.prize_rules ORDER BY event_kind,place")
        bonuses=await conn.fetch(
            """
            SELECT a.allocation_id,a.rank_at_lock,a.activity_score,a.activity_coefficient,
                   a.pool_amount_uah,a.allocation_amount_uah,a.status,u.display_name
            FROM chronos.season_bonus_allocations a
            JOIN public.users u ON u.user_id=a.user_id
            ORDER BY a.rank_at_lock
            """
        )
        return json_response({"awards":[dict(r) for r in rows],"rules":[dict(r) for r in rules],"activity_bonus":[dict(r) for r in bonuses]})
    finally:
        await conn.close()


async def admin_adjust_ledger(request):
    actor_id=request["telegram_user"]["id"]
    try:
        payload=await request.json()
        user_id=int(payload["user_id"])
        currency=payload["currency"]
        amount=int(payload["amount"])
        reason=str(payload["reason"]).strip()
        idempotency_key=str(payload["idempotency_key"]).strip()
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return json_response({"error":"invalid_adjustment_payload"},400)
    if currency not in ("CR","EX","XP") or amount==0 or not reason or not idempotency_key or len(reason)>200 or len(idempotency_key)>160:
        return json_response({"error":"invalid_adjustment_values"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        async with conn.transaction():
            if currency=="EX" and amount>0 and not reason.lower().startswith("correction:"):
                return json_response({"error":"EX_is_only_earned_through_predictions_or_explicit_correction"},403)
            created=await award_ledger(conn,user_id,currency,amount,"admin_adjustment",f"admin:{idempotency_key}",metadata={"reason":reason},created_by=actor_id)
            if not created:
                return json_response({"error":"idempotency_key_used"},409)
            await audit(conn,actor_id,"ledger_adjusted","user",user_id,{"currency":currency,"amount":amount,"reason":reason})
        return json_response({"adjusted":True,"balance":await ledger_balance(conn,user_id,currency)})
    except asyncpg.ForeignKeyViolationError:
        return json_response({"error":"user_not_found"},404)
    finally:
        await conn.close()


async def admin_update_catalog_item(request):
    actor_id=request["telegram_user"]["id"]
    item_id=int(request.match_info["item_id"])
    try:
        payload=await request.json()
        price=int(payload["price"])
        enabled=bool(payload["is_enabled"])
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return json_response({"error":"price_and_is_enabled_required"},400)
    if price<0:
        return json_response({"error":"price_must_be_nonnegative"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        item=await conn.fetchrow(
            """
            UPDATE chronos.catalog_items SET price=$2,is_enabled=$3,is_proposed=NOT $3
            WHERE item_id=$1 RETURNING item_code,name,price,currency,is_enabled
            """,
            item_id,price,enabled,
        )
        if not item:
            return json_response({"error":"catalog_item_not_found"},404)
        await audit(conn,actor_id,"catalog_item_updated","catalog_item",item_id,dict(item))
        return json_response(dict(item))
    finally:
        await conn.close()


async def admin_update_settings(request):
    actor_id=request["telegram_user"]["id"]
    try:
        payload=await request.json()
    except (ValueError,json.JSONDecodeError):
        return json_response({"error":"invalid_json"},400)
    if not isinstance(payload,dict):
        return json_response({"error":"invalid_settings"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        season=await conn.fetchrow(
            "SELECT season_id,platform_settings FROM chronos.seasons ORDER BY season_id DESC LIMIT 1 FOR UPDATE"
        )
        if not season:
            return json_response({"error":"season_not_found"},404)
        settings=json_value(season["platform_settings"],{}) or {}
        settings.setdefault("activity_score",{
            "status":"draft","weights":{"attendance":80,"app":15,"minigame":5},
            "app_actions_cap":13,"minigame_completions_cap":5,
        })
        settings.setdefault("predictions",{
            "status":"draft","expected_reward_ex":5,"min_reward_ex":5,"max_reward_ex":100,
            "max_predictions_per_event":3,"ex_season_cap":500,"store_unlock_after_predictions":6,
        })
        settings.setdefault("economy",{
            "status":"draft","cr_per_confirmed_game":5,"xp_per_confirmed_game":10,
            "cr_per_attended_evening":10,"xp_per_attended_evening":5,
            "minigame_first_clear_xp":20,"minigame_repeat_xp":5,"minigame_repeat_cap":10,
            "season_activity_bonus_uah":500,
        })

        if "activity_score" in payload:
            value=payload["activity_score"]
            if not isinstance(value,dict) or value.get("status") not in ("draft","approved"):
                return json_response({"error":"invalid_activity_score_status"},400)
            weights=value.get("weights",settings["activity_score"].get("weights",{}))
            fixed={"attendance":80,"app":15,"minigame":5}
            if {key:int(weights.get(key,-1)) for key in fixed}!=fixed:
                return json_response({"error":"activity_score_weights_are_fixed_80_15_5"},400)
            settings["activity_score"].update({
                "status":value["status"],
                "weights":fixed,
                "app_actions_cap":13,
                "minigame_completions_cap":5,
            })

        if "economy" in payload:
            value=payload["economy"]
            if not isinstance(value,dict) or value.get("status") not in ("draft","approved"):
                return json_response({"error":"invalid_economy_status"},400)
            settings["economy"]["status"]=value["status"]
            # The v1 earning rates and the 500 UAH pool are fixed by the signed-off
            # economy model. Adjusting them requires a new versioned migration.
            settings["economy"].update({
                "version":"1.0",
                "cr_per_confirmed_game":5,
                "xp_per_confirmed_game":10,
                "cr_per_attended_evening":10,
                "xp_per_attended_evening":5,
                "minigame_first_clear_xp":20,
                "minigame_repeat_xp":5,
                "minigame_repeat_cap":10,
                "season_activity_bonus_uah":500,
                "fixed_prizes_are_not_reduced_by_activity_coefficient":True,
            })

        if "predictions" in payload:
            value=payload["predictions"]
            if not isinstance(value,dict) or value.get("status") not in ("draft","approved"):
                return json_response({"error":"invalid_prediction_status"},400)
            settings["predictions"]["status"]=value["status"]
            settings["predictions"].update({
                "expected_reward_ex":5,
                "min_reward_ex":5,
                "max_reward_ex":100,
                "max_predictions_per_event":3,
                "ex_season_cap":500,
                "store_unlock_after_predictions":6,
                "self_prediction_allowed":False,
                "stake_required":False,
                "loss_on_wrong_prediction":False,
            })

        activity_approved=settings["activity_score"].get("status")=="approved"
        economy_approved=settings["economy"].get("status")=="approved"
        predictions_approved=settings["predictions"].get("status")=="approved"
        if economy_approved and not activity_approved:
            return json_response({"error":"approve_activity_score_before_economy"},409)
        if predictions_approved and not (activity_approved and economy_approved):
            return json_response({"error":"approve_activity_score_and_economy_before_predictions"},409)

        await conn.execute(
            "UPDATE chronos.seasons SET platform_settings=$2::jsonb,updated_at=NOW() WHERE season_id=$1",
            season["season_id"],json.dumps(settings),
        )
        await audit(conn,actor_id,"season_settings_updated","season",season["season_id"],payload)
        return json_response({"saved":True,"platform_settings":settings})
    finally:
        await conn.close()


async def close_slot_attendance(request):
    actor_id=request["telegram_user"]["id"]
    slot_id=int(request.match_info["slot_id"])
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        slot=await conn.fetchrow(
            "SELECT season_id,bot_event_id,title FROM chronos.event_slots WHERE slot_id=$1",
            slot_id,
        )
        if not slot or not slot["bot_event_id"]:
            return json_response({"error":"linked_event_required"},409)
        event_status=await conn.fetchval("SELECT status FROM public.events WHERE event_id=$1",slot["bot_event_id"])
        if event_status!="closed":
            return json_response({"error":"bot_event_must_be_closed_first"},409)
        async with conn.transaction():
            updated=await conn.execute(
                """
                UPDATE chronos.attendance a
                SET status='no_show',marked_by=$2,marked_at=NOW()
                WHERE a.slot_id=$1 AND a.invited=TRUE AND a.status='pending'
                  AND NOT EXISTS(
                    SELECT 1 FROM chronos.games g
                    JOIN chronos.game_players gp ON gp.game_id=g.game_id
                    WHERE g.bot_event_id=(SELECT bot_event_id FROM chronos.event_slots WHERE slot_id=$1)
                      AND g.status='confirmed' AND gp.user_id=a.user_id
                  )
                """,
                slot_id,actor_id,
            )
            await conn.execute(
                """
                UPDATE chronos.final_invitations fi
                SET status='no_show'
                WHERE fi.slot_id=$1 AND fi.status='accepted'
                  AND NOT EXISTS(
                    SELECT 1 FROM chronos.games g
                    JOIN chronos.game_players gp ON gp.game_id=g.game_id
                    WHERE g.bot_event_id=$2 AND g.status='confirmed' AND gp.user_id=fi.user_id
                  )
                """,
                slot_id,slot["bot_event_id"],
            )
            await audit(conn,actor_id,"slot_attendance_closed","event_slot",slot_id,{})
        return json_response({"closed":True,"updates":updated})
    finally:
        await conn.close()

async def update_planned_slot(request):
    actor_id=request["telegram_user"]["id"]
    slot_id=int(request.match_info["slot_id"])
    try:
        payload=await request.json()
    except (ValueError,json.JSONDecodeError):
        return json_response({"error":"invalid_json"},400)
    allowed={"title","planned_date","status"}
    if not isinstance(payload,dict) or not payload or not set(payload).issubset(allowed):
        return json_response({"error":"invalid_slot_update"},400)
    if "status" in payload and payload["status"] not in ("planned","cancelled"):
        return json_response({"error":"invalid_slot_status"},400)
    if "title" in payload and (not isinstance(payload["title"],str) or not payload["title"].strip() or len(payload["title"])>120):
        return json_response({"error":"invalid_slot_title"},400)
    planned_date=None
    if "planned_date" in payload and payload["planned_date"]:
        try:
            planned_date=date.fromisoformat(payload["planned_date"])
        except (TypeError,ValueError):
            return json_response({"error":"planned_date_must_be_YYYY_MM_DD"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        slot=await conn.fetchrow("SELECT * FROM chronos.event_slots WHERE slot_id=$1",slot_id)
        if not slot:
            return json_response({"error":"slot_not_found"},404)
        title=payload.get("title",slot["title"])
        status=payload.get("status",slot["status"])
        target_date=planned_date if "planned_date" in payload else slot["planned_date"]
        await conn.execute(
            "UPDATE chronos.event_slots SET title=$2,planned_date=$3,status=$4,updated_at=NOW() WHERE slot_id=$1",
            slot_id,title,target_date,status,
        )
        await audit(conn,actor_id,"event_slot_updated","event_slot",slot_id,payload)
        return json_response({"updated":True,"slot_id":slot_id})
    finally:
        await conn.close()


async def set_season_status(request):
    actor_id=request["telegram_user"]["id"]
    try:
        payload=await request.json()
        status=payload["status"]
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return json_response({"error":"status_required"},400)
    if status not in ("draft","active","paused","completed"):
        return json_response({"error":"invalid_season_status"},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        async with conn.transaction():
            season=await conn.fetchrow("SELECT season_id,status FROM chronos.seasons ORDER BY season_id DESC LIMIT 1 FOR UPDATE")
            if not season:
                return json_response({"error":"season_not_found"},404)
            if status=="active":
                # Prevent two CHRONOS seasons from being active simultaneously.
                await conn.execute("UPDATE chronos.seasons SET status='paused',updated_at=NOW() WHERE status='active' AND season_id<>$1",season["season_id"])
            await conn.execute("UPDATE chronos.seasons SET status=$2,updated_at=NOW() WHERE season_id=$1",season["season_id"],status)
            await audit(conn,actor_id,"season_status_changed","season",season["season_id"],{"from":season["status"],"to":status})
        return json_response({"updated":True,"status":status})
    finally:
        await conn.close()


async def reject_import(request):
    actor_id=request["telegram_user"]["id"]
    import_id=int(request.match_info["import_id"])
    try:
        payload=await request.json()
        reason=str(payload.get("reason","")).strip()
    except (ValueError,json.JSONDecodeError):
        reason=""
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        result=await conn.execute(
            """
            UPDATE chronos.import_batches SET status='rejected',confirmed_by=$2,confirmed_at=NOW()
            WHERE import_id=$1 AND status='needs_review'
            """,
            import_id,actor_id,
        )
        if result.endswith("0"):
            return json_response({"error":"import_not_rejectable"},409)
        await audit(conn,actor_id,"import_rejected","import",import_id,{"reason":reason})
        return json_response({"rejected":True})
    finally:
        await conn.close()


async def update_prize_rule(request):
    actor_id=request["telegram_user"]["id"]
    try:
        payload=await request.json()
        event_kind=payload["event_kind"]
        place=int(payload["place"])
        amount=int(payload["amount_uah"])
        enabled=bool(payload.get("is_enabled",False))
        note=str(payload.get("rule_note",""))
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):
        return json_response({"error":"invalid_prize_rule"},400)
    fixed_amounts={
        ("intermediate_final",1):1000,("intermediate_final",2):700,("intermediate_final",3):300,
        ("main_final",1):3000,("main_final",2):2000,("main_final",3):1000,
        ("legacy",1):500,
    }
    if (event_kind,place) not in fixed_amounts or amount!=fixed_amounts[(event_kind,place)]:
        return json_response({"error":"prize_amount_is_fixed_by_chronos_rules","expected":fixed_amounts.get((event_kind,place))},400)
    from database import get_connection
    conn=await get_connection()
    try:
        error=await require_admin(request,conn)
        if error:
            return error
        season_id=await conn.fetchval("SELECT season_id FROM chronos.seasons ORDER BY season_id DESC LIMIT 1")
        await conn.execute(
            """
            INSERT INTO chronos.prize_rules(season_id,event_kind,place,amount_uah,is_enabled,rule_note)
            VALUES($1,$2,$3,$4,$5,$6)
            ON CONFLICT(season_id,event_kind,place) DO UPDATE
              SET amount_uah=EXCLUDED.amount_uah,is_enabled=EXCLUDED.is_enabled,rule_note=EXCLUDED.rule_note
            """,
            season_id,event_kind,place,amount,enabled,note,
        )
        await audit(conn,actor_id,"prize_rule_updated","season",season_id,payload)
        return json_response({"saved":True})
    finally:
        await conn.close()

def register_admin_routes(app):
    app.router.add_get("/api/chronos/admin/overview",admin_overview)
    app.router.add_get("/api/chronos/admin/slots",admin_slots)
    app.router.add_post("/api/chronos/admin/slots/{slot_id:\\d+}",update_planned_slot)
    app.router.add_post("/api/chronos/admin/season/status",set_season_status)
    app.router.add_post("/api/chronos/admin/slots/{slot_id:\\d+}/link",link_slot_to_bot_event)
    app.router.add_post("/api/chronos/admin/slots/{slot_id:\\d+}/invitations",generate_invitations)
    app.router.add_post("/api/chronos/admin/slots/{slot_id:\\d+}/close-attendance",close_slot_attendance)
    app.router.add_post("/api/chronos/admin/invitations/process-expired",process_expired_invitations)
    app.router.add_post("/api/chronos/operations/invitations/{invitation_id:\\d+}/respond",respond_invitation)

    app.router.add_post("/api/chronos/admin/imports/upload",upload_import)
    app.router.add_get("/api/chronos/admin/imports",list_imports)
    app.router.add_get("/api/chronos/admin/imports/{import_id:\\d+}",import_detail)
    app.router.add_get("/api/chronos/admin/imports/{import_id:\\d+}/image",import_image)
    app.router.add_post("/api/chronos/admin/imports/{import_id:\\d+}/review",save_import_review)
    app.router.add_post("/api/chronos/admin/imports/{import_id:\\d+}/confirm",confirm_import)
    app.router.add_post("/api/chronos/admin/imports/{import_id:\\d+}/reject",reject_import)

    app.router.add_get("/api/chronos/admin/players",admin_players)
    app.router.add_get("/api/chronos/admin/audit",admin_audit)
    app.router.add_get("/api/chronos/admin/prizes",admin_prizes)
    app.router.add_post("/api/chronos/admin/season-bonus/calculate",calculate_season_activity_bonus)
    app.router.add_post("/api/chronos/admin/season-bonus/{allocation_id:\\d+}/status",update_activity_bonus_status)
    app.router.add_post("/api/chronos/admin/economy/reconcile",reconcile_economy_ledger)
    app.router.add_post("/api/chronos/admin/prize-rules",update_prize_rule)
    app.router.add_post("/api/chronos/admin/prizes",create_prize_awards)
    app.router.add_post("/api/chronos/admin/prizes/{award_id:\\d+}/status",update_prize_status)
    app.router.add_post("/api/chronos/admin/economy/adjust",admin_adjust_ledger)
    app.router.add_post("/api/chronos/admin/catalog/{item_id:\\d+}",admin_update_catalog_item)
    app.router.add_post("/api/chronos/admin/settings",admin_update_settings)
