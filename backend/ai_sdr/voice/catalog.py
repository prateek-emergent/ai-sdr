"""Voices the team can pick on the Talk page before a call (20 Oct: "the voice is a very important part of sounding
human"). Five per language, the most human-sounding of what this project can run, chosen on:
- the Artificial Analysis TTS arena (Cartesia Sonic 3.6 #4, Inworld TTS-2 #7; Deepgram Aura-2 unranked);
- first audio measured on a warm connection from the laptop: Cartesia 0.11-0.14 s, Deepgram 0.28-0.35 s,
  Inworld 0.41 s. Gemini 3.8 Flash TTS (#5) sounds as good but starts 1.1-1.5 s late, too slow for a conversation.
All female, like the persona. LiveKit Inference voices draw on the LiveKit project's monthly credit (the free plan's
$2.50 is roughly 55 minutes of Cartesia speech); when it runs out the call falls back to Deepgram, which uses our key.

No LiveKit imports here: the web backend reads this list too (server.py, GET /api/voices)."""
from __future__ import annotations

from dataclasses import dataclass

CARTESIA = "cartesia/sonic-3.6"
INWORLD = "inworld/inworld-tts-2"


@dataclass(frozen=True)
class CatalogVoice:
    id: str          # what the page sends
    language: str    # it | en
    label: str       # what the page shows
    note: str        # one line on what it sounds like
    provider: str    # livekit (LiveKit Inference) | deepgram (our key)
    model: str       # LiveKit Inference model, or the Aura-2 voice for deepgram
    voice: str = ""  # voice id or name for LiveKit Inference


CATALOG: tuple[CatalogVoice, ...] = (
    CatalogVoice("it-cartesia-francesca", "it", "Francesca · Cartesia", "natural, made for conversation", "livekit",
                 CARTESIA, "d609f27f-f1a4-410f-85bb-10037b4fba99"),
    CatalogVoice("it-cartesia-liv", "it", "Liv · Cartesia", "casual and friendly", "livekit",
                 CARTESIA, "d718e944-b313-4998-b011-d1cc078d4ef3"),
    CatalogVoice("it-cartesia-alessandra", "it", "Alessandra · Cartesia", "melodic, gentle guide", "livekit",
                 CARTESIA, "0e21713a-5e9a-428a-bed4-90d410b87f13"),
    CatalogVoice("it-inworld-orietta", "it", "Orietta · Inworld", "native Italian, expressive", "livekit",
                 INWORLD, "Orietta"),
    CatalogVoice("it-deepgram-maia", "it", "Maia · Deepgram", "caring, warm, fastest fallback", "deepgram",
                 "aura-2-maia-it"),
    CatalogVoice("en-cartesia-allie", "en", "Allie · Cartesia", "natural conversationalist", "livekit",
                 CARTESIA, "2747b6cf-fa34-460c-97db-267566918881"),
    CatalogVoice("en-cartesia-amber", "en", "Amber · Cartesia", "warm support agent", "livekit",
                 CARTESIA, "a7a59115-2425-4192-844c-1e98ec7d6877"),
    CatalogVoice("en-cartesia-aubrey", "en", "Aubrey · Cartesia", "easygoing, relaxed", "livekit",
                 CARTESIA, "87041166-c212-4838-9028-05d7437df750"),
    CatalogVoice("en-inworld-ashley", "en", "Ashley · Inworld", "bright, conversational", "livekit",
                 INWORLD, "Ashley"),
    CatalogVoice("en-deepgram-thalia", "en", "Thalia · Deepgram", "clear, fastest fallback", "deepgram",
                 "aura-2-thalia-en"),
)
BY_ID: dict[str, CatalogVoice] = {v.id: v for v in CATALOG}


def public() -> list[dict]:
    """What the page needs to show the choice (no provider details)."""
    return [{"id": v.id, "language": v.language, "label": v.label, "note": v.note} for v in CATALOG]
