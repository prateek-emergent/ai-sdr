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
