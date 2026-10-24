"""Background coach (24 Oct, "she lacks awareness"): a second, small LLM request that reads the call so far and
writes one steering note for Giulia's NEXT turn (voice/call_notes.py puts it in her call notes).

Never on the spoken path: it starts once Giulia has started speaking (her reply's first audio is already out), runs
while she talks and the caller answers, and is cancelled if a newer turn comes in first. It has its own LLM object,
so its timings stay out of the call's latency metrics. Off unless COACH=1."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from livekit.agents import llm

from .call_notes import CallNotes
from .config import VoiceConfig

log = logging.getLogger("ai_sdr.voice")

TIMEOUT_S = 4.0
MAX_MESSAGES = 14       # the call's recent past is what steering needs
MAX_CHARS = 300         # per message
LANGUAGE_NAME = {"it": "Italian", "en": "English"}

SYSTEM = """You coach Giulia, an AI SDR on a live phone call for Emergent, the platform people use to build apps with AI.
Her one goal: find the caller's biggest blocker or churn risk, and book a short free call with an expert about
exactly that, while staying friendly and never pushy. The caller is an existing Emergent user.

Read the call so far and answer with JSON only, no other text:
{"off_topic_turns": <how many of the caller's latest turns in a row are away from the call's purpose, 0 if on topic>,
 "mood": "calm" | "busy" | "curious" | "positive" | "confused" | "annoyed",
 "signals": [<short labels: leaving, competitor:<name>, pain:<what>, buying signal, support problem>],
 "open_objection": <the pushback she hasn't handled yet, in a few words, or null>,
 "next_step": <one instruction for her next turn, at most 20 words, written in {language}, or "" if she's on track>}

For next_step: a mention of leaving or another tool comes first; if the caller said goodbye, tell her to close in one
sentence; after a clear no to talking, or "don't call me", never suggest pushing; if she's been dragged off-topic,
tell her how to come back to their app or problem in one sentence; if she apologised or folded, tell her to keep calm
and give a reason plus a choice. Describe what to do, never script her exact words. The transcript comes from speech
recognition and may contain mishearings ("emergency" means Emergent)."""


def transcript(items, limit: int = MAX_MESSAGES) -> tuple[str, int]:
    """The recent call as the coach reads it, and how many caller turns there are so far."""
    lines, users = [], 0
    for item in items:
        if getattr(item, "type", None) != "message" or item.role not in ("user", "assistant"):
            continue
        text = (item.text_content or "").strip()
        if not text:
            continue
        if item.role == "user":
            users += 1
        lines.append(f"{'CALLER' if item.role == 'user' else 'GIULIA'}: {text[:MAX_CHARS]}")
    return "\n".join(lines[-limit:]), users


def parse(text: str) -> dict | None:
    """The coach's JSON, tolerating stray text around it; None if there's nothing usable."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    off = data.get("off_topic_turns")
    data["off_topic_turns"] = off if isinstance(off, int) and off >= 0 else 0
    if not isinstance(data.get("next_step"), str):
        data["next_step"] = ""
    return data


def build_llm(cfg: VoiceConfig) -> llm.LLM | None:
    """Same routes as Giulia (LiteLLM first, then the backups), a short reply cap, no prompt cache."""
    from .providers import _one_llm
    models = [_one_llm(route, max_tokens=220) for route in cfg.llm_routes]
    if not models:
        return None
    if len(models) == 1:
        return models[0]
    return llm.FallbackAdapter(models, attempt_timeout=TIMEOUT_S - 1, max_retry_per_llm=0, retry_interval=0.1)


class Coach:
    def __init__(self, cfg: VoiceConfig, notes, controller, model: llm.LLM | None = None):
        self.notes = notes              # voice/call_notes.CallNotes: where the result goes
        self.c = controller             # voice/lifecycle.CallController: session, telemetry, scope, language
        self.model = model or build_llm(cfg)
        self.task: asyncio.Task | None = None
        self.coached = 0                # caller turns already coached

    def attach(self) -> None:
        if self.model is not None:
            self.c.session.on("agent_state_changed", self._on_agent_state)

    def _on_agent_state(self, ev) -> None:
        if ev.new_state != "speaking" or self.c.closing:
            return
        text, users = transcript(self.c.session.history.items)
        if users <= self.coached or users == 0:
            return
        if self.task is not None and not self.task.done():
            self.task.cancel()   # a newer turn: the older read is stale
        self.coached = users
        self.task = self.c.scope.spawn(self._run(text, users, self.c.language), "coach")

    async def _run(self, text: str, users: int, language: str) -> None:
        started = time.monotonic()
        ctx = llm.ChatContext.empty()
        ctx.add_message(role="system", content=SYSTEM.replace("{language}", LANGUAGE_NAME.get(language, "English")))
        ctx.add_message(role="user", content=f"The call so far:\n{text}")
        out, error = "", None
        try:
            async with asyncio.timeout(TIMEOUT_S):
                async with self.model.chat(chat_ctx=ctx) as stream:
                    async for chunk in stream:
                        if chunk.delta is not None and chunk.delta.content:
                            out += chunk.delta.content
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - steering is optional; the call goes on without it
            error = f"{type(e).__name__}: {str(e)[:120]}"
        data = None if error else parse(out)
        if data is not None:
            self.notes.coach, self.notes.coach_turn = data, users
        self.c.telemetry.event("coach", took_s=round(time.monotonic() - started, 3), turn=users,
                               off_topic_turns=(data or {}).get("off_topic_turns"), mood=(data or {}).get("mood"),
                               next_step=((data or {}).get("next_step") or "")[:160],
                               error=error or (None if data else "unparsed"))


def attach_awareness(cfg: VoiceConfig, controller, state) -> None:
    """Call notes on every LLM request, plus the coach when COACH=1: the same for real calls (agent/worker.py) and
    simulated ones (evals/simulate.py)."""
    controller.notes = CallNotes(state, placement=cfg.call_notes)
    if cfg.coach:
        Coach(cfg, controller.notes, controller).attach()
