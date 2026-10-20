"""Simulated calls: a model plays the customer of a scenario (scenarios.py) and talks to the real Giulia (same prompt,
same tools, same LLM route as a call), in text: no audio, no room, the fake calendar, nothing written anywhere. Each
call is graded like a real one, plus whether it reached the outcome its scenario expects.

    python -m ai_sdr.cli evals simulate                       # every scenario once
    python -m ai_sdr.cli evals simulate --scenario it_dnc,it_busy_callback --repeat 3

A suite writes its calls and a summary under EVAL_DIR/runs/<run id>/ (summary.md is the one to read); with --trace
(and Langfuse keys) every simulated call is also a Langfuse session tagged "simulation", with its scores. Off by
default: the free plan's units are better spent on real calls. The customer only hears what Giulia says, never her
tools. Text mode means no speech-to-text errors, no interruptions and no latency: those are graded from voice calls
(watch.py)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from livekit.agents import AgentSession

from ..agent.actions import CallActions, CallState
from ..agent.card import CustomerCard
from ..agent.prompts import PROMPT_DIR, build_instructions, opener
from ..agent.sdr_agent import SDRAgent
from ..config import settings
from ..integrations.calendar import Booking, FakeCalendar
from ..llm import complete
from ..voice import config as voice_config
from ..voice import tracing
from ..voice.lifecycle import CallController
from ..voice.providers import build_llm
from ..voice.telemetry import CallTelemetry
from . import langfuse
from .grade import grade, score
from .scenarios import BY_ID, SCENARIOS, Scenario

log = logging.getLogger("ai_sdr.evals")

TZ = "Europe/Rome"
TURN_TIMEOUT_S = 90       # one reply, tools included; a hung route fails the run instead of the suite
SETTLE_S = 8              # after a reply: wait this long for a follow-up (a language switch's first line)
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
LANGUAGE_NAME = {"it": "Italian", "en": "English"}
SILENCE = {"it": "(silenzio)", "en": "(silence)"}   # what the customer "hears" when she says nothing

CUSTOMER_SYSTEM = """You are role-playing a person who has just picked up a phone call. Stay in character the whole time.

Who you are: {persona}
What you do in this call: {script}

Rules:
- Speak {language} the way people talk on the phone: short, informal, sometimes unfinished sentences. No lists, no emoji.
- Write ONLY the words you say out loud next. No stage directions, no quotation marks, no names before your line.
- React to what the caller actually just said. Follow your script, but don't volunteer what the script doesn't give you,
  and don't suggest the next step yourself unless the script says so.
- If the caller asks something your script doesn't cover, answer briefly and plausibly, in character.
- To end the call (you hang up, or the caller said goodbye), write your last words, if any, then <hangup>."""


class _NoRecorder:
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class Customer:
    """The scenario's customer, played by EVAL_CUSTOMER_MODEL. It hears Giulia's words only."""

    def __init__(self, sc: Scenario):
        self.system = CUSTOMER_SYSTEM.format(persona=sc.persona, script=sc.script,
                                             language=LANGUAGE_NAME.get(sc.language, "English"))

    async def reply(self, heard: list[tuple[str, str]]) -> tuple[str, bool]:
        """(what they say, whether they hang up after it). heard: ("agent" | "customer", text), ending with Giulia.
        Last words come through before the hang-up: a voicemail greeting, or "bye" after her goodbye, so she
        still gets to react (end the call properly) as she would on the phone."""
        messages = [{"role": "user" if who == "agent" else "assistant", "content": text} for who, text in heard]
        out = (await complete(self.system, messages, model=settings().eval_customer_model, max_tokens=160)).strip()
        hangup = "<hangup>" in out.lower()
        return re.sub(r"<hangup>", "", out, flags=re.I).strip().strip('"“” '), hangup


def _busy(calendar: FakeCalendar, busy: tuple[str, ...]) -> None:
    """Mark "weekday HH:MM" (Italian time) as taken on the coming week's calendar."""
    now = datetime.now(ZoneInfo(TZ))
    for spec in busy:
        day, at = spec.split()
        hh, mm = (int(x) for x in at.split(":"))
        ahead = (WEEKDAYS.index(day) - now.weekday()) % 7 or 7
        start = (now + timedelta(days=ahead)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        calendar.booked.append(Booking(start=start.astimezone(timezone.utc), reference=f"busy-{spec}"))


def _outcome(sc: Scenario, state: CallState, tools: list[str]) -> dict:
    """Did the call end where a good call ends, using the tools it had to (deterministic, no model)?"""
    got = "voicemail" if state.voicemail else (state.disposition or "none")
    problems = []
    if got not in sc.outcomes:
        problems.append(f"ended as {got}, expected {' or '.join(sc.outcomes)}")
    if missing := [t for t in sc.tools if t not in tools]:
        problems.append("never called " + ", ".join(missing))
    if used := [t for t in sc.never if t in tools]:
        problems.append("called " + ", ".join(used))
    return {"verdict": "fail" if problems else "pass", "reason": "; ".join(problems) or f"ended as {got}",
            "ended_as": got}


async def _settle(session: AgentSession, controller: CallController) -> None:
    """Wait until Giulia has nothing more to say (or the call is over)."""
    deadline = time.monotonic() + SETTLE_S
    await asyncio.sleep(0.2)
    while time.monotonic() < deadline:
        if controller.state.value == "closed":
            return
        if getattr(session, "current_speech", None) is None and controller.agent_state != "thinking":
            return
        await asyncio.sleep(0.1)


def _new_agent_lines(session: AgentSession, seen: int) -> tuple[str, int]:
    items = session.history.items
    lines = [i.text_content for i in items[seen:]
             if getattr(i, "type", None) == "message" and i.role == "assistant" and i.text_content]
    return " ".join(lines), len(items)


async def run(sc: Scenario, *, label: str = "", n: int = 0) -> dict:
    """One simulated call, graded. Never raises: a broken run comes back with an error instead."""
    cfg = voice_config.load()
    room = f"sim-{sc.id}-{uuid.uuid4().hex[:6]}"
    t0 = time.monotonic()
    session = AgentSession(llm=build_llm(cfg))
    telemetry = CallTelemetry(cfg, room=room, job_id="sim", channel="simulation")
    controller = CallController(session, telemetry, sc.language)
    controller.attach()
    prospect = {"first_name": sc.name, "tz": TZ, "email": None, "context": {}}
    card = CustomerCard.from_demo({"first_name": sc.name, "app": sc.app})
    state = CallState(call_id=0, prospect=prospect, phone=None, tz=TZ, language=sc.language)
    calendar = FakeCalendar(TZ)
    _busy(calendar, sc.busy)
    actions = CallActions(None, state, calendar, None)

    def instructions_for(lang: str) -> str:
        return build_instructions(prospect, language=lang, card=card)

    # voices give the language twin no voice of its own: text mode has none
    agent = SDRAgent(actions, instructions_for(sc.language), _NoRecorder(), controller, language=sc.language,
                     instructions_for=instructions_for, voices=lambda _lang: None,
                     pronunciations=cfg.pronunciations, filler_delay=cfg.filler_delay)
    customer = Customer(sc)
    heard: list[tuple[str, str]] = []
    error, ending = None, "the simulation stopped at its turn limit"
    tracing.call_started(room, channel="simulation", language=sc.language, version=cfg.version,
                         environment="simulation", tags=[sc.id] + ([label] if label else []))
    try:
        await session.start(agent, record=False)
        first = opener(prospect, sc.language, card=card)
        await session.say(first)
        heard.append(("agent", first))
        seen = len(session.history.items)
        for _ in range(sc.max_turns):
            if controller.closing:
                break
            said, hangs_up = await customer.reply(heard)
            if not said:
                ending = "the person hung up"
                break
            heard.append(("customer", said))
            try:
                await asyncio.wait_for(session.run(user_input=said), TURN_TIMEOUT_S)
            except RuntimeError:   # the session closed under the run (end_call while it was waiting)
                pass
            await _settle(session, controller)
            reply, seen = _new_agent_lines(session, seen)
            deadline = time.monotonic() + SETTLE_S
            while not reply and not controller.closing and time.monotonic() < deadline:
                await asyncio.sleep(0.2)   # a language switch: the twin speaks first, a moment after the handoff
                reply, seen = _new_agent_lines(session, seen)
            # silence is something a caller reacts to ("Pronto?"); the customer model also needs her turn last
            heard.append(("agent", reply or SILENCE.get(controller.language, "(silence)")))
            if hangs_up:
                ending = "the person hung up"
                break
    except Exception as e:  # noqa: BLE001 - one broken run must not end the suite
        log.exception("simulated call %s failed", room)
        error = repr(e)[:300]
    finally:
        items = session.history.to_dict(exclude_function_call=False).get("items", [])
        try:
            await session.aclose()
        except Exception:  # noqa: BLE001
            pass
        telemetry.detach_logs()
    tools = [it.get("name") for it in items if it.get("type") == "function_call"]
    if controller.end_reason:
        ending = f"the agent ended it ({controller.end_reason})"
    result = {
        "room": room, "scenario": sc.id, "language": sc.language, "label": label, "n": n,
        "version": cfg.version, "prompt_dir": str(PROMPT_DIR.get()),
        "customer_turns": sum(1 for who, _ in heard if who == "customer"),
        "duration_s": round(time.monotonic() - t0, 1), "error": error, "ending": ending,
        "outcome": _outcome(sc, state, tools),
        "state": {"disposition": state.disposition, "voicemail": state.voicemail, "language": state.language,
                  "meeting": state.booked_start, "callback": state.callback_at,
                  "manual_schedule": state.manual_schedule, "qualification": state.qualification,
                  "support_issues": state.support_issues},
        "items": items,
    }
    if error is None:
        try:
            result["grade"] = await grade(items, sc.language, ending=ending, extra=(
                f"\nThis was a simulated call. What the customer wanted, and what a good call reaches: {sc.expect}\n"))
        except Exception as e:  # noqa: BLE001
            log.exception("grading %s failed", room)
            result["grade_error"] = repr(e)[:300]
    trace_id = tracing.call_ended(room)
    if tracing.enabled():
        await langfuse.post(langfuse.scores_for(room, result.get("grade"), outcome=result["outcome"]["ended_as"],
                                                trace_id=trace_id, environment="simulation"))
    return result


def _summarise(results: list[dict]) -> dict:
    """Per scenario and per check, so a change can be compared run against run."""
    by_check: dict[str, list[str]] = {}
    for r in results:
        for key, c in (r.get("grade") or {}).get("checks", {}).items():
            by_check.setdefault(key, []).append(c["verdict"])
    scenarios = {}
    for r in results:
        s = scenarios.setdefault(r["scenario"], {"runs": 0, "outcome_pass": 0, "scores": [], "must_failed": 0})
        s["runs"] += 1
        s["outcome_pass"] += r["outcome"]["verdict"] == "pass"
        g = r.get("grade") or {}
        if g.get("score") is not None:
            s["scores"].append(g["score"])
        s["must_failed"] += bool(g.get("must_failed"))
    for s in scenarios.values():
        s["score"] = round(sum(s["scores"]) / len(s["scores"]), 3) if s["scores"] else None
        del s["scores"]
    graded = [r["grade"]["score"] for r in results if (r.get("grade") or {}).get("score") is not None]
    return {
        "runs": len(results),
        "outcome_pass_rate": round(sum(r["outcome"]["verdict"] == "pass" for r in results) / len(results), 3)
        if results else None,
        "score": round(sum(graded) / len(graded), 3) if graded else None,
        "must_failed_runs": sum(bool((r.get("grade") or {}).get("must_failed")) for r in results),
        "errors": sum(bool(r.get("error") or r.get("grade_error")) for r in results),
        "checks": {k: {"pass_rate": score({i: {"verdict": v} for i, v in enumerate(vs)}),
                       "applied": sum(v != "n/a" for v in vs)} for k, vs in sorted(by_check.items())},
        "scenarios": scenarios,
    }


def _markdown(run_id: str, label: str, summary: dict, results: list[dict]) -> str:
    lines = [f"# Simulation {run_id}{f' ({label})' if label else ''}", "",
             f"{summary['runs']} calls · outcome reached {summary['outcome_pass_rate']} · score {summary['score']} · "
             f"must-checks failed in {summary['must_failed_runs']} · errors {summary['errors']}", "",
             "| scenario | runs | outcome reached | score | must failed |", "|---|---|---|---|---|"]
    for sid, s in summary["scenarios"].items():
        lines.append(f"| {sid} | {s['runs']} | {s['outcome_pass']}/{s['runs']} | {s['score']} | {s['must_failed']} |")
    lines += ["", "| check | pass rate | applied |", "|---|---|---|"]
    lines += [f"| {k} | {c['pass_rate']} | {c['applied']} |" for k, c in summary["checks"].items()]
    lines += ["", "## Failures", ""]
    for r in results:
        g = r.get("grade") or {}
        fails = [(k, c) for k, c in g.get("checks", {}).items() if c["verdict"] == "fail"]
        if r["outcome"]["verdict"] == "fail" or fails or r.get("error"):
            lines.append(f"### {r['scenario']} #{r['n']} ({r['room']})")
            if r.get("error"):
                lines.append(f"- error: {r['error']}")
            if r["outcome"]["verdict"] == "fail":
                lines.append(f"- outcome: {r['outcome']['reason']}")
            for k, c in fails:
                quote = f' — "{c["quote"]}"' if c.get("quote") else ""
                lines.append(f"- {k}: {c['reason']}{quote}")
            if g.get("notes", {}).get("fix"):
                lines.append(f"- suggested fix: {g['notes']['fix']}")
            lines.append("")
    return "\n".join(lines)


async def suite(ids: list[str] | None = None, *, repeat: int = 1, concurrency: int = 4, label: str = "",
                prompt_dir: Path | None = None, out: Path | None = None, trace: bool = False) -> dict:
    """Run scenarios (all by default) `repeat` times each, `concurrency` at a time; write and return the summary."""
    chosen = [BY_ID[i] for i in ids] if ids else list(SCENARIOS)
    if trace:
        tracing.setup(service="ai-sdr-simulation", version=voice_config.load().version)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{label}" if label else "")
    out = out or Path(settings().eval_dir) / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    gate = asyncio.Semaphore(concurrency)

    async def one(sc: Scenario, n: int) -> dict:
        async with gate:
            if prompt_dir is not None:
                PROMPT_DIR.set(prompt_dir)   # this task only (each task has its own copy of the context)
            r = await run(sc, label=label, n=n)
            (out / f"{sc.id}-{n}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str))
            log.info("simulated %s #%d: outcome %s, score %s", sc.id, n, r["outcome"]["verdict"],
                     (r.get("grade") or {}).get("score"))
            return r

    results = await asyncio.gather(*(one(sc, n) for sc in chosen for n in range(1, repeat + 1)))
    summary = {"run_id": run_id, "label": label, "prompt_dir": str(prompt_dir or PROMPT_DIR.get()),
               **_summarise(list(results))}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str))
    (out / "summary.md").write_text(_markdown(run_id, label, summary, list(results)))
    tracing.flush()
    return {**summary, "dir": str(out), "results": list(results)}
