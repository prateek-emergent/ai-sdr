"""20 Oct: the Talk page's voice choice (voice/catalog.py): five voices per language, built for the call's language
with Deepgram behind LiveKit Inference voices; the other language keeps the configured voice."""
import pytest
from livekit.agents import inference, tts
from livekit.plugins import cartesia, deepgram

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


AMBER = "a7a59115-2425-4192-844c-1e98ec7d6877"


def test_english_speaks_cartesia_amber_with_deepgram_behind(monkeypatch):
    """21 Oct: English is Cartesia "Amber" on our own key, Deepgram stays as the fallback; Italian is unchanged."""
    monkeypatch.setenv("CARTESIA_API_KEY", "test")
    monkeypatch.setenv("CARTESIA_VOICE_ID_EN", AMBER)
    monkeypatch.setenv("TTS_CHAIN", "cartesia,deepgram")
    cfg = voice_config.load()
    voices = Voices(cfg)
    assert voices.chain("en") == ("cartesia", "deepgram") and voices.chain("it") == ("deepgram",)
    english = voices.get("en")
    first, behind = english._tts_instances
    assert isinstance(first, cartesia.TTS) and isinstance(behind, deepgram.TTS)
    assert (first._opts.voice, first._opts.model, first._opts.language) == (AMBER, "sonic-3.6", "en")
    assert behind._opts.model == "aura-2-athena-en"   # the same Deepgram voice as before
    assert isinstance(voices.get("it"), deepgram.TTS)


def test_cartesia_picks_use_our_key_where_a_cartesia_voice_is_set(monkeypatch):
    monkeypatch.setenv("CARTESIA_API_KEY", "test")
    monkeypatch.setenv("CARTESIA_VOICE_ID_EN", AMBER)
    cfg = voice_config.load()
    allie, _ = Voices(cfg, choice=BY_ID["en-cartesia-allie"]).get("en")._tts_instances
    assert isinstance(allie, cartesia.TTS) and allie._opts.model == "sonic-3.6"
    francesca, _ = Voices(cfg, choice=BY_ID["it-cartesia-francesca"]).get("it")._tts_instances
    assert isinstance(francesca, inference.TTS)   # Italian picks stay on LiveKit Inference


def test_cartesia_needs_its_key_and_a_voice(monkeypatch):
    monkeypatch.setenv("TTS_CHAIN", "cartesia,deepgram")
    with pytest.raises(voice_config.ConfigError):
        voice_config.load()
    monkeypatch.setenv("CARTESIA_API_KEY", "test")
    monkeypatch.setenv("CARTESIA_VOICE_ID_EN", AMBER)
    monkeypatch.delenv("TTS_CHAIN")
    assert voice_config.load().tts_chain == ("cartesia", "elevenlabs", "deepgram")   # the default, keys permitting
