"""The dialer: picks due jobs, re-checks every rule at dial time, and dispatches the agent to place the call.

Rules enforced here, in code: kill switch, concurrency and daily caps, DNC/status, attempt limit,
business hours in the prospect's timezone (callbacks: the window the prospect explicitly asked for).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from livekit import api

from . import db
from .config import settings
from .timeutil import in_business_hours, next_business_time

log = logging.getLogger("ai_sdr.dialer")


async def dispatch(room: str, metadata: dict) -> None:
    s = settings()
    lk = api.LiveKitAPI(url=s.livekit_url, api_key=s.livekit_api_key, api_secret=s.livekit_api_secret)
    try:
        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
            agent_name=s.agent_name, room=room, metadata=json.dumps(metadata)))
    finally:
        await lk.aclose()


def room_name(prospect_id: int, job_id: int) -> str:
    return f"sdr-out-{prospect_id}-{job_id}-{int(datetime.now(timezone.utc).timestamp())}"


async def dial_job(conn, job: dict, *, ignore_hours: bool = False) -> str:
    """Returns what happened, for logs: dispatched | rescheduled:<why> | cancelled:<why>."""
    s = settings()
    now = datetime.now(timezone.utc)
    if job["dnc"] or job["prospect_status"] != "active":
        await db.finish_job(conn, job["id"], "cancelled", "prospect not active")
        return "cancelled:not_active"
    if job["kind"] != "callback" and job["attempts"] >= s.max_attempts:
        await db.finish_job(conn, job["id"], "cancelled", "max attempts")
        await db.set_prospect_status(conn, job["prospect_id"], "exhausted")
        return "cancelled:max_attempts"
    if not ignore_hours:
        if job["kind"] == "callback":
            start, end = s.callback_hours
            local_t = now.astimezone(ZoneInfo(job["tz"])).time()
            ok = start <= local_t <= end
        else:
            ok = in_business_hours(now, job["tz"], s.business_hours)
        if not ok:
            nxt = next_business_time(now, job["tz"], s.business_hours)
            await db.reschedule_job(conn, job["id"], nxt, "outside hours")
            return "rescheduled:outside_hours"

    room = room_name(job["prospect_id"], job["id"])
    call_id = await db.create_call(conn, job_id=job["id"], prospect_id=job["prospect_id"], direction="outbound",
                                   room_name=room, phone=job["phone_e164"])
    try:
        await dispatch(room, {"direction": "outbound", "call_id": call_id, "job_id": job["id"],
                              "prospect_id": job["prospect_id"], "phone": job["phone_e164"]})
    except Exception as e:
        log.exception("dispatch failed")
        await db.update_call(conn, call_id, outcome="failed", ended_at=datetime.now(timezone.utc))
        await db.log_event(conn, call_id, "error", {"where": "dispatch", "error": str(e)})
        await db.finish_job(conn, job["id"], "done", "dispatch failed")
        return "failed:dispatch"
    log.info("dispatched call %s to prospect %s (%s job %s)", call_id, job["prospect_id"], job["kind"], job["id"])
    return "dispatched"


async def tick(conn) -> str:
    s = settings()
    await db.reap_stale_calls(conn)
    if await db.kill_switch_on(conn):
        return "kill_switch"
    if await db.active_call_count(conn) >= s.max_concurrent_calls:
        return "busy"
    if await db.calls_started_today(conn) >= s.daily_call_cap:
        return "daily_cap"
    job = await db.claim_due_job(conn)
    if not job:
        return "idle"
    return await dial_job(conn, job)


async def run_forever() -> None:
    s = settings()
    log.info("dialer started (max %s concurrent, %s/day)", s.max_concurrent_calls, s.daily_call_cap)
    async with db.connect() as conn:
        while True:
            try:
                result = await tick(conn)
            except Exception:
                log.exception("dialer tick failed")
                result = "error"
            # dial back-to-back while there is work and capacity; otherwise wait
            await asyncio.sleep(1 if result.startswith("dispatched") else s.dialer_poll_seconds)
