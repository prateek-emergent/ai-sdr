"""Giulia's tools. Names, arguments and descriptions are unchanged from the 16 Oct worker (they are part of the
"intelligence"); only the plumbing changed in the 17 Oct revamp:
- a tool that ends the call asks CallController.end() and raises StopResponse (no reply into a closed room);
- every tool's I/O is time-limited, so a hung calendar or database can't freeze the conversation."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from livekit.agents import Agent, RunContext, function_tool
from livekit.agents.llm import StopResponse, ToolError

from ..voice.lifecycle import CallController
from ..voice.lines import DNC_SAID, GOODBYE_WORDS, line
from .actions import CallActions
from .prompts import goodbye_line

log = logging.getLogger("ai_sdr.agent")

TOOL_TIMEOUT_S = 15.0   # backstop; the calendar itself gives up after 8 s and answers with its own fallback line

Disposition = Literal["meeting_booked", "manual_scheduling", "callback", "not_now", "not_interested", "not_a_fit",
                      "wrong_person", "dnc", "other"]


def _last_agent_text(session) -> str:
    for item in reversed(session.history.items):
        if getattr(item, "type", None) == "message" and item.role == "assistant":
            return item.text_content or ""
    return ""


class SDRAgent(Agent):
    def __init__(self, actions: CallActions, instructions: str, recorder, controller: CallController):
        super().__init__(instructions=instructions)
        self.actions = actions
        self.recorder = recorder
        self.c = controller

    async def _bounded(self, coro):
        try:
            async with asyncio.timeout(TOOL_TIMEOUT_S):
                return await coro
        except TimeoutError:
            log.warning("tool timed out after %ss", TOOL_TIMEOUT_S)
            raise ToolError("That took too long and didn't go through. Tell them a colleague will follow up by "
                            "email.") from None

    @function_tool()
    async def get_available_slots(self, context: RunContext, day: str | None = None) -> str:
        """Get the free times for a call with the team across the coming week (Monday to Saturday). Call this
        before talking about times: never invent them.

        Args:
            day: optional; only if the person asked for a particular day ('monday', 'domani', or YYYY-MM-DD).
        """
        return await self._bounded(self.actions.available_slots(day))

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
        return await self._bounded(self.actions.book_meeting(day, at, email, full_name))

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
        return await self._bounded(self.actions.cancel_meeting(reason))

    @function_tool()
    async def reschedule_meeting(self, context: RunContext, day: str, at: str) -> str:
        """The person changed their mind about the time of the call you already booked: move it to the new day
        and time. Say you'll update it, call this, then confirm the new time.

        Args:
            day: the new day as they said it ('monday', 'tomorrow', 'lunedì') or YYYY-MM-DD.
            at: the new time, HH:MM 24-hour.
        """
        return await self._bounded(self.actions.reschedule_meeting(day, at))

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
    async def stop_recording(self, context: RunContext) -> str:
        """The person does not want the call recorded. Stop the recording and continue the conversation."""
        await self._bounded(self.recorder.stop())
        return "Registrazione interrotta. Conferma che non stai più registrando e continua."

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
