"""Shared CHRONOS API helpers."""

import asyncpg
from aiohttp import web
from datetime import date, datetime
from decimal import Decimal


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
