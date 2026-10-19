"""Speech-to-text, voice and language model, built from VoiceConfig. Every provider is wrapped so a slow or failed
one is replaced instead of leaving the caller in silence (plan root cause 5).

Each call has a language (it | en) and can switch mid-call: speech-to-text hears both in one stream (Soniox language
hints), and the voice is per language (Voices, below)."""
from __future__ import annotations

from collections.abc import Callable

import httpx
from livekit.agents import NOT_GIVEN, inference, llm, stt, tts
from livekit.plugins import anthropic as lk_anthropic
from livekit.plugins import deepgram, elevenlabs, soniox
from livekit.plugins import openai as lk_openai

from ..llm import proxy_url
from .config import DEEPGRAM_VOICES, LLMRoute, VoiceConfig

# what Soniox is told about the conversation (context improves names, product words and numbers)
SONIOX_DOMAIN = "Phone call between Emergent (an AI app builder) and a customer about the apps they build."


def _one_stt(cfg: VoiceConfig, name: str, language: str) -> stt.STT:
    if name == "soniox":
        # the call's language first, then the others: an Italian customer may answer in English, and Italian users of
        # a dev platform drop English words ("deploy", "app", "crediti") into Italian sentences
        hints = [language, *(x for x in cfg.languages if x != language)]
        context = soniox.ContextObject(general=[soniox.ContextGeneralItem(key="domain", value=SONIOX_DOMAIN)],
                                       terms=list(cfg.stt_keyterms) or None)
        return soniox.STT(api_key=cfg.soniox_api_key, params=soniox.STTOptions(
            model=cfg.soniox_model, language_hints=hints, context=context,
            max_endpoint_delay_ms=cfg.soniox_max_endpoint_delay_ms))
    if name == "livekit":
        return inference.STT(model=f"deepgram/{cfg.stt_model}", language=language)
    # Deepgram listens in the language the call started in (keyterm prompting is monolingual nova-3), so it is the
    # fallback, not the bilingual front line. Keyterms go on the connection URL when it is opened: one Deepgram
    # websocket for the whole call. (Session-level stt_context_options would update a live stream, which reconnects it.)
    keyterm = list(cfg.stt_keyterms) if cfg.stt_keyterms and cfg.stt_model.startswith("nova-3") else NOT_GIVEN
    return deepgram.STT(model=cfg.stt_model, language=language, api_key=cfg.deepgram_api_key, keyterm=keyterm)


def build_stt(cfg: VoiceConfig, language: str) -> stt.STT:
    """One engine, or a chain: if the first fails the next one hears the call. The chain keeps the primary's aligned
    transcripts (Soniox: per chunk), which adaptive interruption needs (stt/fallback_adapter.py)."""
    engines = [_one_stt(cfg, name, language) for name in cfg.stt_chain]
    if len(engines) == 1:
        return engines[0]
    # switch at once rather than retry a dead engine mid-call (the voice chain does the same, 17 Oct)
    return stt.FallbackAdapter(engines, attempt_timeout=cfg.stt_timeout, max_retry_per_stt=0, retry_interval=0.5)


def _one_tts(cfg: VoiceConfig, name: str, language: str) -> tts.TTS:
    if name == "elevenlabs":
        from livekit.agents.tokenize import blingfire
        return elevenlabs.TTS(voice_id=cfg.elevenlabs_voice_ids[language], model=cfg.elevenlabs_model,
                              api_key=cfg.elevenlabs_api_key, language=language,
                              word_tokenizer=blingfire.SentenceTokenizer(min_sentence_len=cfg.tts_min_sentence_len))
    if name == "deepgram":
        return deepgram.TTS(model=cfg.deepgram_voices.get(language, DEEPGRAM_VOICES["en"]),
                            api_key=cfg.deepgram_api_key)
    return inference.TTS(model=cfg.livekit_tts_model, voice=cfg.livekit_tts_voice, language=language)


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


def tts_chain_for(cfg: VoiceConfig, requested: list[str] | None, elevenlabs_left: int | None = None,
                  language: str | None = None) -> tuple[str, ...]:
    """The configured voice chain, or a test call's override (the probe asks for Deepgram so automated runs don't
    spend ElevenLabs credits). An override naming a voice without its key falls back to the configured chain. A
    language with no ElevenLabs voice of its own starts on the next voice."""
    language = language or cfg.language
    if not requested:
        chain = cfg.tts_chain
        # nearly out of ElevenLabs credits: start on the next voice (a dead first voice costs ~2.4 s of silence
        # before the fallback speaks, 17 Oct test)
        if elevenlabs_left is not None and elevenlabs_left < ELEVENLABS_MIN_CREDITS and len(chain) > 1:
            chain = tuple(n for n in chain if n != "elevenlabs") or chain
    else:
        ok = {"deepgram": bool(cfg.deepgram_api_key), "livekit": True,
              "elevenlabs": bool(cfg.elevenlabs_api_key and cfg.elevenlabs_voice_ids)}
        chain = tuple(n for n in requested if ok.get(n)) or cfg.tts_chain
    if language not in cfg.elevenlabs_voice_ids:
        chain = tuple(n for n in chain if n != "elevenlabs") or ("deepgram",)
    return chain


def build_tts(cfg: VoiceConfig, chain: tuple[str, ...] | None = None, language: str | None = None) -> tts.TTS:
    """One voice, or a chain: if the first fails (error, outage, out of credits) the next one speaks. The adapter
    never switches in the middle of a sentence that has already started playing."""
    language = language or cfg.language
    voices = [_one_tts(cfg, name, language) for name in (chain or tts_chain_for(cfg, None, None, language))]
    if len(voices) == 1:
        return voices[0]
    # no second try at a failing voice mid-call: switch at once (the adapter re-checks it in the background and
    # switches back when it recovers). 17 Oct test: with one retry, a dead ElevenLabs cost 3.2 s of silence.
    return tts.FallbackAdapter(voices, max_retry_per_tts=0)


class Voices:
    """The voice for each language of one call, built on first use and kept, so switching back and forth between
    Italian and English reuses the same connections. on_build sees every new voice (telemetry listens to it)."""

    def __init__(self, cfg: VoiceConfig, requested: list[str] | None = None, elevenlabs_left: int | None = None,
                 on_build: Callable[[str, tuple[str, ...], tts.TTS], None] | None = None):
        self.cfg, self.requested, self.elevenlabs_left, self.on_build = cfg, requested, elevenlabs_left, on_build
        self._built: dict[str, tts.TTS] = {}

    def chain(self, language: str) -> tuple[str, ...]:
        return tts_chain_for(self.cfg, self.requested, self.elevenlabs_left, language)

    def get(self, language: str) -> tts.TTS:
        if language not in self._built:
            chain = self.chain(language)
            voice = build_tts(self.cfg, chain, language)
            self._built[language] = voice
            if self.on_build is not None:
                self.on_build(language, chain, voice)
        return self._built[language]


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
