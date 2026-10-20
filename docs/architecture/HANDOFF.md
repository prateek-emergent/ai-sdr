# Giulia handoff

What the voice agent looked like when we started from the preview pod (snapshot `0c20695`, VERSION `b7baff2`), what it is now (`824731c` plus local work), and how the backend changed in between. Diagrams: [before.html](before.html) and [after.html](after.html), made with the diagram-design skill, plus [llm-context.html](llm-context.html): everything Giulia's LLM reads on a turn. The core voice agent's low-level designs, with the runs behind each change: [core-agent.html](core-agent.html).

## What changed

**On the call**

- Calls are Italian or English, and switch mid-call when the person prefers the other language.
- On phone calls Giulia starts with the HubSpot customer card (name, app, plan, last contact), read while the phone rings; the web demo builds it from the form.
- Prompt v4: listen before asking, no echoing, spoken register, natural booking lines, a short "let me check".
- A more human voice: 10 voices to pick from with a Deepgram backup, a noise filter, office room tone and typing during calendar lookups.

**Around the call**

- Every call is a Langfuse trace: each turn, the prompt and reply, tokens, voice and tools.
- Every finished call is graded on 15 checks (4 of them must-rules), into the report and onto the trace.
- Quality page: where Giulia slips, how the grader works, and how far to trust it.
- 14 simulated customers and a propose-and-test step for prompt changes; a person approves before anything ships.

**On the page**

- The Talk page redesigned in monochrome frosted glass, light and dark.
- A live timing chart of every reply: heard, turn over, tools, thinking, voice, audible.
- A Trace link per call that opens without a Langfuse login; a Langfuse button for the team.

## How the backend architecture improved

Paths are under `backend/ai_sdr/` unless they say otherwise.

1. **Language is per call, not per deployment.** The worker picks each call's language (page or dialer choice, then the prospect's own, country, phone prefix). Voices are built per language on first use and kept. switch_language hands the call to a twin agent with its own speech-to-text and voice through LiveKit's handoff, history included. A parity check keeps the Italian and English prompts structurally identical.
   `agent/worker.py · voice/providers.py · agent/sdr_agent.py · agent/prompt_check.py`

2. **Customer context before the first word.** The customer card is read from HubSpot while the phone rings (3 s budget), split into what she may say and what only steers her. Do-not-touch contacts are never dialled; inbound calls load the card after the greeting.
   `agent/card.py · agent/prompts.py`

3. **A voice layer with honest fallbacks.** A catalog of 10 voices with no LiveKit import, so the web backend serves it too. A picked voice runs on LiveKit Inference with Deepgram behind it; every switch is recorded and shown on the page. Speech-to-text runs in the call's language. Noise cancellation, room tone, typing sounds and filler lines live in one module.
   `voice/catalog.py · voice/providers.py · voice/texture.py · voice/pronunciation.py`

4. **Tracing built on LiveKit's own spans.** LiveKit's OpenTelemetry spans go to Langfuse, labelled per call through a context variable (session = room, environment, release, tags). Emails and phone numbers are masked before export. Plumbing spans are dropped and their children re-attached, so a 5-turn call costs 31 units instead of 56. Test calls' traces are public. The trace id is saved in the call report. Off until the keys are set.
   `voice/tracing.py`

5. **A live channel to the page.** Each turn's timings come from LiveKit's turn metrics, tool durations from the agent, and the trace id, all over the existing sdr.events data topic. The Talk page draws them as they happen.
   `voice/live.py · agent/sdr_agent.py`

6. **Quality as its own subsystem.** The grader is a separate process started by the web backend, one per machine, restarting itself on new code; a live call never waits for it. Report storage is one interface over MongoDB and files, so the same code runs on the pod and a laptop. The judge goes through the existing LLM gateway. Scores reach Langfuse in one batch with stable ids. Statistics are pure functions. Simulations run the real agent in text mode; the improve step writes a candidate prompt to a folder, checks parity, A/B-tests it and leaves the decision to a person.
   `evals/watch.py · reports.py · rubric.py · grade.py · langfuse.py · quality.py · simulate.py · improve.py`

7. **New endpoints on the web backend.** /api/voices, /api/observability, and /api/quality/summary, /calls, /calls/{room}, /review, /regrade, /rubric. Quality data uses the same access token as /calls.
   `server.py`

8. **Settings, safety and process.** Every new setting is validated at startup and documented in the README. .env files are never committed. decisions.md records each change with how to revert it. A VERSION bump makes the pod's supervisor roll the worker onto new code without dropping calls.
   `config.py · voice/config.py · README.md · decisions.md`

9. **Tests from zero to 45.** Bilingual flow, settings, voice catalog, grading, the tracing wire format and the quality endpoints, plus the prompt parity check before every push.
   `backend/tests/ · agent/prompt_check.py`

## Where it stands

**On the preview pod (VERSION 824731c)**

- Bilingual agent, customer card, prompt v4, voice picker, room tone, noise cancellation.
- Langfuse tracing and the call grader, with keys set; the redesigned Talk page.

**Built and tested locally, not pushed yet**

- Quality page, live timing chart, public trace links, Langfuse button.
- /api/observability and /api/quality/*; voice/live.py, evals/quality.py; 4 new tests.
- These architecture pages (docs/architecture/).

| Measure | Value | Where |
|---|---|---|
| Reply time, median per call | 1.20 to 1.49 s | 4 scripted calls on the pod, 20 Oct |
| Voice first audio, median per call | 0.10 to 0.11 s | same calls |
| LLM first token, median per call | 0.53 to 0.79 s | same calls |
| Langfuse units, 5-turn call | 31, down from 56 | local voice call, LLM wrapper spans dropped |
| Time to grade a call | about 9 s | local grader |
| Simulated customers, first run | 11 of 14 ended right; 70% of checks passed | local, before simulator fixes |
| Automated tests | 45 passing | backend/ |

## Start here

**Read first**

- decisions.md: every change, why, and how to revert it.
- README.md: every setting with its default.
- docs/architecture/before.html and after.html: these diagrams. llm-context.html: where the LLM's context comes from (prompt files, call facts, customer card, tools, history).

**Run and check**

- From backend/: python -m pytest, then python -m ai_sdr.agent.prompt_check.
- python -m ai_sdr.cli evals simulate runs the simulated customers.
- python -m ai_sdr.cli evals improve proposes and tests a prompt change.

**Ship**

- Push to main on github.com/prateek-emergent/ai-sdr; on the pod: cd /app && git pull --no-rebase --no-edit origin main.
- Bump backend/ai_sdr/VERSION so the supervisor rolls the worker; supervisorctl restart backend when server.py changes.

**Open items**

- Rotate the Langfuse keys and the HubSpot token (both pasted in chat).
- Sign Langfuse's DPA before real customer calls are traced.
- The turn detector waits the full 1.2 s on short Italian answers (TURN_UNLIKELY_THRESHOLD is untuned).
- ElevenLabs credits are out until 18 Nov; LiveKit Inference credit resets monthly; the phone path needs a SIP trunk.
