"""Every setting that shapes how a call sounds and behaves, in one frozen object that is validated when the worker
starts. Nothing here is left to LiveKit's defaults, because several of those change with the run mode (dev vs
start) or with the host: the turn-detector model, adaptive interruption, load limits (plan 17 Oct, root cause 1).

The worker refuses to start if this is wrong, instead of failing on the first call."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings

# Deepgram aura-2 voices per language (female; both available on our account, checked 17 Oct)
DEEPGRAM_VOICES = {"en": "aura-2-athena-en", "it": "aura-2-melia-it"}


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
    language: str                       # en | it
    version: str

    # speech-to-text
    stt_provider: str                   # deepgram | livekit
    stt_model: str
    stt_language: str
    deepgram_api_key: str | None
    stt_keyterms: tuple[str, ...]       # words the STT should expect (brand names it otherwise mishears)

    # voice: primary, then fallbacks in order
    tts_chain: tuple[str, ...]          # e.g. ("elevenlabs", "deepgram")
    elevenlabs_api_key: str | None
    elevenlabs_voice_id: str | None
    elevenlabs_model: str
    deepgram_voice: str
    livekit_tts_model: str
    livekit_tts_voice: str

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
            "agent_name": self.agent_name, "language": self.language, "version": self.version,
            "stt": f"{self.stt_provider}:{self.stt_model}:{self.stt_language}",
            "stt_keyterms": list(self.stt_keyterms),
            "tts_chain": list(self.tts_chain), "elevenlabs_model": self.elevenlabs_model,
            "deepgram_voice": self.deepgram_voice,
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


def load() -> VoiceConfig:
    s = settings()
    lang = s.agent_language
    tts_chain = tuple(t.strip() for t in (_env("TTS_CHAIN") or _default_tts_chain()).split(",") if t.strip())
    sink = _env("REPORT_SINK") or ("mongodb" if _env("MONGO_URL") else "file")
    cfg = VoiceConfig(
        agent_name=s.agent_name,
        language=lang,
        version=_version(),
        stt_provider=_env("STT_PROVIDER", "deepgram"),
        stt_model=_env("STT_MODEL", "nova-3"),
        stt_language=s.stt_language,
        deepgram_api_key=_env("DEEPGRAM_API_KEY"),
        # 17 Oct real call: "Emergent" heard as "Emojin" and "I'm urgent" (the 16 Oct setup misheard it too)
        stt_keyterms=tuple(k.strip() for k in (_env("STT_KEYTERMS") or "Emergent").split(",") if k.strip()),
        tts_chain=tts_chain,
        elevenlabs_api_key=_env("ELEVENLABS_API_KEY") or _env("ELEVEN_API_KEY"),
        elevenlabs_voice_id=_env(f"ELEVENLABS_VOICE_ID_{lang.upper()}") or _env("ELEVENLABS_VOICE_ID"),
        # Eleven v4 Turbo: ElevenLabs' latest realtime model (17 Oct test via the LiveKit plugin: first audio 0.41 s vs
        # 0.60 s for Flash v2.5; works on the free plan with built-in voices). Streams via ElevenLabs' text-to-dialogue
        # websocket, which the plugin picks automatically for eleven_v3*/eleven_v4* models.
        elevenlabs_model=_env("ELEVENLABS_MODEL", "eleven_v4_turbo"),
        deepgram_voice=_env("DEEPGRAM_VOICE", DEEPGRAM_VOICES.get(lang, DEEPGRAM_VOICES["en"])),
        livekit_tts_model=s.inference_tts,
        livekit_tts_voice=s.inference_tts_voice,
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
    if (_env("ELEVENLABS_API_KEY") or _env("ELEVEN_API_KEY")) and (
            _env(f"ELEVENLABS_VOICE_ID_{settings().agent_language.upper()}") or _env("ELEVENLABS_VOICE_ID")):
        return "elevenlabs,deepgram"
    return "deepgram"


def validate(cfg: VoiceConfig) -> None:
    problems = []
    s = settings()
    if not (s.livekit_url and s.livekit_api_key and s.livekit_api_secret):
        problems.append("LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET are required")
    if cfg.language not in ("en", "it"):
        problems.append(f"AGENT_LANGUAGE must be en or it, not {cfg.language!r}")
    if cfg.stt_provider not in ("deepgram", "livekit"):
        problems.append(f"STT_PROVIDER must be deepgram or livekit, not {cfg.stt_provider!r}")
    if cfg.stt_provider == "deepgram" and not cfg.deepgram_api_key:
        problems.append("STT_PROVIDER=deepgram needs DEEPGRAM_API_KEY")
    if not cfg.tts_chain:
        problems.append("TTS_CHAIN is empty")
    for t in cfg.tts_chain:
        if t not in ("elevenlabs", "deepgram", "livekit"):
            problems.append(f"unknown TTS {t!r} in TTS_CHAIN (elevenlabs | deepgram | livekit)")
        if t == "elevenlabs" and not (cfg.elevenlabs_api_key and cfg.elevenlabs_voice_id):
            problems.append("TTS elevenlabs needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID[_EN|_IT]")
        if t == "deepgram" and not cfg.deepgram_api_key:
            problems.append("TTS deepgram needs DEEPGRAM_API_KEY")
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
