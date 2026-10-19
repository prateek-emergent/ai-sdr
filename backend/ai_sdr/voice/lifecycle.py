"""CallController: the call's state and the ONE way a call ends (plan root cause 4: five different hang-up paths,
tasks outliving the call, interrupt() raising mid-give-up, a reply generated into an already-deleted room).

How a call ends, whoever asks (a tool, LineWatch, the duration cap, an LLM that keeps failing):
  end(reason, line) -> state CLOSING (once; later calls are ignored)
                    -> cancel the call's other background tasks
                    -> say the closing line, not interruptible (if any)
                    -> session.shutdown(drain=True): returns at once; the session finishes speaking, then closes,
                       and RoomOptions(delete_room_on_close=True) removes the room, which hangs up the person.
end() never awaits, so tools may call it (waiting for playout inside a tool is a circular wait). Tools that end the
call then raise StopResponse so no further LLM reply is generated.
The session's "close" event is the single place the close reason is recorded, including closes we did not ask for
(the person hung up, or three provider errors in a row)."""
from __future__ import annotations

import enum
import logging

from livekit.agents import AgentSession

from .lines import line
from .scope import CallScope
from .telemetry import CallTelemetry

log = logging.getLogger("ai_sdr.voice")

MAX_LLM_RECOVERIES = 2   # "sorry, could you say that again?" this many times in a row, then close politely
RECOVERY_CHECK_S = 0.4   # after an LLM error, wait this long for a reply to start before covering the silence


class State(str, enum.Enum):
    CONNECTING = "connecting"
    GREETING = "greeting"
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"


class CallController:
    def __init__(self, session: AgentSession, telemetry: CallTelemetry, language: str):
        self.session = session
        self.telemetry = telemetry
        self.language = language
        self.scope = CallScope(on_error=telemetry.task_failed)
        self.state = State.CONNECTING
        self.end_reason: str | None = None
        self.agent_state = "initializing"
        self._llm_failures = 0
        self._recovery_pending = False

    @property
    def closing(self) -> bool:
        return self.state in (State.CLOSING, State.CLOSED)

    def attach(self) -> None:
        self.session.on("close", self._on_close)
        self.session.on("error", self._on_error)
        self.session.on("conversation_item_added", self._on_item)
        self.session.on("agent_state_changed", self._on_agent_state)

    def _on_agent_state(self, ev) -> None:
        self.agent_state = ev.new_state

    def _set(self, state: State) -> None:
        if state != self.state:
            self.telemetry.event("call_state", state=state.value)
            self.state = state

    def greet(self, text: str) -> None:
        """Speak first. Agent audio already waits for the person to be subscribed, so no fixed delay is needed."""
        if self.closing:
            return
        self._set(State.GREETING)
        self.telemetry.event("opener_queued")
        handle = self.session.say(text, allow_interruptions=True)
        handle.add_done_callback(lambda _h: self._set(State.ACTIVE) if self.state == State.GREETING else None)

    def end(self, reason: str, closing_line: str | None = None, *, interrupt: bool = False) -> bool:
        """Close the call (idempotent). Returns False if it was already closing."""
        if self.closing:
            self.telemetry.event("end_ignored", reason=reason, already=self.end_reason)
            return False
        self.end_reason = reason
        self._set(State.CLOSING)
        self.telemetry.event("end", reason=reason, line=bool(closing_line), interrupt=interrupt)
        self.scope.close()
        if interrupt:
            try:
                self.session.interrupt(force=True)
            except RuntimeError:
                pass
        if closing_line:
            try:
                self.session.say(closing_line, allow_interruptions=False, add_to_chat_ctx=True)
            except RuntimeError:  # the session is already closing (e.g. the person hung up first)
                pass
        self.session.shutdown(drain=True)
        return True

    # ---- session events
    def _on_close(self, ev) -> None:
        self.scope.close()
        reason = getattr(ev.reason, "value", str(ev.reason))
        self.telemetry.closed(reason, ev.error, self.end_reason)
        self._set(State.CLOSED)

    def _on_item(self, ev) -> None:
        item = ev.item
        if getattr(item, "role", None) == "assistant" and (item.text_content or "") != line("recover", self.language):
            self._llm_failures = 0  # the model answered: the failure streak is over

    def _on_error(self, ev) -> None:
        """Runs before the session decides whether the error closes the call, so it can keep the call alive.

        An LLM failure (every route) used to mean silence: the reply was dropped and the agent went back to
        listening (17 Oct, local probe). The library reports some of these as "recoverable" (it won't close the
        session) but nothing re-asks the model, so every LLM failure is handled here the same way: if no reply is
        on its way shortly after, say "sorry, could you say that again?"; after MAX_LLM_RECOVERIES in a row, close
        politely."""
        self.telemetry.error(ev)
        err = ev.error
        if self.closing or getattr(err, "type", None) != "llm_error":
            return  # voice and speech-to-text failures: their fallbacks already ran; let the session decide
        err.recoverable = True  # we handle it: no silent close
        if not self._recovery_pending:
            self._recovery_pending = True
            self.scope.timer(RECOVERY_CHECK_S, self._recover_if_silent, "llm-recovery")

    def _recover_if_silent(self) -> None:
        self._recovery_pending = False
        if self.closing:
            return
        speech = getattr(self.session, "current_speech", None)
        if self.agent_state == "speaking" or speech is not None:
            return  # a reply is on its way after all (e.g. only a speculative generation failed)
        self._llm_failures += 1
        if self._llm_failures <= MAX_LLM_RECOVERIES:
            self.telemetry.event("llm_recover", attempt=self._llm_failures)
            try:
                self.session.say(line("recover", self.language), allow_interruptions=True, add_to_chat_ctx=True)
            except RuntimeError:
                pass
        else:
            self.end("llm_failed", line("tech_trouble", self.language))
