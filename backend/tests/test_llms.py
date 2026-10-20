"""20 Oct: the Talk page's model choice (voice/llm_catalog.py, providers.build_llm, server.py /api/llms and
/api/session) and the speed numbers per model (evals/quality.py speed, telemetry's per-call models). Nothing here
calls an LLM or LiveKit."""
import base64
import json

import pytest
from fastapi.testclient import TestClient
from livekit.plugins import openai as lk_openai

from ai_sdr.config import settings
from ai_sdr.evals.quality import speed
from ai_sdr.voice import config as voice_config
from ai_sdr.voice.llm_catalog import BY_ID, CATALOG, public
from ai_sdr.voice.providers import build_llm
from ai_sdr.voice.telemetry import CallTelemetry

GROQ = next(m for m in CATALOG if m.provider == "groq")
LITELLM = next(m for m in CATALOG if m.provider == "litellm")


@pytest.fixture
def no_groq(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    settings.cache_clear()
    yield
    settings.cache_clear()


@pytest.fixture
def groq_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    settings.cache_clear()
    yield
    settings.cache_clear()


def test_catalog_shape():
    assert len(BY_ID) == len(CATALOG)   # ids are unique
    assert {m.provider for m in CATALOG} == {"litellm", "groq"}
    assert all(m.label and m.note and m.model for m in CATALOG)
    # the page gets names and availability, never keys or request settings
    assert set(public()[0]) == {"id", "provider", "provider_label", "label", "note", "model", "available", "needs"}


def test_groq_is_offered_once_its_key_is_set(no_groq):
    rows = {m["id"]: m for m in public()}
    assert rows[GROQ.id]["available"] is False and rows[GROQ.id]["needs"] == "GROQ_API_KEY"
    assert rows[LITELLM.id]["available"] is True and rows[LITELLM.id]["needs"] is None   # LITELLM_API_KEY: conftest
    # a pick without its key is ignored: the configured route answers
    assert [m.model for m in build_llm(voice_config.load(), GROQ)._llm_instances] == ["claude-haiku-4-5"]


def test_pick_answers_first_and_the_routes_stay_behind(groq_key):
    first, *behind = build_llm(voice_config.load(), GROQ)._llm_instances
    assert isinstance(first, lk_openai.LLM) and first.model == GROQ.model
    assert first._client.base_url.host == "api.groq.com"
    assert first._strict_tool_schema is False            # plain tool schemas for an OpenAI-compatible vendor
    assert first._opts.max_completion_tokens == 400      # the same output cap as the routes
    assert [m.model for m in behind] == ["claude-haiku-4-5"]
    picked = build_llm(voice_config.load(), LITELLM)._llm_instances[0]
    assert picked.model == LITELLM.model and "litellm" in picked._client.base_url.host


def test_reasoning_and_extra_fields_reach_the_model(groq_key):
    for m in CATALOG:
        built = build_llm(voice_config.load(), m)._llm_instances[0]
        if m.reasoning_effort:
            assert built._opts.reasoning_effort == m.reasoning_effort
        if m.extra_body:
            assert built._opts.extra_body == dict(m.extra_body)


def reply(e2e, ttft, model="claude-haiku-4-5", host="litellm.central-infra-apps.emergentagent.com"):
    return {"e2e_latency": e2e, "llm_node_ttft": ttft, "llm_node_ttfs": ttft + 0.05, "tts_node_ttfb": 0.1,
            "llm_node_tps": 80.0, "llm_metadata": {"model_name": model, "model_provider": host},
            "tts_metadata": {"model_name": "aura-2-melia-it"}}


USER = {"end_of_turn_delay": 0.4, "transcription_delay": 0.3, "stt_metadata": {"model_name": "nova-3"}}


def test_speed_overall_and_per_model():
    groq = ("llama-3.3-70b-versatile", "api.groq.com")
    reports = [
        {"turn_metrics": [{}, USER, reply(1.2, 0.5), USER, reply(1.4, 0.7)], "eval": {"score": 0.8, "must_failed": []}},
        # a picked Groq model that fell back once: that reply counts for Haiku, the call for Groq
        {"turn_metrics": [USER, reply(0.9, 0.2, *groq), USER, reply(1.0, 0.25, *groq), USER, reply(1.6, 0.9)],
         "eval": {"score": 0.5, "must_failed": ["respects_no"]}},
        {"turn_metrics": []},   # nobody spoke
    ]
    s = speed(reports)
    assert s["overall"]["e2e"]["n"] == 5 and s["overall"]["eou"]["n"] == 5 and s["overall"]["eou"]["p50"] == 0.4
    assert s["overall"]["tps"]["p50"] == 80.0
    first, second = s["models"]                                    # sorted by first token
    assert first["model"] == "llama-3.3-70b-versatile" and first["provider"] == "Groq"
    assert first["replies"] == 2 and first["calls"] == 1 and first["ttft"]["p50"] == 0.225
    assert first["score"] == 0.5 and first["must_failed_calls"] == 1
    assert second["model"] == "claude-haiku-4-5" and second["provider"] == "LiteLLM"
    assert second["replies"] == 3 and second["calls"] == 1 and second["score"] == 0.8
    assert second["ttft"]["p95"] <= 0.9 and second["e2e"]["n"] == 3


def test_call_summary_names_the_models_that_worked():
    t = CallTelemetry(voice_config.load(), room="demo-x", job_id="j", channel="web")
    try:
        t.event("llm", choice=GROQ.id, provider="groq", model=GROQ.model)
        history = [{"metrics": USER}, {"metrics": reply(0.9, 0.2, GROQ.model, "api.groq.com")}, {"metrics": USER},
                   {"metrics": reply(1.0, 0.3, GROQ.model, "api.groq.com")}, {"metrics": USER},
                   {"metrics": reply(1.5, 0.8)}]
        s = t.summary(history)
    finally:
        t.detach_logs()
    assert s["llm_model"] == GROQ.model and s["llm_models"] == {GROQ.model: 2, "claude-haiku-4-5": 1}
    assert s["llm_pick"] == GROQ.id and s["tts_model"] == "aura-2-melia-it" and s["stt_model"] == "nova-3"
    assert s["stt_p50"] == 0.3 and s["llm_ttfs_p50"] == 0.35 and s["llm_tps_p50"] == 80.0


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_SINK", "file")
    monkeypatch.setenv("REPORT_DIR", str(tmp_path))
    monkeypatch.setenv("DEBUG_TOKEN", "secret")
    monkeypatch.setenv("RUN_AGENT", "0")
    report = {"room": "demo-s", "channel": "web", "started_at": "2099-01-01T10:00:00+00:00", "summary": {"turns": 2},
              "livekit": {"chat_history": {"items": [{"type": "message", "role": "user", "metrics": USER},
                                                     {"type": "message", "role": "assistant",
                                                      "metrics": reply(1.1, 0.4)}]}}}
    (tmp_path / "demo-s.json").write_text(json.dumps(report))
    import server
    monkeypatch.setattr(server, "_record_session", lambda room: None)   # no database in tests
    return TestClient(server.app)


def _metadata(token: str) -> dict:
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    return json.loads(claims["roomConfig"]["agents"][0]["metadata"])


def test_endpoints(client, no_groq):
    j = client.get("/api/llms").json()
    assert j["default"] == "Claude Haiku 4.5" and len(j["llms"]) == len(CATALOG)
    started = client.post("/api/session", json={"name": "Ada", "llm": LITELLM.id}).json()
    assert _metadata(started["token"])["llm"] == LITELLM.id
    # a model whose key is missing, or an unknown id, never reaches the worker
    for pick in (GROQ.id, "made-up"):
        assert "llm" not in _metadata(client.post("/api/session", json={"name": "Ada", "llm": pick}).json()["token"])
    s = client.get("/api/quality/summary?token=secret&hours=24").json()["speed"]
    assert s["models"][0]["model"] == "claude-haiku-4-5" and s["models"][0]["ttft"]["p50"] == 0.4
    assert s["overall"]["stt"]["p50"] == 0.3


def test_claude_prompt_is_cached_through_litellm(monkeypatch, groq_key):
    from ai_sdr.voice.providers import CACHE_SYSTEM_PROMPT

    haiku = build_llm(voice_config.load())._llm_instances[0]
    assert haiku.model == "claude-haiku-4-5" and haiku._opts.extra_body == CACHE_SYSTEM_PROMPT
    sonnet = build_llm(voice_config.load(), BY_ID["litellm-claude-sonnet-5-5"])._llm_instances[0]
    assert sonnet._opts.extra_body == CACHE_SYSTEM_PROMPT
    # OpenAI caches long prompts by itself; Groq gets only its own fields
    assert not build_llm(voice_config.load(), BY_ID["litellm-gpt-4o"])._llm_instances[0]._opts.extra_body
    assert build_llm(voice_config.load(), GROQ)._llm_instances[0]._opts.extra_body == dict(GROQ.extra_body)
    monkeypatch.setenv("LLM_PROMPT_CACHE", "0")
    assert not build_llm(voice_config.load())._llm_instances[0]._opts.extra_body
