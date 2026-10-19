# decisions

`date · decision · why` — newest last, one line each. PENDING = needs a call from Prateek.

2026-10-19 · livekit-agents 1.8.8, self-hosted `start` mode · latest release; adaptive interruption verified in `start` mode
2026-10-19 · Turn Detector v1 + adaptive interruption · best end-of-turn (eot-bench); Krisp interruption model is EN-only
2026-10-19 · no Deepgram Flux · TD v1 beats it (9.9% vs 12.9% false cut-offs @300 ms); would pay end-of-turn twice
2026-10-19 · TTS ElevenLabs eleven_v4_turbo → Deepgram Aura-2 fallback · most natural voice; 0.41 s first audio
2026-10-20 · LLM via LiteLLM key only (Claude Haiku) · company constraint
2026-10-20 · STT→LLM→TTS pipeline; no voice-to-voice / duplex for now · control, own voice, cost
2026-10-20 · STT Soniox stt-rt-v5 (hints it+en) → Deepgram nova-3 fallback · cheaper/faster; hears both languages without a swap
2026-10-20 · workflow: edit local `marketplace-build-30/` → GitHub → Emergent job pulls into preview pod; no pod edits · versioned, reviewable
2026-10-20 · `.env` never leaves the pod; `.emergent/` not in repo · secrets; platform-managed
2026-10-20 · goal: call existing customers (heavy spenders first) for feedback → qualify → product-team meeting · Prateek
2026-10-20 · keep low-engagement path + credit-pricing angle · part of the purpose (Prateek)
2026-10-20 · languages: Italian for customers, English mandatory for testing · Italy campaign; team can't judge Italian
2026-10-20 · language per call (data → it/en); mid-call switch it↔en via agent handoff · one worker serves both; ~45 Nooks calls lost to language
2026-10-20 · customer card pulled from HubSpot at dial time; prompt split "say aloud" / "background, never say" · 50% of Nooks no's came at the opener, 13% wrong person; no creepy numbers
2026-10-20 · card = name, email, country→lang/tz, contact history, plan, customer-since, apps, status, spend/credit words, priority, why-now, tickets · see analysis; numbers never spoken
2026-10-20 · data team to build: what they built, last active date, support tickets · HubSpot fields exist but <1% / 0% filled
2026-10-20 · meeting pitch = free build review with a product specialist; ask cause of cost pain before credit offers · discounts flipped 0/39 no's; specialist pitch booked more
2026-10-20 · meeting-worthy = live/active app (≤30 d) + business/clients/revenue or several projects + concrete blocker; paused >30 d → callback · ~1 in 10 Nooks "meetings" weren't
2026-10-20 · win-back branch for lapsed customers: why left · what now · what brings them back · 11% moved to other tools, 13% stopped
2026-10-20 · support/billing problems → log_support_issue tool; never upsell while broken · 1 in 5 follow-ups; upsell-while-broken backfired
2026-10-20 · VAD min_silence 0.55 → 0.35 s · in 1.8.8 it (not ENDPOINTING_MIN_S) sets the end-of-turn floor; LiveKit min 0.25
2026-10-20 · filler line when a calendar tool runs >0.8 s and she is silent · Calendly ≤8 s per request, 2–3 per booking
2026-10-20 · pronunciation map in tts_node (word-boundary regex); entries only after listening tests · Samora pattern; no guessing
2026-10-20 · prompt parity check it/en (sections, placeholders, tools) · a fix must land in both
2026-10-20 · post-call summary bilingual + who-for, stage, blockers, wishes, competitor · product-team brief needs them
2026-10-20 · Soniox max_endpoint_delay 2000 → 500 ms · plugin sends finals only at its endpoint; LiveKit needs a final to end a turn
2026-10-20 · Deepgram fallback hears the call's starting language · its keyterms are monolingual (nova-3)
2026-10-20 · language pick: page/dispatch → prospect language → country → +39 → default · Italy = it, everyone else = en
2026-10-20 · switch = LiveKit agent handoff to a twin (own prompt + voice; STT/turns/LLM stay) · supported API, not Samora's private swap
2026-10-20 · fillers = LiveKit RunContext.with_filler (built into 1.8.8) · fires only after silence; nothing custom
2026-10-20 · HubSpot do_not_touch → never dialled, DNC copied locally · outbound team's own flag
2026-10-20 · callbacks open as callbacks; dialer sends job kind · Nooks reps re-pitched callbacks like cold calls
2026-10-20 · support issue → same-day HubSpot task (HUBSPOT_SUPPORT_OWNER_ID, else meeting owner) · the email promise must not get lost
2026-10-20 · HubSpot holds 0 tickets → card ticket line empty until a real support source · support lives elsewhere
2026-10-20 · demo page: IT/EN switch + optional app name · team tests English and the account-aware opener
2026-10-20 · `python -m pytest` + `python -m ai_sdr.agent.prompt_check` before every push · catch drift locally; the pod is the live test
PENDING · pod .env: SONIOX_API_KEY (and drop STT_PROVIDER or set STT_CHAIN=soniox,deepgram), ELEVENLABS_VOICE_ID_EN · else Deepgram / one voice
PENDING · Phase 1 settings not touched: TTS_MIN_SENTENCE_LEN 20→8, INTERRUPTION_MIN_S 0.5→0.3, max tokens ~400 · need a go-ahead
PENDING · "the call is free" claim → add to claims_*.md · claims need Prateek's sign-off
PENDING · legal: dial Italian numbers only if customer-provided; check Registro Pubblico delle Opposizioni · GDPR / Italian telemarketing rules
PENDING · rotate HubSpot private-app token · pasted in chat
