"""Speech-to-text, voice and language model, built from VoiceConfig. Every provider is wrapped so a slow or failed
one is replaced instead of leaving the caller in silence (plan root cause 5)."""
from __future__ import annotations

import httpx
from livekit.agents import NOT_GIVEN, inference, llm, stt, tts
from livekit.plugins import anthropic as lk_anthropic
from livekit.plugins import deepgram, elevenlabs
from livekit.plugins import openai as lk_openai

from ..llm import proxy_url
from .config import LLMRoute, VoiceConfig


def build_stt(cfg: VoiceConfig) -> stt.STT:
    if cfg.stt_provider == "livekit":
        return inference.STT(model=f"deepgram/{cfg.stt_model}", language=cfg.stt_language)
    # keyterms go on the connection URL when it is opened: one Deepgram websocket for the whole call. (Session-level
    # stt_context_options would update a live stream, which reconnects it.) Keyterm prompting is nova-3 only.
    keyterm = list(cfg.stt_keyterms) if cfg.stt_keyterms and cfg.stt_model.startswith("nova-3") else NOT_GIVEN
    return deepgram.STT(model=cfg.stt_model, language=cfg.stt_language, api_key=cfg.deepgram_api_key, keyterm=keyterm)


def _one_tts(cfg: VoiceConfig, name: str) -> tts.TTS:
    if name == "elevenlabs":
        from livekit.agents.tokenize import blingfire
        return elevenlabs.TTS(voice_id=cfg.elevenlabs_voice_id, model=cfg.elevenlabs_model,
                              api_key=cfg.elevenlabs_api_key, language=cfg.language,
                              word_tokenizer=blingfire.SentenceTokenizer(min_sentence_len=cfg.tts_min_sentence_len))
    if name == "deepgram":
        return deepgram.TTS(model=cfg.deepgram_voice, api_key=cfg.deepgram_api_key)
    return inference.TTS(model=cfg.livekit_tts_model, voice=cfg.livekit_tts_voice, language=cfg.language)


ELEVENLABS_MIN_CREDITS = 2000   # below this, calls start on the fallback voice instead of failing mid-call


def elevenlabs_credits_left(api_key: str) -> int | None:
    """Characters left this month on the ElevenLabs account (None if unknown). Checked once per job process,
    before the call (prewarm), so a call never starts on a voice that is about to run out."""
    try:
        r = httpx.get("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": api_key}, timeout=3)
        if r.status_code != 200:
            return None
        d = r.json()
        return int(d["character_limit"]) - int(d["character_count"])
    except Exception:
        return None


def tts_chain_for(cfg: VoiceConfig, requested: list[str] | None,
                  elevenlabs_left: int | None = None) -> tuple[str, ...]:
    """The configured voice chain, or a test call's override (the probe asks for Deepgram so automated runs don't
    spend ElevenLabs credits). An override naming a voice without its key falls back to the configured chain."""
    if not requested:
        chain = cfg.tts_chain
        # nearly out of ElevenLabs credits: start on the next voice (a dead first voice costs ~2.4 s of silence
        # before the fallback speaks, 17 Oct test)
        if elevenlabs_left is not None and elevenlabs_left < ELEVENLABS_MIN_CREDITS and len(chain) > 1:
            chain = tuple(n for n in chain if n != "elevenlabs") or chain
        return chain
    ok = {"deepgram": bool(cfg.deepgram_api_key), "livekit": True,
          "elevenlabs": bool(cfg.elevenlabs_api_key and cfg.elevenlabs_voice_id)}
    chain = tuple(n for n in requested if ok.get(n))
    return chain or cfg.tts_chain


def build_tts(cfg: VoiceConfig, chain: tuple[str, ...] | None = None) -> tts.TTS:
    """One voice, or a chain: if the first fails (error, outage, out of credits) the next one speaks. The adapter
    never switches in the middle of a sentence that has already started playing."""
    voices = [_one_tts(cfg, name) for name in (chain or cfg.tts_chain)]
    if len(voices) == 1:
        return voices[0]
    # no second try at a failing voice mid-call: switch at once (the adapter re-checks it in the background and
    # switches back when it recovers). 17 Oct test: with one retry, a dead ElevenLabs cost 3.2 s of silence.
    return tts.FallbackAdapter(voices, max_retry_per_tts=0)


def _one_llm(route: LLMRoute) -> llm.LLM:
    # the per-attempt time limit comes from the fallback adapter (attempt_timeout); this is only a backstop
    timeout = httpx.Timeout(30.0, connect=5.0)
    if route.name == "litellm":
        return lk_openai.LLM(model=route.model, base_url=route.base_url, api_key=route.api_key, timeout=timeout)
    if route.name == "emergent":  # Emergent universal key: only reachable from Emergent's own servers
        return lk_openai.LLM(model=route.model, base_url=proxy_url() + "/llm", api_key=route.api_key,
                             timeout=timeout)
    return lk_anthropic.LLM(model=route.model, api_key=route.api_key)


def build_llm(cfg: VoiceConfig) -> llm.LLM:
    """Routes in order. A route that sends nothing for attempt_timeout seconds is abandoned for the next one; with a
    single route it is retried once (a fresh request usually answers in about a second: 16 Oct TTFT p50 1.06 s)."""
    models = [_one_llm(r) for r in cfg.llm_routes]
    return llm.FallbackAdapter(models, attempt_timeout=cfg.llm_attempt_timeout,
                               max_retry_per_llm=1 if len(models) == 1 else 0, retry_interval=0.1)
