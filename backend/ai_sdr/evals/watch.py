"""Grade every call once it has ended: the judged and counted checks (grade.py) go into the call report's "eval"
field and, when Langfuse is on, onto the call's trace with its outcome and timings (langfuse.py).

Started by the web backend next to the voice supervisor (`python -m ai_sdr.evals.watch`), never inside the voice
worker: grading takes seconds and a live call must never wait for it. One per machine (a lock); it restarts itself
when the code version changes (a pull to the pod). EVALS_AUTO=0 turns it off."""
from __future__ import annotations

import asyncio
import fcntl
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from . import langfuse
from .grade import GRADER_VERSION, grade
from .reports import save_eval, ungraded
from .rubric import ending_of

log = logging.getLogger("ai_sdr.evals")

POLL_S = 20
LOCK = Path(os.environ.get("EVALS_LOCK", "/tmp/ai_sdr_evals.lock"))
LOG = Path(os.environ.get("EVALS_LOG", "/tmp/ai_sdr_evals.log"))
VERSION_FILE = Path(__file__).resolve().parents[1] / "VERSION"


def _version() -> str:
    try:
        return VERSION_FILE.read_text().strip()
    except FileNotFoundError:
        return "unknown"


def items_of(report: dict) -> list[dict]:
    return ((report.get("livekit") or {}).get("chat_history") or {}).get("items") or []


def language_of(report: dict) -> str:
    return (report.get("extra") or {}).get("language") or (report.get("config") or {}).get("language") or "it"


def outcome_of(report: dict) -> str | None:
    extra = report.get("extra") or {}
    if extra.get("voicemail"):
        return "voicemail"
    return extra.get("disposition") or extra.get("outcome")


def person_spoke(items: list[dict]) -> bool:
    return any(it.get("type") == "message" and it.get("role") == "user"
               and any(isinstance(c, str) and c.strip() for c in it.get("content", [])) for it in items)


async def grade_report(report: dict) -> dict:
    """Grade one report, store the grade, send the scores. Returns the grade."""
    items = items_of(report)
    if not person_spoke(items):   # stored too, so the call is not picked up again
        result = {"grader": GRADER_VERSION, "graded_at": datetime.now(timezone.utc).isoformat(),
                  "skipped": "the person never spoke"}
    else:
        result = await grade(items, language_of(report), ending=ending_of(report.get("close")))
    save_eval(report["room"], result)
    sent = await langfuse.post(langfuse.scores_for(
        report["room"], result if "skipped" not in result else None, outcome=outcome_of(report),
        summary=report.get("summary"), trace_id=report.get("trace_id"), environment=report.get("agent_name")))
    log.info("graded %s: score %s, failed %s, %d scores to langfuse", report["room"], result.get("score"),
             result.get("failed") or result.get("skipped"), sent)
    return result


async def run_forever() -> None:
    started_on = _version()
    while True:
        if _version() != started_on:   # new code on the machine: start again with it
            log.info("code changed (%s -> %s): restarting", started_on, _version())
            os.execv(sys.executable, [sys.executable, "-m", "ai_sdr.evals.watch"])
        for report in list(ungraded()):
            try:
                await grade_report(report)
            except Exception:  # noqa: BLE001 - one bad report must not stop the others
                log.exception("could not grade %s", report.get("room"))
        await asyncio.sleep(POLL_S)


def main() -> None:
    handler = logging.handlers.RotatingFileHandler(LOG, maxBytes=2_000_000, backupCount=2)
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if not settings().evals_auto:
        log.info("EVALS_AUTO=0: not grading")
        return
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("another grader is running")
        return
    log.info("grading calls (code %s, judge %s, langfuse %s)", _version(), settings().eval_judge_model,
             "on" if settings().langfuse_enabled else "off")
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
