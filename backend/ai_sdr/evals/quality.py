"""The numbers behind the Quality page (/quality): how calls are graded, where Giulia slips, and how far the grader
can be trusted. Pure functions over call reports (reports.calls()), so they are tested without a database.

How far the grader can be trusted, two ways:
- reviews: a person marks a verdict right or wrong on the page; agreement per check shows where the judge's
  definition needs work (20 Oct: no_echo failed time confirmations the prompt itself asks for);
- re-grades: the same call graded again; a check whose verdict flips is one the judge can't decide consistently."""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict

from .rubric import BY_KEY, CHECKS


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def outcome(report: dict) -> str | None:
    extra = report.get("extra") or {}
    return "voicemail" if extra.get("voicemail") else extra.get("disposition") or extra.get("outcome")


def latest_reviews(report: dict) -> dict[str, dict]:
    """check -> the latest review of its verdict on this call."""
    out: dict[str, dict] = {}
    for review in report.get("eval_reviews") or []:
        if review.get("check"):
            out[review["check"]] = review
    return out


def compare(first: dict, second: dict) -> dict:
    """Two grades of the same call, check by check."""
    keys = [k for k in first if k in second]
    flipped = [k for k in keys if first[k].get("verdict") != second[k].get("verdict")]
    return {"total": len(keys), "same": len(keys) - len(flipped), "flipped": flipped}


def row(report: dict) -> dict:
    """One line of the Quality page's call list."""
    g = report.get("eval") or {}
    s = report.get("summary") or {}
    reviews = latest_reviews(report)
    return {
        "room": report.get("room"), "channel": report.get("channel"), "started_at": report.get("started_at"),
        "duration_s": report.get("duration_s"), "version": report.get("version"), "agent": report.get("agent_name"),
        "language": (report.get("extra") or {}).get("language"), "outcome": outcome(report),
        "score": g.get("score"), "skipped": g.get("skipped"), "graded": bool(g),
        "failed": g.get("failed") or [], "must_failed": g.get("must_failed") or [],
        "e2e_p50": s.get("e2e_p50"), "turns": s.get("turns"), "trace_id": report.get("trace_id"),
        "llm_model": s.get("llm_model"), "ttft_p50": s.get("llm_ttft_p50"),
        "reviewed": len(reviews), "disagreed": sum(1 for r in reviews.values() if not r.get("agree")),
    }


def summary(reports: list[dict]) -> dict:
    graded = [r for r in reports if (r.get("eval") or {}).get("score") is not None]
    skipped = [r for r in reports if (r.get("eval") or {}).get("skipped")]
    checks = {}
    for c in CHECKS:
        verdicts = [r["eval"]["checks"][c.key]["verdict"] for r in graded if c.key in (r["eval"].get("checks") or {})]
        tally = Counter(verdicts)
        applied = tally["pass"] + tally["fail"]
        checks[c.key] = {"must": c.must, "question": c.question, "applied": applied, "passed": tally["pass"],
                         "failed": tally["fail"], "na": tally["n/a"], "pass_rate": _rate(tally["pass"], applied)}
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in reports:
        by_day[(r.get("started_at") or "")[:10]].append(r)
    trend = []
    for day in sorted(d for d in by_day if d):
        day_reports = by_day[day]
        scores = [r["eval"]["score"] for r in day_reports if (r.get("eval") or {}).get("score") is not None]
        replies = [r["summary"]["e2e_p50"] for r in day_reports if (r.get("summary") or {}).get("e2e_p50")]
        trend.append({"day": day, "calls": len(day_reports), "graded": len(scores),
                      "score": round(sum(scores) / len(scores), 3) if scores else None,
                      "reply_s": _median(replies)})
    scores = [r["eval"]["score"] for r in graded]
    took = [r["eval"]["took_s"] for r in graded if isinstance(r["eval"].get("took_s"), (int, float))]
    replies = [r["summary"]["e2e_p50"] for r in reports if (r.get("summary") or {}).get("e2e_p50")]
    return {
        "calls": len(reports), "graded": len(graded), "skipped": len(skipped),
        "ungraded": len(reports) - len(graded) - len(skipped),
        "score": round(sum(scores) / len(scores), 3) if scores else None, "score_p50": _median(scores),
        "must_failed_calls": sum(1 for r in graded if r["eval"].get("must_failed")),
        "reply_s_p50": _median(replies),
        "outcomes": dict(Counter(o for o in (outcome(r) for r in reports) if o).most_common()),
        "checks": checks, "trend": trend,
        "grader": {"versions": sorted({r["eval"].get("grader") for r in graded if r["eval"].get("grader")}),
                   "judges": sorted({r["eval"].get("judge") for r in graded if r["eval"].get("judge")}),
                   "took_s_p50": _median(took)},
        "reviews": review_stats(graded), "regrades": regrade_stats(graded),
    }


# The standard voice-AI numbers, from LiveKit's per-turn metrics (reports.calls(turns=True)): key -> MetricsReport
# field. eou and stt are measured on the person's turns, the rest on Giulia's replies.
SPEED = {"e2e": "e2e_latency", "eou": "end_of_turn_delay", "stt": "transcription_delay", "ttft": "llm_node_ttft",
         "ttfs": "llm_node_ttfs", "ttfb": "tts_node_ttfb", "tps": "llm_node_tps"}
PER_MODEL = ("e2e", "ttft", "ttfs", "ttfb", "tps")   # the ones a different LLM changes


def _pcts(values: list[float]) -> dict:
    if not values:
        return {"p50": None, "p95": None, "n": 0}
    if len(values) == 1:
        return {"p50": round(values[0], 3), "p95": round(values[0], 3), "n": 1}
    q = statistics.quantiles(values, n=100, method="inclusive")
    return {"p50": round(q[49], 3), "p95": round(q[94], 3), "n": len(values)}


def _provider(host: str | None) -> str | None:
    """LiveKit names an LLM's provider by its host; the page names it by the service."""
    if not host:
        return None
    return "Groq" if "groq" in host else "LiteLLM" if "litellm" in host else host


def speed(reports: list[dict]) -> dict:
    """Every reply's numbers over the window (p50 / p95 per metric), and the same per LLM next to its calls' grades.
    A reply counts for the model that actually wrote it (a picked model can fall back mid-call); a call's grade
    counts for the model that wrote most of its replies."""
    overall: dict[str, list[float]] = {k: [] for k in SPEED}
    per: dict[str, dict] = {}
    for r in reports:
        wrote: Counter = Counter()
        for m in r.get("turn_metrics") or []:
            for key, field in SPEED.items():
                if isinstance(m.get(field), (int, float)):
                    overall[key].append(float(m[field]))
            meta = m.get("llm_metadata") if isinstance(m.get("llm_metadata"), dict) else {}
            if m.get("e2e_latency") is None or not meta.get("model_name"):
                continue
            model = meta["model_name"]
            wrote[model] += 1
            slot = per.setdefault(model, {"provider": _provider(meta.get("model_provider")), "calls": 0,
                                          "scores": [], "must_failed_calls": 0, **{k: [] for k in PER_MODEL}})
            for key in PER_MODEL:
                if isinstance(m.get(SPEED[key]), (int, float)):
                    slot[key].append(float(m[SPEED[key]]))
        if wrote:
            slot = per[wrote.most_common(1)[0][0]]
            slot["calls"] += 1
            g = r.get("eval") or {}
            if g.get("score") is not None:
                slot["scores"].append(g["score"])
                slot["must_failed_calls"] += 1 if g.get("must_failed") else 0
    models = [{"model": model, "provider": v["provider"], "calls": v["calls"], "replies": len(v["e2e"]),
               "graded": len(v["scores"]), "must_failed_calls": v["must_failed_calls"],
               "score": round(sum(v["scores"]) / len(v["scores"]), 3) if v["scores"] else None,
               **{k: _pcts(v[k]) for k in PER_MODEL}} for model, v in per.items()]
    models.sort(key=lambda x: (x["ttft"]["p50"] is None, x["ttft"]["p50"] or 0))
    return {"overall": {k: _pcts(v) for k, v in overall.items()}, "models": models}


def review_stats(reports: list[dict]) -> dict:
    per: dict[str, list[bool]] = defaultdict(list)
    for r in reports:
        for check, review in latest_reviews(r).items():
            per[check].append(bool(review.get("agree")))
    flat = [v for vs in per.values() for v in vs]
    return {"reviewed": len(flat), "agree": sum(flat), "rate": _rate(sum(flat), len(flat)),
            "per_check": {k: {"reviewed": len(vs), "agree": sum(vs), "rate": _rate(sum(vs), len(vs))}
                          for k, vs in sorted(per.items()) if k in BY_KEY}}


def regrade_stats(reports: list[dict]) -> dict:
    per: dict[str, list[bool]] = defaultdict(list)
    for r in reports:
        original = (r.get("eval") or {}).get("checks") or {}
        for again in r.get("eval_regrades") or []:
            for check, verdict in (again.get("checks") or {}).items():
                if check in original:
                    per[check].append(original[check].get("verdict") == verdict.get("verdict"))
    flat = [v for vs in per.values() for v in vs]
    return {"compared": len(flat), "same": sum(flat), "rate": _rate(sum(flat), len(flat)),
            "per_check": {k: {"compared": len(vs), "same": sum(vs), "rate": _rate(sum(vs), len(vs))}
                          for k, vs in sorted(per.items()) if k in BY_KEY}}


def rubric(judge_model: str, grader_version: str) -> dict:
    """How a call is graded, for the page's explainer."""
    from .rubric import LONG_TURN_WORDS

    return {
        "grader": grader_version, "judge": judge_model,
        "checks": [{"key": c.key, "must": c.must, "question": c.question} for c in CHECKS],
        "score": "the share of the checks that applied which passed (n/a checks are left out)",
        "counted": [
            {"key": "turn_words_avg", "what": "average words per turn, opener left out"},
            {"key": "long_turns", "what": f"turns over {LONG_TURN_WORDS} words"},
            {"key": "multi_question_turns", "what": "turns asking two questions or more"},
            {"key": "stock_phrases", "what": "words the prompt bans ('slot', 'assolutamente', ...)"},
            {"key": "enthusiasm_words", "what": "'perfetto' / 'perfect' and friends (the prompt allows one)"},
            {"key": "echo_starts", "what": "turns starting with 'So' / 'Quindi'"},
            {"key": "agent_talk_share", "what": "her share of the words spoken"},
        ],
        "when": "every call, about 20 seconds after it ends; calls where the person never spoke are skipped",
    }
