"""One turn of the improvement loop: what keeps going wrong, one proposed change to the prompts, and whether it
helps, measured on the same simulated customers.

    python -m ai_sdr.cli evals improve                    # failures from the last 7 days of graded calls + a fresh simulation
    python -m ai_sdr.cli evals improve --repeat 2         # steadier comparison (each scenario twice per side)
    python -m ai_sdr.cli evals improve --apply <dir>      # copy an accepted candidate's prompts into the repo

1. Evidence: the failed checks of graded calls (real and test, --days) and of a baseline simulation run now.
2. Proposal: EVAL_IMPROVE_MODEL reads both prompts, the checks and the failures (with quotes) and proposes a few
   precise edits, each made in Italian AND English (the prompts must stay in step, agent/prompt_check.py).
3. Test: the edits go into a copy of prompts/; the copy must pass the parity check; the same scenarios run on it.
4. A person reads the report (EVAL_DIR/improve/<id>/report.md) and decides. Nothing reaches the repo without
   --apply, nor the pod without the usual commit, push and pull."""
from __future__ import annotations

import difflib
import logging
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..agent.prompt_check import problems as parity_problems
from ..agent.prompts import DIR as PROMPTS
from ..config import settings
from ..llm import structured
from .grade import describe
from .reports import recent
from .rubric import CHECKS
from .simulate import suite

log = logging.getLogger("ai_sdr.evals")

EDITABLE = ("system_it.md", "system_en.md")
EXAMPLES_PER_CHECK = 4


class Edit(BaseModel):
    file: Literal["system_it.md", "system_en.md"]
    find: str = Field(description="a passage copied EXACTLY from the current file, long enough to occur only once")
    replace: str = Field(description="what replaces it")
    why: str = Field(description="which failure this fixes, in English")


class Proposal(BaseModel):
    diagnosis: str = Field(description="what goes wrong in these calls and why the current instructions allow it")
    edits: list[Edit] = Field(description="each change made in both system_it.md and system_en.md")
    expected_effect: str = Field(description="which checks should improve, and what could get worse")


SYSTEM = (
    "You improve the instructions of Giulia, an AI assistant who phones customers of Emergent (an AI app builder) "
    "in Italian or English to hear how it is going and book a free call with an expert when they have a real need. "
    "Her calls are graded on checks; you get the checks that failed, with the judge's reasons and her words. "
    "Propose a few precise edits to her instructions that fix the most frequent and most serious failures.\n"
    "Rules for edits:\n"
    "- Every change is made in BOTH files, system_it.md (Italian) and system_en.md (English), saying the same thing. "
    "They must keep the same structure: same sections (#, ##), same numbered steps, same number of bullets, same "
    "{placeholders}, same tool names. If you add a bullet in one, add one in the other.\n"
    "- 'find' must be copied character for character from the current file and occur in it exactly once.\n"
    "- Prefer small, sharp changes: tighten a rule, add a short good/bad example in the examples section, move a "
    "rule to where it applies. Do not rewrite whole sections, do not add numbers or new claims about the company, "
    "never touch the {placeholders}.\n"
    "- Fix the cause, not one transcript: the instructions must still work for every other customer.")


def _evidence(calls: list[dict], sims: list[dict]) -> tuple[str, Counter]:
    """The failures, grouped by check, most frequent first, with a few examples each."""
    fails: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    applied: Counter = Counter()
    fixes: list[str] = []
    sources = [("call", r.get("room"), r.get("eval") or {}) for r in calls] + \
              [("simulated", f"{r['scenario']}", r.get("grade") or {}) for r in sims]
    for kind, name, g in sources:
        for key, c in (g.get("checks") or {}).items():
            if c.get("verdict") != "n/a":
                applied[key] += 1
            if c.get("verdict") == "fail":
                fails[key] += 1
                if len(examples[key]) < EXAMPLES_PER_CHECK:
                    quote = f' Her words: "{c["quote"]}"' if c.get("quote") else ""
                    examples[key].append(f"  - ({kind} {name}) {c.get('reason', '')}{quote}")
        if (g.get("notes") or {}).get("fix"):
            fixes.append(f"  - ({kind} {name}) {g['notes']['fix']}")
    for r in sims:
        if r["outcome"]["verdict"] == "fail":
            fails["scenario_outcome"] += 1
            if len(examples["scenario_outcome"]) < EXAMPLES_PER_CHECK:
                examples["scenario_outcome"].append(f"  - (simulated {r['scenario']}) {r['outcome']['reason']}")
    lines = [f"{len(calls)} graded calls and {len(sims)} simulated calls.", ""]
    for key, n in fails.most_common():
        what = "the call reached the outcome its scenario expects" if key == "scenario_outcome" else describe(key)
        lines.append(f"- {key}: failed {n} of {applied.get(key, n)} — {what}")
        lines.extend(examples[key])
    if fixes:
        lines += ["", "Fixes the judge suggested for single calls:", *fixes[:12]]
    return "\n".join(lines), fails


def _apply(proposal: Proposal, into: Path) -> list[str]:
    """Write the edits into the candidate folder; returns the edits that could not be applied."""
    skipped = []
    for e in proposal.edits:
        path = into / e.file
        text = path.read_text()
        if text.count(e.find) != 1:
            skipped.append(f"{e.file}: passage found {text.count(e.find)} times: {e.find[:80]!r}")
            continue
        path.write_text(text.replace(e.find, e.replace))
    return skipped


def _diff(old: Path, new: Path) -> str:
    out = []
    for name in EDITABLE:
        out += difflib.unified_diff((old / name).read_text().splitlines(), (new / name).read_text().splitlines(),
                                    f"prompts/{name}", f"candidate/{name}", lineterm="", n=1)
    return "\n".join(out)


def _verdict(base: dict, cand: dict) -> str:
    if cand["errors"] or cand["score"] is None or base["score"] is None:
        return "inconclusive: some runs failed"
    if cand["must_failed_runs"] > base["must_failed_runs"]:
        return "worse: more calls broke a MUST check"
    if cand["outcome_pass_rate"] < base["outcome_pass_rate"] - 0.05:
        return "worse: fewer calls reached their outcome"
    if cand["score"] > base["score"] + 0.02 and cand["outcome_pass_rate"] >= base["outcome_pass_rate"]:
        return "better"
    if cand["score"] < base["score"] - 0.02:
        return "worse: lower score"
    return "no clear difference (try --repeat 2 or 3 before deciding)"


async def improve(*, days: float = 7, scenarios: list[str] | None = None, repeat: int = 1, max_edits: int = 4,
                  concurrency: int = 4) -> dict:
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(settings().eval_dir) / "improve" / run_id
    out.mkdir(parents=True, exist_ok=True)
    calls = recent(hours=days * 24)
    log.info("improve %s: %d graded calls; running the baseline simulation", run_id, len(calls))
    base = await suite(scenarios, repeat=repeat, concurrency=concurrency, label="baseline", out=out / "baseline")
    evidence, fails = _evidence(calls, base["results"])
    current = {name: (PROMPTS / name).read_text() for name in EDITABLE}
    proposal = await structured(SYSTEM, (
        f"Checks:\n" + "\n".join(f"- {c.key}{' (MUST)' if c.must else ''}: {c.question}" for c in CHECKS) +
        f"\n\nFailures:\n{evidence}\n\nPropose at most {max_edits} changes (each in both files, so at most "
        f"{2 * max_edits} edits).\n\n=== system_it.md ===\n{current['system_it.md']}\n\n"
        f"=== system_en.md ===\n{current['system_en.md']}"),
        Proposal, model=settings().eval_improve_model, max_tokens=8000)
    candidate = out / "candidate"
    shutil.copytree(PROMPTS, candidate)
    skipped = _apply(proposal, candidate)
    parity = parity_problems(candidate)
    report = {"run_id": run_id, "calls": len(calls), "failures": dict(fails), "proposal": proposal.model_dump(),
              "skipped_edits": skipped, "parity": parity, "baseline": {k: v for k, v in base.items() if k != "results"}}
    if parity:
        report["verdict"] = "rejected: the candidate prompts are out of step (parity check)"
    elif len(skipped) == len(proposal.edits):
        report["verdict"] = "rejected: no edit could be applied"
    else:
        log.info("improve %s: simulating the candidate", run_id)
        cand = await suite(scenarios, repeat=repeat, concurrency=concurrency, label="candidate",
                           prompt_dir=candidate, out=out / "candidate_runs")
        report["candidate"] = {k: v for k, v in cand.items() if k != "results"}
        report["verdict"] = _verdict(base, cand)
    (out / "report.md").write_text(_markdown(report, evidence, _diff(PROMPTS, candidate), candidate))
    return {**report, "dir": str(out)}


def _markdown(r: dict, evidence: str, diff: str, candidate: Path) -> str:
    p = r["proposal"]
    lines = [f"# Improvement run {r['run_id']}", "", f"**Verdict: {r['verdict']}**", "",
             "## What goes wrong", "", p["diagnosis"], "", "## Evidence", "", evidence, "",
             "## Proposed change", "", p["expected_effect"], ""]
    for e in p["edits"]:
        lines.append(f"- {e['file']}: {e['why']}")
    if r["skipped_edits"]:
        lines += ["", "Edits that could not be applied:", *(f"- {s}" for s in r["skipped_edits"])]
    if r["parity"]:
        lines += ["", "Parity problems:", *(f"- {s}" for s in r["parity"])]
    lines += ["", "```diff", diff or "(no change)", "```", ""]
    if "candidate" in r:
        b, c = r["baseline"], r["candidate"]
        lines += ["## Before and after (same scenarios)", "", "| | baseline | candidate |", "|---|---|---|",
                  f"| score | {b['score']} | {c['score']} |",
                  f"| outcome reached | {b['outcome_pass_rate']} | {c['outcome_pass_rate']} |",
                  f"| calls breaking a MUST check | {b['must_failed_runs']} | {c['must_failed_runs']} |",
                  f"| errors | {b['errors']} | {c['errors']} |"]
        for key in sorted(set(b["checks"]) | set(c["checks"])):
            lines.append(f"| {key} | {b['checks'].get(key, {}).get('pass_rate')} | "
                         f"{c['checks'].get(key, {}).get('pass_rate')} |")
        lines += ["", f"Runs: {b['dir']} and {c['dir']}"]
    lines += ["", "## To keep it", "", f"`python -m ai_sdr.cli evals improve --apply {candidate}` copies the candidate "
              "prompts into the repo; then the usual prompt check, commit, push and pull."]
    return "\n".join(lines)


def apply_candidate(candidate: Path) -> list[str]:
    """Copy an accepted candidate's prompts into the repo (after a person read its report)."""
    if parity := parity_problems(candidate):
        raise SystemExit("candidate is out of step:\n  - " + "\n  - ".join(parity))
    changed = []
    for name in EDITABLE:
        new = (candidate / name).read_text()
        if new != (PROMPTS / name).read_text():
            (PROMPTS / name).write_text(new)
            changed.append(name)
    return changed
