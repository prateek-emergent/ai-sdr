"""21 Oct experiments: two concrete slots, worded for the phone (italian.spoken_slot, actions SLOT_OFFER=two)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ai_sdr.italian import spoken_slot

ROME = ZoneInfo("Europe/Rome")
NOW = datetime(2026, 10, 21, 11, 0, tzinfo=ROME)   # a Wednesday


@pytest.mark.parametrize("dt, it, en", [
    (datetime(2026, 10, 22, 10, 0, tzinfo=ROME), "domani alle dieci", "tomorrow at ten"),
    (datetime(2026, 10, 23, 15, 0, tzinfo=ROME), "venerdì alle tre del pomeriggio", "Friday at three in the afternoon"),
    (datetime(2026, 10, 24, 9, 30, tzinfo=ROME), "sabato alle nove e mezza", "Saturday at nine thirty"),
    (datetime(2026, 10, 26, 12, 0, tzinfo=ROME), "lunedì a mezzogiorno", "Monday at noon"),
    (datetime(2026, 10, 27, 13, 0, tzinfo=ROME), "martedì all'una del pomeriggio", "Tuesday at one in the afternoon"),
    (datetime(2026, 10, 28, 11, 30, tzinfo=ROME), "mercoledì prossimo alle undici e mezza", "next Wednesday at eleven thirty"),
])
def test_spoken_slot(dt, it, en):
    assert spoken_slot(dt, NOW, "it") == it
    assert spoken_slot(dt, NOW, "en") == en
