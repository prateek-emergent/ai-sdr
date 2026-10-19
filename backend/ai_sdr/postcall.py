"""After every call: summarise, cross-check, log to HubSpot, brief the meeting owner, decide the next step.

Runs as its own loop (uv run ai-sdr postcall) so a slow API never holds up a live call.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from . import db, followup
from .agent.prompts import allowed_claims
from .config import settings
from .llm import structured
from .integrations.hubspot import HubSpot, task_due_before_meeting
from .italian import when_phrase

log = logging.getLogger("ai_sdr.postcall")


class Objection(BaseModel):
    objection: str
    response: str
    worked: bool


class CallSummary(BaseModel):
    summary_en: str = Field(description="3-5 sentence summary in English for our team")
    disposition: Literal["meeting_booked", "manual_scheduling", "callback", "not_now", "not_interested", "not_a_fit", "wrong_person",
                         "dnc", "hung_up", "other"]
    qualification: Literal["qualified", "maybe", "not_qualified", "unknown"]
    qualification_reasons: list[str]
    what_they_built: str = Field(description="what the prospect built or wants to build, or empty")
    pain_points: list[str]
    product_feedback: list[str] = Field(
        description="each distinct piece of feedback about the platform (praise or criticism), in English, specific "
                    "enough for the product team, e.g. 'credits run out after a few prompts on a CRUD app'")
    meeting_reason: str = Field(description="what the agreed call with our team is about, in English, or empty")
    objections: list[Objection]
    quotes: list[str] = Field(description="2-3 short verbatim quotes from the prospect, in Italian")
    asked_not_to_be_called: bool = Field(description="true if the prospect asked in any way not to be called again")
    asked_if_ai: bool
    agent_claimed_human: bool
    agent_possible_unapproved_claims: list[str] = Field(
        description="statements by the agent about the product, prices, customers or numbers that go beyond the "
                    "allowed claims listed in the instructions")
    agent_turns_too_long: bool = Field(description="true if the agent often spoke more than two sentences in a row")


SYSTEM = ("You review transcripts of short Italian sales-development phone calls made by an AI assistant. "
          "Extract the facts precisely. Do not guess: if something did not happen, say so (empty list / false).\n"
          "The only claims the agent may make (no numbers of any kind):\n")


def transcript_text(transcript: dict | None) -> str:
    lines = []
    for item in (transcript or {}).get("items", []):
        if item.get("type") == "message":
            text = " ".join(c if isinstance(c, str) else "" for c in item.get("content", [])).strip()
            if text:
                who = "AGENT" if item.get("role") == "assistant" else "PROSPECT"
                lines.append(f"{who}: {text}")
        elif item.get("type") == "function_call":
            lines.append(f"[tool {item.get('name')} {item.get('arguments')}]")
    return "\n".join(lines)


async def summarise(text: str) -> CallSummary:
    return await structured(SYSTEM + allowed_claims(), f"Transcript:\n\n{text}", CallSummary,
                            model=settings().summary_model, max_tokens=4000)


def review_flags(call: dict, s: CallSummary | None) -> list[str]:
    flags = []
    if s is None:
        return flags
    if s.asked_not_to_be_called and call.get("disposition") != "dnc":
        flags.append("prospect asked not to be called but DNC tool was not used (DNC applied in post-call)")
    if s.agent_claimed_human:
        flags.append("agent claimed to be human")
    if s.agent_possible_unapproved_claims:
        flags.append("possible unapproved claims: " + "; ".join(s.agent_possible_unapproved_claims)[:300])
    if s.agent_turns_too_long:
        flags.append("agent turns too long")
    return flags


def brief(call: dict, s: CallSummary) -> str:
    who = " ".join(x for x in (call.get("first_name"), call.get("last_name")) if x) or call.get("phone_e164")
    tz = call.get("tz") or "Europe/Rome"
    when = when_phrase(call["meeting_start"].astimezone(ZoneInfo(tz))) if call.get("meeting_start") else "n/a"
    parts = [f"AI SDR call brief: {who}" + (f", {call['company']}" if call.get("company") else ""),
             f"Meeting: {when} ({tz})",
             f"Qualification: {s.qualification}: " + "; ".join(s.qualification_reasons),
             f"What they built: {s.what_they_built or 'n/a'}",
             f"Meeting about: {s.meeting_reason or 'n/a'}",
             "Pain points: " + ("; ".join(s.pain_points) or "n/a"),
             "Product feedback: " + ("; ".join(s.product_feedback) or "n/a"),
             "Objections: " + ("; ".join(f"{o.objection} -> {o.response}" for o in s.objections) or "none"),
             "Quotes: " + (" | ".join(f'"{q}"' for q in s.quotes) or "n/a"),
             f"Summary: {s.summary_en}"]
    if call.get("recording_uri"):
        parts.append(f"Recording: {call['recording_uri']}")
    return "\n".join(parts)


def manual_scheduling_brief(call: dict, s: CallSummary | None) -> str:
    m = call.get("manual_schedule") or {}
    who = " ".join(x for x in (call.get("first_name"), call.get("last_name")) if x) or call.get("phone_e164")
    parts = [f"AI SDR: please book this meeting by hand and email the invite. None of our free slots fitted.",
             f"Who: {who}" + (f", {call['company']}" if call.get("company") else ""),
             f"Email: {m.get('email', 'n/a')}",
             f"Preferred times (their words, {m.get('tz', 'Europe/Rome')}): {m.get('preferred', 'n/a')}"]
    if s:
        parts += [f"Meeting about: {s.meeting_reason or 'n/a'}",
                  "Problems raised: " + ("; ".join(s.pain_points) or "n/a"),
                  f"Summary: {s.summary_en}"]
    return "\n".join(parts)


def manual_task_due(now: datetime) -> datetime:
    """Same day, so the person hears back while the call is fresh."""
    return now + timedelta(hours=2)


async def process(conn, call: dict, hubspot: HubSpot) -> None:
    now = datetime.now(timezone.utc)
    summary: CallSummary | None = None
    if call["outcome"] == "completed" and call.get("transcript"):
        text = transcript_text(call["transcript"])
        if text:
            summary = await summarise(text)

    # cross-check: a DNC request the agent missed is still honoured, immediately
    if summary and summary.asked_not_to_be_called and call.get("prospect_id"):
        await db.mark_dnc(conn, call["prospect_id"], "detected in post-call review")
        call["disposition"] = "dnc"
    elif summary and not call.get("disposition"):
        call["disposition"] = summary.disposition

    flags = review_flags(call, summary)
    await db.update_call(conn, call["id"], summary=summary.model_dump() if summary else None,
                         disposition=call.get("disposition"),
                         qualification=call.get("qualification") or (
                             summary.qualification if summary and summary.qualification != "unknown" else None),
                         review_status="flagged" if flags else "pending", review_reasons=flags or None)

    step = await followup.apply(conn, call, now)

    # HubSpot
    if call.get("prospect_id"):
        p = await db.get_prospect(conn, call["prospect_id"])
        contact_id = p.get("hubspot_contact_id") or await hubspot.find_contact(email=p.get("email"),
                                                                              phone=p["phone_e164"])
        if contact_id:
            if p["dnc"]:
                await hubspot.mark_dnc(contact_id, p.get("dnc_reason") or "requested on AI call")
            started = call.get("answered_at") or call["created_at"]
            duration = int((call["ended_at"] - started).total_seconds()) if call.get("answered_at") else 0
            body = (summary.summary_en if summary else f"Outcome: {call['outcome']}") + \
                   ("\n\nProduct feedback:\n- " + "\n- ".join(summary.product_feedback)
                    if summary and summary.product_feedback else "") + \
                   (f"\n\nTranscript:\n{transcript_text(call.get('transcript'))[:6000]}" if summary else "")
            hs_id = await hubspot.log_call(contact_id, started=started, duration_s=duration, outcome=call["outcome"],
                                           title=f"AI SDR call: {call.get('disposition') or call['outcome']}",
                                           body=body, recording_url=None, to_number=call.get("phone_e164"),
                                           from_number=settings().caller_number)
            next_at = step.due_at.isoformat() if step.due_at else None
            await hubspot.update_contact(contact_id, {
                "ai_call_status": p["status"], "ai_call_attempts": str(p["attempts"]),
                "ai_last_call_at": call["ended_at"].date().isoformat(), "ai_next_call_at": next_at,
                "ai_disposition": call.get("disposition"),
                "ai_qualification": summary.qualification if summary else None,
                "ai_qual_reason": "; ".join(summary.qualification_reasons)[:500] if summary else None,
                "ai_persona_variant": call.get("persona_variant"),
                "ai_meeting_booked_at": call["meeting_start"].date().isoformat() if call.get("meeting_start") else None,
                "ai_preferred_times": (call.get("manual_schedule") or {}).get("preferred")})
            if call.get("disposition") == "meeting_booked" and call.get("meeting_start") and summary:
                text = brief(call, summary)
                await hubspot.add_note(contact_id, text)
                await hubspot.add_task(contact_id, "Prep: AI-booked meeting", text,
                                       task_due_before_meeting(call["meeting_start"]),
                                       settings().hubspot_owner_id)
            if call.get("disposition") == "manual_scheduling" and call.get("manual_schedule"):
                # no free slot fitted: a same-day task for the meeting owner to book by hand and email the invite
                text = manual_scheduling_brief(call, summary)
                await hubspot.add_note(contact_id, text)
                await hubspot.add_task(contact_id, "Book by hand: AI SDR call, no slot fitted", text,
                                       manual_task_due(now), settings().hubspot_owner_id)
            await db.update_call(conn, call["id"], hubspot_call_id=hs_id or None)

    await db.update_call(conn, call["id"], postcall_done=True)
    log.info("post-call done for call %s: %s / %s -> %s", call["id"], call["outcome"], call.get("disposition"),
             step.action)


async def run_forever(poll_seconds: int = 10) -> None:
    hubspot = HubSpot()
    async with db.connect() as conn:
        while True:
            calls = await db.calls_needing_postcall(conn)
            for call in calls:
                try:
                    await process(conn, call, hubspot)
                except Exception as e:
                    log.exception("post-call failed for call %s", call["id"])
                    await db.log_event(conn, call["id"], "error", {"where": "postcall", "error": str(e)})
                    await db.update_call(conn, call["id"], postcall_done=True, review_status="flagged",
                                         review_reasons=[f"post-call error: {e}"[:300]])
            if not calls:
                await asyncio.sleep(poll_seconds)
