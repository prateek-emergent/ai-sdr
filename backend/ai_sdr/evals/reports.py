"""The call reports the grader reads and writes back to: the same place voice/telemetry.py saves them (REPORT_SINK:
mongodb on the pod, one JSON file per call on a laptop). A report's grade lives in its "eval" field."""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..voice import config as voice_config


def _sink() -> tuple[str, Path]:
    """Same rule as VoiceConfig, without loading (and validating) the whole voice config."""
    sink = os.environ.get("REPORT_SINK") or ("mongodb" if os.environ.get("MONGO_URL") else "file")
    default_dir = Path(voice_config.__file__).resolve().parents[3] / "call_reports"
    return sink, Path(os.environ.get("REPORT_DIR") or default_dir)


def _mongo():
    from pymongo import MongoClient
    client = MongoClient(os.environ["MONGO_URL"], serverSelectionTimeoutMS=5000)
    return client, client[os.environ.get("DB_NAME", "ai_sdr")].call_reports


def ungraded(max_age_hours: float = 24, limit: int = 20) -> Iterator[dict]:
    """Finished calls from the last max_age_hours with no grade yet, oldest first. Calls where nobody spoke are
    skipped by the caller (nothing to grade)."""
    since = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    sink, folder = _sink()
    if sink == "mongodb":
        client, coll = _mongo()
        try:
            yield from coll.find({"eval": {"$exists": False}, "ended_at": {"$gte": since.isoformat()}},
                                 {"_id": 0}).sort("ended_at", 1).limit(limit)
        finally:
            client.close()
        return
    if not folder.exists():
        return
    found = []
    for path in folder.glob("*.json"):
        if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < since:
            continue
        try:
            report = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if "eval" not in report:
            found.append(report)
    found.sort(key=lambda r: r.get("ended_at") or "")
    yield from found[:limit]


def recent(hours: float = 168, limit: int = 200) -> list[dict]:
    """Graded calls from the last `hours` (the improvement step reads their failures)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    sink, folder = _sink()
    if sink == "mongodb":
        client, coll = _mongo()
        try:
            return list(coll.find({"eval.score": {"$exists": True}, "ended_at": {"$gte": since}},
                                  {"_id": 0, "logs": 0, "events": 0, "transport": 0}).sort("ended_at", -1).limit(limit))
        finally:
            client.close()
    out = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit * 3]:
        try:
            report = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if (report.get("eval") or {}).get("score") is not None and (report.get("ended_at") or "") >= since:
            out.append(report)
    return out[:limit]


# what the Quality page needs from each report (not the logs, events or transport samples)
LIST_FIELDS = ("room", "channel", "started_at", "ended_at", "duration_s", "version", "agent_name", "close", "summary",
               "extra", "eval", "eval_reviews", "eval_regrades", "trace_id")


def calls(hours: float = 168, limit: int = 300) -> list[dict]:
    """Calls from the last `hours`, newest first, graded or not, with only LIST_FIELDS."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    sink, folder = _sink()
    if sink == "mongodb":
        client, coll = _mongo()
        try:
            return list(coll.find({"started_at": {"$gte": since}}, {"_id": 0, **{f: 1 for f in LIST_FIELDS}})
                        .sort("started_at", -1).limit(limit))
        finally:
            client.close()
    out = []
    if folder.exists():
        for path in folder.glob("*.json"):
            try:
                report = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if (report.get("started_at") or "") >= since:
                out.append({f: report.get(f) for f in LIST_FIELDS if f in report})
    out.sort(key=lambda r: r.get("started_at") or "", reverse=True)
    return out[:limit]


def _push(room: str, field: str, value: dict) -> bool:
    """Append to a list field of one report (reviews and re-grades). False if the call isn't there."""
    sink, folder = _sink()
    value = json.loads(json.dumps(value, default=str))
    if sink == "mongodb":
        client, coll = _mongo()
        try:
            return coll.update_one({"room": room}, {"$push": {field: value}}).matched_count == 1
        finally:
            client.close()
    path = folder / f"{room}.json"
    if not path.exists():
        return False
    report = json.loads(path.read_text())
    report.setdefault(field, []).append(value)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return True


def save_review(room: str, review: dict) -> bool:
    return _push(room, "eval_reviews", review)


def save_regrade(room: str, regrade: dict) -> bool:
    return _push(room, "eval_regrades", regrade)


def get(room: str) -> dict | None:
    sink, folder = _sink()
    if sink == "mongodb":
        client, coll = _mongo()
        try:
            return coll.find_one({"room": room}, {"_id": 0})
        finally:
            client.close()
    path = folder / f"{room}.json"
    return json.loads(path.read_text()) if path.exists() else None


def save_eval(room: str, grade: dict) -> None:
    sink, folder = _sink()
    if sink == "mongodb":
        client, coll = _mongo()
        try:
            coll.update_one({"room": room}, {"$set": {"eval": json.loads(json.dumps(grade, default=str))}})
        finally:
            client.close()
        return
    path = folder / f"{room}.json"
    report = json.loads(path.read_text())
    report["eval"] = grade
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
