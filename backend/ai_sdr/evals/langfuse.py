"""Scores on a call's Langfuse trace: its grade, how it ended and its timings, so calls can be filtered and charted
in Langfuse ("every call this week where books_the_yes failed"). Plain REST (one POST /api/public/scores per call,
a list): the Langfuse SDK would install a second OpenTelemetry setup next to LiveKit's. Off unless both keys are set.

The free plan counts every score as a unit, so a call sends about ten: the score, the number of MUST failures, the
outcome, the main timings, and one score per FAILED check (the pass/fail of every check stays in the call report).
Score ids come from the call and the score name, so grading a call again updates its scores instead of adding."""
from __future__ import annotations

import logging
import uuid

import httpx

from ..config import settings

log = logging.getLogger("ai_sdr.evals")

TIMINGS = ("e2e_p50", "e2e_p95", "llm_ttft_p50", "eot_p50")


_project: dict | None = None


def project() -> dict | None:
    """The Langfuse project the keys belong to ({id, name}), for links; None when Langfuse is off or unreachable.
    Asked once per process."""
    global _project
    s = settings()
    if _project is None and s.langfuse_enabled:
        try:
            r = httpx.get(f"{s.langfuse_host}/api/public/projects", timeout=5,
                          auth=(s.langfuse_public_key, s.langfuse_secret_key))
            data = (r.json().get("data") or []) if r.status_code == 200 else []
            if data:
                _project = {"id": data[0]["id"], "name": data[0].get("name")}
        except (httpx.HTTPError, ValueError):
            log.warning("langfuse project lookup failed", exc_info=True)
    return _project


def links() -> dict:
    """What a page needs to link into Langfuse: the project's dashboard (members log in) and the base of a trace's
    address (a public trace opens for anyone)."""
    s = settings()
    p = project()
    base = f"{s.langfuse_host}/project/{p['id']}" if p else None
    return {"enabled": bool(p), "host": s.langfuse_host, "project": p, "dashboard_url": base,
            "trace_url_prefix": f"{base}/traces/" if base else None, "public_channels": s.trace_public}


def _id(room: str, name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ai-sdr/{room}/{name}"))


def scores_for(room: str, grade: dict | None = None, *, outcome: str | None = None, summary: dict | None = None,
               trace_id: str | None = None, environment: str | None = None) -> list[dict]:
    """The score payloads for one call (built here, sent by post())."""
    target = {"traceId": trace_id} if trace_id else {"sessionId": room}
    out: list[dict] = []

    def add(name: str, value, data_type: str, comment: str | None = None) -> None:
        if value is None:
            return
        item = {"id": _id(room, name), **target, "name": name, "value": value, "dataType": data_type}
        if comment:
            item["comment"] = comment[:500]
        if environment:
            item["environment"] = environment
        out.append(item)

    if grade:
        notes = grade.get("notes") or {}
        add("score", grade.get("score"), "NUMERIC",
            f"grader {grade.get('grader')}, judge {grade.get('judge')}. Fix: {notes.get('fix') or '-'}")
        add("must_failed", len(grade.get("must_failed") or []), "NUMERIC", ", ".join(grade.get("must_failed") or []))
        for key, check in (grade.get("checks") or {}).items():
            if check.get("verdict") == "fail":
                comment = check.get("reason", "") + (f' "{check["quote"]}"' if check.get("quote") else "")
                add(f"failed.{key}", 1, "BOOLEAN", comment)
        add("turn_words_avg", (grade.get("counted") or {}).get("turn_words_avg"), "NUMERIC")
    if outcome:
        add("outcome", outcome, "CATEGORICAL")
    for key in TIMINGS:
        add(f"timing.{key}", (summary or {}).get(key), "NUMERIC")
    return out


async def post(scores: list[dict]) -> int:
    """Send one call's scores; returns how many Langfuse accepted. Never raises, never retries (Langfuse asks not to
    retry a partly accepted batch)."""
    s = settings()
    if not s.langfuse_enabled or not scores:
        return 0
    try:
        async with httpx.AsyncClient(base_url=s.langfuse_host, timeout=15,
                                     auth=(s.langfuse_public_key, s.langfuse_secret_key)) as client:
            r = await client.post("/api/public/scores", json=scores)
    except httpx.HTTPError as e:
        log.warning("langfuse scores not sent: %r", e)
        return 0
    if r.status_code in (200, 202):
        return len(scores)
    if r.status_code == 207:
        body = r.json()
        for err in body.get("errors", [])[:5]:
            log.warning("langfuse score rejected: %s", err.get("message"))
        return int(body.get("accepted", 0))
    log.warning("langfuse scores not accepted: %s %s", r.status_code, r.text[:300])
    return 0
