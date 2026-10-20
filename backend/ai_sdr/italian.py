"""Italian date/time wording for read-backs ("giovedì 16 ottobre alle 11:00")."""
from __future__ import annotations

from datetime import datetime

WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
          "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def day_phrase(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]} {dt.day} {MONTHS[dt.month - 1]}"


def time_phrase(dt: datetime) -> str:
    # "alle 11:00", but "all'una" / "alle 13:00" is fine on a phone line: keep digits, they read naturally
    return f"alle {dt:%H:%M}"


def when_phrase(dt: datetime, now: datetime | None = None) -> str:
    """'oggi alle 15:00', 'domani, venerdì 16 ottobre, alle 11:00', or 'lunedì 19 ottobre alle 10:30'.

    Both datetimes must already be in the prospect's timezone.
    """
    if now is not None:
        delta = (dt.date() - now.date()).days
        if delta == 0:
            return f"oggi {time_phrase(dt)}"
        if delta == 1:
            return f"domani, {day_phrase(dt)}, {time_phrase(dt)}"
    return f"{day_phrase(dt)} {time_phrase(dt)}"


def _next_days(now: datetime, n: int = 14) -> list[datetime]:
    from datetime import timedelta
    return [now + timedelta(days=i) for i in range(1, n + 1)]


def today_line(now: datetime) -> str:
    """Context line for the prompt so the LLM can resolve 'domani', 'lunedì prossimo', etc. The day list means the
    model never has to count dates itself (eval 2026-10-16: it turned "Monday" into a Wednesday)."""
    days = "; ".join(f"{day_phrase(d)} = {d:%Y-%m-%d}" for d in _next_days(now))
    return (f"Oggi è {day_phrase(now)} {now.year} ({now:%Y-%m-%d}), ore {now:%H:%M} (fuso orario {now.tzinfo}). "
            f"Prossimi giorni: {days}.")


# English wording, for demos run with AGENT_LANGUAGE=en (the team can't judge Italian yet).
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]


def when_phrase_en(dt: datetime, now: datetime | None = None) -> str:
    """'today at 15:00', 'tomorrow, Friday 16 October, at 11:00', or 'Monday 19 October at 10:30'."""
    day = f"{WEEKDAYS_EN[dt.weekday()]} {dt.day} {MONTHS_EN[dt.month - 1]}"
    if now is not None:
        delta = (dt.date() - now.date()).days
        if delta == 0:
            return f"today at {dt:%H:%M}"
        if delta == 1:
            return f"tomorrow, {day}, at {dt:%H:%M}"
    return f"{day} at {dt:%H:%M}"


def today_line_en(now: datetime) -> str:
    days = "; ".join(f"{WEEKDAYS_EN[d.weekday()]} {d.day} {MONTHS_EN[d.month - 1]} = {d:%Y-%m-%d}"
                     for d in _next_days(now))
    return (f"Today is {WEEKDAYS_EN[now.weekday()]} {now.day} {MONTHS_EN[now.month - 1]} {now.year} "
            f"({now:%Y-%m-%d}), {now:%H:%M} (time zone {now.tzinfo}). Next days: {days}.")


def when(dt: datetime, now: datetime | None = None, language: str | None = None) -> str:
    """Read-back wording in the call's language (default: the agent's default language)."""
    if language is None:
        from .config import settings
        language = settings().agent_language
    return when_phrase_en(dt, now) if language == "en" else when_phrase(dt, now)


HOURS_IT = ["mezzanotte", "l'una", "le due", "le tre", "le quattro", "le cinque", "le sei", "le sette", "le otto",
            "le nove", "le dieci", "le undici", "mezzogiorno"]
HOURS_EN = ["midnight", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "noon"]


def spoken_slot(dt: datetime, now: datetime, language: str) -> str:
    """A slot the way a person offers it on the phone (21 Oct research: weekday names, no digits, "del pomeriggio" for
    afternoons): 'giovedì alle dieci', 'domani alle due e mezza del pomeriggio', 'Thursday at ten'. Both datetimes in
    the prospect's time zone."""
    delta = (dt.date() - now.date()).days
    h12, half = dt.hour % 12 or 12, dt.minute >= 30
    if language == "en":
        day = "tomorrow" if delta == 1 else f"next {WEEKDAYS_EN[dt.weekday()]}" if delta >= 7 else WEEKDAYS_EN[dt.weekday()]
        hour = "noon" if dt.hour == 12 and not half else HOURS_EN[h12]
        at = f"at {hour}" + (" thirty" if half else "")
        return f"{day} {at}" + (" in the afternoon" if 13 <= dt.hour < 19 else "")
    day = "domani" if delta == 1 else f"{WEEKDAYS[dt.weekday()]} prossimo" if delta >= 7 else WEEKDAYS[dt.weekday()]
    if dt.hour == 12:
        at = "a mezzogiorno" + (" e mezza" if half else "")
    else:
        name = HOURS_IT[h12]
        at = ("all'" + name[2:] if name.startswith("l'") else "al" + name) + (" e mezza" if half else "")
    return f"{day} {at}" + (" del pomeriggio" if 13 <= dt.hour < 19 else "")


def month_year(dt, language: str) -> str:
    """'marzo 2026' / 'March 2026' (for "customer since ...")."""
    return f"{(MONTHS_EN if language == 'en' else MONTHS)[dt.month - 1]} {dt.year}"


def day_month(dt, language: str) -> str:
    """'29 settembre' / '29 September'."""
    return f"{dt.day} {(MONTHS_EN if language == 'en' else MONTHS)[dt.month - 1]}"
