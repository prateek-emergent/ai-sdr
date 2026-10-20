"""20 Oct changes: bilingual calls, the customer card, the openers, the pronunciation map, the voice/STT chains,
support issues, the language hand-off and the post-call brief. Run from backend/: `python -m pytest`."""
from __future__ import annotations

import asyncio
import dataclasses
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from ai_sdr.agent.actions import CallActions, CallState
from ai_sdr.agent.card import App, CustomerCard, fetch_card
from ai_sdr.agent.prompt_check import problems
from ai_sdr.agent.prompts import build_instructions, opener
from ai_sdr.integrations.calendar import FakeCalendar
from ai_sdr.voice import config as voice_config
from ai_sdr.voice.lines import variants
from ai_sdr.voice.pronunciation import Pronunciations
from ai_sdr.voice.providers import Voices, build_stt, tts_chain_for

NOW = datetime(2026, 10, 20, 11, 0, tzinfo=ZoneInfo("Europe/Rome"))
AMOUNTS = re.compile(r"\b(1250|1,250|400|900)\b")


def sample_card(**overrides) -> CustomerCard:
    card = CustomerCard(first_name="Marco", last_name="Rossi", plan="monthly_standard",
                        customer_since=date(2026, 3, 4), apps=[App("Trattoria Manager", "orders and stock", True)],
                        ltv=1250.0, topup_60d=400.0, credits_15d=900.0, credit_balance=40.0, segment="fde",
                        priority="P1", last_contacted=date(2026, 9, 29), last_call_outcome="follow up required",
                        open_tickets=["Play Store publishing"])
    return dataclasses.replace(card, **overrides)


# ---- prompts
def test_prompts_in_step():
    assert problems() == []


@pytest.mark.parametrize("language", ["it", "en"])
@pytest.mark.parametrize("inbound", [False, True])
def test_instructions_filled_in_both_languages(language, inbound):
    text = build_instructions({"tz": "Europe/Rome"}, language=language, inbound=inbound, card=sample_card(), now=NOW)
    assert "{" not in text and "}" not in text, "a placeholder was left unfilled"
    assert "Trattoria Manager" in text
    assert "switch_language" in text and "log_support_issue" in text
    assert not AMOUNTS.search(text), "an amount reached the prompt"


def test_say_aloud_and_background():
    card = sample_card()
    say_en, bg_en = card.say_aloud("en", NOW.date()), card.background("en", NOW.date())
    assert "Built with us: Trattoria Manager (orders and stock, live)" in say_en
    assert "Customer since March 2026" in say_en and "Plan: Standard, monthly" in say_en
    assert "Value to us: high" in bg_en and "tops up a lot lately" in bg_en and "balance running low" in bg_en
    assert "may need engineering help" in bg_en and "Open support issue: Play Store publishing" in bg_en
    say_it, bg_it = card.say_aloud("it", NOW.date()), card.background("it", NOW.date())
    assert "Cliente dal marzo 2026" in say_it and "Ha creato con noi: Trattoria Manager" in say_it
    assert "Valore per noi: alto" in bg_it
    for text in (bg_en, bg_it):
        assert not AMOUNTS.search(text)


def test_card_from_hubspot_cleans_and_parses():
    card = CustomerCard.from_hubspot(
        {"firstname": "Giulio", "app_name": "my-crm_v2", "ob_what_they_built": "CRM, write to mario@example.com",
         "deployed_url": "https://x.emergent.host", "sales_acq_date": "2026-03-04", "do_not_touch": "true",
         "notes_last_contacted": "1790000000000", "sales_current_plan": "none", "ltv": "180"},
        calls=[{"hs_timestamp": "2026-09-01T10:00:00Z", "hs_call_title": "[Nooks Call] - Not interested - X - by Y"},
               {"hs_timestamp": "2026-09-29T10:00:00Z", "hs_call_title": "[Nooks Call] - Meeting booked - X - by Y"}],
        tickets=[{"subject": "Can't publish", "closed_date": None}, {"subject": "old", "closed_date": "2026-01-01"}])
    assert card.apps[0].name == "my crm v2" and card.apps[0].live and "@" not in (card.apps[0].what or "")
    assert card.do_not_touch and card.customer_since == date(2026, 3, 4) and card.last_contacted is not None
    assert card.last_call_outcome == "meeting booked" and card.open_tickets == ["Can't publish"]


def test_card_from_prospect_csv_context():
    card = CustomerCard.from_prospect({"first_name": "Anna", "context": {"what_they_built": "gestionale bar",
                                                                         "plan": "pro", "note": "call 333 1234567"}})
    assert card.first_app() == "gestionale bar"
    assert "plan: pro" in card.notes and not any("1234567" in n for n in card.notes)


async def test_fetch_card_from_hubspot_and_timeout():
    class FakeHubSpot:
        enabled = True

        def __init__(self, delay=0.0):
            self.delay = delay

        async def find_contact(self, *, email, phone):
            return "42"

        async def get_contact(self, contact_id, props):
            await asyncio.sleep(self.delay)
            return {"properties": {"firstname": "Sara", "app_name": "Gym Booking"}, "calls": [], "tickets": []}

        async def read_objects(self, kind, ids, props):
            return []

    card = await fetch_card(FakeHubSpot(), {"email": "s@example.com"}, timeout=1)
    assert card is not None and card.first_app() == "Gym Booking"
    assert await fetch_card(FakeHubSpot(delay=0.5), {"email": "s@example.com"}, timeout=0.05) is None
    assert await fetch_card(None, {}, timeout=1) is None


# ---- openers
def test_openers():
    card = sample_card()
    morning = datetime(2026, 10, 20, 9, 30, tzinfo=ZoneInfo("Europe/Rome"))
    evening = datetime(2026, 10, 20, 18, 30, tzinfo=ZoneInfo("Europe/Rome"))
    it = opener({"first_name": "Marco"}, "it", card=card, now=morning)
    assert it.startswith("Buongiorno Marco,") and "assistente AI" in it and "la sua app, Trattoria Manager:" in it
    assert opener({"first_name": "Marco"}, "it", card=card, now=evening).startswith("Buonasera Marco,")
    en = opener(None, "en", card=card, now=morning)
    assert "your app, Trattoria Manager:" in en and "AI assistant" in en
    assert "la richiamo come d'accordo" in opener({"first_name": "Marco"}, "it", card=card, callback=True)
    assert "calling you back as we agreed" in opener(None, "en", card=card, callback=True)
    assert "building apps with AI" in opener({"first_name": "Anna"}, "en")


# ---- language choice
def test_call_language():
    from ai_sdr.agent import worker
    assert worker.call_language({"language": "en"}) == "en"
    assert worker.call_language({}, None, "+393331234567") == "it"
    assert worker.call_language({}, None, "+14155550100") == "en"
    assert worker.call_language({}, {"context": {"country": "Italy"}}, "+14155550100") == "it"
    assert worker.call_language({}, {"context": {"language": "en"}}, "+393331234567") == "en"
    assert worker.call_language({}, card=sample_card(country="Italy")) == "it"
    assert worker.call_language({}) == "it"


# ---- pronunciation map
async def test_pronunciations_whole_words_across_chunks():
    p = Pronunciations({"AI": "A.I.", "Emergent": "Imèrgent"})
    assert p.apply("mai detto AI") == "mai detto A.I."

    async def chunks():
        for c in ["Ciao da Emer", "gent, l'AI", " di oggi"]:
            yield c

    assert "".join([x async for x in p.stream(chunks())]) == "Ciao da Imèrgent, l'A.I. di oggi"
    assert not Pronunciations({})


# ---- voices and speech-to-text
def test_voice_config_defaults_and_floor(monkeypatch):
    cfg = voice_config.load()
    assert cfg.languages == ("it", "en") and cfg.stt_chain == ("soniox", "deepgram")
    assert cfg.vad_min_silence == 0.35 and cfg.soniox_max_endpoint_delay_ms == 500
    assert cfg.elevenlabs_voice_ids == {"it": "voice-it", "en": "voice-en"}
    monkeypatch.setenv("VAD_MIN_SILENCE_S", "0.2")
    with pytest.raises(voice_config.ConfigError):
        voice_config.load()


def test_tts_chain_per_language():
    cfg = voice_config.load()
    assert tts_chain_for(cfg, None, None, "it") == ("elevenlabs", "deepgram")
    only_it = dataclasses.replace(cfg, elevenlabs_voice_ids={"it": "voice-it"})
    assert tts_chain_for(only_it, None, None, "en") == ("deepgram",)
    assert tts_chain_for(cfg, None, 100, "it") == ("deepgram",)  # ElevenLabs nearly out of credits


def test_stt_chain_is_bilingual():
    cfg = voice_config.load()
    stt = build_stt(cfg, "it")
    primary = stt._stt_instances[0]
    assert type(primary).__module__.startswith("livekit.plugins.soniox")
    assert primary._params.language_hints == ["it", "en"] and primary._params.max_endpoint_delay_ms == 500
    assert primary._params.context.terms == ["Emergent"]
    assert stt.capabilities.aligned_transcript == "chunk"  # adaptive interruption keeps working
    assert build_stt(cfg, "en")._stt_instances[0]._params.language_hints == ["en", "it"]


def test_deepgram_language():
    """20 Oct: Deepgram listens in the call's language (a switch gives the twin its own stream); "multi" on request."""
    cfg = dataclasses.replace(voice_config.load(), stt_chain=("deepgram",))
    assert cfg.deepgram_language == "call"
    assert build_stt(cfg, "it")._opts.language == "it" and build_stt(cfg, "en")._opts.language == "en"
    assert build_stt(dataclasses.replace(cfg, deepgram_language="multi"), "it")._opts.language == "multi"


def test_voices_built_once_per_language():
    built = []
    voices = Voices(voice_config.load(), on_build=lambda lang, chain, voice: built.append(lang))
    assert voices.get("it") is voices.get("it")
    voices.get("en")
    assert built == ["it", "en"]


# ---- actions, lines
async def test_actions_follow_the_call_language():
    state = CallState(call_id=0, prospect=None, phone=None, language="en")
    actions = CallActions(None, state, FakeCalendar(), None)
    reply = await actions.log_support_issue("can't publish to the Play Store", "publishing")
    assert reply.startswith("Logged for the team") and state.support_issues[0]["kind"] == "publishing"
    state.language = "it"
    assert actions._say("ciao", "hello") == "ciao"


def test_line_variants():
    assert len(variants("recover")) == 2


# ---- language hand-off
async def test_switch_language_hands_off_to_a_twin():
    from ai_sdr.agent.sdr_agent import SDRAgent
    from ai_sdr.agent.worker import NullRecorder

    class Controller:
        language = "it"

        def set_language(self, language):
            self.language = language

    controller = Controller()
    actions = CallActions(None, CallState(call_id=0, prospect=None, phone=None, language="it"), FakeCalendar(), None)
    agent = SDRAgent(actions, "prompt-it", NullRecorder(), controller, language="it",
                     instructions_for=lambda lang: f"prompt-{lang}", voices=lambda lang: f"voice-{lang}")
    twin = await agent.switch_language(None, "en")
    assert isinstance(twin, SDRAgent) and twin.language == "en" and twin._handoff
    assert twin.instructions == "prompt-en" and controller.language == "en" and actions.state.language == "en"
    assert isinstance(await twin.switch_language(None, "en"), str)  # already English: nothing to switch


# ---- post-call
def test_postcall_brief_has_the_new_fields():
    from ai_sdr.postcall import CallSummary, brief, support_brief
    s = CallSummary(summary_en="Runs a trattoria app.", disposition="meeting_booked", qualification="qualified",
                    qualification_reasons=["live app"], what_they_built="orders app", pain_points=["credits"],
                    product_feedback=["credits burn fast"], meeting_reason="credit costs", language="it",
                    who_for="own_business", stage="live_with_users_or_revenue", blockers=["credit cost"],
                    wishes=["predictable pricing"], competitors=["Lovable"], support_issues=["can't publish"],
                    objections=[], quotes=["costa troppo"], asked_not_to_be_called=False, asked_if_ai=False,
                    agent_claimed_human=False, agent_possible_unapproved_claims=[], agent_turns_too_long=False)
    text = brief({"first_name": "Marco", "tz": "Europe/Rome", "meeting_start": None}, s)
    assert "Blockers: credit cost" in text and "Other tools: Lovable" in text and "stage: live with users" in text
    assert "can't publish" in support_brief({"first_name": "Marco"}, s)
