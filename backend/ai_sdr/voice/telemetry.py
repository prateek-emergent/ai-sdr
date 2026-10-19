"""What happened on a call, in one place: a timeline of our own events plus LiveKit's session report (every
session event, per-turn latency), summarised into numbers we can check against the targets.

One report per call, written when the job ends (plan root cause 9: yesterday's "stuck" calls could not be explained
because nothing like this existed)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import VoiceConfig

log = logging.getLogger("ai_sdr.voice")

DEAD_AIR_S = 5.0
LATENCY_KEYS = ("e2e_latency", "llm_node_ttft", "tts_node_ttfb", "end_of_turn_delay", "transcription_delay")


def _pct(values: list[float], q: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 3)
    return round(statistics.quantiles(values, n=100, method="inclusive")[q - 1], 3)


MAX_LOG_LINES = 1500


class CallLogBuffer(logging.Handler):
    """Keeps this call's log lines (INFO and up) for its report, so the metrics page can show them next to the
    timeline. A job runs in its own process, so everything logged here belongs to this call."""

    STALL_FIELDS = ("duration", "gc_time", "cpu_time", "task", "import")

    def __init__(self, t0: float):
        super().__init__(level=logging.INFO)
        self.t0, self.lines, self.dropped = t0, [], 0
        self.stalls: list[dict] = []   # LiveKit's loop monitor: "event loop blocked", with gc and cpu time

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("ai_sdr.worker_output"):
            return
        if len(self.lines) >= MAX_LOG_LINES:
            self.dropped += 1
            return
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        t = round(time.monotonic() - self.t0, 3)
        line = {"t": t, "level": record.levelname, "logger": record.name, "msg": msg[:1000]}
        if msg.startswith("event loop blocked"):
            # keep the monitor's own numbers: gc_time ~ duration means garbage collection, cpu_time ~ 0 means the
            # process wasn't running (CPU starved), else work on the loop (plan round 2)
            stall = {"t": t, **{k: getattr(record, k) for k in self.STALL_FIELDS if hasattr(record, k)}}
            if hasattr(record, "stack"):
                stall["stack"] = str(record.stack)[:1500]
            self.stalls.append(stall)
            line["stall"] = stall
        self.lines.append(line)


class CallTelemetry:
    def __init__(self, cfg: VoiceConfig, *, room: str, job_id: str, channel: str, call_id: Any = None):
        self.cfg = cfg
        self.room, self.job_id, self.channel, self.call_id = room, job_id, channel, call_id
        self.started_at = datetime.now(timezone.utc)
        self._t0 = time.monotonic()
        self.events: list[dict] = []
        self.close: dict | None = None
        self.errors: list[dict] = []
        self.task_failures: list[dict] = []
        self.chars_spoken = 0
        self.turn_detector = None   # set by the worker; .model is read at the end (it can fall back mid-call)
        self.log_buffer = CallLogBuffer(self._t0)
        self.transport: list[dict] = []   # samples of the media path to LiveKit (voice/transport.py)
        logging.getLogger().addHandler(self.log_buffer)

    def now(self) -> float:
        return round(time.monotonic() - self._t0, 3)

    def event(self, kind: str, **data: Any) -> None:
        self.events.append({"t": self.now(), "kind": kind, **data})

    # ---- wiring to the session
    def attach(self, session) -> None:
        session.on("agent_state_changed", lambda ev: self.event("agent_state", state=ev.new_state))
        session.on("user_state_changed", lambda ev: self.event("user_state", state=ev.new_state))
        session.on("conversation_item_added", self._on_item)
        session.on("function_tools_executed", lambda ev: self.event(
            "tools", calls=[c.name for c in ev.function_calls]))
        session.on("agent_false_interruption", lambda ev: self.event("false_interruption"))

    def _on_item(self, ev) -> None:
        item = ev.item
        if getattr(item, "role", None) == "assistant":
            text = item.text_content or ""
            self.chars_spoken += len(text)
            self.event("agent_said", chars=len(text), interrupted=bool(getattr(item, "interrupted", False)))
        elif getattr(item, "role", None) == "user":
            self.event("user_said", words=len((item.text_content or "").split()))

    def transport_sample(self, snap: dict) -> None:
        self.transport.append({"t": self.now(), **snap})

    def error(self, ev) -> None:
        err = ev.error
        rec = {"t": self.now(), "type": getattr(err, "type", type(err).__name__),
               "recoverable": bool(getattr(err, "recoverable", False)),
               "source": getattr(getattr(ev, "source", None), "provider", None) or repr(getattr(ev, "source", None)),
               "error": repr(getattr(err, "error", err))[:300]}
        self.errors.append(rec)
        log.warning("call error %s", rec)

    def task_failed(self, name: str, exc: BaseException) -> None:
        self.task_failures.append({"t": self.now(), "task": name, "error": repr(exc)[:300]})

    def closed(self, reason: str, error: Any, requested: str | None) -> None:
        self.close = {"t": self.now(), "reason": reason, "requested": requested,
                      "error": None if error is None else repr(getattr(error, "error", error))[:300]}
        self.event("closed", reason=reason, requested=requested)

    # ---- the report
    def summary(self, history_items: list[dict]) -> dict:
        vals: dict[str, list[float]] = {k: [] for k in LATENCY_KEYS}
        for item in history_items:
            m = item.get("metrics") or {}
            for k in LATENCY_KEYS:
                if isinstance(m.get(k), (int, float)):
                    vals[k].append(float(m[k]))
        e2e = vals["e2e_latency"]
        return {
            "turns": len(e2e),
            "e2e_p50": _pct(e2e, 50), "e2e_p95": _pct(e2e, 95), "e2e_max": round(max(e2e), 3) if e2e else None,
            "dead_air_turns": sum(1 for v in e2e if v >= DEAD_AIR_S),
            "llm_ttft_p50": _pct(vals["llm_node_ttft"], 50), "llm_ttft_p95": _pct(vals["llm_node_ttft"], 95),
            "tts_ttfb_p50": _pct(vals["tts_node_ttfb"], 50), "tts_ttfb_p95": _pct(vals["tts_node_ttfb"], 95),
            "eot_p50": _pct(vals["end_of_turn_delay"], 50), "eot_p95": _pct(vals["end_of_turn_delay"], 95),
            "eot_hit_max": sum(1 for v in vals["end_of_turn_delay"] if v >= self.cfg.endpointing_max - 0.05),
            "errors": len(self.errors), "task_failures": len(self.task_failures),
            "chars_spoken": self.chars_spoken,
            # first agent audio, counted from when the session was being built (startup steps are in events)
            "opener_audio_s": next((e["t"] for e in self.events
                                    if e["kind"] == "agent_state" and e.get("state") == "speaking"), None),
            "startup": next(({k: v for k, v in e.items() if k not in ("t", "kind")}
                             for e in self.events if e["kind"] == "startup"), {}),
            **self._pauses(),
            **self._stalls(),
            "transport": self.transport[-1] if self.transport else None,
        }

    def _pauses(self) -> dict:
        """Giulia going quiet in the MIDDLE of a line and carrying on: what a caller hears as "stuck". Her line is
        in progress from "speaking" until its item is added ("agent_said"); a "listening" inside that span is a
        pause (LiveKit pauses her on a possible interruption), and "speaking" again before the item ends it."""
        gaps, in_line, paused_at, stops = [], False, None, 0
        for e in self.events:
            if e["kind"] == "agent_said":
                in_line, paused_at = False, None
            elif e["kind"] == "agent_state":
                state = e.get("state")
                if state == "speaking":
                    if paused_at is not None:
                        gaps.append(round(e["t"] - paused_at, 3))
                    in_line, paused_at = True, None
                elif state == "listening" and in_line and paused_at is None:
                    paused_at, stops = e["t"], stops + 1
        return {"false_interruptions": sum(1 for e in self.events if e["kind"] == "false_interruption"),
                # every time she went quiet before her line was done, resumed or not (17 Oct: the probe hung up
                # during a pause, so "resumed pauses" alone missed it)
                "agent_mid_line_stops": stops,
                "agent_pauses": len(gaps), "agent_pause_max_s": max(gaps) if gaps else None,
                "agent_pause_total_s": round(sum(gaps), 3) if gaps else 0.0}

    def _stalls(self) -> dict:
        st = self.log_buffer.stalls
        worst = max(st, key=lambda s: s.get("duration", 0), default=None)
        return {"stalls": len(st), "stall_worst_ms": round(1000 * worst["duration"]) if worst else None,
                "stall_worst_gc_ms": round(1000 * worst.get("gc_time", 0)) if worst else None,
                "stall_worst_cpu_ms": round(1000 * worst.get("cpu_time", 0)) if worst else None}

    def build(self, ctx, session, extra: dict | None = None) -> dict:
        try:
            lk = ctx.make_session_report(session).to_dict()
        except Exception as e:  # never lose our own part of the report
            lk = {"error": repr(e)}
        history = (lk.get("chat_history") or {}).get("items") or []
        if not history:
            try:
                history = session.history.to_dict(exclude_function_call=False).get("items", [])
            except Exception:
                history = []
        td = self.turn_detector
        report = {
            "room": self.room, "job_id": self.job_id, "channel": self.channel, "call_id": self.call_id,
            "agent_name": self.cfg.agent_name, "version": self.cfg.version,
            "started_at": self.started_at.isoformat(), "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": self.now(),
            "config": self.cfg.describe(),
            "turn_detector_used": getattr(td, "model", None),
            "close": self.close, "errors": self.errors, "task_failures": self.task_failures,
            "summary": self.summary(history),
            "events": self.events,
            "logs": self.log_buffer.lines, "logs_dropped": self.log_buffer.dropped,
            "stalls": self.log_buffer.stalls, "transport": self.transport,
            "extra": extra or {},
            "livekit": lk,
        }
        return report

    def detach_logs(self) -> None:
        logging.getLogger().removeHandler(self.log_buffer)

    def log_summary(self, report: dict) -> None:
        s = report["summary"]
        log.info("call_summary %s", json.dumps({
            "room": self.room, "channel": self.channel, "version": self.cfg.version,
            "close": (report.get("close") or {}).get("reason"), "requested": (report.get("close") or {}).get("requested"),
            "turn_detector": report.get("turn_detector_used"), **s}, default=str))


async def save_report(cfg: VoiceConfig, report: dict) -> str:
    """Write the report to the configured sink. Returns where it went."""
    if cfg.report_sink == "mongodb":
        def write() -> str:
            from pymongo import MongoClient
            client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
            try:
                db = client[os.environ.get("DB_NAME", "ai_sdr")]
                db.call_reports.replace_one({"room": report["room"]}, json.loads(json.dumps(report, default=str)),
                                            upsert=True)
            finally:
                client.close()
            return f"mongodb:call_reports/{report['room']}"
        return await asyncio.to_thread(write)
    out = Path(cfg.report_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{report['room']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return str(path)
