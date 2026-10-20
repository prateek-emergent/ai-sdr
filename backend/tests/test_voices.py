"""20 Oct: the Talk page's voice choice (voice/catalog.py): five voices per language, built for the call's language
with Deepgram behind LiveKit Inference voices; the other language keeps the configured voice."""
from livekit.agents import inference, tts
from livekit.plugins import deepgram

from ai_sdr.voice import config as voice_config
from ai_sdr.voice.catalog import BY_ID, CATALOG, public
from ai_sdr.voice.providers import Voices


def test_catalog_shape():
    assert len(BY_ID) == len(CATALOG)  # ids are unique
    for lang in ("it", "en"):
        mine = [v for v in CATALOG if v.language == lang]
        assert len(mine) == 5 and all(v.id.startswith(f"{lang}-") for v in mine)
    for v in CATALOG:
        assert v.provider in ("livekit", "deepgram")
        assert (v.model.startswith("aura-2-") and v.model.endswith(f"-{v.language}")) if v.provider == "deepgram" \
            else (v.voice and "/" in v.model)
    assert set(public()[0]) == {"id", "language", "label", "note"}  # no provider details on the page


def test_picked_voice_speaks_its_language_only():
    cfg = voice_config.load()
    voices = Voices(cfg, choice=BY_ID["it-cartesia-francesca"])
    italian = voices.get("it")
    assert isinstance(italian, tts.FallbackAdapter)
    first, behind = italian._tts_instances
    assert isinstance(first, inference.TTS) and isinstance(behind, deepgram.TTS)
    assert voices.chain("it") == ("catalog:it-cartesia-francesca", "deepgram")
    assert not voices.chain("en")[0].startswith("catalog:")  # English keeps the configured voice


def test_deepgram_pick_has_no_fallback_layer():
    voices = Voices(voice_config.load(), choice=BY_ID["en-deepgram-thalia"])
    assert isinstance(voices.get("en"), deepgram.TTS)
    assert voices.chain("en") == ("catalog:en-deepgram-thalia",)
