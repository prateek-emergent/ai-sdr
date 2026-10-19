"""Builds the agent's instructions and the fixed opener from the Markdown templates in prompts/."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import settings
from ..italian import today_line, today_line_en

DIR = Path(__file__).parent / "prompts"
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _load(name: str) -> str:
    return _COMMENT.sub("", (DIR / name).read_text()).strip()


def _en() -> bool:
    return settings().agent_language == "en"


def _prospect_line(p: dict | None) -> str:
    if not p:
        return "unknown number, nothing on file." if _en() else "numero sconosciuto, nessun dato in archivio."
    name = " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x) or (
        "name unknown" if _en() else "nome non noto")
    company = f", {p['company']}" if p.get("company") else ""
    return f"{name}{company}."


def _prospect_context(p: dict | None) -> str:
    ctx = (p or {}).get("context") or {}
    if isinstance(ctx, str):
        ctx = json.loads(ctx)
    if not ctx:
        return "nothing else." if _en() else "nessuna informazione aggiuntiva."
    # keep it short and speakable; never read this back verbatim to the prospect
    return "; ".join(f"{k}: {v}" for k, v in ctx.items() if v not in (None, ""))[:800]


def allowed_claims() -> str:
    """The approved claims, for the agent's prompt and for the judges that check the agent stayed inside them."""
    return _load(f"claims_{settings().agent_language}.md").format(company_name=settings().company_name)


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


def build_instructions(prospect: dict | None, *, inbound: bool = False, now: datetime | None = None) -> str:
    s = settings()
    tz = (prospect or {}).get("tz") or "Europe/Rome"
    now_local = (now or datetime.now(ZoneInfo(tz))).astimezone(ZoneInfo(tz))
    claims = allowed_claims()
    lang = s.agent_language
    template = _load(f"inbound_{lang}.md" if inbound else f"system_{lang}.md")
    return template.format(
        persona_name=s.agent_persona_name,
        company_name=s.company_name,
        company_office=s.company_office,
        allowed_claims=claims,
        recording_clause=(", and that the call is recorded" if lang == "en" else ", e che la chiamata è registrata")
        if s.recording_enabled else "",
        known_email=(prospect or {}).get("email") or ("unknown" if lang == "en" else "non nota"),
        today_line=today_line_en(now_local) if lang == "en" else today_line(now_local),
        prospect_line=_prospect_line(prospect),
        prospect_context=_prospect_context(prospect),
        goodbye=goodbye_line(now_local, lang),
    )


def opener(prospect: dict | None) -> str:
    """Said verbatim as soon as the person picks up and greets: AI disclosure first (EU AI Act art. 50)."""
    s = settings()
    first = (prospect or {}).get("first_name")
    if _en():
        recording = " This call is recorded to improve our service." if s.recording_enabled else ""
        who = "the AI assistant from the founder's office at" if s.persona_variant == "founders_office" \
            else "the AI assistant at"
        return (f"Hi{' ' + first if first else ''}, I'm {s.agent_persona_name}, {who} {s.company_name}, the platform "
                f"you used to build apps with AI. I'm calling for some quick feedback on your experience.{recording} "
                f"Do you have a couple of minutes?")
    hello = f"Buongiorno {first}," if first else "Buongiorno,"
    recording = " La chiamata è registrata per migliorare il servizio." if s.recording_enabled else ""
    # Say what the company is up front: "Emergent" is often misheard as "emergency" (analysis/SYNTHESIS.md §3).
    who = ("l'assistente AI dell'ufficio del founder di" if s.persona_variant == "founders_office"
           else "l'assistente AI di")
    return (f"{hello} sono {s.agent_persona_name}, {who} {s.company_name}, la piattaforma che ha usato per creare "
            f"app con l'intelligenza artificiale. La chiamo per un breve feedback sulla sua esperienza.{recording} "
            f"Ha un paio di minuti?")


def inbound_greeting() -> str:
    s = settings()
    if _en():
        return (f"Hello, this is {s.agent_persona_name}, the AI assistant at {s.company_name}, based in "
                f"{s.company_office}. How can I help?")
    return (f"Buongiorno, risponde {s.agent_persona_name}, l'assistente AI di {s.company_name}, "
            f"con sede a {s.company_office}. Come posso aiutarla?")
