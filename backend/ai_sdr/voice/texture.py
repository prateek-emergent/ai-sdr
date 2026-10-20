"""What makes a call sound like a person at a desk instead of a server (20 Oct: the team's main feedback was "it feels
like talking to a bot").

- Room tone: a quiet office ambience under the whole call, and keyboard typing while she looks something up in the
  calendar (a slow tool). Never before ordinary replies: LiveKit's built-in "thinking" sound would type before every
  answer, which no person does.
- Noise cancellation on the caller's audio (LiveKit Cloud's Krisp models: BVC for browsers, BVCTelephony for phone
  lines), so a TV, traffic or a fan doesn't count as the caller talking and cut her off.
- Optionally (LLM_WARM_ON_SPEECH), the LLM connection is reopened when Giulia finishes speaking. The HTTP client
  drops idle connections after 5 s and the LiteLLM proxy drops them sooner still, so replies can pay a fresh TLS
  handshake (20 Oct, from the laptop: first token 0.33 s on a warm connection, 0.85-1.2 s on a new one).
  `LLM.prewarm()` runs once per call, so this calls the provider's warm-up request (a token-free model list) again.
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from livekit import rtc
from livekit.agents import AgentSession, AudioConfig, BackgroundAudioPlayer, BuiltinAudioClip
from livekit.agents import llm as lk_llm
from livekit.agents.voice import room_io

from .config import VoiceConfig
from .scope import CallScope

log = logging.getLogger("ai_sdr.texture")

def room_options(cfg: VoiceConfig, **kwargs) -> room_io.RoomOptions:
    """The session's room options, with noise cancellation on the caller's audio when it is available."""
    selector = _noise_cancellation(cfg)
    if selector is not None:
        # with a selector LiveKit leaves gain control to us; the Krisp models expect it off
        kwargs["audio_input"] = room_io.AudioInputOptions(noise_cancellation=selector, auto_gain_control=False)
    return room_io.RoomOptions(**kwargs)


def _noise_cancellation(cfg: VoiceConfig):
    if cfg.noise_cancellation == "off":
        return None
    try:
        from livekit.plugins import noise_cancellation
    except ImportError:
        log.warning("noise cancellation is on but livekit-plugins-noise-cancellation isn't installed")
        return None

    def pick(params: room_io.NoiseCancellationParams):
        if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
            return noise_cancellation.BVCTelephony()
        return noise_cancellation.BVC()

    return pick


class Texture:
    """The call's background audio (one per call). typing() is a no-op until start() has run, or when it's off."""

    def __init__(self, cfg: VoiceConfig):
        self.cfg = cfg
        self.player: BackgroundAudioPlayer | None = None

    async def start(self, room: rtc.Room, session: AgentSession) -> None:
        """After the room is connected: publishes the background track and starts the room tone."""
        if self.cfg.ambience == "off" and not self.cfg.typing_sound:
            return
        ambient = (AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=self.cfg.ambience_volume, fade_in=1.5)
                   if self.cfg.ambience == "office" else None)
        self.player = BackgroundAudioPlayer(ambient_sound=ambient)
        try:
            await self.player.start(room=room, agent_session=session)
        except Exception:  # the call must go on without it
            log.exception("background audio did not start")
            self.player = None

    @contextlib.asynccontextmanager
    async def typing(self) -> AsyncIterator[None]:
        """Keyboard typing for as long as a slow lookup runs."""
        handle = None
        if self.player is not None and self.cfg.typing_sound:
            try:
                handle = self.player.play(AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=self.cfg.typing_volume,
                                                      fade_in=0.2, fade_out=0.4), loop=True)
            except Exception:
                log.exception("typing sound failed")
        try:
            yield
        finally:
            if handle is not None:
                handle.stop()

    async def aclose(self) -> None:
        if self.player is not None:
            await self.player.aclose()
            self.player = None


def keep_llm_warm(cfg: VoiceConfig, session: AgentSession, scope: CallScope) -> None:
    """Reopen the LLM connection each time Giulia finishes speaking: the caller usually answers within a few seconds,
    so their reply finds a fresh connection, and nothing else is talking to the LLM at that moment. (Warming while
    the caller spoke competed with the early, preemptive request and made replies slower; see config.warm_llm.)"""
    if not cfg.warm_llm:
        return
    model = session.llm
    targets = [m for m in (getattr(model, "_llm_instances", None) or [model])
               if isinstance(m, lk_llm.LLM) and type(m)._prewarm_impl is not lk_llm.LLM._prewarm_impl]
    if not targets:
        return

    async def warm() -> None:
        for m in targets:
            try:
                await m._prewarm_impl()
            except Exception:  # only an optimisation
                pass

    def on_agent_state(ev) -> None:
        if ev.old_state == "speaking" and ev.new_state == "listening":
            scope.spawn(warm(), "llm-warm")

    session.on("agent_state_changed", on_agent_state)
