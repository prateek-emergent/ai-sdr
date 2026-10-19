"""Every setting that shapes how a call sounds and behaves, in one frozen object that is validated when the worker
starts. Nothing here is left to LiveKit's defaults, because several of those change with the run mode (dev vs
start) or with the host: the turn-detector model, adaptive interruption, load limits (plan 17 Oct, root cause 1).

The worker refuses to start if this is wrong, instead of failing on the first call."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings

# Deepgram aura-2 voices per language (female; both available on our account, checked 17 Oct)
DEEPGRAM_VOICES = {"en": "aura-2-athena-en", "it": "aura-2-melia-it"}

# Languages a call can be held in: Italian for customers, English for the team's own tests (decided 20 Oct). Each call
# starts in one of them and can switch mid-call (switch_language tool).
LANGUAGES = ("it", "en")

# LiveKit 1.8.8 refuses a VAD whose min_silence_duration is below this when the streaming turn detector is used
# (audio_recognition._check_vad_silence_requirement: MIN_SILENCE_DURATION_MS 200 + 50 ms).
VAD_MIN_SILENCE_FLOOR = 0.25


def _env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


def _int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _version() -> str:
    """Which code is running: APP_VERSION if the deploy sets it, else the git commit, else 'unknown'."""
    if _env("APP_VERSION"):
        return _env("APP_VERSION")
    try:
        root = Path(__file__).resolve().parents[3]
        return subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=2).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LLMRoute:
    name: str          # litellm | emergent | anthropic
    base_url: str | None
    api_key: str
    model: str


@dataclass(frozen=True)
class VoiceConfig:
    agent_name: str
    language: str                       # default call language (it | en); a call's own language wins (worker.py)
    languages: tuple[str, ...]          # languages a call may use and switch between
    version: str

    # speech-to-text: providers in order; the first one that works hears the call
    stt_chain: tuple[str, ...]          # soniox | deepgram | livekit
    stt_model: str                      # Deepgram model (deepgram / livekit entries)
    deepgram_api_key: str | None
    soniox_api_key: str | None
    soniox_model: str
    soniox_max_endpoint_delay_ms: int   # the plugin emits a final transcript only at Soniox's endpoint (see load())
    stt_keyterms: tuple[str, ...]       # words the STT should expect (brand names it otherwise mishears)

    # voice: primary, then fallbacks in order, one voice per language
    tts_chain: tuple[str, ...]          # e.g. ("elevenlabs", "deepgram")
    elevenlabs_api_key: str | None
    elevenlabs_voice_ids: dict[str, str]  # language -> voice id; a language without one starts on the next voice
    elevenlabs_model: str
    deepgram_voices: dict[str, str]     # language -> aura-2 voice
    livekit_tts_model: str
    livekit_tts_voice: str
    pronunciations: dict[str, dict[str, str]]  # language -> {"written": "spoken"}, applied before the voice

    # language model: routes tried in order; each attempt gets attempt_timeout seconds of silence before the next
    llm_routes: tuple[LLMRoute, ...]
    llm_attempt_timeout: float

    # turn-taking (explicit: the library picks different defaults per run mode)
    turn_detector_version: str          # v1 (LiveKit cloud) | v1-mini (local)
    endpointing_min: float
    endpointing_max: float
    interruption_mode: str              # adaptive | vad
    interruption_min_duration: float
    interruption_min_words: int         # words the caller must say before Giulia pauses (0 = any sound)
    backchannel_boundary: tuple[float, float]  # seconds at the start/end of her lines where plain VAD decides
    false_interruption_timeout: float
    preemptive_generation: bool
    preemptive_tts: bool
    preemptive_max_speech: float        # longest caller turn (s) for which the reply is prepared early
    tts_min_sentence_len: int           # ElevenLabs: shortest text piece (chars) sent to the voice on its own
    aec_warmup: float | None            # seconds at the start of the first agent line where barge-in is ignored
    user_away_timeout: float            # silence before the person counts as "away" (first check-in)
    vad_min_silence: float              # silence before Silero ends the person's speech (the end-of-turn floor)
    filler_delay: float                 # quiet seconds into a slow calendar step before a filler line plays

    # provider connection budgets (per attempt)
    stt_timeout: float
    tts_timeout: float
    max_unrecoverable_errors: int

    # worker process
    max_sessions: int                   # calls one worker accepts at once (load = active calls / this)
    idle_processes: int
    health_port: int
    drain_timeout: int
    initialize_process_timeout: float
    memory_warn_mb: float

    # where call reports go: a directory, or mongodb (MONGO_URL + DB_NAME)
    report_sink: str = field(default="file")
    report_dir: str = field(default="")

    def describe(self) -> dict:
        """Safe summary for logs and reports: no secrets."""
        return {
            "agent_name": self.agent_name, "language": self.language, "languages": list(self.languages),
            "version": self.version,
            # one line for the metrics page (Calls.js shows config.stt)
            "stt": " → ".join(f"{n}:{self.soniox_model if n == 'soniox' else self.stt_model}" for n in self.stt_chain),
            "stt_chain": list(self.stt_chain), "stt_model": self.stt_model, "soniox_model": self.soniox_model,
            "soniox_max_endpoint_delay_ms": self.soniox_max_endpoint_delay_ms,
            "stt_keyterms": list(self.stt_keyterms),
            "tts_chain": list(self.tts_chain), "elevenlabs_model": self.elevenlabs_model,
            "elevenlabs_voice_languages": sorted(self.elevenlabs_voice_ids),
            "deepgram_voices": dict(self.deepgram_voices),
            "pronunciations": {lang: len(table) for lang, table in self.pronunciations.items()},
            "llm_routes": [f"{r.name}:{r.model}" for r in self.llm_routes],
            "llm_attempt_timeout": self.llm_attempt_timeout,
            "turn_detector": self.turn_detector_version,
            "endpointing": [self.endpointing_min, self.endpointing_max],
            "interruption": {"mode": self.interruption_mode, "min_duration": self.interruption_min_duration,
                             "min_words": self.interruption_min_words,
                             "backchannel_boundary": list(self.backchannel_boundary),
                             "false_timeout": self.false_interruption_timeout},
            "preemptive": {"enabled": self.preemptive_generation, "tts": self.preemptive_tts,
                           "max_speech_s": self.preemptive_max_speech},
            "tts_min_sentence_len": self.tts_min_sentence_len,
            "aec_warmup": self.aec_warmup, "user_away_timeout": self.user_away_timeout,
            "vad_min_silence": self.vad_min_silence, "filler_delay": self.filler_delay,
            "max_sessions": self.max_sessions, "report_sink": self.report_sink,
        }


def _llm_routes() -> tuple[LLMRoute, ...]:
    """LLM_ROUTES=litellm,emergent (default: every route whose key is present, in that order). Every route must serve
    the same model family, so a fallback never changes what Giulia says."""
    s = settings()
    available = {
        "litellm": (s.litellm_base_url, s.litellm_api_key, _env("LITELLM_MODEL", "claude-haiku-4-5")),
        "emergent": (None, s.emergent_llm_key, _env("EMERGENT_MODEL", "claude-haiku-4-5-20251001")),
        "anthropic": (None, _env("ANTHROPIC_API_KEY"), _env("ANTHROPIC_MODEL", "claude-haiku-4-5")),
    }
    wanted = [r.strip() for r in (_env("LLM_ROUTES") or "litellm,emergent").split(",") if r.strip()]
    routes = []
    for name in wanted:
        if name not in available:
            raise ConfigError(f"unknown LLM route {name!r} (litellm | emergent | anthropic)")
        base, key, model = available[name]
        if key:
            routes.append(LLMRoute(name, base, key, model))
    return tuple(routes)


def _languages(default: str) -> tuple[str, ...]:
    """AGENT_LANGUAGES=it,en (default both). The default language is always included, first."""
    langs = [x.strip() for x in (_env("AGENT_LANGUAGES") or ",".join(LANGUAGES)).split(",") if x.strip()]
    return tuple(dict.fromkeys([default, *langs]))


def _pronunciations(langs: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """TTS_PRONUNCIATIONS_IT / _EN: a JSON object {"written": "spoken"}. Empty until entries are tested by ear."""
    out: dict[str, dict[str, str]] = {}
    for lang in langs:
        raw = _env(f"TTS_PRONUNCIATIONS_{lang.upper()}")
        if not raw:
            continue
        try:
            table = json.loads(raw)
        except ValueError as e:
            raise ConfigError(f"TTS_PRONUNCIATIONS_{lang.upper()} is not JSON: {e}") from None
        if not isinstance(table, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in table.items()):
            raise ConfigError(f"TTS_PRONUNCIATIONS_{lang.upper()} must be an object of strings, "
                              'e.g. {"SaaS": "sass"}')
        out[lang] = {k: v for k, v in table.items() if k.strip()}
    return out


def load() -> VoiceConfig:
    s = settings()
    lang = s.agent_language
    langs = _languages(lang)
    tts_chain = tuple(t.strip() for t in (_env("TTS_CHAIN") or _default_tts_chain()).split(",") if t.strip())
    stt_chain = tuple(t.strip() for t in (_env("STT_CHAIN") or _default_stt_chain()).split(",") if t.strip())
    sink = _env("REPORT_SINK") or ("mongodb" if _env("MONGO_URL") else "file")
    generic_voice = _env("ELEVENLABS_VOICE_ID")
    cfg = VoiceConfig(
        agent_name=s.agent_name,
        language=lang,
        languages=langs,
        version=_version(),
        stt_chain=stt_chain,
        stt_model=_env("STT_MODEL", "nova-3"),
        deepgram_api_key=_env("DEEPGRAM_API_KEY"),
        soniox_api_key=_env("SONIOX_API_KEY"),
        soniox_model=_env("SONIOX_MODEL", "stt-rt-v5"),
        # The Soniox plugin (1.8.8) sends a final transcript only when Soniox detects an endpoint, and LiveKit won't end
        # the person's turn before it has one (audio_recognition._run_eou_detection). So this is the floor of every
        # reply with Soniox in front: 500 ms is Soniox's minimum (plugin default 2000). Turn-taking itself stays with
        # LiveKit's turn detector; an early endpoint only makes the words final sooner. Measure with the probe.
        soniox_max_endpoint_delay_ms=_int("SONIOX_MAX_ENDPOINT_DELAY_MS", 500),
        # 17 Oct real call: "Emergent" heard as "Emojin" and "I'm urgent" (the 16 Oct setup misheard it too)
        stt_keyterms=tuple(k.strip() for k in (_env("STT_KEYTERMS") or "Emergent").split(",") if k.strip()),
        tts_chain=tts_chain,
        elevenlabs_api_key=_env("ELEVENLABS_API_KEY") or _env("ELEVEN_API_KEY"),
        # one voice per language; ELEVENLABS_VOICE_ID alone gives both languages the same (multilingual) voice
        elevenlabs_voice_ids={x: v for x in langs if (v := _env(f"ELEVENLABS_VOICE_ID_{x.upper()}") or generic_voice)},
        # Eleven v4 Turbo: ElevenLabs' latest realtime model (17 Oct test via the LiveKit plugin: first audio 0.41 s vs
        # 0.60 s for Flash v2.5; works on the free plan with built-in voices). Streams via ElevenLabs' text-to-dialogue
        # websocket, which the plugin picks automatically for eleven_v3*/eleven_v4* models.
        elevenlabs_model=_env("ELEVENLABS_MODEL", "eleven_v4_turbo"),
        deepgram_voices={x: _env(f"DEEPGRAM_VOICE_{x.upper()}") or DEEPGRAM_VOICES.get(x, DEEPGRAM_VOICES["en"])
                         for x in langs},
        livekit_tts_model=s.inference_tts,
        livekit_tts_voice=s.inference_tts_voice,
        pronunciations=_pronunciations(langs),
        llm_routes=_llm_routes(),
        llm_attempt_timeout=_float("LLM_ATTEMPT_TIMEOUT_S", 4.0),
        turn_detector_version=_env("TURN_DETECTOR", "v1"),
        endpointing_min=_float("ENDPOINTING_MIN_S", 0.3),
        # longest wait for "have they finished?" when the turn model is unsure. 2.5 s (library default) hit in ~1 of 9
        # turns on preview (17 Oct suite) and made the slowest replies; 1.8 s approved by the user, measured by the probe
        endpointing_max=_float("ENDPOINTING_MAX_S", 1.8),
        interruption_mode=_env("INTERRUPTION_MODE", "adaptive"),
        interruption_min_duration=_float("INTERRUPTION_MIN_S", 0.5),
        # 17 Oct: a 0.13 s wordless sound 0.6 s into her line froze her for 2.2 s (real call; probe reproduced 3/3).
        # Cause: for the first 1.0 s of each line LiveKit lets plain VAD decide interruptions (backchannel_boundary
        # start), and any sound pauses her. Measured on the same machine (probe, 3 calls each):
        #   default (min_words 0, boundary 1.0): froze 3/3; real barge-in stop 1.22-1.28 s
        #   min_words 1:                         no freeze;  stop 1.95-2.08 s (too slow)
        #   boundary start 0.3 (min_words 0):    no freeze;  stop 1.35-1.37 s   <- chosen
        interruption_min_words=_int("INTERRUPTION_MIN_WORDS", 0),
        backchannel_boundary=(_float("BACKCHANNEL_BOUNDARY_START_S", 0.3), _float("BACKCHANNEL_BOUNDARY_END_S", 1.0)),
        # if a false pause still happens, resume after 1 s instead of 2 (safe: the timer starts when the sound ends,
        # and real words interrupt instead of resuming)
        false_interruption_timeout=_float("FALSE_INTERRUPTION_TIMEOUT_S", 1.0),
        preemptive_generation=_env("PREEMPTIVE_GENERATION", "1") == "1",
        preemptive_tts=_env("PREEMPTIVE_TTS", "1") == "1",
        # LiveKit default 10 s: after a longer answer the reply is NOT prepared during the end-of-turn wait (19 Oct
        # prod: the 2.84 s turn followed 19.9 s of speech)
        preemptive_max_speech=_float("PREEMPTIVE_MAX_SPEECH_S", 10.0),
        # LiveKit's sentence splitter default 20: "Got it." (7 chars) waits for the next sentence before the voice
        # starts (19 Oct prod: 0.18-0.65 s per turn). Deepgram's voice streams word by word and ignores this.
        tts_min_sentence_len=_int("TTS_MIN_SENTENCE_LEN", 20),
        aec_warmup=None if _env("AEC_WARMUP_S", "3.0") in ("off", "0") else _float("AEC_WARMUP_S", 3.0),
        user_away_timeout=s.silence_check_after_s,
        # Silero's default (0.55 s) is the real end-of-turn floor in 1.8.8: the turn decision only runs once Silero says
        # speech ended, so ENDPOINTING_MIN_S=0.3 never took effect (audio_recognition.py: END_OF_SPEECH -> EOU). 0.35 s
        # saves ~0.2 s whenever the turn model is confident; when it isn't, ENDPOINTING_MAX_S still applies.
        vad_min_silence=_float("VAD_MIN_SILENCE_S", 0.35),
        # a calendar request can take up to 8 s (calendar.py) and a booking makes 2-3 of them
        filler_delay=_float("FILLER_DELAY_S", 0.8),
        stt_timeout=_float("STT_TIMEOUT_S", 5.0),
        tts_timeout=_float("TTS_TIMEOUT_S", 4.0),
        max_unrecoverable_errors=_int("MAX_UNRECOVERABLE_ERRORS", 3),
        max_sessions=_int("MAX_SESSIONS", 3),
        idle_processes=_int("AGENT_IDLE_PROCESSES", 1),
        health_port=_int("AGENT_HEALTH_PORT", 8081),
        drain_timeout=_int("AGENT_DRAIN_TIMEOUT_S", 900),
        initialize_process_timeout=_float("AGENT_INIT_TIMEOUT_S", 30.0),
        memory_warn_mb=_float("AGENT_MEMORY_WARN_MB", 1500),
        report_sink=sink,
        report_dir=_env("REPORT_DIR", str(Path(__file__).resolve().parents[3] / "call_reports")),
    )
    validate(cfg)
    return cfg


def _default_tts_chain() -> str:
    """ElevenLabs first when it is configured (more natural voice), Deepgram always as the fallback."""
    if _env("TTS_PROVIDER") == "livekit":
        return "livekit"
    voices = [_env(f"ELEVENLABS_VOICE_ID_{x.upper()}") for x in LANGUAGES] + [_env("ELEVENLABS_VOICE_ID")]
    if (_env("ELEVENLABS_API_KEY") or _env("ELEVEN_API_KEY")) and any(voices):
        return "elevenlabs,deepgram"
    return "deepgram"


def _default_stt_chain() -> str:
    """Soniox first when its key is set (decided 20 Oct: cheaper, hears Italian and English in one stream), Deepgram
    as the fallback. STT_PROVIDER (the old single-provider setting) is still honoured when STT_CHAIN isn't set."""
    legacy = _env("STT_PROVIDER")
    if legacy in ("deepgram", "livekit"):
        return legacy
    chain = [name for name, key in (("soniox", "SONIOX_API_KEY"), ("deepgram", "DEEPGRAM_API_KEY")) if _env(key)]
    return ",".join(chain) or "deepgram"


def validate(cfg: VoiceConfig) -> None:
    problems = []
    s = settings()
    if not (s.livekit_url and s.livekit_api_key and s.livekit_api_secret):
        problems.append("LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET are required")
    if cfg.language not in LANGUAGES:
        problems.append(f"AGENT_LANGUAGE must be one of {', '.join(LANGUAGES)}, not {cfg.language!r}")
    for x in cfg.languages:
        if x not in LANGUAGES:
            problems.append(f"unknown language {x!r} in AGENT_LANGUAGES ({' | '.join(LANGUAGES)})")
    if not cfg.stt_chain:
        problems.append("STT_CHAIN is empty")
    for t in cfg.stt_chain:
        if t not in ("soniox", "deepgram", "livekit"):
            problems.append(f"unknown STT {t!r} in STT_CHAIN (soniox | deepgram | livekit)")
        if t == "soniox" and not cfg.soniox_api_key:
            problems.append("STT soniox needs SONIOX_API_KEY")
        if t == "deepgram" and not cfg.deepgram_api_key:
            problems.append("STT deepgram needs DEEPGRAM_API_KEY")
    if not 500 <= cfg.soniox_max_endpoint_delay_ms <= 3000:
        problems.append("SONIOX_MAX_ENDPOINT_DELAY_MS must be between 500 and 3000 (Soniox's range)")
    if not cfg.tts_chain:
        problems.append("TTS_CHAIN is empty")
    for t in cfg.tts_chain:
        if t not in ("elevenlabs", "deepgram", "livekit"):
            problems.append(f"unknown TTS {t!r} in TTS_CHAIN (elevenlabs | deepgram | livekit)")
        if t == "elevenlabs" and not (cfg.elevenlabs_api_key and cfg.elevenlabs_voice_ids):
            problems.append("TTS elevenlabs needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID[_EN|_IT]")
        if t == "deepgram" and not cfg.deepgram_api_key:
            problems.append("TTS deepgram needs DEEPGRAM_API_KEY")
    for x in cfg.languages:  # every language needs at least one voice that can speak it
        if cfg.tts_chain == ("elevenlabs",) and x not in cfg.elevenlabs_voice_ids:
            problems.append(f"no voice for {x!r}: set ELEVENLABS_VOICE_ID_{x.upper()} or add deepgram to TTS_CHAIN")
    if cfg.vad_min_silence < VAD_MIN_SILENCE_FLOOR:
        problems.append(f"VAD_MIN_SILENCE_S must be >= {VAD_MIN_SILENCE_FLOOR} (LiveKit's turn detector needs it)")
    if cfg.filler_delay < 0:
        problems.append("FILLER_DELAY_S must be >= 0")
    if not cfg.llm_routes:
        problems.append("no LLM route has a key (LITELLM_API_KEY / EMERGENT_LLM_KEY / ANTHROPIC_API_KEY)")
    if cfg.turn_detector_version not in ("v1", "v1-mini"):
        problems.append(f"TURN_DETECTOR must be v1 or v1-mini, not {cfg.turn_detector_version!r}")
    if cfg.interruption_mode not in ("adaptive", "vad"):
        problems.append(f"INTERRUPTION_MODE must be adaptive or vad, not {cfg.interruption_mode!r}")
    if not 0 < cfg.endpointing_min < cfg.endpointing_max <= 6:
        problems.append("need 0 < ENDPOINTING_MIN_S < ENDPOINTING_MAX_S <= 6")
    if cfg.llm_attempt_timeout < 1:
        problems.append("LLM_ATTEMPT_TIMEOUT_S must be >= 1")
    if cfg.max_sessions < 1:
        problems.append("MAX_SESSIONS must be >= 1")
    if cfg.report_sink not in ("file", "mongodb"):
        problems.append(f"REPORT_SINK must be file or mongodb, not {cfg.report_sink!r}")
    if cfg.report_sink == "mongodb" and not _env("MONGO_URL"):
        problems.append("REPORT_SINK=mongodb needs MONGO_URL")
    if problems:
        raise ConfigError("voice config is invalid:\n  - " + "\n  - ".join(problems))
