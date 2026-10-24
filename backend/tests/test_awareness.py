"""24 Oct ("she lacks awareness"): call notes added to each LLM request, brand mishearings fixed before the model
reads them, a background coach, and a guard against switching language twice in one turn. The notes must never
change the session's own context (LiveKit drops the early reply when it changes) and must sit after the cached
prompt."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime

from livekit.agents import llm

from ai_sdr.voice.call_notes import CallNotes, fix_mishearings, signals_in
from ai_sdr.voice.coach import Coach, parse, transcript


@dataclass
class State:
    offered: list = field(default_factory=list)
    booked_start: datetime | None = None
    manual_schedule: dict | None = None
    callback_at: datetime | None = None
    support_issues: list = field(default_factory=list)


def ctx(*turns, system="PROMPT"):
    c = llm.ChatContext.empty()
    c.add_message(role="system", content=system)
    for role, text in turns:
        c.add_message(role=role, content=text)
    return c


def test_brand_mishearings_are_fixed_by_context():
    assert fix_mishearings("I built it on emergency", "en") == "I built it on Emergent"
    assert fix_mishearings("Emojin credits run out", "en") == "Emergent credits run out"
    assert fix_mishearings("I'm urgent, the app is slow", "en") == "Emergent, the app is slow"
    # a real emergency is left alone
    for text in ("I had an emergency yesterday", "the emergency room", "I'm urgent"):
        assert fix_mishearings(text, "en") == text
    assert fix_mishearings("lo sto facendo su emergenza", "it") == "lo sto facendo su Emergent"
    assert fix_mishearings("ho avuto un'emergenza", "it") == "ho avuto un'emergenza"
    assert fix_mishearings("in caso di emergenza", "it") == "in caso di emergenza"


def test_signals():
    assert signals_in("I'm thinking of switching to Lovable") == ["competitor:Lovable", "leaving"]
    assert signals_in("sto passando a replit") == ["competitor:Replit", "leaving"]
    assert signals_in("Okay. Bye bye.") == ["goodbye"]
    assert signals_in("Why are you calling me?") == ["annoyed"]
    assert signals_in("credits run out really fast") == ["cost"]
    # everyday words and language requests are not signals
    for text in ("can you switch to Italian", "moving to production soon", "the cursor is stuck", "mi basta un "
                 "minuto", "passare a inglese"):
        assert signals_in(text) == [], text
    assert signals_in("I use Cursor now") == ["competitor:Cursor"]


def test_notes_follow_the_call():
    notes = CallNotes(State())
    c = ctx(("assistant", "Hi, it's Giulia..."), ("user", "Hi"), ("assistant", "Sorry, what are you building?"),
            ("user", "I'm thinking of switching to Lovable"))
    text = notes.render(c, "en")
    assert text.startswith("[Call notes")
    assert "another tool (Lovable)" in text and "what's pulling them to Lovable" in text
    assert "apologised 1 time" in text
    assert "conversation (turn 2)" in text
    bye = notes.render(ctx(("assistant", "hello"), ("user", "Okay. Bye bye.")), "en")
    assert "close in one sentence" in bye
    booked = CallNotes(State(booked_start=datetime(2026, 10, 26, 14))).render(ctx(("user", "great")), "en")
    assert "meeting booked" in booked
    italian = notes.render(ctx(("user", "sto passando a Replit")), "it")
    assert italian.startswith("[Note sulla chiamata") and "Replit" in italian


def test_notes_never_touch_the_sessions_context():
    notes = CallNotes(State())
    c = ctx(("assistant", "Hi"), ("user", "I built it on emergency and I'm moving to Lovable"))
    before = [(i.role, list(i.content)) for i in c.items]
    out = notes.apply(c, "en")
    assert [(i.role, list(i.content)) for i in c.items] == before   # LiveKit keeps its early reply
    last = out.items[-1]
    assert last.role == "user" and last.content[0] == "I built it on Emergent and I'm moving to Lovable"
    assert "[Call notes" in last.content[-1]
    assert out.items[0].content == ["PROMPT"]   # the cached prompt is unchanged
    system = CallNotes(State(), placement="system").apply(c, "en")
    assert system.items[-1].role == "system" and "[Call notes" in system.items[-1].content[0]
    off = CallNotes(State(), placement="off").apply(c, "en")
    assert len(off.items) == len(c.items) and "[Call notes" not in str(off.items[-1].content)


def test_no_notes_on_a_reply_after_a_tool():
    c = ctx(("user", "Thursday at ten?"))
    c.insert(llm.FunctionCall(call_id="1", name="book_meeting", arguments="{}"))
    c.insert(llm.FunctionCallOutput(call_id="1", name="book_meeting", output="booked", is_error=False))
    out = CallNotes(State()).apply(c, "en")
    assert len(out.items) == len(c.items) and "[Call notes" not in str(out.items[0].content)


def test_coach_note_reaches_the_notes_and_goes_stale():
    notes = CallNotes(State())
    notes.coach = {"off_topic_turns": 3, "next_step": "Offer the expert call about latency."}
    notes.coach_turn = 2
    c = ctx(("user", "a"), ("assistant", "b"), ("user", "c"))
    text = notes.render(c, "en")
    assert "Off-topic for 3 turns" in text and "Coach: Offer the expert call about latency." in text
    many = ctx(*[(r, "x") for _ in range(5) for r in ("user", "assistant")], ("user", "y"))
    assert "Coach:" not in notes.render(many, "en")   # written six turns ago


def test_coach_parsing_and_transcript():
    data = parse('Sure: {"off_topic_turns": 2, "mood": "annoyed", "next_step": "Give the reason and a choice."}')
    assert data["off_topic_turns"] == 2 and data["next_step"].startswith("Give")
    assert parse("no json here") is None
    assert parse('{"off_topic_turns": "lots", "next_step": 5}') == {"off_topic_turns": 0, "next_step": ""}
    text, users = transcript(ctx(("assistant", "Hi"), ("user", "Hello"), ("assistant", "How's it going?")).items)
    assert users == 1 and text.splitlines() == ["GIULIA: Hi", "CALLER: Hello", "GIULIA: How's it going?"]


class FakeChunk:
    def __init__(self, text):
        self.delta = type("D", (), {"content": text})()


class FakeStream:
    def __init__(self, parts):
        self.parts = parts

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def __aiter__(self):
        async def gen():
            for p in self.parts:
                yield FakeChunk(p)
        return gen()


class FakeLLM:
    def __init__(self, parts):
        self.parts, self.calls = parts, 0

    def chat(self, chat_ctx):
        self.calls += 1
        return FakeStream(self.parts)


class FakeController:
    def __init__(self, items):
        self.events = []
        self.language = "en"
        self.closing = False
        self.session = type("S", (), {"history": type("H", (), {"items": items})(), "on": lambda *a: None})()
        self.telemetry = type("T", (), {"event": lambda _s, name, **kw: self.events.append((name, kw))})()
        self.scope = type("Sc", (), {"spawn": lambda _s, coro, name: asyncio.ensure_future(coro)})()


def test_coach_runs_once_per_caller_turn_after_she_starts_speaking():
    async def go():
        notes = CallNotes(State())
        items = ctx(("assistant", "Hi"), ("user", "I'm moving to Lovable")).items
        c = FakeController(items)
        model = FakeLLM(['{"off_topic_turns": 0, "next_step": "Ask what Lovable does better."}'])
        coach = Coach(None, notes, c, model=model)
        speaking = type("E", (), {"new_state": "speaking"})()
        coach._on_agent_state(type("E", (), {"new_state": "listening"})())   # not yet
        assert coach.task is None
        coach._on_agent_state(speaking)
        await coach.task
        coach._on_agent_state(speaking)   # same caller turn: no second read
        assert model.calls == 1
        assert notes.coach["next_step"] == "Ask what Lovable does better." and notes.coach_turn == 1
        assert c.events[0][0] == "coach" and c.events[0][1]["error"] is None
    asyncio.run(go())


def test_language_switch_runs_once():
    from ai_sdr.agent.actions import CallActions, CallState
    from ai_sdr.agent.sdr_agent import SDRAgent
    from ai_sdr.integrations.calendar import FakeCalendar

    class C:
        language = "en"
        notes = None
        closing = False

        def set_language(self, lang):
            self.language = lang

    state = CallState(call_id=0, prospect=None, phone=None, language="en")
    actions = CallActions(None, state, FakeCalendar(), None)
    controller = C()
    agent = SDRAgent(actions, "x", None, controller, language="en", instructions_for=lambda lang: "y",
                     voices=lambda lang: None)

    async def event(*a, **k):
        return None
    actions._event = event
    switch = SDRAgent.switch_language.__wrapped__   # the plain method behind the tool
    first = asyncio.run(switch(agent, None, "it"))
    assert isinstance(first, SDRAgent) and controller.language == "it"
    second = asyncio.run(switch(agent, None, "it"))   # the model's duplicate call in the same turn
    assert "non parlarne" in second   # in the call's new language: nothing to switch, nothing to say


def test_notes_list_questions_already_asked_and_buying_signals():
    c = ctx(("assistant", "Hi. What are you building at the moment?"), ("user", "a booking app"),
            ("assistant", "Nice. Is it live yet, or still in progress?"), ("user", "Can I talk to an expert about it?"))
    text = CallNotes(State()).render(c, "en")
    assert "interest in an expert call" in text and "go straight to booking it" in text
    assert '"What are you building at the moment?"' in text and '"Is it live yet, or still in progress?"' in text
