"""Test setup: backend/ on the import path and the settings the worker validates at import. The values are fake:
nothing in these tests talks to LiveKit, an LLM, a speech provider, HubSpot or the database."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for key, value in {
    "LIVEKIT_URL": "wss://example.invalid", "LIVEKIT_API_KEY": "test", "LIVEKIT_API_SECRET": "test",
    "DEEPGRAM_API_KEY": "test", "SONIOX_API_KEY": "test", "LITELLM_API_KEY": "test",
    "ELEVENLABS_API_KEY": "test", "ELEVENLABS_VOICE_ID_IT": "voice-it", "ELEVENLABS_VOICE_ID_EN": "voice-en",
    "AGENT_LANGUAGE": "it", "REPORT_SINK": "file",
}.items():
    os.environ.setdefault(key, value)
