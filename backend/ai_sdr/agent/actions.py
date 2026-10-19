"""What the agent's tools actually do. Plain async code, no LiveKit, so it can be tested and reused by evals.

The LLM only chooses *which* action to take; times, eligibility and DNC are enforced here.
conn=None is the browser demo: same rules and same replies, nothing written to the database.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import db
from ..config import settings
from ..integrations.calendar import Calendar, CalendarError
from ..integrations.hubspot import HubSpot
from ..italian import MONTHS_EN, WEEKDAYS_EN, day_phrase, when as when_phrase
from ..timeutil import CallbackError, parse_day, resolve_callback

log = logging.getLogger("ai_sdr.actions")


def _say(it: str, en: str) -> str:
    """Tool results the agent repeats out loud must be in the call's language (instructions may stay Italian)."""
    return en if settings().agent_language == "en" else it

DISPOSITIONS = {"meeting_booked", "manual_scheduling", "callback", "not_now", "not_interested", "not_a_fit",
                "wrong_person", "dnc", "hung_up", "other"}


@dataclass
class CallState:
    call_id: int
    prospect: dict | None
    phone: str | None
    tz: str = "Europe/Rome"
    offered: list[datetime] = field(default_factory=list)
    booked_start: datetime | None = None
    booked_ref: str | None = None
    booked_email: str | None = None
    booked_name: str | None = None
    manual_schedule: dict | None = None   # no slot fitted: what they'd prefer, for the team to book by hand
    callback_at: datetime | None = None
    disposition: str | None = None
    qualification: str | None = None
    qual_reasons: list[str] = field(default_factory=list)
    voicemail: bool = False


class CallActions:
    def __init__(self, conn, state: CallState, calendar: Calendar, hubspot: HubSpot | None = None):
        self.conn = conn
        self.state = state
        self.calendar = calendar
        self.hubspot = hubspot
        self.notify = None  # optional async callback(type, payload): the browser demo shows actions live

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _local(self, dt: datetime) -> datetime:
        return dt.astimezone(ZoneInfo(self.state.tz))

    async def _event(self, type_: str, payload: dict) -> None:
        log.info("call %s %s %s", self.state.call_id, type_, payload)
        if self.notify is not None:
            try:
                await self.notify(type_, payload)
            except Exception:  # the live panel must never break a call
                log.exception("could not notify")
        if self.conn is None:
            return
        try:
            await db.log_event(self.conn, self.state.call_id, type_, payload)
        except Exception:  # logging must never break a live call
            log.exception("could not log event")

    # ----- tools -----

    async def _free_slots(self, day: str | None = None) -> list[datetime]:
        s = settings()
        start = self._now() + timedelta(hours=s.meeting_min_lead_hours)
        if day:
            try:
                wanted = datetime.combine(parse_day(day, self._local(self._now()).date()), time(0),
                                          tzinfo=ZoneInfo(self.state.tz))
                start = max(start, wanted.astimezone(timezone.utc))
            except ValueError:
                pass
        return await self.calendar.free_slots(start, start + timedelta(days=s.meeting_search_days))

    def _week_overview(self, slots: list[datetime]) -> str:
        """'Monday 19 October 09:30-13:00, 14:30-18:00; Tuesday ...' (free ranges per day, local time)."""
        en = settings().agent_language == "en"
        days: dict = {}
        for x in sorted(slots):
            days.setdefault(self._local(x).date(), []).append(self._local(x))
        parts = []
        for d, times in days.items():
            ranges, first, prev = [], times[0], times[0]
            for cur in times[1:] + [None]:
                if cur is not None and cur - prev == timedelta(minutes=30):
                    prev = cur
                    continue
                ranges.append(f"{first:%H:%M}-{(prev + timedelta(minutes=30)):%H:%M}")
                if cur is not None:
                    first = prev = cur
            name = (f"{WEEKDAYS_EN[d.weekday()]} {d.day} {MONTHS_EN[d.month - 1]}" if en else day_phrase(times[0]))
            parts.append(f"{name} ({d:%Y-%m-%d}) {', '.join(ranges)}")
        return "; ".join(parts)

    def _alternatives(self, slots: list[datetime], target: datetime, n: int = 3) -> str:
        near = sorted(slots, key=lambda x: abs((x - target).total_seconds()))[:n]
        now_local = self._local(self._now())
        return "; ".join(when_phrase(self._local(x), now_local) for x in sorted(near))

    async def _resolve_slot(self, day: str, at: str) -> tuple[datetime | None, str | None]:
        """The person's chosen day/time -> a free slot (UTC), or (None, message with the nearest free times)."""
        try:
            d = parse_day(day, self._local(self._now()).date())
            t = time.fromisoformat(at)
        except ValueError:
            return None, _say("Non ho capito il giorno o l'orario: chiedilo di nuovo.",
                              "Couldn't read that day or time: ask again.")
        target = datetime.combine(d, t, tzinfo=ZoneInfo(self.state.tz)).astimezone(timezone.utc)
        slots = await self._free_slots()
        if target in slots:
            return target, None
        if not slots:
            return None, _say("Nessuno slot libero nei prossimi giorni: proponi di far scrivere un collega via email.",
                              "No free slots in the next few days: offer to have a colleague email them.")
        alts = self._alternatives(slots, target)
        return None, _say(f"Quell'orario non è libero. I più vicini liberi: {alts}. Dillo con naturalezza e chiedi "
                          "quale preferisce.",
                          f"That time isn't free. Nearest free times: {alts}. Say so naturally and ask which "
                          "they'd like.")

    async def available_slots(self, day: str | None = None) -> str:
        """The open times across the coming week (Mon-Sat), for the agent to summarise; `day` starts from that day."""
        try:
            slots = await self._free_slots(day)
        except CalendarError as e:
            await self._event("error", {"where": "free_slots", "error": str(e)})
            return _say("Non riesco a vedere il calendario in questo momento. Proponi di far scrivere un collega "
                        "via email.", "Can't see the calendar right now. Offer to have a colleague email them.")
        self.state.offered = slots
        await self._event("tool_call", {"tool": "get_available_slots", "day": day, "free": len(slots)})
        if not slots:
            return _say("Nessuno slot libero nei prossimi giorni. Proponi di far scrivere un collega via email.",
                        "No free slots in the next few days. Offer to have a colleague email them.")
        overview = self._week_overview(slots)
        return _say(f"Orari liberi (ora italiana, slot da 30 minuti): {overview}. Riassumi in una o due frasi in "
                    "modo naturale (per esempio \"da lunedì a sabato, la mattina dalle nove e mezza e il pomeriggio "
                    "dalle due e mezza\"), senza leggere ogni orario, e chiedi che giorno e che ora le va meglio.",
                    f"Free times (Italian time, 30-minute slots): {overview}. Summarise in one or two natural "
                    "sentences (for example \"Monday to Saturday, mornings from half nine and afternoons from half "
                    "two\"), without reading every time, and ask what day and time suits them.")

    def _email(self, said: str = "") -> str | None:
        """The email we already have for this person (we never ask on the call), unless they gave another one."""
        said = (said or "").strip().lower().replace(" ", "")
        if "@" in said and "." in said.split("@")[-1]:
            return said
        on_file = (self.state.prospect or {}).get("email")
        if on_file:
            return on_file
        return "demo@emergent.sh" if self.conn is None else None  # browser demo: nothing on file

    async def book_meeting(self, day: str, at: str, email: str = "", full_name: str = "") -> str:
        email = self._email(email)
        if email is None:
            return _say("Non abbiamo un'email per questa persona: solo in questo caso chiedila e ripetila.",
                        "We have no email for this person: only in this case ask for it and read it back.")
        if self.state.booked_start:
            return _say("C'è già una call prenotata: se vuole cambiare orario usa reschedule_meeting.",
                        "A call is already booked: if they want a different time, use reschedule_meeting.")
        start, problem = await self._resolve_slot(day, at)
        if start is None:
            return problem
        try:
            pr = self.state.prospect or {}
            full_name = full_name or " ".join(x for x in (pr.get("first_name"), pr.get("last_name")) if x) or "Ospite"
            booking = await self.calendar.book(start, name=full_name, email=email, tz=self.state.tz,
                                               call_ref=str(self.state.call_id))
        except CalendarError as e:
            await self._event("error", {"where": "book", "error": str(e)})
            return _say("La prenotazione non è andata a buon fine: richiama get_available_slots e proponi altri "
                        "orari.", "The booking failed: call get_available_slots and offer other times.")
        self.state.booked_start, self.state.booked_ref = booking.start, booking.reference
        self.state.booked_email, self.state.booked_name = email, full_name
        self.state.disposition = "meeting_booked"
        if self.conn is not None:
            await db.update_call(self.conn, self.state.call_id, meeting_start=booking.start,
                                 meeting_ref=booking.reference, disposition="meeting_booked")
        if self.conn is not None and self.state.prospect:
            await self.conn.execute("UPDATE prospects SET email = COALESCE(email, %s) WHERE id = %s",
                                    [email, self.state.prospect["id"]])
        await self._event("tool_call", {"tool": "book_meeting", "start": booking.start.isoformat(),
                                        "ref": booking.reference})
        phrase = when_phrase(self._local(booking.start), self._local(self._now()))
        return _say(f"Prenotato. Conferma così: call fissata {phrase}; l'invito arriva all'email del suo account.",
                    f"Booked. Confirm like this: the call is set for {phrase}; the invite is on its way to the email "
                    "on your account.")

    async def request_manual_scheduling(self, preferred_times: str, email: str = "") -> str:
        """No free time fits: log their preferred times so the team books by hand and emails an invite."""
        email = self._email(email) or ""
        self.state.manual_schedule = {"preferred": preferred_times.strip(), "email": email,
                                      "tz": self.state.tz, "logged_at": self._now().isoformat()}
        if self.state.disposition not in ("dnc", "meeting_booked"):
            self.state.disposition = "manual_scheduling"
        if self.conn is not None:
            await db.update_call(self.conn, self.state.call_id, manual_schedule=self.state.manual_schedule,
                                 disposition=self.state.disposition)
            if self.state.prospect and self.state.prospect.get("id"):
                await self.conn.execute("UPDATE prospects SET email = COALESCE(email, %s) WHERE id = %s",
                                        [email, self.state.prospect["id"]])
        await self._event("tool_call", {"tool": "request_manual_scheduling", **self.state.manual_schedule})
        return _say("Registrato per il team. Di' così: \"Perfetto, lo passo al team: controllano il calendario e le "
                    "mandano un invito via email per uno di quegli orari.\" Non promettere un orario o una data "
                    "precisa.",
                    "Logged for the team. Say: \"Great, I'll pass these to the team: they'll check their calendar and "
                    "email you an invite for one of those times.\" Don't promise a specific time or date.")

    async def cancel_meeting(self, reason: str = "") -> str:
        """They no longer want the call booked earlier in this conversation (after the one question and one nudge)."""
        if not self.state.booked_start:
            return _say("Non c'è nessuna call prenotata da annullare.", "There's no booked call to cancel.")
        ref = self.state.booked_ref
        try:
            if ref:
                await self.calendar.cancel(ref, reason or "cancelled on the call")
        except CalendarError as e:
            await self._event("error", {"where": "cancel_meeting", "error": str(e)})
            return _say("L'annullamento non è riuscito: di' che un collega gliela annullerà via email.",
                        "The cancellation failed: say a colleague will cancel it by email.")
        self.state.booked_start = self.state.booked_ref = None
        self.state.disposition = "not_interested"
        if self.conn is not None:
            await db.update_call(self.conn, self.state.call_id, meeting_start=None, meeting_ref=None,
                                 disposition="not_interested")
        await self._event("tool_call", {"tool": "cancel_meeting", "old_ref": ref, "reason": reason})
        return _say("Annullata. Conferma brevemente che è annullata e che l'invito non vale più, poi chiudi.",
                    "Cancelled. Briefly confirm it's cancelled and the invite no longer stands, then wrap up.")

    async def reschedule_meeting(self, day: str, at: str) -> str:
        """The person changed their mind about the time of the call already booked on this call."""
        if not self.state.booked_start:
            return _say("Non c'è ancora nessuna call prenotata: usa book_meeting.",
                        "Nothing is booked yet: use book_meeting.")
        start, problem = await self._resolve_slot(day, at)
        if start is None:
            return problem
        old_ref = self.state.booked_ref
        try:
            booking = await self.calendar.book(start, name=self.state.booked_name or "Ospite",
                                               email=self.state.booked_email or "", tz=self.state.tz,
                                               call_ref=str(self.state.call_id))
            if old_ref:
                await self.calendar.cancel(old_ref, "rescheduled on the call")
        except CalendarError as e:
            await self._event("error", {"where": "reschedule", "error": str(e)})
            return _say("Lo spostamento non è riuscito: di' che resta l'orario di prima e che un collega la "
                        "ricontatta per spostarlo.", "The change failed: say the earlier time still stands and a "
                        "colleague will be in touch to move it.")
        self.state.booked_start, self.state.booked_ref = booking.start, booking.reference
        if self.conn is not None:
            await db.update_call(self.conn, self.state.call_id, meeting_start=booking.start,
                                 meeting_ref=booking.reference)
        await self._event("tool_call", {"tool": "reschedule_meeting", "start": booking.start.isoformat(),
                                        "old_ref": old_ref, "ref": booking.reference})
        phrase = when_phrase(self._local(booking.start), self._local(self._now()))
        return _say(f"Spostata. Conferma così: fatto, la call ora è {phrase}; le arriva il nuovo invito via email, "
                    "quello vecchio è annullato.",
                    f"Moved. Confirm like this: done, the call is now {phrase}; a new invite is on its way by email "
                    "and the old one is cancelled.")

    async def schedule_callback(self, day: str, at: str) -> str:
        s = settings()
        try:
            when = resolve_callback(day, at, self.state.tz, self._now(), s.callback_hours)
        except CallbackError as e:
            await self._event("tool_call", {"tool": "schedule_callback", "day": day, "at": at, "error": str(e)})
            return f"Errore: {e}"
        pid = self.state.prospect.get("id") if self.state.prospect else None
        if self.conn is None:  # demo: confirm exactly as a real call would, without queueing anything
            self.state.callback_at = when
            self.state.disposition = self.state.disposition or "callback"
            await self._event("tool_call", {"tool": "schedule_callback", "day": day, "at": at, "utc": when.isoformat()})
            phrase = when_phrase(self._local(when), self._local(self._now()))
            return _say(f"Fissato e registrato. Conferma esattamente così: \"Perfetto, allora la richiamo io {phrase}.\"",
                        f"Scheduled and logged. Confirm exactly like this: \"Perfect, I'll call you back {phrase}.\"")
        if pid is None:
            return "Non ho i dati di questa persona: chiedi di scriverci, non posso fissare la richiamata."
        job_id = await db.enqueue_job(self.conn, pid, "callback", when, reason="requested on call", created_by="agent")
        if job_id is None:
            return "Non posso fissare la richiamata per questo contatto."
        self.state.callback_at = when
        self.state.disposition = self.state.disposition or "callback"
        await db.update_call(self.conn, self.state.call_id, callback_at=when)
        await self._event("tool_call", {"tool": "schedule_callback", "day": day, "at": at, "utc": when.isoformat()})
        phrase = when_phrase(self._local(when), self._local(self._now()))
        return _say(f"Fissato e registrato. Conferma esattamente così: \"Perfetto, allora la richiamo io {phrase}.\"",
                    f"Scheduled and logged. Confirm exactly like this: \"Perfect, I'll call you back {phrase}.\"")

    async def cancel_callback(self) -> str:
        """The person first asked for a callback, then changed their mind and wants to talk now."""
        if self.state.callback_at is None:
            return _say("Non c'è nessuna richiamata da annullare: continua la conversazione.",
                        "There is no callback to cancel: carry on the conversation.")
        pid = self.state.prospect.get("id") if self.state.prospect else None
        if self.conn is not None and pid is not None:
            await self.conn.execute(
                """UPDATE call_jobs SET status = 'cancelled', reason = 'changed mind on call', updated_at = now()
                   WHERE prospect_id = %s AND status = 'queued' AND kind = 'callback'""", [pid])
            await db.update_call(self.conn, self.state.call_id, callback_at=None)
        self.state.callback_at = None
        if self.state.disposition == "callback":
            self.state.disposition = None
        await self._event("tool_call", {"tool": "cancel_callback"})
        return _say("Richiamata annullata: continua la conversazione adesso, senza tornarci sopra.",
                    "Callback cancelled: carry on the conversation now, without dwelling on it.")

    async def mark_do_not_call(self, reason: str) -> str:
        self.state.disposition = "dnc"
        if self.conn is None:
            pass
        elif self.state.prospect:
            await db.mark_dnc(self.conn, self.state.prospect["id"], reason or "requested on call")
        elif self.state.phone:
            pid = await db.upsert_prospect(self.conn, {"phone_e164": self.state.phone, "tz": self.state.tz})
            await db.mark_dnc(self.conn, pid, reason or "requested on call (inbound)")
        if self.conn is not None:
            await db.update_call(self.conn, self.state.call_id, disposition="dnc")
        await self._event("tool_call", {"tool": "mark_do_not_call", "reason": reason})
        # HubSpot is updated by post-call (postcall.py, from prospects.dnc), never here: a slow CRM call mid-call
        # held the closing line for up to ~45 s (17 Oct revamp). The DNC flag above is already in our DB.
        return _say("Fatto: non verrà più chiamato. Se ti sei già scusata e hai già salutato, non ripeterlo: chiama "
                    "subito end_call. Altrimenti una sola frase breve di scuse e saluto, poi end_call.",
                    "Done: they will never be called again. If you've already apologised and said goodbye, don't say "
                    "it again: call end_call now. Otherwise one short line of apology and goodbye, then end_call.")

    async def record_qualification(self, score: str, reasons: list[str]) -> str:
        if score not in ("qualified", "maybe", "not_qualified"):
            return "score deve essere qualified, maybe o not_qualified."
        self.state.qualification, self.state.qual_reasons = score, reasons[:6]
        if self.conn is not None:
            await db.update_call(self.conn, self.state.call_id, qualification=score, qual_reasons=reasons[:6])
        await self._event("tool_call", {"tool": "record_qualification", "score": score, "reasons": reasons})
        return "Registrato."

    async def set_disposition(self, disposition: str) -> None:
        if disposition not in DISPOSITIONS:
            disposition = "other"
        # a DNC or a booked meeting is never downgraded by a later, vaguer label
        if self.state.disposition in ("dnc", "meeting_booked"):
            return
        self.state.disposition = disposition
        if self.conn is not None:
            await db.update_call(self.conn, self.state.call_id, disposition=disposition)
