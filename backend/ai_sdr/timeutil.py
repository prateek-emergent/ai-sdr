"""Calling-time rules, all done in code (never by the LLM).

- Business-hours gate in the prospect's timezone, skipping weekends and Italian holidays.
- Exact callbacks ("call me tomorrow at 11"): validated and stored as UTC + timezone.
- Retry spacing after no-answer / busy / voicemail / "not now".
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .holidays_it import is_holiday

Window = tuple[time, time]


class CallbackError(ValueError):
    """Raised with an Italian, speakable reason the agent can relay."""


def _local(dt: datetime, tz: str) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return dt.astimezone(ZoneInfo(tz))


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and not is_holiday(d)


def in_business_hours(dt: datetime, tz: str, windows: list[Window]) -> bool:
    local = _local(dt, tz)
    if not is_working_day(local.date()):
        return False
    t = local.time()
    return any(start <= t < end for start, end in windows)


def next_business_time(dt: datetime, tz: str, windows: list[Window]) -> datetime:
    """dt itself if it is callable, otherwise the start of the next calling window (returned in UTC)."""
    if in_business_hours(dt, tz, windows):
        return dt.astimezone(timezone.utc)
    zone = ZoneInfo(tz)
    local = _local(dt, tz)
    day = local.date()
    for _ in range(30):
        if is_working_day(day):
            for start, end in sorted(windows):
                candidate = datetime.combine(day, start, tzinfo=zone)
                if candidate > local:
                    return candidate.astimezone(timezone.utc)
        day += timedelta(days=1)
    raise RuntimeError("no calling window found in the next 30 days")


def add_business_days(dt: datetime, tz: str, days: int) -> date:
    d = _local(dt, tz).date()
    added = 0
    while added < days:
        d += timedelta(days=1)
        if is_working_day(d):
            added += 1
    return d


def retry_time(now: datetime, tz: str, windows: list[Window], attempt: int, reason: str) -> datetime:
    """When to try again.

    reason: 'no_answer' | 'busy' | 'voicemail' | 'failed' -> next business day, alternating morning/afternoon
            'not_now'                                      -> +2 business days, then +5
    attempt: number of attempts already made (1 after the first call).
    """
    zone = ZoneInfo(tz)
    if reason == "not_now":
        day = add_business_days(now, tz, 2 if attempt <= 1 else 5)
    else:
        day = add_business_days(now, tz, 1)
    # alternate time of day: odd attempts -> afternoon window, even -> morning window
    ordered = sorted(windows)
    start, end = ordered[-1] if attempt % 2 == 1 else ordered[0]
    mid = (datetime.combine(day, start) + (datetime.combine(day, end) - datetime.combine(day, start)) / 3).time()
    candidate = datetime.combine(day, mid, tzinfo=zone)
    return next_business_time(candidate, tz, windows)


_WEEKDAY_WORDS = {
    "monday": 0, "lunedi": 0, "tuesday": 1, "martedi": 1, "wednesday": 2, "mercoledi": 2, "thursday": 3,
    "giovedi": 3, "friday": 4, "venerdi": 4, "saturday": 5, "sabato": 5, "sunday": 6, "domenica": 6}
_RELATIVE_WORDS = {"today": 0, "oggi": 0, "tomorrow": 1, "domani": 1, "day after tomorrow": 2, "dopodomani": 2}


def parse_day(day: str, today: date) -> date:
    """'2026-10-19', 'monday', 'lunedì prossimo', 'tomorrow', 'domani' -> a date. Weekdays mean the next one
    after today. Done in code because the LLM miscounted dates (eval 2026-10-16: "Monday" became a Wednesday)."""
    text = day.strip().lower()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    plain = (text.replace("ì", "i").replace("è", "e").replace("é", "e").replace("next ", "")
             .replace(" prossimo", "").replace(" prossima", "").replace("this ", "").strip())
    if plain in _RELATIVE_WORDS:
        return today + timedelta(days=_RELATIVE_WORDS[plain])
    if plain in _WEEKDAY_WORDS:
        ahead = (_WEEKDAY_WORDS[plain] - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    raise ValueError(day)


def resolve_callback(day: str, at: str, tz: str, now: datetime, callback_hours: Window,
                     max_days: int = 30) -> datetime:
    """Validate a callback the prospect asked for. day='YYYY-MM-DD', at='HH:MM' (prospect's local time).

    Explicit requests are honoured outside normal business hours, but only Mon–Sat within callback_hours,
    not on holidays, at least 5 minutes ahead and at most max_days ahead. Returns UTC.
    """
    zone = ZoneInfo(tz)
    try:
        d = parse_day(day, _local(now, tz).date())
        t = time.fromisoformat(at)
    except ValueError as exc:
        raise CallbackError("Non ho capito bene il giorno o l'orario.") from exc
    when = datetime.combine(d, t, tzinfo=zone)
    local_now = _local(now, tz)
    if when < local_now + timedelta(minutes=5):
        raise CallbackError("Quell'orario è già passato o troppo vicino: possiamo scegliere un altro momento?")
    if when > local_now + timedelta(days=max_days):
        raise CallbackError(f"Posso fissare richiamate solo entro {max_days} giorni.")
    if d.weekday() == 6 or is_holiday(d):
        raise CallbackError("Quel giorno è festivo: preferisce un altro giorno?")
    start, end = callback_hours
    if not (start <= t <= end):
        raise CallbackError(f"Posso richiamare tra le {start:%H:%M} e le {end:%H:%M}: va bene un altro orario?")
    return when.astimezone(timezone.utc)
