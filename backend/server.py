"""AI SDR on Emergent: the "Talk to Giulia" web backend. Source of truth: ai-sdr/pipeline/deploy/emergent (copied to
the pod by deploy/sync_pod.py, never edited on the pod).

- POST /api/session            a fresh LiveKit room per click, the agent dispatched into it (alias: /api/demo/start)
- GET  /health, /api/health    the backend AND the voice worker: ready = registered with LiveKit, right code version
- GET  /api/calls/{room}/report  the call report (timeline, latency, close reason) + the browser's events   [token]
- GET  /api/calls/stats          numbers over recent calls                                                    [token]
- POST /api/client-events        the page reports what the person experienced (connected, audio blocked...)
- GET  /api/agent-log            tail of the voice worker's log                                               [token]

On startup it launches the voice worker supervisor (ai_sdr.voice.run): one per machine, survives backend reloads,
restarts the worker if it dies, and rolls over to new code while calls in progress finish. It also launches the
call grader (ai_sdr.evals.watch, 20 Oct): every finished call is graded into its report, and onto its Langfuse trace
when tracing is on. EVALS_AUTO=0 turns the grader off.
"""
import json
import logging
import os
import secrets
import socket
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from livekit import api
from pydantic import BaseModel, Field

from ai_sdr.voice.catalog import BY_ID as VOICE_CATALOG, public as voice_catalog
from ai_sdr.voice import llm_catalog

ROOT = Path(__file__).parent
# Settings the platform itself provides (on the deployed app: Emergent's Secrets panel) are in the environment before
# .env is read; remember their NAMES so the voice supervisor never lets the deployed app's frozen .env copy override
# them (19 Oct: prod's worker used the old ElevenLabs + deleted LiteLLM keys from that copy).
_PLATFORM_KEYS = set(os.environ)
load_dotenv(ROOT / ".env")
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ai-sdr-backend")

# Each environment has its own agent name so preview and the deployed app never answer each other's calls (16 Oct).
# The preview pod's hostname is agent-env-<id>; if its .env still says the deployed name, keep them apart anyway.
AGENT = os.environ.get("AGENT_NAME", "ai-sdr")
if socket.gethostname().startswith("agent-env-") and not AGENT.endswith("-preview"):
    log.warning("preview pod with AGENT_NAME=%s: using %s-preview", AGENT, AGENT)
    AGENT += "-preview"
STATUS = Path(os.environ.get("AGENT_STATUS", "/tmp/ai_sdr_agent_status.json"))
AGENT_LOG = Path(os.environ.get("AGENT_LOG", "/tmp/ai_sdr_agent.log"))
VERSION = (ROOT / "ai_sdr" / "VERSION").read_text().strip() if (ROOT / "ai_sdr" / "VERSION").exists() else "unknown"
SESSION_TTL = timedelta(hours=2)
REQUIRED = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "MONGO_URL")
MISSING = [k for k in REQUIRED if not os.environ.get(k)]
if MISSING:
    log.error("missing settings: %s", ", ".join(MISSING))
MAX_CLIENT_EVENTS = 300

app = FastAPI(title="AI SDR")
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])

_mongo = None


def db():
    """The app's MongoDB (call reports are written by the worker; sessions and client events by this backend)."""
    global _mongo
    if _mongo is None:
        from pymongo import MongoClient
        _mongo = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
    return _mongo[os.environ.get("DB_NAME", "ai_sdr")]


def _require_token(token: str) -> None:
    expected = os.environ.get("DEBUG_TOKEN", "")
    if not expected or not secrets.compare_digest(token or "", expected):
        raise HTTPException(status_code=404)


def _env_file_keys() -> set[str]:
    from dotenv import dotenv_values
    try:
        return set(dotenv_values(ROOT / ".env"))
    except Exception:
        return set()


@app.on_event("startup")
def start_voice_worker() -> None:
    if os.environ.get("RUN_AGENT", "1") != "1":
        return
    env = {**os.environ, "AGENT_NAME": AGENT, "AGENT_STATUS": str(STATUS), "AGENT_LOG": str(AGENT_LOG),
           # the supervisor re-reads .env for every worker; these values are this backend's decision, keep them
           "SUPERVISOR_PINNED": "AGENT_NAME,AGENT_STATUS,AGENT_LOG",
           "SUPERVISOR_PLATFORM_KEYS": ",".join(sorted(k for k in _PLATFORM_KEYS if k in _env_file_keys()))}
    # the supervisor exits at once if one is already running (lock); its own session keeps live calls alive when
    # this backend reloads. Its output goes to its own rotating log, never to this process's stdout.
    subprocess.Popen([sys.executable, "-m", "ai_sdr.voice.run"], cwd=ROOT, env=env, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log.info("voice worker supervisor launch requested (agent %s, code %s)", AGENT, VERSION)
    if os.environ.get("EVALS_AUTO", "1") != "0":
        # same pattern: its own process and session, one per machine (lock), restarts itself on new code
        subprocess.Popen([sys.executable, "-m", "ai_sdr.evals.watch"], cwd=ROOT, env={**os.environ, "AGENT_NAME": AGENT},
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import threading
    threading.Thread(target=_indexes, daemon=True).start()


def _indexes() -> None:
    """Indexes for the metrics page (newest calls first) and the per-room lookups. Off the startup path."""
    try:
        db().call_reports.create_index("started_at")
        db().call_reports.create_index("room")
        db().client_events.create_index("room")
        db().sessions.create_index("room")
    except Exception:
        log.exception("could not create indexes")


def _voice_status() -> dict:
    try:
        st = json.loads(STATUS.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"ready": False, "problem": "voice worker supervisor not running yet"}
    w = st.get("worker") or {}
    stale = time.time() - st.get("updated_at", 0) > 15
    problems = []
    if stale:
        problems.append("supervisor not updating its status")
    if st.get("phase") not in (None, "running"):
        problems.append(f"voice worker {st['phase']}")
    elif not w.get("alive"):
        problems.append("worker not running")
    elif not w.get("registered"):
        problems.append("worker not registered with LiveKit yet")
    if w.get("version") not in (None, VERSION):
        problems.append(f"worker runs code {w.get('version')}, backend has {VERSION}")
    return {"ready": not problems, "problems": problems, "agent": AGENT, "worker_version": w.get("version"),
            "worker_up_s": w.get("up_s"), "restarts": st.get("restarts"), "last_exit": st.get("last_exit"),
            "draining": len(st.get("draining") or []), "health_port": w.get("port")}


@app.get("/health")  # the deployment's liveness probe: stays 200 while the backend works; "voice" tells the rest
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "ai-sdr", "agent": AGENT, "version": VERSION,
            "language": os.environ.get("AGENT_LANGUAGE", "it"),
            "languages": os.environ.get("AGENT_LANGUAGES", "it,en"), "missing_settings": MISSING,
            "voice": _voice_status()}


class SessionStart(BaseModel):
    name: str = Field("", max_length=60)
    tz: str | None = Field(None, max_length=60)
    # the call's language (customers get Italian; the team also tests in English) and, optionally, an app for
    # Giulia to talk about, as on a real call where the customer card names what they built
    language: str | None = Field(None, max_length=5)
    app: str | None = Field(None, max_length=60)
    # a voice the page offers (ai_sdr/voice/catalog.py), to hear this test call in it
    voice: str | None = Field(None, max_length=60)
    # a model the page offers (ai_sdr/voice/llm_catalog.py), to compare its speed on this test call
    llm: str | None = Field(None, max_length=60)
    # test calls only (the probe): pick the voice chain, e.g. ["deepgram"] so automated runs don't spend
    # ElevenLabs credits. Ignored without the debug token.
    tts_chain: list[str] | None = Field(None, max_length=3)
    test_token: str | None = Field(None, max_length=100)


@app.get("/api/voices")
def voices() -> dict:
    """The voices the Talk page offers, five per language (ai_sdr/voice/catalog.py)."""
    return {"voices": voice_catalog()}


@app.get("/api/llms")
def llms() -> dict:
    """The models the Talk page offers (ai_sdr/voice/llm_catalog.py); a provider without its key is listed as such."""
    return {"default": llm_catalog.default_label(), "default_model": llm_catalog.default_model(),
            "llms": llm_catalog.public()}


@app.post("/api/session")
@app.post("/api/demo/start")  # the old page's endpoint, until every client uses /api/session
def session_start(body: SessionStart, background: BackgroundTasks) -> dict:
    if any(k.startswith("LIVEKIT") for k in MISSING):
        raise HTTPException(status_code=503, detail=f"server is missing settings: {', '.join(MISSING)}")
    room = f"demo-{secrets.token_hex(4)}"
    meta = {"direction": "web", "first_name": body.name.strip(),
            "tz": body.tz or os.environ.get("DEMO_TZ", "Europe/Rome")}
    if body.language in ("it", "en"):
        meta["language"] = body.language
    if body.app and body.app.strip():
        meta["app"] = body.app.strip()
    if body.voice in VOICE_CATALOG:
        meta["voice"] = body.voice
    if body.llm in llm_catalog.BY_ID and llm_catalog.available(llm_catalog.BY_ID[body.llm]):
        meta["llm"] = body.llm
    expected = os.environ.get("DEBUG_TOKEN", "")
    if body.tts_chain and expected and secrets.compare_digest(body.test_token or "", expected):
        meta["tts_chain"] = [t for t in body.tts_chain if t in ("deepgram", "elevenlabs", "livekit")]
    token = (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
             .with_identity(f"web-{secrets.token_hex(3)}").with_name(body.name or "Guest")
             .with_grants(api.VideoGrants(room_join=True, room=room))
             .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(
                 agent_name=AGENT, metadata=json.dumps(meta))]))
             .with_ttl(SESSION_TTL).to_jwt())
    background.add_task(_record_session, room)  # after the response: a click never waits on bookkeeping
    return {"url": os.environ["LIVEKIT_URL"], "token": token, "room": room, "agent": AGENT}


def _record_session(room: str) -> None:
    try:
        db().sessions.insert_one({"room": room, "created_at": datetime.now(timezone.utc), "agent": AGENT,
                                  "version": VERSION})
    except Exception:
        log.exception("could not record the session")


class ClientEvents(BaseModel):
    room: str = Field(..., max_length=40)
    events: list[dict] = Field(..., max_length=50)


@app.post("/api/client-events")
def client_events(body: ClientEvents) -> dict:
    """What the person's browser saw. Only for rooms this backend created in the last 2 hours, capped per room."""
    since = datetime.now(timezone.utc) - SESSION_TTL
    if not db().sessions.find_one({"room": body.room, "created_at": {"$gte": since}}):
        raise HTTPException(status_code=404)
    n = db().client_events.count_documents({"room": body.room})
    keep = [{"room": body.room, "received_at": datetime.now(timezone.utc),
             **{k: v for k, v in e.items() if isinstance(k, str) and len(k) < 40}}
            for e in body.events[: max(0, MAX_CLIENT_EVENTS - n)]]
    if keep:
        db().client_events.insert_many(keep)
    return {"stored": len(keep)}


@app.get("/api/calls")
def call_list(token: str = "", limit: int = 50, before: str = "", channel: str = "") -> dict:
    """Newest calls first, one line each (the metrics page list). Page with ?before=<started_at of the last row>."""
    _require_token(token)
    q: dict = {}
    if before:
        q["started_at"] = {"$lt": before}
    if channel in ("web", "phone"):
        q["channel"] = channel
    rows = list(db().call_reports.find(q, {
        "_id": 0, "room": 1, "channel": 1, "started_at": 1, "ended_at": 1, "duration_s": 1, "version": 1,
        "agent_name": 1, "close": 1, "summary": 1, "turn_detector_used": 1, "extra.disposition": 1,
        "config.tts_chain": 1, "config.turn_detector": 1}).sort("started_at", -1).limit(max(1, min(limit, 200))))
    return json.loads(json.dumps({"calls": rows}, default=str))


@app.get("/api/calls/{room}/report")
def call_report(room: str, token: str = ""):
    _require_token(token)
    report = db().call_reports.find_one({"room": room}, {"_id": 0})
    if report is None:
        return JSONResponse({"detail": "report pending"}, status_code=404)
    report["client_events"] = list(db().client_events.find({"room": room}, {"_id": 0, "room": 0}).limit(500))
    return JSONResponse(json.loads(json.dumps(report, default=str)))


def _pct(v: list[float], q: int):
    return None if not v else round(v[0], 3) if len(v) == 1 else round(
        statistics.quantiles(v, n=100, method="inclusive")[q - 1], 3)


@app.get("/api/calls/stats")
def call_stats(token: str = "", hours: int = 24) -> dict:
    _require_token(token)
    since = (datetime.now(timezone.utc) - timedelta(hours=max(1, min(hours, 24 * 30)))).isoformat()
    reports = list(db().call_reports.find({"ended_at": {"$gte": since}},
                                          {"_id": 0, "summary": 1, "close": 1, "turn_detector_used": 1,
                                           "config.turn_detector": 1, "version": 1, "room": 1}))
    e2e = [r["summary"]["e2e_p50"] for r in reports if (r.get("summary") or {}).get("e2e_p50") is not None]
    reasons: dict[str, int] = {}
    for r in reports:
        key = f"{(r.get('close') or {}).get('reason')}/{(r.get('close') or {}).get('requested')}"
        reasons[key] = reasons.get(key, 0) + 1
    return {"calls": len(reports), "close_reasons": reasons,
            "per_call_e2e_p50": {"p50": _pct(e2e, 50), "p95": _pct(e2e, 95)},
            "dead_air_turns": sum((r.get("summary") or {}).get("dead_air_turns", 0) for r in reports),
            "errors": sum((r.get("summary") or {}).get("errors", 0) for r in reports),
            "task_failures": sum((r.get("summary") or {}).get("task_failures", 0) for r in reports),
            "turn_detector_fallbacks": sum(1 for r in reports if (r.get("config") or {}).get("turn_detector") == "v1"
                                           and r.get("turn_detector_used") != "turn-detector-v1"),
            "versions": sorted({r.get("version") for r in reports if r.get("version")})}


# ---- observability and grading (20 Oct): Langfuse links for every page, the Quality page's data
@app.get("/api/observability")
def observability() -> dict:
    """Langfuse links (no token: a project id and a host are not secrets; a trace opens only if it was made public)."""
    from ai_sdr.evals import langfuse
    return {"langfuse": langfuse.links()}


@app.get("/api/quality/rubric")
def quality_rubric() -> dict:
    from ai_sdr.config import settings
    from ai_sdr.evals.grade import GRADER_VERSION
    from ai_sdr.evals.quality import rubric
    return rubric(settings().eval_judge_model, GRADER_VERSION)


def _quality_reports(hours: int, channel: str, turns: bool = False) -> list[dict]:
    from ai_sdr.evals import reports
    rows = reports.calls(hours=max(1, min(hours, 24 * 30)), limit=500, turns=turns)
    return [r for r in rows if not channel or r.get("channel") == channel]


@app.get("/api/quality/summary")
def quality_summary(token: str = "", hours: int = 168, channel: str = "") -> dict:
    _require_token(token)
    from ai_sdr.evals.quality import speed, summary
    rows = _quality_reports(hours, channel, turns=True)   # turns: each reply's numbers, for speed per model
    return json.loads(json.dumps({**summary(rows), "speed": speed(rows)}, default=str))


@app.get("/api/quality/calls")
def quality_calls(token: str = "", hours: int = 168, channel: str = "", check: str = "", limit: int = 100) -> dict:
    """The graded calls, newest first; check=<key> keeps the calls where that check failed."""
    _require_token(token)
    from ai_sdr.evals.quality import row
    rows = [row(r) for r in _quality_reports(hours, channel)]
    if check:
        rows = [r for r in rows if check in r["failed"]]
    return json.loads(json.dumps({"calls": rows[:max(1, min(limit, 300))]}, default=str))


@app.get("/api/quality/calls/{room}")
def quality_call(room: str, token: str = ""):
    _require_token(token)
    from ai_sdr.evals import reports
    from ai_sdr.evals.quality import latest_reviews, row
    report = reports.get(room)
    if report is None:
        raise HTTPException(status_code=404)
    items = [i for i in ((report.get("livekit") or {}).get("chat_history") or {}).get("items") or []
             if i.get("type") in ("message", "function_call", "function_call_output")]
    return JSONResponse(json.loads(json.dumps({
        **row(report), "eval": report.get("eval"), "reviews": latest_reviews(report),
        "regrades": report.get("eval_regrades") or [], "summary": report.get("summary"), "items": items,
        "close": report.get("close")}, default=str)))


class Review(BaseModel):
    check: str = Field(max_length=40)
    agree: bool                                         # the grader's verdict is right
    verdict: str | None = Field(default=None, pattern="^(pass|fail|n/a)$")   # what it should be, when it isn't
    note: str = Field(default="", max_length=500)


@app.post("/api/quality/calls/{room}/review")
async def quality_review(room: str, body: Review, token: str = "") -> dict:
    """A person marks one of the grader's verdicts right or wrong: the grader's own report card."""
    _require_token(token)
    import asyncio
    from ai_sdr.evals import langfuse, reports
    report = await asyncio.to_thread(reports.get, room)
    checks = ((report or {}).get("eval") or {}).get("checks") or {}
    if body.check not in checks:
        raise HTTPException(status_code=404)
    review = {**body.model_dump(), "judge_verdict": checks[body.check].get("verdict"),
              "grader": report["eval"].get("grader"), "at": datetime.now(timezone.utc).isoformat()}
    await asyncio.to_thread(reports.save_review, room, review)
    # also on the call's Langfuse trace, so the judge's misses can be filtered there too
    await langfuse.post([{"id": langfuse._id(room, f"review.{body.check}"), "name": f"review.{body.check}",
                          "value": 1 if body.agree else 0, "dataType": "BOOLEAN", "comment": body.note or None,
                          **({"traceId": report["trace_id"]} if report.get("trace_id") else {"sessionId": room})}])
    return {"saved": True, "review": review}


@app.post("/api/quality/calls/{room}/regrade")
async def quality_regrade(room: str, token: str = "") -> dict:
    """Grade the call again with the same judge: checks whose verdict flips are ones the judge can't decide
    consistently (the page's consistency figure)."""
    _require_token(token)
    import asyncio
    from ai_sdr.evals import reports
    from ai_sdr.evals.grade import grade
    from ai_sdr.evals.quality import compare
    from ai_sdr.evals.rubric import ending_of
    from ai_sdr.evals.watch import items_of, language_of
    report = await asyncio.to_thread(reports.get, room)
    original = ((report or {}).get("eval") or {}).get("checks")
    if not original:
        raise HTTPException(status_code=404)
    again = await grade(items_of(report), language_of(report), ending=ending_of(report.get("close")))
    entry = {"at": again["graded_at"], "grader": again["grader"], "judge": again["judge"], "score": again["score"],
             "took_s": again.get("took_s"),
             "checks": {k: {"verdict": c["verdict"], "reason": c["reason"]} for k, c in again["checks"].items()}}
    await asyncio.to_thread(reports.save_regrade, room, entry)
    return {"original_score": report["eval"].get("score"), "score": again["score"],
            **compare(original, again["checks"]), "checks": entry["checks"]}


@app.get("/api/agent-log")
def agent_log(token: str = "", lines: int = 200):
    """Last lines of the voice worker's log (reads only the end of the file)."""
    _require_token(token)
    lines = max(1, min(lines, 2000))
    try:
        with open(AGENT_LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - lines * 600))
            text = f.read().decode(errors="replace").splitlines()[-lines:]
    except FileNotFoundError:
        text = ["(no agent log yet)"]
    return PlainTextResponse("\n".join(text))
