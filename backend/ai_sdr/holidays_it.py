"""Italian national public holidays (no calls on these days)."""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=32)
def holidays(year: int) -> frozenset[date]:
    fixed = [(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)]
    days = {date(year, m, d) for m, d in fixed}
    days.add(easter_sunday(year) + timedelta(days=1))  # Pasquetta (Easter Monday)
    if year >= 2026:
        days.add(date(year, 10, 4))  # San Francesco, national holiday again from 2026
    return frozenset(days)


def is_holiday(d: date) -> bool:
    return d in holidays(d.year)
