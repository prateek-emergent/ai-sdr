"""20 Oct: the Quality page's numbers and endpoints (evals/quality.py, server.py /api/quality/*), and the live timing
events the Talk page draws (voice/live.py). Call reports are JSON files in a temporary folder."""
import json

import pytest
from fastapi.testclient import TestClient

from ai_sdr.evals.quality import compare, regrade_stats, review_stats, row, summary
from ai_sdr.voice.live import turn_payload


def report(room, *, score=None, checks=None, skipped=None, started="2026-10-20T10:00:00+00:00", **more):
    r = {"room": room, "channel": "web", "started_at": started, "ended_at": started, "agent_name": "ai-sdr-local",
         "summary": {"e2e_p50": 1.3, "turns": 4}, "extra": {"disposition": "callback", "language": "it"},
         "trace_id": "ab" * 16,
         "livekit": {"chat_history": {"items": [
             {"type": "message", "role": "assistant", "content": ["Buongiorno, sono Giulia, l'assistente AI."]},
             {"type": "message", "role": "user", "content": ["Mi richiami domani."]}]}}, **more}
    if score is not None or skipped:
        r["eval"] = {"grader": "g2", "judge": "j", "took_s": 12.0, "score": score, "skipped": skipped,
                     "checks": checks or {}, "failed": [k for k, c in (checks or {}).items() if c["verdict"] == "fail"],
                     "must_failed": []}
    return r


CHECKS = {"no_echo": {"verdict": "fail", "reason": "echoed", "quote": "Quindi..."},
          "language": {"verdict": "pass", "reason": "ok", "quote": ""},
          "callback_done": {"verdict": "n/a", "reason": "-", "quote": ""}}


def test_summary_counts_checks_and_trend():
    reports = [report("a", score=0.5, checks=CHECKS), report("b", skipped="the person never spoke"), report("c")]
    s = summary(reports)
    assert (s["calls"], s["graded"], s["skipped"], s["ungraded"]) == (3, 1, 1, 1)
    assert s["checks"]["no_echo"] == {**s["checks"]["no_echo"], "applied": 1, "failed": 1, "pass_rate": 0.0}
    assert s["checks"]["callback_done"]["applied"] == 0 and s["checks"]["callback_done"]["na"] == 1
    assert s["trend"] == [{"day": "2026-10-20", "calls": 3, "graded": 1, "score": 0.5, "reply_s": 1.3}]
    assert s["outcomes"] == {"callback": 3} and s["grader"]["took_s_p50"] == 12.0


def test_reviews_and_regrades_measure_the_grader():
    r = report("a", score=0.5, checks=CHECKS,
               eval_reviews=[{"check": "no_echo", "agree": True}, {"check": "no_echo", "agree": False},
                             {"check": "language", "agree": True}],
               eval_regrades=[{"checks": {"no_echo": {"verdict": "pass"}, "language": {"verdict": "pass"}}}])
    reviews = review_stats([r])   # the latest review of a check counts
    assert (reviews["reviewed"], reviews["agree"]) == (2, 1)
    assert reviews["per_check"]["no_echo"] == {"reviewed": 1, "agree": 0, "rate": 0.0}
    again = regrade_stats([r])
    assert (again["compared"], again["same"]) == (2, 1) and again["per_check"]["no_echo"]["rate"] == 0.0
    assert compare(CHECKS, {"no_echo": {"verdict": "pass"}, "language": {"verdict": "pass"}}) == \
        {"total": 2, "same": 1, "flipped": ["no_echo"]}
    assert row(r)["reviewed"] == 2 and row(r)["disagreed"] == 1


def test_live_turn_timings():
    user = turn_payload("user", {"end_of_turn_delay": 0.4321, "transcription_delay": 0.2,
                                 "stt_metadata": {"model_name": "nova-3"}})
    assert user == {"role": "user", "stt_s": 0.2, "eot_s": 0.432, "stt_model": "nova-3"}
    agent = turn_payload("assistant", {"e2e_latency": 1.21, "llm_node_ttft": 0.62, "tts_node_ttfb": 0.11,
                                       "llm_metadata": {"model_name": "claude-haiku-4-5"}}, interrupted=True)
    assert agent["e2e_s"] == 1.21 and agent["llm_model"] == "claude-haiku-4-5" and agent["interrupted"] is True
    assert turn_payload("assistant", {}) is None   # the opener and code-said lines carry no timings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_SINK", "file")
    monkeypatch.setenv("REPORT_DIR", str(tmp_path))
    monkeypatch.setenv("DEBUG_TOKEN", "secret")
    monkeypatch.setenv("RUN_AGENT", "0")
    now = "2099-01-01T10:00:00+00:00"   # inside any "last N hours" window
    for r in (report("demo-a", score=0.5, checks=CHECKS, started=now), report("demo-b", started=now)):
        (tmp_path / f"{r['room']}.json").write_text(json.dumps(r))
    import server
    return TestClient(server.app), tmp_path


def test_quality_endpoints(client):
    c, folder = client
    assert c.get("/api/quality/summary?token=wrong").status_code == 404
    s = c.get("/api/quality/summary?token=secret").json()
    assert s["graded"] == 1 and s["ungraded"] == 1
    calls = c.get("/api/quality/calls?token=secret&check=no_echo").json()["calls"]
    assert [x["room"] for x in calls] == ["demo-a"]
    detail = c.get("/api/quality/calls/demo-a?token=secret").json()
    assert detail["eval"]["score"] == 0.5 and len(detail["items"]) == 2
    saved = c.post("/api/quality/calls/demo-a/review?token=secret",
                   json={"check": "no_echo", "agree": False, "verdict": "pass", "note": "a time confirmation"})
    assert saved.status_code == 200 and saved.json()["review"]["judge_verdict"] == "fail"
    on_disk = json.loads((folder / "demo-a.json").read_text())
    assert on_disk["eval_reviews"][0]["verdict"] == "pass"
    assert c.post("/api/quality/calls/demo-a/review?token=secret", json={"check": "nope", "agree": True}).status_code == 404
    assert c.get("/api/quality/rubric").json()["checks"][0]["key"] == "ai_disclosure"
    assert c.get("/api/observability").json()["langfuse"]["enabled"] is False   # no keys in tests
