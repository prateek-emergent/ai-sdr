"""Builds the agent's instructions and the fixed opener from the Markdown templates in prompts/, in the call's language
(it | en: a call can start in either and switch mid-call, so nothing here reads a global language)."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import settings
from ..italian import today_line, today_line_en
from .card import CustomerCard

DIR = Path(__file__).parent / "prompts"
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _load(name: str) -> str:
    return _COMMENT.sub("", (DIR / name).read_text()).strip()


def allowed_claims(language: str | None = None) -> str:
    """The approved claims, for the agent's prompt and for the judges that check the agent stayed inside them."""
    return _load(f"claims_{language or settings().agent_language}.md").format(company_name=settings().company_name)


def goodbye_line(now_local: datetime, lang: str) -> str:
    """Closing line that fits the person's time of day (user request 2026-10-16)."""
    h = now_local.hour
    if lang == "en":
        if 5 <= h < 17:
            return "It was nice talking to you. Have a nice day!"
        if 17 <= h < 21:
            return "It was nice talking to you. Have a lovely evening!"
        return "It was nice speaking to you. Good night!"
    if 5 <= h < 17:
        return "È stato un piacere parlare con lei. Buona giornata!"
    if 17 <= h < 21:
        return "È stato un piacere parlare con lei. Buona serata!"
    return "È stato un piacere parlare con lei. Buonanotte!"


def build_instructions(prospect: dict | None, *, language: str, inbound: bool = False, now: datetime | None = None,
                       card: CustomerCard | None = None) -> str:
    """The prompt in `language`. card: what we know about the person (HubSpot, else the prospect row), rendered as
    "say aloud" and "background" (agent/card.py)."""
    s = settings()
    tz = (prospect or {}).get("tz") or "Europe/Rome"
    now_local = (now or datetime.now(ZoneInfo(tz))).astimezone(ZoneInfo(tz))
    card = card or CustomerCard.from_prospect(prospect)
    template = _load(f"inbound_{language}.md" if inbound else f"system_{language}.md")
    recorded = ", and that the call is recorded" if language == "en" else ", e che la chiamata è registrata"
    return template.format(
        persona_name=s.agent_persona_name,
        company_name=s.company_name,
        company_office=s.company_office,
        allowed_claims=allowed_claims(language),
        recording_clause=recorded if s.recording_enabled else "",
        today_line=today_line_en(now_local) if language == "en" else today_line(now_local),
        say_aloud=card.say_aloud(language, now_local.date()),
        background=card.background(language, now_local.date()),
        goodbye=goodbye_line(now_local, language),
    )


def opener(prospect: dict | None, language: str, *, card: CustomerCard | None = None, callback: bool = False) -> str:
    """Said verbatim as soon as the person picks up and greets: AI disclosure first (EU AI Act art. 50). Names the app
    they built when we know it (20 Oct: half the Nooks "no"s came at a generic opener), and a callback they asked for
    is introduced as one instead of as a first call."""
    s = settings()
    first = (card.first_name if card and card.first_name else None) or (prospect or {}).get("first_name")
    app = card.first_app() if card else None
    if language == "en":
        recording = " This call is recorded to improve our service." if s.recording_enabled else ""
        who = "the AI assistant from the founder's office at" if s.persona_variant == "founders_office" \
            else "the AI assistant at"
        hi = f"Hi{' ' + first if first else ''},"
        if callback:
            return (f"{hi} it's {s.agent_persona_name}, {who} {s.company_name}, calling you back as we agreed."
                    f"{recording} Is now still a good time?")
        what = f"the platform you used to build {app}" if app else "the platform you used to build apps with AI"
        return (f"{hi} I'm {s.agent_persona_name}, {who} {s.company_name}, {what}. I'm calling for some quick feedback "
                f"on your experience.{recording} Do you have a couple of minutes?")
    hello = f"Buongiorno {first}," if first else "Buongiorno,"
    recording = " La chiamata è registrata per migliorare il servizio." if s.recording_enabled else ""
    # Say what the company is up front: "Emergent" is often misheard as "emergency" (analysis/SYNTHESIS.md §3).
    who = ("l'assistente AI dell'ufficio del founder di" if s.persona_variant == "founders_office"
           else "l'assistente AI di")
    if callback:
        return (f"{hello} sono {s.agent_persona_name}, {who} {s.company_name}: la richiamo come d'accordo."
                f"{recording} È ancora un buon momento?")
    what = (f"la piattaforma con cui ha creato {app}" if app
            else "la piattaforma che ha usato per creare app con l'intelligenza artificiale")
    return (f"{hello} sono {s.agent_persona_name}, {who} {s.company_name}, {what}. La chiamo per un breve feedback "
            f"sulla sua esperienza.{recording} Ha un paio di minuti?")


def inbound_greeting(language: str) -> str:
    s = settings()
    if language == "en":
        return (f"Hello, this is {s.agent_persona_name}, the AI assistant at {s.company_name}, based in "
                f"{s.company_office}. How can I help?")
    return (f"Buongiorno, risponde {s.agent_persona_name}, l'assistente AI di {s.company_name}, "
            f"con sede a {s.company_office}. Come posso aiutarla?")
