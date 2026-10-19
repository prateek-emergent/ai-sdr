"""What we know about the person before the call, split into what Giulia may say and what only steers her (decided
20 Oct, after 1,016 Nooks conversations: half the "no"s came at the opener, 13% reached the wrong person or someone
who didn't recognise Emergent, and openers pitched as if to a stranger failed 16 times in 24).

- say aloud: name, customer since, plan, the apps they built (and whether they're live), when we last spoke. Naming
  their app early shows we know them and checks we have the right person.
- background, never said: active / paused / lapsed, value, credit situation, why we picked them, the last call's
  outcome, a meeting already booked, open support issues. Only words, never amounts: personalisation, not
  surveillance.

Read fresh from HubSpot at dial time (balances and activity change daily), from the prospect row (CSV import) when
there's no HubSpot match, or from the web demo's form."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from ..italian import day_month, month_year

log = logging.getLogger("ai_sdr.card")

CARD_PROPS = ["firstname", "lastname", "company", "sales_country", "sales_current_plan", "sales_acq_date",
              "sales_last_active_date", "sales_last_payment_date", "ltv", "sales_topup_60d_usd", "sales_ecu_15d",
              "sales_ecu_balance", "sales_segment", "sales_priority_tier", "sales_why_now", "notes_last_contacted",
              "do_not_touch", "app_name", "deploy_name", "deployed_url", "ob_what_they_built", "build_goal",
              "ob_meeting_booked_at"]
CALL_PROPS = ["hs_timestamp", "hs_call_title"]
TICKET_PROPS = ["subject", "closed_date"]

# prospect-row context keys (CSV import) that describe what they built: safe to say aloud
APP_KEYS = ("app_name", "what_they_built", "project", "app")

PLANS = {"monthly_standard": ("Standard, monthly", "Standard mensile"),
         "annual_standard": ("Standard, annual", "Standard annuale"),
         "monthly_pro": ("Pro, monthly", "Pro mensile"), "annual_pro": ("Pro, annual", "Pro annuale"),
         "starter": ("Starter", "Starter"), "pro_lite": ("Pro Lite", "Pro Lite")}

# sales_segment / the label of sales_why_now -> why we're calling them (en, it)
WHY = [("fde", ("very heavy use on one project, may need engineering help",
                "uso molto intenso su un progetto, potrebbe servire supporto tecnico")),
       ("ltv_ge_", ("one of our highest-value customers", "tra i clienti di maggior valore")),
       ("high-value", ("high-value customer", "cliente di alto valore")),
       ("top_500", ("one of our top 500 customers", "tra i nostri 500 clienti principali")),
       ("annual_pro", ("good fit for an annual Pro plan", "adatto a un piano Pro annuale")),
       ("annual pro", ("good fit for an annual Pro plan", "adatto a un piano Pro annuale")),
       ("agency", ("agency building for clients", "agenzia che costruisce per i clienti")),
       ("bulk", ("buys credits in bulk", "compra crediti in quantità")),
       ("topup", ("recent signup who already topped up", "iscritto da poco che ha già ricaricato")),
       ("mof_", ("mid-spend customer", "cliente con spesa media")),
       ("signed_never_paid", ("signed up, never paid", "iscritto, non ha mai pagato")),
       ("signed_init", ("signed up, never paid", "iscritto, non ha mai pagato")),
       ("plg", ("self-serve subscriber", "abbonato in autonomia"))]

_EMAIL = re.compile(r"\S+@\S+")
_URL = re.compile(r"https?://\S+|www\.\S+")
_PHONE = re.compile(r"\+?\d[\d ().-]{6,}\d")


def _clean(text, limit: int = 80) -> str | None:
    """Free text that may reach the prompt: no emails, links or phone numbers, short."""
    if not text:
        return None
    s = _PHONE.sub("", _URL.sub("", _EMAIL.sub("", str(text))))
    s = re.sub(r"\s+", " ", s).strip(" -;,.")
    return (s[:limit].rsplit(" ", 1)[0] + "…" if len(s) > limit else s) or None


def _speakable(name) -> str | None:
    """An app name the voice can say: "my-crm_v2" -> "my crm v2"."""
    s = _clean(name, 40)
    return re.sub(r"[_\-]+", " ", s).strip() if s else None


def _date(value) -> date | None:
    """HubSpot dates: 'YYYY-MM-DD', ISO datetimes, or epoch milliseconds."""
    if value in (None, ""):
        return None
    s = str(value).strip()
    try:
        if s.isdigit():
            return datetime.fromtimestamp(int(s) / 1000, tz=timezone.utc).date()
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _num(value) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@dataclass
class App:
    name: str
    what: str | None = None
    live: bool = False


@dataclass
class CustomerCard:
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    country: str | None = None
    plan: str | None = None
    customer_since: date | None = None
    apps: list[App] = field(default_factory=list)
    last_active: date | None = None
    last_payment: date | None = None
    ltv: float | None = None
    topup_60d: float | None = None
    credits_15d: float | None = None
    credit_balance: float | None = None
    segment: str | None = None
    priority: str | None = None
    why_now: str | None = None
    last_contacted: date | None = None
    last_call_outcome: str | None = None
    meeting_booked: date | None = None
    do_not_touch: bool = False
    open_tickets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # other background facts (CSV context), already cleaned
    callback: bool = False                           # this call is the callback they asked for

    # ---- building
    @classmethod
    def from_hubspot(cls, props: dict, calls: list[dict] | None = None,
                     tickets: list[dict] | None = None) -> "CustomerCard":
        p = props or {}
        apps = []
        for key in ("app_name", "deploy_name"):
            name = _speakable(p.get(key))
            if name and all(a.name.lower() != name.lower() for a in apps):
                apps.append(App(name=name, what=_clean(p.get("ob_what_they_built") or p.get("build_goal")),
                                live=bool(p.get("deployed_url"))))
        if not apps and (p.get("ob_what_they_built") or p.get("build_goal")):
            what = _clean(p.get("ob_what_they_built") or p.get("build_goal"), 60)
            apps.append(App(name=what, live=bool(p.get("deployed_url"))))
        outcome = None
        dated = sorted((c for c in calls or [] if c.get("hs_timestamp")), key=lambda c: str(c["hs_timestamp"]))
        if dated:
            outcome = _call_outcome(dated[-1].get("hs_call_title"))
        return cls(
            first_name=_clean(p.get("firstname"), 40), last_name=_clean(p.get("lastname"), 40),
            company=_clean(p.get("company"), 60), country=_clean(p.get("sales_country"), 40),
            plan=(p.get("sales_current_plan") or None), customer_since=_date(p.get("sales_acq_date")), apps=apps,
            last_active=_date(p.get("sales_last_active_date")), last_payment=_date(p.get("sales_last_payment_date")),
            ltv=_num(p.get("ltv")), topup_60d=_num(p.get("sales_topup_60d_usd")),
            credits_15d=_num(p.get("sales_ecu_15d")), credit_balance=_num(p.get("sales_ecu_balance")),
            segment=p.get("sales_segment") or None, priority=p.get("sales_priority_tier") or None,
            why_now=p.get("sales_why_now") or None, last_contacted=_date(p.get("notes_last_contacted")),
            last_call_outcome=outcome, meeting_booked=_date(p.get("ob_meeting_booked_at")),
            do_not_touch=str(p.get("do_not_touch") or "").lower() == "true",
            open_tickets=[t for t in (_clean(x.get("subject"), 60) for x in tickets or [] if not x.get("closed_date"))
                          if t])

    @classmethod
    def from_prospect(cls, prospect: dict | None) -> "CustomerCard":
        """No HubSpot match: the prospect row (CSV import). Context keys about the app are speakable, the rest is
        background."""
        p = prospect or {}
        ctx = p.get("context") or {}
        if isinstance(ctx, str):
            import json
            try:
                ctx = json.loads(ctx)
            except ValueError:
                ctx = {}
        apps = [App(name=n) for n in (_speakable(ctx.get(k)) for k in APP_KEYS) if n][:2]
        notes = [f"{k}: {v}" for k, v in ((k, _clean(v, 80)) for k, v in ctx.items() if k not in APP_KEYS) if v]
        return cls(first_name=_clean(p.get("first_name"), 40), last_name=_clean(p.get("last_name"), 40),
                   company=_clean(p.get("company"), 60), apps=apps, notes=notes[:8])

    @classmethod
    def from_demo(cls, meta: dict) -> "CustomerCard":
        """The web demo's form: a first name and, optionally, an app to talk about."""
        app = _speakable(meta.get("app"))
        return cls(first_name=_clean(meta.get("first_name"), 40), apps=[App(name=app)] if app else [])

    # ---- reading
    def first_app(self) -> str | None:
        return self.apps[0].name if self.apps else None

    def lapsed(self, today: date) -> bool:
        no_plan = (self.plan or "none").lower() in ("none", "")
        return no_plan and (self.last_payment is None or (today - self.last_payment).days > 35)

    def say_aloud(self, lang: str, today: date | None = None) -> str:
        today = today or datetime.now(timezone.utc).date()
        en = lang == "en"
        out = []
        name = " ".join(x for x in (self.first_name, self.last_name) if x)
        if name or self.company:
            out.append(("Name: " if en else "Nome: ") + ", ".join(x for x in (name, self.company) if x))
        if self.customer_since:
            out.append(("Customer since " if en else "Cliente dal ") + month_year(self.customer_since, lang))
        if self.plan and self.plan.lower() in PLANS:
            out.append(("Plan: " if en else "Piano: ") + PLANS[self.plan.lower()][0 if en else 1])
        if self.apps:
            parts = []
            for a in self.apps[:2]:
                extra = [x for x in (a.what if a.what and a.what != a.name else None,
                                     ("live" if en else "online") if a.live else None) if x]
                parts.append(a.name + (f" ({', '.join(extra)})" if extra else ""))
            out.append(("Built with us: " if en else "Ha creato con noi: ") + "; ".join(parts))
        if self.last_contacted and 0 <= (today - self.last_contacted).days <= 120:
            out.append(("We were last in touch on " if en else "Ultimo contatto con noi: il ")
                       + day_month(self.last_contacted, lang))
        if self.callback:
            out.append("This is the callback they asked for." if en else "È la richiamata che aveva chiesto.")
        return "\n".join(f"- {x}" for x in out) or ("- Only their name." if en else "- Solo il nome.")

    def background(self, lang: str, today: date | None = None) -> str:
        today = today or datetime.now(timezone.utc).date()
        en = lang == "en"
        out = []
        status = self._status(today, en)
        if status:
            out.append(("Status: " if en else "Stato: ") + status)
        if self.ltv is not None:
            level = (("high", "alto") if self.ltv >= 1000 else ("medium", "medio") if self.ltv >= 300
                     else ("low", "basso"))
            out.append(("Value to us: " if en else "Valore per noi: ") + level[0 if en else 1])
        credits = self._credits(en)
        if credits:
            out.append(("Credits: " if en else "Crediti: ") + credits)
        why = self._why(en)
        if why:
            out.append(("Why we're calling them: " if en else "Perché la chiamiamo: ") + why)
        if self.priority:
            out.append(("Priority: " if en else "Priorità: ") + self.priority + (" (P1 = highest)" if en else
                                                                               " (P1 = la più alta)"))
        if self.last_call_outcome:
            out.append(("Last call with us: " if en else "Ultima chiamata con noi: ") + self.last_call_outcome)
        if self.meeting_booked and self.meeting_booked >= today:
            out.append(f"A meeting with the team is already booked ({day_month(self.meeting_booked, lang)}): don't "
                       "book another; you may mention it." if en else
                       f"Ha già una call fissata con il team ({day_month(self.meeting_booked, lang)}): non fissarne "
                       "un'altra; puoi citarla.")
        for t in self.open_tickets[:2]:
            out.append(("Open support issue: " if en else "Problema aperto con il supporto: ") + t)
        out.extend(self.notes)
        return "\n".join(f"- {x}" for x in out) or ("- Nothing else." if en else "- Nient'altro.")

    def _status(self, today: date, en: bool) -> str | None:
        if self.lapsed(today) and (self.last_payment or self.plan):
            return "lapsed: no current plan" if en else "non più attivo: nessun piano in corso"
        if self.last_active:
            days = (today - self.last_active).days
            if days <= 14:
                return "active" if en else "attivo"
            if days <= 30:
                return "quiet for a few weeks" if en else "fermo da qualche settimana"
            return "paused for over a month" if en else "fermo da più di un mese"
        if self.credits_15d is not None:
            if self.credits_15d > 0:
                return "active (used credits in the last two weeks)" if en else \
                    "attivo (ha usato crediti nelle ultime due settimane)"
            return "no usage in the last two weeks" if en else "nessun utilizzo nelle ultime due settimane"
        return None

    def _credits(self, en: bool) -> str | None:
        notes = []
        if self.topup_60d is not None and self.topup_60d >= 200:
            notes.append("tops up a lot lately" if en else "ricarica spesso ultimamente")
        elif self.topup_60d:
            notes.append("topped up recently" if en else "ha ricaricato di recente")
        if self.credit_balance is not None and self.credit_balance < 100 and (self.credits_15d or 0) > 0:
            notes.append("balance running low" if en else "saldo quasi esaurito")
        return ", ".join(notes) or None

    def _why(self, en: bool) -> str | None:
        label = (self.why_now or "").split(":")[0].strip().lower()
        for key in (label, (self.segment or "").lower()):
            if not key:
                continue
            for prefix, words in WHY:
                if key.startswith(prefix) or prefix in key:
                    return words[0 if en else 1]
        return (self.segment or "").replace("_", " ") or None


def _call_outcome(title) -> str | None:
    """'[Nooks Call] - Meeting booked - Name - by Rep' -> 'meeting booked' (never names)."""
    if not title:
        return None
    parts = [x.strip() for x in str(title).split(" - ")]
    if len(parts) >= 2 and parts[0].lower().startswith("[nooks"):
        return parts[1].lower()
    m = re.match(r"AI SDR call:\s*(\S+)", str(title))
    return m.group(1).replace("_", " ") if m else None


async def fetch_card(hubspot, prospect: dict | None, *, timeout: float) -> CustomerCard | None:
    """The card from HubSpot (None if HubSpot is off, the contact isn't found, or it takes too long). Never raises:
    a missing card only makes the call less personal."""
    if hubspot is None or not getattr(hubspot, "enabled", False):
        return None
    p = prospect or {}
    try:
        async with asyncio.timeout(timeout):
            contact_id = p.get("hubspot_contact_id") or await hubspot.find_contact(email=p.get("email"),
                                                                                    phone=p.get("phone_e164"))
            if not contact_id:
                return None
            c = await hubspot.get_contact(str(contact_id), CARD_PROPS)
            calls = await hubspot.read_objects("calls", c.get("calls", []), CALL_PROPS)
            tickets = await hubspot.read_objects("tickets", c.get("tickets", []), TICKET_PROPS)
        return CustomerCard.from_hubspot(c.get("properties", {}), calls, tickets)
    except TimeoutError:
        log.warning("customer card: HubSpot took longer than %ss, calling without it", timeout)
    except Exception:
        log.exception("customer card: HubSpot read failed, calling without it")
    return None
