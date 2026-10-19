"""Meeting slots and booking.

CalendlyCalendar uses Calendly's Scheduling API (paid plan; personal access token or OAuth):
  GET  /event_type_available_times?event_type=..&start_time=..&end_time=..   (window <= 31 days)
  POST /invitees  {event_type, start_time, invitee{name,email,timezone}, tracking{utm_*}}
FakeCalendar is for local runs and tests: it offers business-hour slots and "books" in memory.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

import httpx

from ..config import settings
from ..timeutil import in_business_hours, next_business_time


@dataclass
class Booking:
    start: datetime          # UTC
    reference: str           # Calendly event URI, or fake id
    reschedule_url: str | None = None


class CalendarError(RuntimeError):
    pass


class Calendar(Protocol):
    async def free_slots(self, after: datetime, before: datetime) -> list[datetime]: ...
    async def book(self, start: datetime, *, name: str, email: str, tz: str, call_ref: str) -> Booking: ...
    async def cancel(self, reference: str, reason: str) -> None: ...


def pick_offer(slots: list[datetime], tz: str, n: int = 2) -> list[datetime]:
    """Offer slots on different days and different halves of the day, e.g. Tue 10:00 + Wed 15:00."""
    zone = ZoneInfo(tz)
    chosen: list[datetime] = []
    for s in sorted(slots):
        local = s.astimezone(zone)
        if any(c.astimezone(zone).date() == local.date() for c in chosen):
            continue
        if chosen and (chosen[-1].astimezone(zone).hour < 13) == (local.hour < 13):
            continue  # alternate morning / afternoon
        chosen.append(s)
        if len(chosen) == n:
            return chosen
    for s in sorted(slots):  # not enough variety: fill with whatever is earliest
        if s not in chosen:
            chosen.append(s)
        if len(chosen) == n:
            break
    return sorted(chosen)


class CalendlyCalendar:
    base = "https://api.calendly.com"

    def __init__(self, token: str, event_type_uri: str):
        self.event_type = event_type_uri
        # 8 s at most per request: this runs while the caller waits on the line
        self.client = httpx.AsyncClient(base_url=self.base, timeout=httpx.Timeout(8.0, connect=3.0),
                                        headers={"Authorization": f"Bearer {token}"})

    async def _request(self, method: str, url: str, **kw) -> httpx.Response:
        """Network failures and timeouts become CalendarError, so the tools' spoken fallbacks apply (they used to
        escape as raw httpx errors and reach the model as "an internal error occurred")."""
        try:
            return await self.client.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise CalendarError(f"Calendly {method} {url}: {type(e).__name__}") from e

    async def free_slots(self, after: datetime, before: datetime) -> list[datetime]:
        r = await self._request("GET", "/event_type_available_times", params={
            "event_type": self.event_type,
            "start_time": after.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end_time": before.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")})
        if r.status_code != 200:
            raise CalendarError(f"Calendly availability {r.status_code}: {r.text[:200]}")
        out = []
        for item in r.json().get("collection", []):
            if item.get("status", "available") == "available":
                out.append(datetime.fromisoformat(item["start_time"].replace("Z", "+00:00")))
        return out

    async def book(self, start: datetime, *, name: str, email: str, tz: str, call_ref: str) -> Booking:
        s = settings()
        r = await self._request("POST", "/invitees", json={
            "event_type": self.event_type,
            "start_time": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "invitee": {"name": name, "email": email, "timezone": tz},
            "tracking": {"utm_source": "ai_sdr", "utm_medium": "phone",
                         "utm_campaign": s.utm_campaign, "utm_content": call_ref}})
        if r.status_code not in (200, 201):
            raise CalendarError(f"Calendly booking {r.status_code}: {r.text[:200]}")
        res = r.json().get("resource", r.json())
        return Booking(start=start, reference=res.get("event") or res.get("uri") or "",
                       reschedule_url=res.get("reschedule_url"))

    async def cancel(self, reference: str, reason: str) -> None:
        """reference = the scheduled-event URI from book(). Untested against a live account."""
        r = await self._request("POST", f"{reference}/cancellation", json={"reason": reason})
        if r.status_code not in (200, 201):
            raise CalendarError(f"Calendly cancel {r.status_code}: {r.text[:200]}")


class FakeCalendar:
    """Demo/test calendar: 30-minute slots Monday to Saturday inside MEETING_HOURS (no holidays); bookings kept in
    memory. Real availability comes from Calendly."""

    def __init__(self, tz: str = "Europe/Rome"):
        self.tz = tz
        self.booked: list[Booking] = []

    async def free_slots(self, after: datetime, before: datetime) -> list[datetime]:
        from ..holidays_it import is_holiday
        s, zone = settings(), ZoneInfo(self.tz)
        slots, day = [], after.astimezone(zone).date()
        while datetime.combine(day, datetime.min.time(), tzinfo=zone) < before:
            if day.weekday() in s.meeting_weekdays and not is_holiday(day):
                for start, end in s.meeting_hours:
                    t = datetime.combine(day, start, tzinfo=zone)
                    while t + timedelta(minutes=30) <= datetime.combine(day, end, tzinfo=zone):
                        if after <= t < before and all(b.start != t for b in self.booked):
                            slots.append(t.astimezone(timezone.utc))
                        t += timedelta(minutes=30)
            day += timedelta(days=1)
        return slots

    async def book(self, start: datetime, *, name: str, email: str, tz: str, call_ref: str) -> Booking:
        b = Booking(start=start, reference=f"fake-{call_ref}-{int(start.timestamp())}")
        self.booked.append(b)
        return b

    async def cancel(self, reference: str, reason: str) -> None:
        self.booked = [b for b in self.booked if b.reference != reference]


def get_calendar() -> Calendar:
    s = settings()
    if s.calendar_provider == "calendly":
        if not (s.calendly_token and s.calendly_event_type):
            raise CalendarError("CALENDLY_API_KEY and CALENDLY_EVENT_TYPE_URI are required")
        return CalendlyCalendar(s.calendly_token, s.calendly_event_type)
    return FakeCalendar()
