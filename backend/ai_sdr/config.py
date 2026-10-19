"""All settings come from the environment (see .env.example). Nothing secret lives in code."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _int(name: str, default: int) -> int:
    return int(_env(name, str(default)))


def _bool(name: str, default: bool = False) -> bool:
    return (_env(name, "1" if default else "0") or "").lower() in ("1", "true", "yes", "on")


def _windows(spec: str) -> list[tuple[time, time]]:
    """'09:30-13:00,14:30-18:00' -> [(09:30, 13:00), (14:30, 18:00)]"""
    out = []
    for part in spec.split(","):
        start, end = part.strip().split("-")
        out.append((time.fromisoformat(start), time.fromisoformat(end)))
    return out


def _provider() -> str:
    """anthropic | litellm | emergent. Explicit LLM_PROVIDER wins; otherwise a direct Anthropic key, then the internal
    LiteLLM key, then the Emergent universal key."""
    explicit = _env("LLM_PROVIDER")
    if explicit:
        return explicit
    if _env("ANTHROPIC_API_KEY"):
        return "anthropic"
    if _env("LITELLM_API_KEY"):
        return "litellm"
    return "emergent" if _env("EMERGENT_LLM_KEY") else "anthropic"


def _default_model() -> str:
    # model names differ per gateway; none of them serves Haiku 5.5 (checked 2026-10-16)
    return {"emergent": "claude-haiku-4-5-20251001", "litellm": "claude-haiku-4-5"}.get(_provider(),
                                                                                          "claude-haiku-5-5")


@dataclass(frozen=True)
class Settings:
    # storage
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "postgresql://sdr:sdr@localhost:5432/sdr"))

    # LiveKit + telephony
    livekit_url: str | None = field(default_factory=lambda: _env("LIVEKIT_URL"))
    livekit_api_key: str | None = field(default_factory=lambda: _env("LIVEKIT_API_KEY"))
    livekit_api_secret: str | None = field(default_factory=lambda: _env("LIVEKIT_API_SECRET"))
    agent_name: str = field(default_factory=lambda: _env("AGENT_NAME", "ai-sdr"))
    sip_outbound_trunk_id: str | None = field(default_factory=lambda: _env("SIP_OUTBOUND_TRUNK_ID"))
    caller_number: str | None = field(default_factory=lambda: _env("CALLER_NUMBER"))  # +1..., shown to prospects
    ringing_timeout_s: int = field(default_factory=lambda: _int("RINGING_TIMEOUT_S", 30))
    # 0 = no limit (the user's call, 2026-10-16: "keep it flowing"). Booked Nooks calls ran up to ~17 min.
    max_call_seconds: int = field(default_factory=lambda: _int("MAX_CALL_SECONDS", 0))
    demo_max_call_seconds: int = field(default_factory=lambda: _int("DEMO_MAX_CALL_SECONDS", 0))
    # silence handling (user, 2026-10-16): after 10 s of silence ask "are you there?", ask once more 6 s after that line ends,
    # wait 6 s more, then say we will connect at a better time and hang up (~30 s in total)
    silence_check_after_s: float = field(default_factory=lambda: float(_env("SILENCE_CHECK_AFTER_S", "10")))
    silence_check_every_s: float = field(default_factory=lambda: float(_env("SILENCE_CHECK_EVERY_S", "6")))
    silence_check_ins: int = field(default_factory=lambda: _int("SILENCE_CHECK_INS", 2))
    # silence check-ins + "your voice is breaking, could you repeat?" together; past this the call is rescheduled
    max_line_retries: int = field(default_factory=lambda: _int("MAX_LINE_RETRIES", 5))

    # company identity used in the opener and the inbound line
    company_name: str = field(default_factory=lambda: _env("COMPANY_NAME", "Emergent"))
    company_office: str = field(default_factory=lambda: _env("COMPANY_OFFICE", "San Francisco, Stati Uniti"))
    agent_persona_name: str = field(default_factory=lambda: _env("AGENT_PERSONA_NAME", "Giulia"))
    prompt_version: str = field(default_factory=lambda: _env("PROMPT_VERSION", "it-v0"))
    persona_variant: str = field(default_factory=lambda: _env("PERSONA_VARIANT", "check_in"))

    # models. LLM_PROVIDER=emergent uses the Emergent universal key (EMERGENT_LLM_KEY) via emergentintegrations;
    # it only works from Emergent's servers (see llm.py). Its model list has no Haiku 5.5, hence the other default.
    llm_provider: str = field(default_factory=lambda: _provider())
    emergent_llm_key: str | None = field(default_factory=lambda: _env("EMERGENT_LLM_KEY"))
    # internal LiteLLM (VPN only). Direct, no relay: Haiku 4.5 ~0.82 s / Sonnet 4.6 ~1.28 s to first word, vs
    # 0.94 / 1.54 s via the relay (16 Oct, unique prompts; identical repeats hit a response cache and look faster)
    litellm_base_url: str = field(default_factory=lambda: _env(
        "LITELLM_BASE_URL", "https://litellm.central-infra-apps.emergentagent.com/v1"))
    litellm_api_key: str | None = field(default_factory=lambda: _env("LITELLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", _default_model()))
    summary_model: str = field(default_factory=lambda: _env("SUMMARY_MODEL", _default_model()))
    # it = real calls; en = demos while the team can't judge Italian. Prompt, opener, read-backs, STT and voice follow.
    agent_language: str = field(default_factory=lambda: _env("AGENT_LANGUAGE", "it"))
    stt_language: str = field(default_factory=lambda: _env("STT_LANGUAGE", _env("AGENT_LANGUAGE", "it")))
    # livekit = LiveKit Inference: speech-to-text and voices billed through the LiveKit Cloud account, no extra keys
    stt_provider: str = field(default_factory=lambda: _env("STT_PROVIDER", "deepgram"))  # deepgram | livekit
    inference_stt: str = field(default_factory=lambda: _env("INFERENCE_STT", "deepgram/nova-3"))
    tts_provider: str = field(default_factory=lambda: _env("TTS_PROVIDER", "azure"))  # azure | elevenlabs | livekit
    inference_tts: str = field(default_factory=lambda: _env("INFERENCE_TTS", "deepgram/aura-2"))
    inference_tts_voice: str = field(default_factory=lambda: _env(
        "INFERENCE_TTS_VOICE", "athena" if _env("AGENT_LANGUAGE", "it") == "en" else "melia"))  # both female
    azure_voice: str = field(default_factory=lambda: _env("AZURE_TTS_VOICE", "it-IT-IsabellaNeural"))
    elevenlabs_voice_id: str | None = field(default_factory=lambda: _env("ELEVENLABS_VOICE_ID"))
    elevenlabs_model: str = field(default_factory=lambda: _env("ELEVENLABS_MODEL", "eleven_flash_v2_5"))

    # calendar
    calendar_provider: str = field(default_factory=lambda: _env("CALENDAR_PROVIDER", "fake"))  # calendly | fake
    calendly_token: str | None = field(default_factory=lambda: _env("CALENDLY_API_KEY"))
    calendly_event_type: str | None = field(default_factory=lambda: _env("CALENDLY_EVENT_TYPE_URI"))
    meeting_min_lead_hours: int = field(default_factory=lambda: _int("MEETING_MIN_LEAD_HOURS", 20))
    meeting_search_days: int = field(default_factory=lambda: _int("MEETING_SEARCH_DAYS", 7))
    # demo calendar only (Calendly has the real availability): Monday=0 ... Saturday=5
    meeting_weekdays: tuple[int, ...] = field(default_factory=lambda: tuple(
        int(x) for x in _env("MEETING_WEEKDAYS", "0,1,2,3,4,5").split(",")))
    meeting_hours: list[tuple[time, time]] = field(
        default_factory=lambda: _windows(_env("MEETING_HOURS", "09:30-13:00,14:30-18:00")))
    utm_campaign: str = field(default_factory=lambda: _env("UTM_CAMPAIGN", "ai_sdr"))

    # HubSpot (dry-run unless HUBSPOT_WRITE=1, same convention as outbound-hubspot)
    hubspot_token: str | None = field(default_factory=lambda: _env("HUBSPOT_API_KEY"))
    hubspot_write: bool = field(default_factory=lambda: _bool("HUBSPOT_WRITE"))
    hubspot_owner_id: str | None = field(default_factory=lambda: _env("HUBSPOT_MEETING_OWNER_ID"))

    # dialer policy
    business_hours: list[tuple[time, time]] = field(
        default_factory=lambda: _windows(_env("BUSINESS_HOURS", "09:30-13:00,14:30-18:00")))
    callback_hours: tuple[time, time] = field(
        default_factory=lambda: _windows(_env("CALLBACK_HOURS", "08:00-20:00"))[0])
    max_attempts: int = field(default_factory=lambda: _int("MAX_ATTEMPTS", 3))
    max_concurrent_calls: int = field(default_factory=lambda: _int("MAX_CONCURRENT_CALLS", 2))
    daily_call_cap: int = field(default_factory=lambda: _int("DAILY_CALL_CAP", 50))
    dialer_poll_seconds: int = field(default_factory=lambda: _int("DIALER_POLL_SECONDS", 15))

    # recording (LiveKit egress to an S3-compatible bucket; off unless configured)
    recording_enabled: bool = field(default_factory=lambda: _bool("RECORDING_ENABLED"))
    s3_bucket: str | None = field(default_factory=lambda: _env("RECORDING_S3_BUCKET"))
    s3_endpoint: str | None = field(default_factory=lambda: _env("RECORDING_S3_ENDPOINT"))
    s3_region: str | None = field(default_factory=lambda: _env("RECORDING_S3_REGION", "auto"))
    s3_access_key: str | None = field(default_factory=lambda: _env("RECORDING_S3_ACCESS_KEY"))
    s3_secret: str | None = field(default_factory=lambda: _env("RECORDING_S3_SECRET"))


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()
