"""20 Oct latency/cost settings (approved, not yet proven on calls; revert values in decisions.md)."""
from livekit.agents import NOT_GIVEN

from ai_sdr.voice import config as voice_config
from ai_sdr.voice.providers import build_llm


def test_new_defaults():
    cfg = voice_config.load()
    assert cfg.tts_min_sentence_len == 8          # was 20
    assert cfg.interruption_min_duration == 0.3   # was 0.5
    assert cfg.llm_max_output_tokens == 400       # was none (OpenAI-format) / 1024 (Anthropic)


def test_output_cap_reaches_every_route(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("LLM_ROUTES", "litellm,anthropic")
    caps = [getattr(m._opts, "max_completion_tokens", None) or getattr(m._opts, "max_tokens", None)
            for m in build_llm(voice_config.load())._llm_instances]
    assert caps == [400, 400]


def test_cap_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "0")
    litellm = build_llm(voice_config.load())._llm_instances[0]
    assert litellm._opts.max_completion_tokens is NOT_GIVEN
