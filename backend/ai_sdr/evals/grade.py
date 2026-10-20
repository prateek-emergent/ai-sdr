"""Grade one call: the judged checks (one judge call reads the whole transcript), the counted checks, and, for a
simulated call, whether it reached what its scenario expects.

The judge is a stronger model than the one on the call (EVAL_JUDGE_MODEL, default claude-sonnet-5-5 on the same
gateway): a judge as weak as the agent misses the agent's own blind spots. It writes in English for both languages."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, create_model

from ..agent.prompts import allowed_claims
from ..config import settings
from ..llm import structured
from .rubric import BY_KEY, CHECKS, MUST, counted, transcript

log = logging.getLogger("ai_sdr.evals")

GRADER_VERSION = "g1"   # bump when the checks change, so trends compare like with like


class Verdict(BaseModel):
    verdict: Literal["pass", "fail", "n/a"]
    reason: str = Field(description="one short sentence, in English")
    quote: str = Field(default="", description="the agent's own words that show it, verbatim, or empty")


class Notes(BaseModel):
    worst_moment: str = Field(description="the single agent turn that hurt the call most, and why, in English")
    fix: str = Field(description="the one change to the agent's instructions that would most improve this call, "
                                 "in English, concrete enough to write into a prompt; empty if none")


Judgment = create_model("Judgment", **{c.key: (Verdict, ...) for c in CHECKS}, notes=(Notes, ...))

SYSTEM = (
    "You grade phone calls made by Giulia, an AI assistant who calls customers of Emergent (an AI app builder) to "
    "hear how it is going and, when they have a real need, books a free call with an expert. Calls are in Italian "
    "or English; grade in English. The transcript is speech-to-text, so the PERSON's words can be garbled: judge "
    "the agent on what a careful listener could have understood. [tool] lines are the agent's actions and [result] "
    "lines what the system answered.\n"
    "For each check answer pass, fail or n/a (only when the check says when n/a applies, or the situation never "
    "arose). Be strict: one clear breach is a fail, but never fail the agent for saying what her instructions tell "
    "her to say. Quote the agent verbatim when you fail a check.\n"
    "Approved lines (from her instructions, true as said): at the end of a booked call 'I've noted that and passed "
    "it on to our experts. They'll look into it and go through it with you on the call' (every call's summary "
    "reaches the team automatically); 'Your feedback's been noted and our experts will be working on it'; after "
    "log_support_issue, 'someone from the team will follow up by email'; a taken time said naturally ('Ten on "
    "Thursday's already taken, unfortunately').\n\n"
    "The only claims the agent may make about the company:\n")


def _checklist() -> str:
    return "\n".join(f"- {c.key}{' (MUST)' if c.must else ''}: {c.question}" for c in CHECKS)


def judge_model() -> str:
    return settings().eval_judge_model


async def judge(items: list[dict], language: str, *, extra: str = "", ending: str | None = None) -> BaseModel:
    text = transcript(items, ending)
    prompt = (f"Call language: {'Italian' if language == 'it' else 'English'}.\n\nChecks:\n{_checklist()}\n"
              f"{extra}\nTranscript:\n{text}")
    return await structured(SYSTEM + allowed_claims("en"), prompt, Judgment, model=judge_model(), max_tokens=3000)


def score(checks: dict[str, dict]) -> float | None:
    """Share of the checks that applied which passed (n/a left out)."""
    applied = [c["verdict"] for c in checks.values() if c["verdict"] != "n/a"]
    return round(sum(v == "pass" for v in applied) / len(applied), 3) if applied else None


async def grade(items: list[dict], language: str, *, extra: str = "", ending: str | None = None) -> dict:
    """The grade stored in the call report (and pushed to Langfuse as scores). ending: how the call ended."""
    j = await judge(items, language, extra=extra, ending=ending)
    checks = {c.key: getattr(j, c.key).model_dump() for c in CHECKS}
    return {
        "grader": GRADER_VERSION, "judge": judge_model(),
        "graded_at": datetime.now(timezone.utc).isoformat(),
        "score": score(checks),
        "must_failed": [k for k in MUST if checks[k]["verdict"] == "fail"],
        "failed": [k for k, c in checks.items() if c["verdict"] == "fail"],
        "checks": checks,
        "notes": j.notes.model_dump(),
        "counted": counted(items, language),
    }


def describe(check: str) -> str:
    return BY_KEY[check].question if check in BY_KEY else check
