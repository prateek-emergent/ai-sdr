"""What happens to a prospect after a call. Single place for next-step rules (pure function + DB apply)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import db
from .config import settings
from .timeutil import retry_time

RETRYABLE_OUTCOMES = {"no_answer", "busy", "voicemail", "failed", "declined"}
CLOSING_DISPOSITIONS = {"meeting_booked": "meeting_booked", "not_interested": "not_interested",
                        "not_a_fit": "not_a_fit", "wrong_person": "wrong_person"}


@dataclass
class NextStep:
    action: str                 # retry | close | none
    status: str | None = None   # prospect status when closing
    due_at: datetime | None = None
    reason: str | None = None


def decide(*, outcome: str, disposition: str | None, attempts: int, max_attempts: int, now: datetime, tz: str,
           windows, has_callback: bool, dnc: bool) -> NextStep:
    if dnc or disposition == "dnc":
        return NextStep("none", reason="dnc")                       # already handled at the moment it was said
    if outcome == "bad_number":
        return NextStep("close", status="bad_number")
    if disposition in CLOSING_DISPOSITIONS:
        return NextStep("close", status=CLOSING_DISPOSITIONS[disposition])
    if disposition == "manual_scheduling":  # no slot fitted: the team books by hand, so the dialer stops here
        return NextStep("close", status="meeting_requested", reason="team books the meeting by hand")
    if disposition == "callback" or has_callback:
        return NextStep("none", reason="callback already queued")
    if attempts >= max_attempts:
        return NextStep("close", status="exhausted")
    if outcome in RETRYABLE_OUTCOMES:
        return NextStep("retry", due_at=retry_time(now, tz, windows, attempts, "no_answer"), reason=outcome)
    if outcome == "completed" and disposition in ("not_now", "hung_up", "other", None):
        return NextStep("retry", due_at=retry_time(now, tz, windows, attempts, "not_now"),
                        reason=disposition or "no decision")
    return NextStep("none")


async def apply(conn, call: dict, now: datetime) -> NextStep:
    s = settings()
    if not call.get("prospect_id"):
        return NextStep("none", reason="unknown caller")
    p = await db.get_prospect(conn, call["prospect_id"])
    step = decide(outcome=call["outcome"], disposition=call.get("disposition"), attempts=p["attempts"],
                  max_attempts=s.max_attempts, now=now, tz=p["tz"], windows=s.business_hours,
                  has_callback=call.get("callback_at") is not None, dnc=p["dnc"])
    if step.action == "close":
        await db.set_prospect_status(conn, p["id"], step.status)
    elif step.action == "retry":
        await db.enqueue_job(conn, p["id"], "retry", step.due_at, reason=step.reason)
    return step
