"""Postgres access. Every state change the pipeline makes goes through here."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings

SCHEMA = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"


@asynccontextmanager
async def connect():
    conn = await psycopg.AsyncConnection.connect(settings().database_url, row_factory=dict_row, autocommit=True)
    try:
        yield conn
    finally:
        await conn.close()


async def init_schema() -> None:
    async with connect() as conn:
        await conn.execute(SCHEMA.read_text())


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- settings / kill switch ----------

async def kill_switch_on(conn) -> bool:
    row = await (await conn.execute("SELECT value FROM settings WHERE key = 'kill_switch'")).fetchone()
    return bool(row and row["value"])


async def set_kill_switch(conn, on: bool) -> None:
    await conn.execute("UPDATE settings SET value = %s WHERE key = 'kill_switch'", [Jsonb(on)])


# ---------- prospects ----------

async def upsert_prospect(conn, p: dict[str, Any]) -> int:
    row = await (await conn.execute(
        """INSERT INTO prospects (external_id, first_name, last_name, email, company, phone_e164, tz,
                                  segment, context, hubspot_contact_id)
           VALUES (%(external_id)s, %(first_name)s, %(last_name)s, %(email)s, %(company)s, %(phone_e164)s,
                   %(tz)s, %(segment)s, %(context)s, %(hubspot_contact_id)s)
           ON CONFLICT (phone_e164) DO UPDATE SET
               first_name = EXCLUDED.first_name, last_name = EXCLUDED.last_name, email = EXCLUDED.email,
               company = EXCLUDED.company, segment = EXCLUDED.segment, context = EXCLUDED.context,
               external_id = COALESCE(EXCLUDED.external_id, prospects.external_id),
               hubspot_contact_id = COALESCE(EXCLUDED.hubspot_contact_id, prospects.hubspot_contact_id),
               updated_at = now()
           RETURNING id""",
        {**{k: p.get(k) for k in ("external_id", "first_name", "last_name", "email", "company",
                                  "segment", "hubspot_contact_id")},
         "phone_e164": p["phone_e164"], "tz": p.get("tz") or "Europe/Rome",
         "context": Jsonb(p.get("context") or {})})).fetchone()
    return row["id"]


async def get_prospect(conn, prospect_id: int) -> dict | None:
    return await (await conn.execute("SELECT * FROM prospects WHERE id = %s", [prospect_id])).fetchone()


async def find_prospect_by_phone(conn, phone: str) -> dict | None:
    return await (await conn.execute("SELECT * FROM prospects WHERE phone_e164 = %s", [phone])).fetchone()


async def set_prospect_status(conn, prospect_id: int, status: str) -> None:
    # dnc is sticky: nothing may overwrite it
    await conn.execute(
        "UPDATE prospects SET status = %s, updated_at = now() WHERE id = %s AND status <> 'dnc'",
        [status, prospect_id])


async def mark_dnc(conn, prospect_id: int, reason: str) -> None:
    """Immediate and permanent: flag the prospect and cancel every pending job."""
    async with conn.transaction():
        await conn.execute(
            """UPDATE prospects SET dnc = TRUE, dnc_at = COALESCE(dnc_at, now()), dnc_reason = %s,
                      status = 'dnc', updated_at = now() WHERE id = %s""", [reason, prospect_id])
        await conn.execute(
            """UPDATE call_jobs SET status = 'cancelled', reason = 'dnc', updated_at = now()
               WHERE prospect_id = %s AND status = 'queued'""", [prospect_id])


# ---------- jobs ----------

async def enqueue_job(conn, prospect_id: int, kind: str, due_at: datetime, reason: str | None = None,
                      created_by: str = "system") -> int | None:
    """Replace any queued job for this prospect (one queued job per prospect). Refuses DNC prospects."""
    async with conn.transaction():
        p = await (await conn.execute("SELECT dnc, status FROM prospects WHERE id = %s FOR UPDATE",
                                      [prospect_id])).fetchone()
        if not p or p["dnc"] or p["status"] != "active":
            return None
        await conn.execute(
            """UPDATE call_jobs SET status = 'cancelled', reason = 'superseded', updated_at = now()
               WHERE prospect_id = %s AND status = 'queued'""", [prospect_id])
        row = await (await conn.execute(
            """INSERT INTO call_jobs (prospect_id, kind, due_at, reason, created_by)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            [prospect_id, kind, due_at, reason, created_by])).fetchone()
        return row["id"]


async def claim_due_job(conn) -> dict | None:
    """Take the oldest due job, locking it so two dialers never take the same one."""
    async with conn.transaction():
        row = await (await conn.execute(
            """SELECT j.*, p.phone_e164, p.tz, p.dnc, p.status AS prospect_status, p.attempts
               FROM call_jobs j JOIN prospects p ON p.id = j.prospect_id
               WHERE j.status = 'queued' AND j.due_at <= now()
               ORDER BY j.due_at
               FOR UPDATE OF j SKIP LOCKED LIMIT 1""")).fetchone()
        if row:
            await conn.execute("UPDATE call_jobs SET status = 'dialing', updated_at = now() WHERE id = %s",
                               [row["id"]])
        return row


async def finish_job(conn, job_id: int, status: str = "done", reason: str | None = None) -> None:
    await conn.execute(
        "UPDATE call_jobs SET status = %s, reason = COALESCE(%s, reason), updated_at = now() WHERE id = %s",
        [status, reason, job_id])


async def reschedule_job(conn, job_id: int, due_at: datetime, reason: str) -> None:
    await conn.execute(
        "UPDATE call_jobs SET status = 'queued', due_at = %s, reason = %s, updated_at = now() WHERE id = %s",
        [due_at, reason, job_id])


# ---------- calls ----------

async def create_call(conn, *, job_id: int | None, prospect_id: int | None, direction: str, room_name: str,
                      phone: str | None) -> int:
    s = settings()
    async with conn.transaction():
        row = await (await conn.execute(
            """INSERT INTO calls (job_id, prospect_id, direction, room_name, phone_e164, prompt_version,
                                  persona_variant, outcome)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            [job_id, prospect_id, direction, room_name, phone, s.prompt_version, s.persona_variant,
             "dialing" if direction == "outbound" else "in_progress"])).fetchone()
        if prospect_id and direction == "outbound":
            await conn.execute(
                "UPDATE prospects SET attempts = attempts + 1, last_called_at = now() WHERE id = %s",
                [prospect_id])
        return row["id"]


async def update_call(conn, call_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = %({k})s" for k in fields)
    params = {k: (Jsonb(v) if isinstance(v, (dict, list)) else v) for k, v in fields.items()}
    params["_id"] = call_id
    await conn.execute(f"UPDATE calls SET {cols} WHERE id = %(_id)s", params)


async def get_call(conn, call_id: int) -> dict | None:
    return await (await conn.execute("SELECT * FROM calls WHERE id = %s", [call_id])).fetchone()


async def log_event(conn, call_id: int, type_: str, payload: dict | None = None) -> None:
    await conn.execute("INSERT INTO call_events (call_id, type, payload) VALUES (%s, %s, %s)",
                       [call_id, type_, Jsonb(json.loads(json.dumps(payload or {}, default=str)))])


async def active_call_count(conn) -> int:
    row = await (await conn.execute(
        """SELECT count(*) AS n FROM calls
           WHERE outcome IN ('dialing','in_progress') AND created_at > now() - interval '20 minutes'""")).fetchone()
    return row["n"]


async def calls_started_today(conn, tz: str = "Europe/Rome") -> int:
    row = await (await conn.execute(
        """SELECT count(*) AS n FROM calls
           WHERE direction = 'outbound' AND (created_at AT TIME ZONE %s)::date = (now() AT TIME ZONE %s)::date""",
        [tz, tz])).fetchone()
    return row["n"]


async def reap_stale_calls(conn) -> int:
    """Calls whose agent process died: close them so the dialer's concurrency count frees up."""
    cur = await conn.execute(
        """UPDATE calls SET outcome = 'failed', ended_at = now()
           WHERE outcome IN ('dialing','in_progress') AND created_at < now() - interval '20 minutes'
           RETURNING job_id""")
    rows = await cur.fetchall()
    for r in rows:
        if r["job_id"]:
            await finish_job(conn, r["job_id"], "done", "stale")
    return len(rows)


async def calls_needing_postcall(conn, limit: int = 10) -> list[dict]:
    cur = await conn.execute(
        """SELECT c.*, p.first_name, p.last_name, p.email, p.company, p.hubspot_contact_id, p.tz,
                  p.attempts, p.segment, p.context
           FROM calls c LEFT JOIN prospects p ON p.id = c.prospect_id
           WHERE c.postcall_done = FALSE AND c.ended_at IS NOT NULL
           ORDER BY c.ended_at LIMIT %s""", [limit])
    return await cur.fetchall()
