"""Giulia's tools. Names, arguments and descriptions are unchanged from the 16 Oct worker (they are part of the
"intelligence"); only the plumbing changed in the 17 Oct revamp:
- a tool that ends the call asks CallController.end() and raises StopResponse (no reply into a closed room);
- every tool's I/O is time-limited, so a hung calendar or database can't freeze the conversation.

20 Oct: calls are bilingual. switch_language hands the call to a twin agent in the other language (LiveKit's own
handoff: the history carries over, the twin brings that language's prompt and voice; speech-to-text already hears
both). New tool log_support_issue. A filler line plays when a slow calendar step keeps her silent, and the
pronunciation map is applied before the voice."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterable, Awaitable, Callable
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from livekit import rtc
from livekit.agents import Agent, ModelSettings, RunContext, function_tool, llm, stt as lk_stt, tts as lk_tts
from livekit.agents.llm import StopResponse, ToolError

from ..voice import live
from ..voice.lifecycle import CallController
from ..voice.lines import DNC_SAID, GOODBYE_WORDS, line
from ..voice.pronunciation import Pronunciations
from .actions import CallActions
from .prompts import goodbye_line

log = logging.getLogger("ai_sdr.agent")

TOOL_TIMEOUT_S = 15.0   # backstop; the calendar itself gives up after 8 s and answers with its own fallback line

Disposition = Literal["meeting_booked", "manual_scheduling", "callback", "not_now", "not_interested", "not_a_fit",
                      "wrong_person", "dnc", "other"]
Language = Literal["it", "en"]
IssueKind = Literal["bug", "publishing", "billing", "refund", "account", "cancel", "other"]

# what the twin says first after a switch: carry on, in the new language, from where the conversation was
_AFTER_SWITCH = {
    "en": "The person prefers English. Carry on in English from where the conversation was, in one short turn. If "
          "they may not have understood the opener, first say briefly who you are, that you're an AI assistant, and "
          "why you're calling.",
    "it": "La persona preferisce l'italiano. Continua in italiano da dove eravate, con un turno breve. Se potrebbe non "
          "aver capito l'apertura, di' prima in breve chi sei, che sei un'assistente AI e perché chiami.",
}


def _last_agent_text(session) -> str:
    for item in reversed(session.history.items):
        if getattr(item, "type", None) == "message" and item.role == "assistant":
            return item.text_content or ""
    return ""


class SDRAgent(Agent):
    def __init__(self, actions: CallActions, instructions: str, recorder, controller: CallController, *,
                 language: str = "it", instructions_for: Callable[[str], str] | None = None,
                 voices: Callable[[str], lk_tts.TTS] | None = None,
                 pronunciations: dict[str, dict[str, str]] | None = None, filler_delay: float = 0.8,
                 handoff: bool = False, chat_ctx=None, tts: lk_tts.TTS | None = None,
                 hearing: Callable[[str], lk_stt.STT] | None = None, stt: lk_stt.STT | None = None):
        """instructions_for(language) and voices(language) make the twin for switch_language (without them the
        call stays in one language); hearing(language) gives the twin speech-to-text in its language. handoff: this
        agent took over mid-call from its twin."""
        extra = {}
        if chat_ctx is not None:
            extra["chat_ctx"] = chat_ctx
        if tts is not None:   # NOT None-to-disable: only an override when given; otherwise the session's voice
            extra["tts"] = tts
        if stt is not None:   # same: the twin hears in its own language, the first agent uses the session's
            extra["stt"] = stt
        super().__init__(instructions=instructions, **extra)
        self.actions = actions
        self.recorder = recorder
        self.c = controller
        self.language = language
        self._instructions_for = instructions_for
        self._voices = voices
        self._hearing = hearing
        self._pronunciation_tables = pronunciations or {}
        self._say_as = Pronunciations(self._pronunciation_tables.get(language))
        self._filler_delay = filler_delay
        self._handoff = handoff

    async def on_enter(self) -> None:
        if self._handoff:  # the first agent of a call says nothing here: CallController.greet speaks the opener
            self.session.generate_reply(instructions=_AFTER_SWITCH[self.language])

    async def llm_node(self, chat_ctx: llm.ChatContext, tools: list[llm.Tool], model_settings: ModelSettings):
        """The LLM reads a copy of the conversation with mishearings fixed and the call notes attached
        (voice/call_notes.py, 24 Oct). Done here, not in on_user_turn_completed: editing the session's context there
        makes LiveKit throw away the reply it started early (preemptive generation)."""
        notes = self.c.notes
        if notes is not None:
            chat_ctx = notes.apply(chat_ctx, self.language)
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk

    async def tts_node(self, text: AsyncIterable[str], model_settings: ModelSettings) -> AsyncIterable[rtc.AudioFrame]:
        if self._say_as:  # words the voice says wrong, rewritten just before it (voice/pronunciation.py)
            text = self._say_as.stream(text)
        async for frame in Agent.default.tts_node(self, text, model_settings):
            yield frame

    async def _bounded(self, coro):
        name = getattr(coro, "__qualname__", "tool").rsplit(".", 1)[-1]   # CallActions.book_meeting -> book_meeting
        t = time.monotonic()
        try:
            async with asyncio.timeout(TOOL_TIMEOUT_S):
                return await coro
        except TimeoutError:
            log.warning("tool timed out after %ss", TOOL_TIMEOUT_S)
            raise ToolError("That took too long and didn't go through. Tell them a colleague will follow up by "
                            "email.") from None
        finally:   # the Talk page's timing chart shows each step's duration (voice/live.py)
            live.send_soon(self.actions.notify, "timing",
                           {"role": "tool", "tool": name, "took_s": round(time.monotonic() - t, 3)})

    async def _with_filler(self, context: RunContext, filler: str, coro: Awaitable):
        """A slow calendar step (up to 8 s per request, 2-3 requests per booking): if she has been silent for
        filler_delay seconds while it runs, say one short line (LiveKit's RunContext.with_filler: it waits for the
        session to be idle, so it never talks over a "let me check" the model already said). Keyboard typing plays
        while it runs, as when a person looks something up (voice/texture.py)."""
        typing = self.c.texture.typing() if self.c.texture else contextlib.nullcontext()
        async with typing, context.with_filler(line(filler, self.c.language), delay=self._filler_delay):
            return await self._bounded(coro)

    @function_tool()
    async def get_available_slots(self, context: RunContext, day: str | None = None) -> str:
        """Get the free times for a call with the team across the coming week (Monday to Saturday). Call this
        before talking about times: never invent them.

        Args:
            day: optional; only if the person asked for a particular day ('monday', 'domani', or YYYY-MM-DD).
        """
        return await self._with_filler(context, "filler_calendar", self.actions.available_slots(day))

    @function_tool()
    async def book_meeting(self, context: RunContext, day: str, at: str, email: str = "", full_name: str = "") -> str:
        """Book the call at the day and time the person chose. Their email and name are already on file: never
        ask for them.

        Args:
            day: the day as they said it ('monday', 'tomorrow', 'lunedì') or YYYY-MM-DD.
            at: the time, HH:MM 24-hour (e.g. 14:30).
            email: leave empty; only if they themselves asked for the invite to go to a different email.
            full_name: leave empty.
        """
        return await self._with_filler(context, "filler_calendar",
                                       self.actions.book_meeting(day, at, email, full_name))

    @function_tool()
    async def request_manual_scheduling(self, context: RunContext, preferred_times: str, email: str = "") -> str:
        """None of the free times work for the person. Record the days and times they'd prefer so the team can
        book it by hand and email them an invite. Only after you've offered the nearest free times.

        Args:
            preferred_times: their preferred days and time windows, in their words (e.g. 'Tuesday or Wednesday
                after 6 pm, or Saturday morning').
            email: leave empty (it's on file); only if they asked for a different email.
        """
        return await self._bounded(self.actions.request_manual_scheduling(preferred_times, email))

    @function_tool()
    async def cancel_meeting(self, context: RunContext, reason: str = "") -> str:
        """Cancel the call you booked earlier in this conversation. Only after asking once what changed and nudging
        once, and they still want it cancelled. Never say it's cancelled unless this succeeded.

        Args:
            reason: their words, briefly.
        """
        return await self._with_filler(context, "filler_update", self.actions.cancel_meeting(reason))

    @function_tool()
    async def reschedule_meeting(self, context: RunContext, day: str, at: str) -> str:
        """The person changed their mind about the time of the call you already booked: move it to the new day
        and time. Say you'll update it, call this, then confirm the new time.

        Args:
            day: the new day as they said it ('monday', 'tomorrow', 'lunedì') or YYYY-MM-DD.
            at: the new time, HH:MM 24-hour.
        """
        return await self._with_filler(context, "filler_update", self.actions.reschedule_meeting(day, at))

    @function_tool()
    async def schedule_callback(self, context: RunContext, day: str, at: str) -> str:
        """Schedule a callback at the exact time the person asked for, in their local time.

        Args:
            day: the day exactly as the person said it, e.g. 'monday', 'tomorrow', 'lunedì', 'domani'; use YYYY-MM-DD only if they named a calendar date.
            at: the local time in HH:MM 24-hour format.
        """
        return await self._bounded(self.actions.schedule_callback(day, at))

    @function_tool()
    async def cancel_callback(self, context: RunContext) -> str:
        """The person asked for a callback earlier in this call but has now changed their mind and wants to talk
        now. Cancels the callback you scheduled."""
        return await self._bounded(self.actions.cancel_callback())

    @function_tool()
    async def mark_do_not_call(self, context: RunContext, reason: str) -> None:
        """The person doesn't want to be called again, or doesn't want to talk about this at all. Call it right away
        and say nothing yourself: the system says the one closing line and ends the call.

        Args:
            reason: their words, briefly.
        """
        await self._bounded(self.actions.mark_do_not_call(reason))
        await self.actions.set_disposition("dnc")
        # one closing line, said by code; skipped if the model already said it in its own words (16 Oct demo: the
        # model said goodbye, called this tool, then said a second and third goodbye)
        await context.wait_for_playout()
        said = DNC_SAID.search(_last_agent_text(context.session))
        self.c.end("dnc", None if said else line("dnc", self.c.language))
        raise StopResponse()

    @function_tool()
    async def record_qualification(self, context: RunContext,
                                   score: Literal["qualified", "maybe", "not_qualified"],
                                   reasons: list[str]) -> str:
        """Record whether this person is a fit for a meeting with our team. Call once, before ending.

        Args:
            score: qualified, maybe or not_qualified.
            reasons: short reasons based on what the person said.
        """
        return await self._bounded(self.actions.record_qualification(score, reasons))

    @function_tool()
    async def log_support_issue(self, context: RunContext, summary: str, kind: IssueKind = "other") -> str:
        """The person has a problem you must not troubleshoot or sell around: a bug, can't publish, billing, a
        refund, getting into their account, or cancelling. Log it for the team, then tell them someone will follow
        up by email.

        Args:
            summary: one line, in their words.
            kind: bug, publishing, billing, refund, account, cancel or other.
        """
        return await self._bounded(self.actions.log_support_issue(summary, kind))

    @function_tool()
    async def switch_language(self, context: RunContext, language: Language):
        """Carry on the call in the other language: "it" (Italian) or "en" (English). Call it straight away,
        without saying anything first, when the person answers in the other language, asks for it, or clearly
        struggles with this one. Not for a single foreign word, a name or a greeting.

        Args:
            language: "it" or "en".
        """
        if language == self.language or language == self.c.language:
            # 21 Oct: the model fired switch_language twice in one turn, and the second result ("you're already
            # speaking Italian") came out as "I'm already speaking Italian" to the caller. A switch in progress (the
            # first call set c.language) or no switch needed: nothing to say about it.
            return self.actions._say("Già fatto: non parlarne, continua normalmente.",
                                     "Already done: don't mention it, just carry on.")
        if self._instructions_for is None or self._voices is None:
            return self.actions._say("In questa chiamata non puoi cambiare lingua: continua in italiano.",
                                     "This call can't switch language: carry on in English.")
        self.c.set_language(language)
        self.actions.state.language = language
        await self.actions._event("language_switch", {"to": language})
        # returning an agent hands the call to it (generation.make_tool_output); a bare agent means the old one says
        # nothing more and the twin speaks first, in its own language and voice (on_enter)
        # the twin also hears in its language: Deepgram listens in one language at a time (20 Oct: "multi" lost the
        # punctuation the turn detector reads, so turns waited the full ENDPOINTING_MAX_S)
        return SDRAgent(self.actions, self._instructions_for(language), self.recorder, self.c, language=language,
                        instructions_for=self._instructions_for, voices=self._voices, hearing=self._hearing,
                        pronunciations=self._pronunciation_tables, filler_delay=self._filler_delay, handoff=True,
                        chat_ctx=self.chat_ctx.copy(exclude_instructions=True), tts=self._voices(language),
                        stt=self._hearing(language) if self._hearing else None)

    @function_tool()
    async def stop_recording(self, context: RunContext) -> str:
        """The person does not want the call recorded. Stop the recording and continue the conversation."""
        await self._bounded(self.recorder.stop())
        return self.actions._say("Registrazione interrotta. Conferma che non stai più registrando e continua.",
                                 "Recording stopped. Confirm you're no longer recording and carry on.")

    @function_tool()
    async def detected_answering_machine(self, context: RunContext) -> str:
        """You reached voicemail or a recorded message. Call immediately; do not leave a message."""
        self.actions.state.voicemail = True
        self.c.end("voicemail")
        raise StopResponse()

    @function_tool()
    async def end_call(self, context: RunContext, disposition: Disposition) -> str:
        """End the call after you have said goodbye.

        Args:
            disposition: how the call ended.
        """
        await self.actions.set_disposition(disposition)
        # let the goodbye finish first (waiting on the tool's own speech handle instead would be a circular wait)
        await context.wait_for_playout()
        said = _last_agent_text(context.session)
        closing = None
        # never hang up without a goodbye: the model sometimes calls end_call silently (16 Oct demo)
        if not GOODBYE_WORDS.search(said):
            now_local = datetime.now(ZoneInfo(self.actions.state.tz))
            thanks = "" if any(w in said.lower() for w in ("thank", "grazie")) else line("thanks", self.c.language)
            closing = thanks + goodbye_line(now_local, self.c.language)
        self.c.end(f"end_call:{disposition}", closing)
        raise StopResponse()
