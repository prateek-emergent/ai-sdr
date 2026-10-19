"""HubSpot writes for AI calls.

Same convention as outbound-hubspot/hubspot_store.py: reads always run, writes are logged as DRY-RUN
unless HUBSPOT_WRITE=1. New contact fields (group "AI calling") must exist first; writes skip any field
that HubSpot doesn't know yet, so nothing breaks before the change record is approved.

Association type ids (HubSpot-defined): call->contact 194, note->contact 202, task->contact 204.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from ..config import settings

log = logging.getLogger("ai_sdr.hubspot")

AI_PROPS = ["ai_call_status", "ai_call_attempts", "ai_last_call_at", "ai_next_call_at", "ai_disposition",
            "ai_qualification", "ai_qual_reason", "ai_persona_variant", "ai_meeting_booked_at",
            "ai_preferred_times"]

# hs_call_status values HubSpot accepts
CALL_STATUS = {"completed": "COMPLETED", "no_answer": "NO_ANSWER", "busy": "BUSY", "voicemail": "COMPLETED",
               "failed": "FAILED", "bad_number": "FAILED", "declined": "NO_ANSWER", "in_progress": "IN_PROGRESS"}


def _ms(dt: datetime) -> str:
    return str(int(dt.timestamp() * 1000))


class HubSpot:
    def __init__(self) -> None:
        s = settings()
        self.write = s.hubspot_write
        self.enabled = bool(s.hubspot_token)
        self.client = httpx.AsyncClient(base_url="https://api.hubapi.com", timeout=15,
                                        headers={"Authorization": f"Bearer {s.hubspot_token or ''}"})
        self._known: set[str] | None = None

    async def _req(self, method: str, path: str, body: dict | None = None, *, is_write: bool) -> dict:
        if not self.enabled:
            log.info("HubSpot disabled (no HUBSPOT_API_KEY): %s %s", method, path)
            return {"id": "disabled"}
        if is_write and not self.write:
            log.info("DRY-RUN %s %s %s", method, path, body)
            return {"id": "dry-run"}
        r = await self.client.request(method, path, json=body)
        if r.status_code >= 300:
            raise RuntimeError(f"HubSpot {method} {path} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    async def known_props(self) -> set[str]:
        if self._known is None:
            if not self.enabled:
                self._known = set()
            else:
                res = await self._req("GET", "/crm/v3/properties/contacts", is_write=False)
                self._known = {p["name"] for p in res.get("results", [])}
        return self._known

    async def find_contact(self, *, email: str | None, phone: str | None) -> str | None:
        for prop, value in (("email", (email or "").lower()), ("phone", phone)):
            if not value:
                continue
            res = await self._req("POST", "/crm/v3/objects/contacts/search", {
                "filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}],
                "properties": ["email", "do_not_touch"], "limit": 1}, is_write=False)
            hits = res.get("results", [])
            if hits:
                return hits[0]["id"]
        return None

    async def update_contact(self, contact_id: str, props: dict) -> None:
        known = await self.known_props()
        props = {k: v for k, v in props.items() if v is not None and (k in known or not self.enabled)}
        if props:
            await self._req("PATCH", f"/crm/v3/objects/contacts/{contact_id}", {"properties": props}, is_write=True)

    async def mark_dnc(self, contact_id: str, reason: str) -> None:
        """Reuses the existing do_not_touch flag the outbound team already honours."""
        await self.update_contact(contact_id, {
            "do_not_touch": "true", "dnt_source": "ai_call", "dnt_reason": reason[:250],
            "dnt_set_date": datetime.now(timezone.utc).date().isoformat(), "ai_call_status": "dnc"})

    async def log_call(self, contact_id: str, *, started: datetime, duration_s: int, outcome: str,
                       title: str, body: str, recording_url: str | None, to_number: str | None,
                       from_number: str | None) -> str:
        props = {
            "hs_timestamp": _ms(started),
            "hs_call_title": title,
            "hs_call_body": body,
            "hs_call_direction": "OUTBOUND",
            "hs_call_status": CALL_STATUS.get(outcome, "COMPLETED"),
            "hs_call_duration": str(duration_s * 1000),
            "hs_call_to_number": to_number,
            "hs_call_from_number": from_number,
        }
        if recording_url:
            props["hs_call_recording_url"] = recording_url  # must be HTTPS .mp3/.wav
        res = await self._req("POST", "/crm/v3/objects/calls", {
            "properties": {k: v for k, v in props.items() if v is not None},
            "associations": [{"to": {"id": contact_id}, "types": [
                {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 194}]}]}, is_write=True)
        return res.get("id", "")

    async def add_note(self, contact_id: str, text: str) -> None:
        await self._req("POST", "/crm/v3/objects/notes", {
            "properties": {"hs_timestamp": _ms(datetime.now(timezone.utc)), "hs_note_body": text},
            "associations": [{"to": {"id": contact_id}, "types": [
                {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]}]}, is_write=True)

    async def add_task(self, contact_id: str, subject: str, body: str, due: datetime,
                       owner_id: str | None) -> None:
        props = {"hs_timestamp": _ms(due), "hs_task_subject": subject, "hs_task_body": body,
                 "hs_task_status": "NOT_STARTED", "hs_task_priority": "HIGH"}
        if owner_id:
            props["hubspot_owner_id"] = owner_id
        await self._req("POST", "/crm/v3/objects/tasks", {
            "properties": props,
            "associations": [{"to": {"id": contact_id}, "types": [
                {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 204}]}]}, is_write=True)


def task_due_before_meeting(meeting_start: datetime) -> datetime:
    return meeting_start - timedelta(hours=1)
