"""The only place an AgentSession is built. Phone and web calls get exactly the same pipeline."""
from __future__ import annotations

from dataclasses import dataclass

from livekit.agents import AgentSession, inference, tts as lk_tts, vad as lk_vad
from livekit.agents.types import APIConnectOptions
from livekit.agents.voice.agent_session import SessionConnectOptions

from .config import VoiceConfig
from .llm_catalog import CatalogLLM
from .providers import build_llm, build_stt


@dataclass
class BuiltSession:
    session: AgentSession
    turn_detector: inference.TurnDetector   # kept to report which model actually ran (it can fall back mid-call)


def build_session(cfg: VoiceConfig, vad: lk_vad.VAD, *, language: str, tts: lk_tts.TTS,
                  channel: str = "web", llm_choice: CatalogLLM | None = None) -> BuiltSession:
    """language: the one the call starts in. tts: that language's voice (providers.Voices); after a mid-call switch
    the new agent brings its own voice, while speech-to-text, turn detection and the LLM stay with the session.
    llm_choice: a model picked on the Talk page (voice/llm_catalog.py)."""
    # A new turn detector for every call: when it falls back to the local model (cloud error, or one prediction
    # slower than 1 s) it changes its own state, and a shared one would carry that into every later call.
    td = inference.TurnDetector(version=cfg.turn_detector_version,
                                **({"unlikely_threshold": cfg.turn_unlikely_threshold}
                                   if cfg.turn_unlikely_threshold else {}))
    session = AgentSession(
        stt=build_stt(cfg, language),
        llm=build_llm(cfg, llm_choice),
        tts=tts,
        vad=vad,
        turn_handling={
            "turn_detection": td,
            "endpointing": {"mode": cfg.endpointing_mode, "min_delay": cfg.endpointing_min,
                            "max_delay": cfg.endpointing_max},
            "interruption": {"enabled": True, "mode": cfg.interruption_mode,
                             "min_duration": cfg.interruption_min_duration,
                             "min_words": cfg.interruption_min_words,
                             "backchannel_boundary": cfg.backchannel_boundary,
                             "resume_false_interruption": True,
                             "false_interruption_timeout": cfg.false_interruption_timeout},
            "preemptive_generation": {"enabled": cfg.preemptive_generation, "preemptive_tts": cfg.preemptive_tts,
                                      "max_speech_duration": cfg.preemptive_max_speech},
        },
        # web only: on phone calls LiveKit decides per participant (off for outbound SIP, where it would blank the
        # callee's words for the first 3 s of the opener). Passing any value, even None, overrides that.
        **({"aec_warmup_duration": cfg.aec_warmup} if channel == "web" else {}),
        user_away_timeout=cfg.user_away_timeout,
        expressive=cfg.tts_expressive,
        conn_options=SessionConnectOptions(
            stt_conn_options=APIConnectOptions(max_retry=2, retry_interval=0.5, timeout=cfg.stt_timeout),
            tts_conn_options=APIConnectOptions(max_retry=1, retry_interval=0.3, timeout=cfg.tts_timeout),
            max_unrecoverable_errors=cfg.max_unrecoverable_errors,
        ),
    )
    return BuiltSession(session, td)
