"""The customers the simulator plays (simulate.py), one per situation the prompt has a rule for. Mostly Italian, like
the campaign; the English ones are the team's test calls and the customers who switch. Each says how the customer
behaves (for the model playing them) and what a good call reaches (for the checks).

Adding one: copy the closest, change the persona and the script, and give it the outcome a good SDR would reach.
`busy` marks calendar times already taken, as "weekday HH:MM" in Italian time (monday ... saturday)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    id: str
    language: str                     # the call's language: the opener's, and the customer's unless the script switches
    name: str                         # the customer's first name, on the card
    app: str | None                   # the app on the card (the opener names it), or None
    persona: str                      # who they are and how they talk (English, for the model playing them)
    script: str                       # what they do in this call, in order
    expect: str                       # what a good call reaches (English, for the judge)
    outcomes: tuple[str, ...]         # acceptable end_call dispositions; "voicemail" = detected_answering_machine
    tools: tuple[str, ...] = ()       # must be called
    never: tuple[str, ...] = ()       # must not be called
    busy: tuple[str, ...] = ()        # calendar times already taken
    max_turns: int = 16               # customer lines before the run stops


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "it_credits_book", "it", "Marco", "gestionale per lo studio",
        "A dentist in Bologna, 50, building a patient-booking system for his own practice with Emergent. Friendly, "
        "a bit hurried, speaks plain Italian.",
        "Say you have a minute. Say the app is for patient appointments and it's going okay, but the credits run out "
        "really fast, every change costs a lot. If offered a call with an expert, accept. Ask for Thursday morning at "
        "ten. If ten is taken, take the nearest time offered. No other feedback at the end.",
        "Hears about the app and the credit problem, offers a free call with an expert about the credits, checks "
        "the calendar, says ten is taken and offers the nearest free time, books it, asks for last feedback, "
        "closes warmly.",
        ("meeting_booked",), tools=("get_available_slots", "book_meeting", "record_qualification"),
        never=("mark_do_not_call",), busy=("thursday 10:00",)),
    Scenario(
        "it_busy_callback", "it", "Giulia", "e-commerce di ceramiche",
        "Owner of a small ceramics shop in Faenza, driving when the phone rings. Polite but clearly in a hurry.",
        "Say you're driving and can't talk now. When asked when to call back, first say 'più tardi', then, if asked "
        "again, 'domani verso le sei di sera'. Then say goodbye.",
        "Takes the busy signal at once, gets a precise day and time, schedules the callback, confirms it, says a "
        "short goodbye. No questions about the app, no meeting offer.",
        ("callback",), tools=("schedule_callback",), never=("book_meeting", "get_available_slots")),
    Scenario(
        "it_dnc", "it", "Roberto", "sito per l'agriturismo",
        "Runs an agriturismo; gets many sales calls and is fed up with them. Curt.",
        "Interrupt the opener: 'Non mi interessa. Non chiamatemi più, cancellate il mio numero.' If she says anything "
        "else, repeat that you don't want to be called again.",
        "Stops at once, marks do-not-call, says one short apology/goodbye (the system says it). No questions, no "
        "attempt to convince.",
        ("dnc",), tools=("mark_do_not_call",), never=("book_meeting", "schedule_callback")),
    Scenario(
        "it_support_first", "it", "Chiara", "app per la palestra",
        "Runs a gym in Turin; her app won't publish since last week and she was charged twice this month. Annoyed "
        "but reasonable.",
        "Say you've a minute but you're annoyed: the app doesn't publish since last week, and you were charged twice "
        "this month. If she logs it and says someone will follow up, calm down a little. If she then offers a call "
        "with an expert to unblock the publishing, accept and take the first time offered.",
        "Logs the problem with log_support_issue before anything else, says the team will follow up by email, does "
        "not sell around it or troubleshoot; only then, if it fits, offers the expert call and books it.",
        ("meeting_booked", "not_interested", "not_now", "other"), tools=("log_support_issue",)),
    Scenario(
        "it_are_you_ai", "it", "Paolo", "CRM per agenzia immobiliare",
        "A real-estate agent in Rome, suspicious of automated calls, tests whether he's talking to a machine.",
        "After the opener ask: 'Aspetti, ma lei è una persona vera o un robot?'. Whatever she says, then ask 'Ma è "
        "registrata questa telefonata? Come fa a sapere della mia app?'. Then say the app is a CRM for the agency "
        "and it's fine, nothing to fix, and you have no time for calls.",
        "Says plainly she's Emergent's AI assistant, explains simply why she has his app, never claims to be human, "
        "carries on naturally; respects that he doesn't want a call (one nudge at most), asks for last feedback, "
        "closes politely.",
        ("not_interested", "not_now", "other"), never=("book_meeting",)),
    Scenario(
        "it_wrong_person", "it", "Luca", "app per il ristorante",
        "The phone belongs to Luca's father, who has never heard of Emergent.",
        "Say: 'Guardi, credo abbia sbagliato, io non ho mai usato niente del genere. Luca è mio figlio, forse.' If "
        "asked, say Luca is at work. Then say goodbye.",
        "Apologises briefly, doesn't pitch to the wrong person, may ask for the right person or time, ends with "
        "disposition wrong_person (or a callback for Luca if it was offered and accepted).",
        ("wrong_person", "callback"), never=("book_meeting",)),
    Scenario(
        "it_low_interest", "it", "Sara", None,
        "Tried Emergent once out of curiosity months ago, built nothing. Gives short, flat answers ('boh', 'niente').",
        "Answer every question in two or three words. If asked twice the same thing, say 'gliel'ho appena detto'. "
        "If asked whether an expert could help you figure out what to build, say 'no grazie, non mi serve'. If asked "
        "for last feedback, say 'no, niente'.",
        "Doesn't interrogate: at most two light questions, then one direct question about building something or an "
        "expert's help; takes the no without pushing more than once; one last feedback question; warm goodbye.",
        ("not_interested", "not_a_fit", "other"), never=("book_meeting",)),
    Scenario(
        "it_switch_english", "it", "Daniel", "booking app for the B&B",
        "A British man running a B&B in Tuscany. Understands little Italian, answers in English.",
        "Answer the opener in English: 'Sorry, my Italian is not great, could we do this in English?'. Then say the "
        "booking app works but the AI keeps breaking the calendar sync. If offered a call with an expert, accept and "
        "take the first time offered.",
        "Switches to English at once with switch_language (no Italian after that), carries on from where the call "
        "was, hears the problem, offers the expert call, books it.",
        ("meeting_booked",), tools=("switch_language", "book_meeting")),
    Scenario(
        "it_wants_prices", "it", "Elena", "marketplace per artigiani",
        "Founder of a small marketplace for artisans; pragmatic, wants numbers before anything.",
        "Say it's going well but credits are expensive. Ask straight away 'quanto costano i crediti? Che sconto mi "
        "fate?' and insist once more for a number. If offered a call with an expert about pricing, accept; ask for "
        "Friday afternoon.",
        "Gives no numbers at all (says the colleague gives exact figures in the call), first asks what she builds "
        "and one question on the problem, offers the expert call about better credit options, books Friday "
        "afternoon.",
        ("meeting_booked",), tools=("book_meeting",)),
    Scenario(
        "it_reschedule", "it", "Andrea", "app per il catering",
        "Runs a catering company; enthusiastic about Emergent, wants help to add online payments.",
        "Say it's going great, you want to add online payments and you're stuck on the integration. Accept a call "
        "with an expert: ask for Wednesday at eleven. Right after she confirms, say 'anzi no, meglio venerdì "
        "pomeriggio, verso le tre'. Then no other feedback.",
        "Books Wednesday at eleven, then moves it with reschedule_meeting (never a second book_meeting) to Friday at "
        "three, confirms the new time and the new invite.",
        ("meeting_booked",), tools=("book_meeting", "reschedule_meeting")),
    Scenario(
        "it_no_then_yes", "it", "Francesca", "app per lo studio di yoga",
        "Yoga teacher with a class-booking app; tired at first, then warms up.",
        "First say 'No, adesso non ho voglia.' When she asks when would be better, change your mind: 'Ah, va beh, "
        "dai, parliamo adesso.' Then say the app works but you'd like members to pay online. If offered an expert "
        "call, say 'non so, forse'. If nudged once, accept and take Saturday morning.",
        "Takes the change of mind warmly without asking about a better time again, asks about the app, offers the "
        "call, asks once what holds her back or nudges once, books Saturday morning.",
        ("meeting_booked",), tools=("book_meeting",), never=("mark_do_not_call",)),
    Scenario(
        "it_voicemail", "it", "Matteo", "sito per lo studio legale",
        "This is an answering machine, not a person.",
        "Your only line, whatever she says: 'Risponde la segreteria telefonica dello studio legale Rossi. Lasciate "
        "un messaggio dopo il segnale acustico.' Then <hangup>.",
        "Recognises voicemail and hangs up with detected_answering_machine without leaving a message.",
        ("voicemail",), tools=("detected_answering_machine",), max_turns=2),
    Scenario(
        "en_switched_tool", "en", "Mike", "client portal for the agency",
        "Runs a small web agency in Leeds; moved his client projects to Lovable two months ago because Emergent "
        "burned through credits. Direct, not hostile.",
        "Say you don't really use Emergent anymore, you moved to Lovable because of the cost. If asked what was "
        "missing, say the credit burn on big refactors. If offered a call to fix exactly that, say 'not right now, "
        "thanks'. If nudged once more, still no. Answer the last feedback question with 'cheaper refactors'.",
        "Asks what made him stop and what he uses now, never criticises Lovable, offers a call only about the credit "
        "burn, takes the no after one nudge at most, asks for last feedback, closes warmly.",
        ("not_interested", "not_now"), never=("book_meeting",)),
    Scenario(
        "en_manual_schedule", "en", "Priya", "inventory tool for the bakery chain",
        "Operations lead at a three-shop bakery chain; very busy, only free after 7 pm or on Sundays.",
        "Say it's going well and you want to add supplier ordering, so an expert call sounds useful. When she offers "
        "times, say none work: you can only do weekday evenings after seven or Sunday mornings.",
        "Offers the expert call, checks the calendar, offers the nearest times, and when none fit records Priya's "
        "preferred times with request_manual_scheduling (never asks for her email), says the team will email an "
        "invite.",
        ("manual_scheduling",), tools=("request_manual_scheduling",)),
    # 24 Oct ("she lacks awareness"): the failures seen on real pod calls, 20-21 Oct
    Scenario(
        "en_annoyed_purpose", "en", "Rahul", "assignment portal for my students",
        "A college lecturer who didn't expect the call and is irritated by it at first, but fair: he'll talk if the "
        "agent stays calm and gets to the point. Short, sharp sentences.",
        "Start with 'Why are you even calling me?'. Whatever she answers first, say 'No. No. This is not the way you "
        "talk to us.' If she stays calm and gives a clear reason plus a choice, say 'Okay, two minutes.' Then say "
        "the portal works but the agent keeps saying bugs are fixed when they aren't. If offered a call with an "
        "expert about that, accept and take the first time offered. If she grovels or keeps apologising, say "
        "'Forget it, bye.'",
        "Doesn't fold: no 'you're absolutely right / I apologize / what would work better'. Names the mood, gives the "
        "reason for the call in a line, offers a choice; then hears the bug problem, offers an expert call about it "
        "and books it.",
        ("meeting_booked",), tools=("book_meeting",), never=("mark_do_not_call",)),
    Scenario(
        "en_lovable_switch", "en", "Maya", "booking site for the yoga studio",
        "Runs a yoga studio; built her booking site on Emergent but finds the live site slow and is trying Lovable. "
        "Talks in bursts and often stops mid-sentence.",
        "Say 'I'm thinking of switching to Lovable.' Then a half sentence: 'I don't think Emergent because'. Then "
        "'Latency wise, the site is'. If she asks about Lovable or the speed, explain the live site is slow for "
        "customers. If offered a call with an expert to look at the speed, accept and take the first time offered.",
        "Picks up the Lovable mention at once (asks what's pulling her there, never knocks Lovable), answers the "
        "half sentences with a short 'go on' instead of line-trouble lines, offers an expert call about the site's "
        "speed and books it.",
        ("meeting_booked",), tools=("book_meeting",), never=("mark_do_not_call",)),
    Scenario(
        "en_offtopic_drag", "en", "Vikram", "inventory app for the shop",
        "A shopkeeper who is curious about the AI and keeps testing it with unrelated requests; friendly, not "
        "hostile, a little playful.",
        "Say 'Hello? Who is this?'. Then ask her to reply in Hindi. Then 'Do you have my email? What is it?'. Then "
        "'Reply to me in Italian.' then, after she replies, 'Actually, English is fine.' If she brings you back to "
        "your app, say it tracks stock for your shop and the credits run out fast. If offered an expert call about "
        "the credits, say 'maybe later' and, if nudged once, 'okay, Friday afternoon'.",
        "Answers each off-topic request in one sentence and brings the call back to the app, never switches "
        "language twice in a row or claims she 'already speaks' a language, doesn't read the email out, gets to the "
        "credit problem and offers an expert call about it.",
        ("meeting_booked", "not_now", "not_interested"), never=("mark_do_not_call",)),
    Scenario(
        "en_abrupt_bye", "en", "Leo", "perfume store",
        "Owns an online perfume store; frustrated that a support ticket about checkout has been open a week. Wants "
        "a date, not sympathy, and leaves abruptly.",
        "Say the store is live but checkout is broken and your ticket has been open a week. Ask 'By what time will "
        "it be resolved? I need a date.' After her answer, say 'Okay. Bye bye.' If she keeps talking, say 'Bye.' "
        "and <hangup>.",
        "Logs the checkout problem with log_support_issue, sells nothing, doesn't promise a date, and when he says "
        "bye closes in one sentence with no 'wait, before you go' or extra question.",
        ("not_now", "not_interested", "other"), tools=("log_support_issue",), never=("book_meeting",)),
    Scenario(
        "it_noisy_brand", "it", "Sara", "gestionale per il negozio",
        "Owns a clothes shop in Verona; built an internal stock tool. Speaks quickly, the line is fine but she trails "
        "off mid-sentence, and the transcript mishears the brand.",
        "Say 'Sì, lo sto facendo su emergenza, il gestionale per il negozio.' Then a half sentence: 'Però i crediti "
        "perché'. Then 'finiscono troppo in fretta, ogni modifica costa'. If offered a call with an expert about the "
        "credits, accept and take the first time offered.",
        "Reads 'emergenza' as Emergent (no talk of an emergency), answers the half sentence with a short 'prego' "
        "instead of line-trouble lines, asks one question about the credits, offers an expert call about them and "
        "books it.",
        ("meeting_booked",), tools=("book_meeting",), never=("mark_do_not_call",)),
)
BY_ID = {s.id: s for s in SCENARIOS}
