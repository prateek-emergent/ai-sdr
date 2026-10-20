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
2026-10-20 · TTS_MIN_SENTENCE_LEN 20 → 8 · short replies waited 0.18–0.65 s for a 2nd sentence · UNPROVEN, revert: TTS_MIN_SENTENCE_LEN=20
2026-10-20 · INTERRUPTION_MIN_S 0.5 → 0.3 · barge-in stop 1.35 s · UNPROVEN (watch mid-line stops), revert: INTERRUPTION_MIN_S=0.5
2026-10-20 · LLM output cap 400 tokens (was none / 1024) · turns ≤25 words; stops runaway replies · UNPROVEN, revert: LLM_MAX_OUTPUT_TOKENS=0
2026-10-20 · all three in one commit ("Latency settings…") · `git revert` it, or set the env values above on the pod
2026-10-20 · claim "the call with our team is free" (claims_*.md + meeting pitch, it/en) · Prateek signed off
2026-10-20 · repo: github.com/prateek-emergent/ai-sdr (private); commit 1 = pod snapshot b7baff2, changes in revertable commits · Prateek
2026-10-20 · bump backend/ai_sdr/VERSION (= last code commit) on every push · pod supervisor restarts the worker only when VERSION or .env changes; /health shows it
2026-10-20 · pod .env already overrides TTS_MIN_SENTENCE_LEN=6, ENDPOINTING_MAX_S=1.2, PREEMPTIVE_MAX_SPEECH_S=60 · .env beats code defaults: on the pod sentence length stays 6, not 8
2026-10-20 · pod .env: no Italian ElevenLabs voice, STT_PROVIDER=deepgram, no SONIOX/HUBSPOT keys · found when pulling .env; fixes listed in chat
PENDING · legal: dial Italian numbers only if customer-provided; check Registro Pubblico delle Opposizioni · GDPR / Italian telemarketing rules
PENDING · rotate HubSpot private-app token · pasted in chat
2026-10-20 · Talk page redesign: monochrome frosted glass, light + dark (system default; toggle remembered per browser) · Prateek's brief, built with the Impeccable skill
2026-10-20 · Talk page only, conversation first (transcript main, actions rail, slim status bar); /calls untouched, keeps latency colours · question round answers
2026-10-20 · glass sits over a "voice light": Giulia's disc (left) and yours (right) swell with live audio level · gives the blur a job; shows who's talking
2026-10-20 · Talk page uses the system UI font, not Inter · Impeccable detector flags Inter as overused; system stack fits working screens
2026-10-20 · "What Giulia did" also lists language switches, support issues, calendar errors; callback failures no longer show as booked · backend already sent them
2026-10-20 · PRODUCT.md, DESIGN.md, .impeccable/ (surface brief, design.json) in repo; .impeccable/review/ screenshots gitignored · design record for later UI work; PNGs not app code
2026-10-20 · voice light level = clamp((volume - 0.08) × 3) (App.js VoiceField) · mic never reads 0 (room noise) · UNPROVEN, tune if a disc sits swollen in silence or barely moves
2026-10-20 · Impeccable concept roll skipped (FORM: direction pinned) · Prateek pinned palette, material, layout; reviewer's one open item · PENDING: Prateek accepts or asks for a roll
2026-10-20 · Giulia's voice = ElevenLabs "Ginevra" QITiGyM4owEZrBEf0QV8, for it AND en · warm, no strong accent, built for conversation, free-plan allowed; one voice = same person after a mid-call switch · alts: Rossana MuTiG4dbrEGYEy3XP4iP, Giusy 8KInRSd4DtD5L5gK7itu
2026-10-20 · local run on the Mac: run-local.sh, AGENT_NAME=ai-sdr-local, reports to files (no MongoDB yet); pod copies of .env kept as pod.env · local calls never reach the pod or prod
PENDING · ElevenLabs is on the free plan and its 10k credits are used up until 18 Nov 2026 (Deepgram voice until then); Starter $6/mo = 30k credits + commercial licence · Prateek
PENDING · Soniox key: no free API credits since Oct 2025; pay-as-you-go $0.12/h streaming · Prateek creates console.soniox.com account
PENDING · pod .env: ELEVENLABS_VOICE_ID_IT and _EN = QITiGyM4owEZrBEf0QV8 · same voice as local
2026-10-20 · PREEMPTIVE_TTS 1 → 0 · a cancelled draft voice stream closed the TTS websocket, so every reply reconnected (+0.8 s from the laptop); scripted IT call e2e p50 2.61 → 1.79 s · revert: PREEMPTIVE_TTS=1
2026-10-20 · prompt v4 (it/en): listen before asking, spoken register, natural booking lines, Lei → tu if they use tu, "let me check" before lookups · test calls re-offered an accepted call, said "non è disponibile in questo momento", "slot" · revert: git revert
2026-10-20 · opener: spoken wording, app as apposition ("la sua app, X"), Buonasera after 17:00 their time · "ha creato gestionale per lo studio" had no article
2026-10-20 · Deepgram in the call's language; the language twin gets its own STT stream · "multi" lost punctuation → turns waited ENDPOINTING_MAX_S; it→en switch test heard English fine · revert: DEEPGRAM_LANGUAGE=multi
2026-10-20 · office room tone (0.8) + typing only during calendar lookups (0.5) · "feels like a bot"; levels measured: room tone ~29 dB, typing ~18 dB under her voice · UNPROVEN by ear, revert: BACKGROUND_AMBIENCE=off TYPING_SOUND=0
2026-10-20 · noise cancellation: Krisp BVC (web), BVCTelephony (phone) · noise shouldn't count as the caller talking · revert: NOISE_CANCELLATION=off; pod needs livekit-plugins-noise-cancellation
2026-10-20 · LLM warm-up built, off (LLM_WARM_ON_SPEECH) · laptop: slower while the caller spoke (ttft p50 1.61 vs 1.04 s), no gain after she spoke; proxy drops idle connections · retest on the pod
2026-10-20 · knobs: ENDPOINTING_MODE, TURN_UNLIKELY_THRESHOLD, TTS_EXPRESSIVE · short Italian answers ("Sì, sì. Dimmi pure.") wait the full 1.2 s; tune on real calls
2026-10-20 · voice: most human = ElevenLabs v4 Turbo (AA #1, paid plan or startup grant); best free = Inworld TTS-2 via LiveKit Inference (AA #7, Italian GA, ~1.8 h/month on the free credit, first audio +0.2 s vs Deepgram) · local runs Inworld "Orietta" → Deepgram fallback
PENDING · Prateek picks Giulia's voice by ear (~/.ai-sdr-local/voice-samples) · then set on the pod
PENDING · ElevenLabs library voices (Ginevra) need a paid plan: the free tier can't use library voices via the API
2026-10-20 · repo github.com/prateek-emergent/ai-sdr is PUBLIC (logged as private above); Prateek keeps it public · scanned: no .env, keys or tokens in it
2026-10-20 · CORRECTION: PREEMPTIVE_TTS stays 1 (default). The 'off' finding was a laptop artifact: pod run of the same call, preemptive on = first audio 0.07 s, e2e p50 1.20 s; reconnects are only slow far from Deepgram · local .env keeps PREEMPTIVE_TTS=0
2026-10-20 · Talk page voice picker: 5 IT + 5 EN female voices (voice/catalog.py): Cartesia Sonic 3.6 ×3, Inworld TTS-2, Deepgram Aura-2 per language; Deepgram behind every LiveKit Inference pick · AA arena (Cartesia #4, Inworld #7) + measured first audio (Cartesia 0.11-0.14 s warm); Gemini 3.8 Flash (#5) left out: 1.1-1.5 s first audio
2026-10-20 · a voice fallback is shown on the page (chip "Deepgram (fallback)" + action row) · picks out of credit fell back silently, so a test would name the wrong voice
PENDING · LiveKit Inference voices refuse with 429 (free plan's monthly quota used by the day's voice tests); Cartesia/Inworld picks speak Deepgram until the reset or an upgrade, or Cartesia/Inworld keys of our own
2026-10-20 · tracing: Langfuse Cloud (free Hobby, EU region), fed by LiveKit's own OpenTelemetry spans; one call = one Langfuse session (room name) · over LangSmith: LiveKit documents it, Langfuse already parses LiveKit's spans, MIT self-host if we outgrow the free plan, 2 seats/30 days vs 1/14, EU + DPA free · off until LANGFUSE_* keys are set
2026-10-20 · traces masked by default (emails, phone numbers) and only the readable spans sent (TRACE_SPANS=turns, ~5 per turn instead of ~12) · Italian customers' data; the free plan counts spans and scores (50k units/month): a local 5-turn call sent 31 spans instead of 56, so ≈ 400 calls of ~20 turns a month · revert: TRACE_CONTENT=full, TRACE_SPANS=all
2026-10-20 · every finished call graded by a judge (claude-sonnet-5-5) on 15 checks from prompt v4 + the Nooks findings, 4 of them MUST (AI disclosure, allowed claims, respecting a no, honest actions) · grade in the report ("eval") and as Langfuse scores; the grader runs beside the worker, never in it · EVALS_AUTO=0 to stop
2026-10-20 · self-improvement loop rebuilt for free instead of Cekura: 14 simulated customers (text, real prompt + tools, fake calendar), `evals improve` proposes a prompt change and A/B-tests it on them; a person applies it · Cekura's "Optimize" doesn't support self-hosted LiveKit agents; free = 300 credits (~60 voice-test min); LiveKit's own audio simulations: 60 turns/month on Build
2026-10-20 · Langfuse project "My Project" (EU cloud) live: keys in the local .env; a local voice call and two simulations traced, graded and scored end to end · Langfuse Cloud is v4-only for new projects: reads go through /api/public/v2/observations and /v3/scores (the v1 trace/session reads answer 410)
PENDING · Langfuse keys into the pod .env, with the push of the tracing code · Prateek says push
PENDING · rotate the Langfuse API keys (pasted in chat) · Prateek, Langfuse settings → API keys
PENDING · DPA with Langfuse (ClickHouse DPA, SCCs) before real customer calls are traced; test calls are fine · legal
PENDING · LiveKit Cloud's own observability (recordings, transcripts, traces; free on Build) is off: session.start(record=False) · decide: on for web test calls only? recordings need the "call is recorded" line on phone calls
