"""Bad line, handled in code: the same user-approved policy as the 16 Oct worker, on the new foundations.

- Silence: after user_away_timeout (10 s) ask "are you there? I can't hear you", once more 6 s after that line ends,
  wait 6 s, then say we'll get in touch later and close (~30 s).
- One cumulative counter for the whole call: every silence check-in AND every "could you repeat that?" the agent says
  counts as a retry. Past MAX_LINE_RETRIES (5) the code asks ONCE "when would be a good time to call you back?",
  waits 10 s for an answer, and closes politely if none comes.

Changes from 16 Oct (bugs, not policy):
- "the one question has been asked" is now set where the code asks it. It used to be inferred with a regex over
  anything the agent said, so an ordinary "when is a good time to call you back?" armed a trap that hung up a healthy
  call on the next "could you repeat that?".
- Timers belong to the call's scope and the call ends through CallController.end (no stray tasks, no interrupt()
  raising on a line that can't be interrupted).
- Giving up no longer overwrites an outcome already recorded (callback, manual scheduling...).
- The "sorry, could you say that again?" that covers an LLM failure is not counted as a bad line."""
from __future__ import annotations

import asyncio
import logging

from ..config import settings
from .lifecycle import CallController
from .lines import TROUBLE_WORDS, check_ins, line

log = logging.getLogger("ai_sdr.voice")


class LineWatch:
    ANSWER_WAIT_S = 10.0

    def __init__(self, controller: CallController, actions):
        self.c = controller
        self.session = controller.session
        self.actions = actions
        self.lang = controller.language
        self.task: asyncio.Task | None = None
        self.answer_timer: asyncio.Task | None = None
        self.retries = 0          # cumulative for the whole call
        self.silence_step = 0     # check-ins in the current silence; reset by real words
        self.asked_time = False   # the one "when should I call you back?" has been asked
        self._own_lines = {line("recover", self.lang), line("tech_trouble", self.lang)}

    def attach(self) -> None:
        self.session.on("user_state_changed", self._on_user_state)
        self.session.on("user_input_transcribed", self._on_transcript)
        self.session.on("conversation_item_added", self._on_item)

    # ---- events
    def _on_user_state(self, ev) -> None:
        if self.asked_time or self.c.closing:
            return  # after the one question, the answer timer decides
        if ev.new_state == "away" and self.task is None:
            self.task = self.c.scope.spawn(self._check_in(), "line-check-in")
        elif ev.new_state == "speaking" and self.task is not None:
            self.task.cancel()  # they're making sound: the conversation takes it from here
            self.task = None

    def _on_transcript(self, ev) -> None:
        if not ev.is_final or not ev.transcript.strip():
            return
        if self.answer_timer is not None:  # any reply to "when should I call you back?" goes to the agent
            self.answer_timer.cancel()
            self.answer_timer = None
        if len(ev.transcript.split()) >= 3:
            self.silence_step = 0  # real words end this silence; the cumulative counter is never reset

    def _on_item(self, ev) -> None:
        item = ev.item
        if getattr(item, "role", None) != "assistant" or self.c.closing:
            return
        text = item.text_content or ""
        if text in self._own_lines or not TROUBLE_WORDS.search(text):
            return
        if self.asked_time:  # still can't hear after the one question: close
            self._give_up()
            return
        self.retries += 1
        self.c.telemetry.event("line_retry", n=self.retries)
        log.info("line trouble retry %s/%s", self.retries, settings().max_line_retries)
        if self.retries > settings().max_line_retries:
            self.c.scope.spawn(self._ask_time_once(), "line-ask-time")

    # ---- actions
    async def _ask_time_once(self) -> None:
        if self.asked_time or self.c.closing:
            return
        self.asked_time = True
        if self.task is not None:
            self.task.cancel()
            self.task = None
        try:
            self.session.interrupt()
        except RuntimeError:  # a line that can't be interrupted is playing: ask right after it
            pass
        self.c.telemetry.event("line_ask_time")
        await self.session.say(line("ask_time", self.lang), add_to_chat_ctx=True)  # waits until spoken
        if not self.c.closing:
            self.answer_timer = self.c.scope.timer(self.ANSWER_WAIT_S, self._give_up, "line-answer-wait")

    async def _check_in(self) -> None:
        s = settings()
        lines = check_ins(self.lang, s.silence_check_ins)
        try:
            while self.silence_step < len(lines) and not self.c.closing:
                said = lines[self.silence_step]
                self.silence_step += 1
                self.c.telemetry.event("line_check_in", n=self.silence_step)
                await self.session.say(said, add_to_chat_ctx=True)  # waits until the line has been spoken
                await asyncio.sleep(s.silence_check_every_s)      # then 6 s of silence after it ends
            self._give_up()
        finally:
            self.task = None

    def _give_up(self) -> None:
        if self.c.closing:
            return
        state = self.actions.state
        if state.disposition in (None, "other"):
            state.disposition = "not_now"
        self.c.telemetry.event("line_give_up", retries=self.retries, silence_step=self.silence_step)
        self.c.scope.spawn(self.actions._event("line_trouble", {"retries": self.retries,
                                                                "silence_step": self.silence_step}),
                           "line-trouble-event", keep_on_close=True)
        self.c.end("line_trouble", line("give_up", self.lang), interrupt=True)
