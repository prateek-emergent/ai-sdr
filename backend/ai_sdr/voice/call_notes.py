"""Call notes: what the call has established so far, added to each LLM request (24 Oct: "she lacks awareness: she
gets dragged off-topic, misses that the caller is switching to Lovable, folds when they're annoyed").

Computed in code, in microseconds, from the conversation, the call state and the background coach's last note
(voice/coach.py). They're added where the LLM request is built (SDRAgent.llm_node) to a COPY of the context:
- the session's own chat context never changes, so LiveKit keeps the reply it started early (preemptive generation
  is thrown away when on_user_turn_completed edits the context: voice/agent_activity.py, 1.8.8);
- they go after the cached prompt (on the caller's last message by default), so Anthropic's prompt cache still
  reads the tools and instructions.
The same copy also fixes known mishearings of the brand ("emergency" -> Emergent) before the model reads them."""
from __future__ import annotations

import re
from dataclasses import dataclass

from livekit.agents import llm

PLACEMENTS = ("user", "system", "off")

# ---- mishearings of "Emergent" (STT, 16-23 Oct: "emergency", "Emojin", "I'm urgent", "emergenza")
_EN_FIXES = (
    # not "an emergency", "emergency room/services/number..." (a real emergency is rare on these calls, but kept)
    (re.compile(r"(?<!\ban )(?<!\bAn )\bemergenc(?:y|ies)\b(?!\s+(?:room|services?|numbers?|exit|contacts?|"
                r"situation|call|vehicle|surgery|care)\b)", re.I), "Emergent"),
    (re.compile(r"\bemo[jg]in\b", re.I), "Emergent"),
    (re.compile(r"\bemerg(?:a|e)nt\b", re.I), "Emergent"),
)
_IT_FIXES = (
    # not "un'emergenza" / "un emergenza" / "in caso di emergenza"
    (re.compile(r"(?<!\bun')(?<!\bun )(?<!\bdi )\bemergenz[ae]\b", re.I), "Emergent"),
    (re.compile(r"\bemo[jg]in\b", re.I), "Emergent"),
)
_PRODUCT_WORDS = re.compile(r"\b(app|apps|platform|credits?|agent|build|building|built|tool|account|project|"
                            r"subscription|plan|piattaforma|crediti|progetto|abbonamento|piano)\b", re.I)
_IM_URGENT = re.compile(r"\bI'?m urgent\b", re.I)


def fix_mishearings(text: str, language: str) -> str:
    """Known mishearings of the brand, corrected the way a human listener would (by context)."""
    if not text:
        return text
    out = text
    for pattern, repl in (_IT_FIXES if language == "it" else _EN_FIXES):
        out = pattern.sub(repl, out)
    if language == "it":   # Italian calls drop English words in too ("lo sto facendo su emergency")
        out = _EN_FIXES[0][0].sub("Emergent", out)
    if _IM_URGENT.search(out) and _PRODUCT_WORDS.search(out):
        out = _IM_URGENT.sub("Emergent", out)
    return out


# ---- signals worth acting on, in the order the prompt ranks them ("What matters most")
# names that are also everyday words ("the cursor", "a bolt") only count when written as names
COMPETITORS = ("Lovable", "Replit", "Base44", "Windsurf", "Claude Code", "Webflow", "Softr", "FlutterFlow")
COMPETITORS_CASED = ("Bolt", "Cursor", "Bubble", "Glide", "Codex", "v0")
_COMPETITOR = re.compile(r"\b((?i:" + "|".join(re.escape(c) for c in COMPETITORS) + r")|"
                         + "|".join(re.escape(c) for c in COMPETITORS_CASED) + r")\b")
_CANONICAL = {c.lower(): c for c in (*COMPETITORS, *COMPETITORS_CASED)}
SIGNALS: tuple[tuple[str, re.Pattern], ...] = (
    # not "switch to Italian", "moving to production"
    ("leaving", re.compile(r"\b(cancel+(?:ing|ed)?|unsubscrib\w*|"
                           r"switch(?:ing|ed)? (?:over )?to (?!english|italian|inglese|italiano)|"
                           r"leav(?:e|ing) (?:emergent|you)|stop(?:ped)? using|not worth|refund|quit(?:ting)?|"
                           r"disdir\w*|passare a (?!inglese|italiano)|sto passando a|rimborso|ho smesso|"
                           r"non ne vale la pena)\b", re.I)),
    ("cost", re.compile(r"\b(too expensive|expensive|costs? (?:too much|a lot)|credits? (?:run|ran|burn|finish|go)|"
                        r"burn(?:ing|s)? (?:through )?credits|troppo car[oi]|costa troppo|costano troppo|"
                        r"crediti (?:finiscono|si consumano|costano))\b", re.I)),
    ("annoyed", re.compile(r"\b(why are you calling|who gave you|how did you get my number|stop calling|annoying|"
                           r"waste of (?:my )?time|not the way you talk|leave me alone|perché mi chiama|"
                           r"chi le ha dato|chi vi ha dato|mi disturba|che fastidio|perdita di tempo)\b",
                re.I)),
    ("busy", re.compile(r"\b(i'?m (?:busy|driving|in a meeting)|call (?:me )?(?:back )?later|not a good time|"
                        r"sto guidando|sono occupat[oa]|sono in riunione|mi richiami|non è il momento)\b", re.I)),
    ("goodbye", re.compile(r"\b(bye|goodbye|gotta go|have to go|talk (?:to you )?later|arrivederci|ciao ciao|"
                           r"devo andare|devo scappare|buona giornata|buona serata)\b", re.I)),
)
_APOLOGY = re.compile(r"\b(sorry|apologi[sz]e|my apologies|scusi|scusa|mi scuso|mi dispiace)\b", re.I)


def signals_in(text: str) -> list[str]:
    """Signals in one caller turn, e.g. ["competitor:Lovable", "leaving"]."""
    found = [f"competitor:{_CANONICAL.get(m.group(1).lower(), m.group(1))}" for m in _COMPETITOR.finditer(text or "")]
    found = list(dict.fromkeys(found))   # one per tool name, in order
    found += [kind for kind, pattern in SIGNALS if pattern.search(text or "")]
    return found


def _text(item) -> str:
    return (item.text_content or "") if getattr(item, "type", None) == "message" else ""


_SAY = {
    "en": {
        "head": "[Call notes: written by your own system from the call so far. The caller didn't say this and "
                "can't see it. Use it, never read it out.]",
        "stage": "Stage: {stage}.",
        "now": "Heard just now: {sig}.",
        "before": "Heard earlier: {sig}.",
        "competitor": "another tool ({name})",
        "leaving": "leaving or cancelling",
        "cost": "cost or credits",
        "annoyed": "annoyed",
        "busy": "busy",
        "goodbye": "goodbye",
        "act_competitor": "This comes first: ask, calm and curious, what's pulling them to {name}.",
        "act_leaving": "This comes first: ask what's making them think of leaving.",
        "act_annoyed": "Keep the call: name it in a few words, one line on why you're calling, then a choice.",
        "act_goodbye": "They're leaving: close in one sentence and end the call. No last questions.",
        "apologies": "You've apologised {n} time(s) already: no more apologies unless you make a new mistake.",
        "coach": "Coach: {note}",
        "offtrack": "Off-topic for {n} turns: answer briefly and come back to their app or problem.",
        "stages": {
            "opener": "their answer to the opener",
            "talk": "conversation (turn {n})",
            "issue": "a support issue is logged; no selling until they say they're happy to carry on",
            "slots": "booking, helping them pick a time",
            "booked": "meeting booked; last feedback question, then close",
            "manual": "the team will book by hand; close",
            "callback": "callback scheduled; say goodbye and end the call",
        },
    },
    "it": {
        "head": "[Note sulla chiamata: le scrive il tuo sistema da quello che è successo finora. La persona non le "
                "ha dette e non le vede. Usale, non leggerle mai ad alta voce.]",
        "stage": "Fase: {stage}.",
        "now": "Appena sentito: {sig}.",
        "before": "Sentito prima: {sig}.",
        "competitor": "un altro strumento ({name})",
        "leaving": "vuole lasciare o disdire",
        "cost": "costi o crediti",
        "annoyed": "fastidio",
        "busy": "ha da fare",
        "goodbye": "sta salutando",
        "act_competitor": "Questo viene prima di tutto: chiedi, calma e curiosa, cosa la attira verso {name}.",
        "act_leaving": "Questo viene prima di tutto: chiedi cosa la fa pensare di lasciare.",
        "act_annoyed": "Tieni la chiamata: dai un nome a come si sente in poche parole, una riga sul perché "
                       "chiami, poi una scelta.",
        "act_goodbye": "Sta chiudendo: saluta in una frase e chiudi la chiamata. Niente ultime domande.",
        "apologies": "Ti sei già scusata {n} volta/e: niente altre scuse se non sbagli qualcosa di nuovo.",
        "coach": "Coach: {note}",
        "offtrack": "Fuori tema da {n} turni: rispondi in breve e torna alla sua app o al suo problema.",
        "stages": {
            "opener": "la risposta all'apertura",
            "talk": "conversazione (turno {n})",
            "issue": "un problema è stato girato al supporto; non proporre niente finché non dice che vuole "
                     "continuare",
            "slots": "prenotazione, la aiuti a scegliere un orario",
            "booked": "call fissata; ultima domanda sul feedback, poi chiudi",
            "manual": "il team fisserà a mano; chiudi",
            "callback": "richiamata fissata; saluta e chiudi la chiamata",
        },
    },
}


@dataclass
class CallNotes:
    """One per call (CallController.notes), shared by Giulia and her twin after a language switch."""
    state: object                       # agent.actions.CallState (duck-typed: booked_start, offered, ...)
    placement: str = "user"             # user | system | off (config.call_notes)
    coach: dict | None = None           # the coach's last read of the call (voice/coach.py)
    coach_turn: int = -1                # the caller turn it was written after

    # ---- what the notes say
    def stage(self, user_turns: int) -> str:
        s = self.state
        if getattr(s, "callback_at", None):
            return "callback"
        if getattr(s, "booked_start", None):
            return "booked"
        if getattr(s, "manual_schedule", None):
            return "manual"
        if getattr(s, "offered", None):
            return "slots"
        if getattr(s, "support_issues", None):
            return "issue"
        return "opener" if user_turns <= 1 else "talk"

    def render(self, ctx: llm.ChatContext, language: str) -> str | None:
        say = _SAY["it" if language == "it" else "en"]
        messages = [i for i in ctx.items if getattr(i, "type", None) == "message"]
        users = [i for i in messages if i.role == "user"]
        if not users:
            return None
        n = len(users)
        now = signals_in(_text(users[-1]))
        before: dict[str, int] = {}
        for idx, item in enumerate(users[:-1], 1):
            for sig in signals_in(_text(item)):
                before.setdefault(sig, idx)
        lines = [say["head"], "- " + say["stage"].format(stage=say["stages"][self.stage(n)].format(n=n))]

        def label(sig: str) -> str:
            kind, _, name = sig.partition(":")
            return say["competitor"].format(name=name) if kind == "competitor" else say.get(kind, kind)

        if now:
            lines.append("- " + say["now"].format(sig=", ".join(label(x) for x in now)))
        earlier = [x for x in before if x not in now and x != "goodbye"]
        if earlier:
            lines.append("- " + say["before"].format(sig=", ".join(label(x) for x in earlier[:4])))
        # what to do about it: the strongest signal of this turn wins (same order as the prompt)
        competitor = next((x.split(":", 1)[1] for x in now if x.startswith("competitor:")), None)
        if "goodbye" in now:
            lines.append("- " + say["act_goodbye"])
        elif competitor:
            lines.append("- " + say["act_competitor"].format(name=competitor))
        elif "leaving" in now:
            lines.append("- " + say["act_leaving"])
        elif "annoyed" in now:
            lines.append("- " + say["act_annoyed"])
        apologies = sum(1 for i in messages if i.role == "assistant" and _APOLOGY.search(_text(i)))
        if apologies:
            lines.append("- " + say["apologies"].format(n=apologies))
        coach = self.coach if self.coach_turn >= n - 2 else None   # stale after two turns
        if coach:
            off = coach.get("off_topic_turns") or 0
            if isinstance(off, int) and off >= 2:
                lines.append("- " + say["offtrack"].format(n=off))
            note = (coach.get("next_step") or "").strip()
            if note:
                lines.append("- " + say["coach"].format(note=note[:200]))
        return "\n".join(lines)

    # ---- the copy the LLM reads
    def apply(self, ctx: llm.ChatContext, language: str) -> llm.ChatContext:
        """A copy with mishearings fixed and the notes attached; `ctx` itself is never changed."""
        out = ctx.copy()
        items = out.items
        for i, item in enumerate(items):
            if getattr(item, "type", None) == "message" and item.role == "user":
                fixed = [fix_mishearings(c, language) if isinstance(c, str) else c for c in item.content]
                if fixed != item.content:
                    items[i] = item.model_copy(update={"content": fixed})
        if self.placement == "off" or not items:
            return out
        last = items[-1]
        if getattr(last, "type", None) != "message" or last.role != "user":
            return out   # a reply after a tool result continues the same turn: the notes were already there
        notes = self.render(out, language)
        if not notes:
            return out
        if self.placement == "system":
            out.add_message(role="system", content=notes)
        else:
            items[-1] = last.model_copy(update={"content": [*last.content, "\n\n" + notes]})
        return out
