"""20 Oct: the improvement loop (ai_sdr/evals). Everything here runs without a model: the counted checks, the
transcript the judge reads, the scenarios, the scores sent to Langfuse, and the candidate-prompt plumbing."""
import re
import shutil
from types import SimpleNamespace

from ai_sdr.agent import prompts
from ai_sdr.agent.prompt_check import DISPOSITIONS, problems, tool_names
from ai_sdr.evals import langfuse
from ai_sdr.evals.improve import Edit, Proposal, _apply
from ai_sdr.evals.rubric import CHECKS, MUST, counted, ending_of, transcript
from ai_sdr.evals.scenarios import SCENARIOS
from ai_sdr.evals.simulate import WEEKDAYS, _outcome


def msg(role, text, interrupted=False):
    return {"type": "message", "role": role, "content": [text], "interrupted": interrupted}


CALL = [
    msg("assistant", "Buongiorno Marco, sono Giulia, l'assistente AI di Emergent. Ha due minuti?"),
    msg("user", "Sì, mi dica."),
    msg("assistant", "Perfetto! Quindi sta costruendo un gestionale? Per chi è? E come va?"),
    msg("user", "Per il mio studio."),
    msg("assistant", "Ottimo. Guardo gli slot liberi.", interrupted=True),
    {"type": "function_call", "name": "get_available_slots", "arguments": "{}"},
    {"type": "function_call_output", "name": "get_available_slots", "output": "giovedì 10:00-13:00", "is_error": False},
    msg("assistant", " ".join(["parola"] * 40)),
]


def test_counted_checks():
    c = counted(CALL, "it")
    assert c["agent_turns"] == 4 and c["opener_says_ai"] is True
    assert c["enthusiasm_words"] == 2            # Perfetto, Ottimo
    assert c["echo_starts"] == 0                 # "Perfetto! Quindi..." does not START with Quindi
    assert c["multi_question_turns"] == 1 and c["long_turns"] == 1
    assert c["stock_phrases"] == ["slot"] and c["cut_off_turns"] == 1
    assert c["tools"] == ["get_available_slots"]


def test_transcript_shows_tools_cuts_and_ending():
    text = transcript(CALL, "the person hung up")
    assert "AGENT: Buongiorno Marco" in text and "PERSON: Sì, mi dica." in text
    assert "[tool get_available_slots {}]" in text and "[result] giovedì 10:00-13:00" in text
    assert "[cut off: the person spoke over her]" in text
    assert text.endswith("[call ended: the person hung up]")


def test_ending_of_a_real_call():
    assert ending_of({"reason": "participant_disconnected", "requested": None}) == "the person hung up"
    assert ending_of({"reason": "user_initiated", "requested": "end_call:meeting_booked"}).startswith("the agent")
    assert ending_of({"reason": "user_initiated", "requested": "max_duration"}) == "the system ended it (max_duration)"
    assert ending_of(None) is None


def test_checks_are_unique_and_musts_are_compliance():
    keys = [c.key for c in CHECKS]
    assert len(keys) == len(set(keys))
    assert set(MUST) == {"ai_disclosure", "allowed_claims", "respects_no", "honest_actions"}


def test_scenarios_are_consistent_with_the_agent():
    tools = tool_names()
    assert len({s.id for s in SCENARIOS}) == len(SCENARIOS)
    for s in SCENARIOS:
        assert s.language in ("it", "en") and s.id.startswith(f"{s.language}_")
        assert set(s.outcomes) <= set(DISPOSITIONS) | {"voicemail"}, s.id
        assert set(s.tools) <= tools and set(s.never) <= tools, s.id
        for spec in s.busy:
            day, at = spec.split()
            assert day in WEEKDAYS and re.fullmatch(r"\d{2}:\d{2}", at), spec


def test_outcome_check():
    sc = next(s for s in SCENARIOS if s.id == "it_busy_callback")
    good = SimpleNamespace(voicemail=False, disposition="callback")
    assert _outcome(sc, good, ["schedule_callback"])["verdict"] == "pass"
    bad = _outcome(sc, SimpleNamespace(voicemail=False, disposition="meeting_booked"),
                   ["get_available_slots", "book_meeting"])
    assert bad["verdict"] == "fail"
    assert "expected callback" in bad["reason"] and "never called schedule_callback" in bad["reason"]
    assert "called book_meeting, get_available_slots" in bad["reason"]


def test_langfuse_scores_are_few_and_stable():
    grade = {"score": 0.8, "grader": "g1", "judge": "j", "must_failed": [], "notes": {"fix": "x"},
             "checks": {"no_echo": {"verdict": "fail", "reason": "echoed", "quote": "Quindi..."},
                        "language": {"verdict": "pass", "reason": "ok", "quote": ""}},
             "counted": {"turn_words_avg": 12.5}}
    by_session = langfuse.scores_for("demo-1", grade, outcome="callback", summary={"e2e_p50": 1.2},
                                     environment="ai-sdr-preview")
    names = {s["name"] for s in by_session}
    assert names == {"score", "must_failed", "failed.no_echo", "turn_words_avg", "outcome", "timing.e2e_p50"}
    assert all(s["sessionId"] == "demo-1" and s["environment"] == "ai-sdr-preview" for s in by_session)
    failed = next(s for s in by_session if s["name"] == "failed.no_echo")
    assert failed["value"] == 1 and failed["dataType"] == "BOOLEAN" and "Quindi" in failed["comment"]
    by_trace = langfuse.scores_for("demo-1", grade, trace_id="ab" * 16)
    assert all(s["traceId"] == "ab" * 16 and "sessionId" not in s for s in by_trace)
    # grading the same call again updates its scores: same ids
    assert [s["id"] for s in langfuse.scores_for("demo-1", grade)] == \
        [s["id"] for s in langfuse.scores_for("demo-1", grade)]


def test_candidate_prompts_are_checked_and_read(tmp_path):
    cand = tmp_path / "candidate"
    shutil.copytree(prompts.DIR, cand)
    assert problems(cand) == []
    text = (cand / "system_en.md").read_text()
    marker = "# Role and goal"
    edits = Proposal(diagnosis="d", expected_effect="e", edits=[
        Edit(file="system_en.md", find=marker, replace=marker + "\nCANDIDATE MARKER", why="test"),
        Edit(file="system_it.md", find="not in the file", replace="x", why="test")])
    skipped = _apply(edits, cand)
    assert len(skipped) == 1 and "found 0 times" in skipped[0]
    assert "CANDIDATE MARKER" in (cand / "system_en.md").read_text() and text != (cand / "system_en.md").read_text()
    # a simulated call can read the candidate; calls keep reading the repo's prompts
    token = prompts.PROMPT_DIR.set(cand)
    try:
        assert "CANDIDATE MARKER" in prompts.build_instructions(None, language="en")
    finally:
        prompts.PROMPT_DIR.reset(token)
    assert "CANDIDATE MARKER" not in prompts.build_instructions(None, language="en")
    # an extra bullet in one language only breaks the parity check
    (cand / "system_it.md").write_text((cand / "system_it.md").read_text() + "\n- un punto in più\n")
    assert any("bullets differ" in p for p in problems(cand))
