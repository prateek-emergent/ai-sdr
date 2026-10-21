# AI SDR · LLM relay

Forwards the AI SDR pipeline's OpenAI-format chat calls to the Emergent LLM proxy
(`integrations.emergentagent.com/llm`), which only accepts traffic from Emergent's servers.

- `POST /api/llm/chat/completions`: needs `Authorization: Bearer <EMERGENT_LLM_KEY>` (the same key this app holds). Streaming supported.
- `GET /api/health`

Pipeline side: `LLM_PROVIDER=emergent`, `EMERGENT_LLM_KEY=...`, `INTEGRATION_PROXY_URL=https://<this app>/api`.

## Voice agent settings (20 Oct: bilingual calls, customer card)

Decisions and their reasons: `decisions.md`. In `backend/.env` (never committed):

| Setting | Default | What it does |
|---|---|---|
| `SONIOX_API_KEY` | — | Turns on Soniox speech-to-text (Italian + English in one stream), Deepgram stays as fallback. If `STT_PROVIDER` is set, remove it or set `STT_CHAIN=soniox,deepgram`. |
| `STT_BACKUP` | `1` | Speech-to-text never runs alone: Deepgram (with its key) and LiveKit Inference go behind the configured engine, and the call switches in ~0.1 s if it fails. `0` keeps `STT_CHAIN` / `STT_PROVIDER` exactly as written. |
| `ELEVENLABS_VOICE_ID_IT` / `_EN` | `ELEVENLABS_VOICE_ID` | Giulia's voice per language. A language without one uses Deepgram's voice. |
| `CARTESIA_API_KEY` / `CARTESIA_VOICE_ID_EN` | — | Cartesia with our own key (21 Oct: English = "Amber", `a7a59115-2425-4192-844c-1e98ec7d6877`). Put it first in `TTS_CHAIN` (`cartesia,deepgram`): Deepgram speaks if Cartesia fails. A language without a Cartesia voice id starts on the next voice (Italian → Deepgram). English Cartesia picks on the Talk page use this key too. |
| `CARTESIA_MODEL` | `sonic-3.6` | Cartesia model (the one the Talk page's Cartesia voices were chosen on). |
| `AGENT_LANGUAGE` / `AGENT_LANGUAGES` | `it` / `it,en` | Default call language / languages a call may switch between. |
| `HUBSPOT_API_KEY` | — | Also feeds the customer card read at dial time (`CARD_TIMEOUT_S`, default 3). |
| `HUBSPOT_SUPPORT_OWNER_ID` | meeting owner | Who gets the task when a call logs a support issue. |
| `VAD_MIN_SILENCE_S` | `0.35` | Silence before a turn can end (LiveKit needs ≥ 0.25). |
| `SONIOX_MAX_ENDPOINT_DELAY_MS` | `500` | How soon Soniox makes words final (500–3000). |
| `FILLER_DELAY_S` | `0.8` | Silent seconds into a slow calendar step before "one moment…". |
| `TTS_PRONUNCIATIONS_IT` / `_EN` | empty | JSON `{"written": "spoken"}` for words the voice says wrong. |
| `TTS_MIN_SENTENCE_LEN` | `8` (was 20) | Shortest piece sent to the voice on its own. Unproven: revert with `20`. |
| `INTERRUPTION_MIN_S` | `0.3` (was 0.5) | Speech needed before Giulia stops talking. Unproven: revert with `0.5`. |
| `LLM_MAX_OUTPUT_TOKENS` | `400` | Cap on one reply. Unproven: `0` turns the cap off. |
| `PREEMPTIVE_TTS` | `1` | Start the voice on the draft reply (pod: first audio 0.07 s). Set `0` only far from the providers (a laptop in India), where each cancelled draft costs a 0.8 s reconnect. |
| `DEEPGRAM_LANGUAGE` | `call` | Deepgram hears the call's language; a language switch gives the new agent its own stream. `multi` = both in one stream (worse punctuation). |
| `TTS_CHAIN` / `INFERENCE_TTS` / `INFERENCE_TTS_VOICE` | — | e.g. `livekit,deepgram` + `inworld/inworld-tts-2` + `Orietta`: a more human voice through LiveKit Inference, Deepgram as fallback. |
| `TTS_EXPRESSIVE` | `0` | LLM adds emotion/pace tags the voice performs (Inworld/Cartesia via LiveKit Inference, alone in the chain). |
| `BACKGROUND_AMBIENCE` / `AMBIENCE_VOLUME` | `office` / `0.8` | Quiet office room tone under the call; `off` to disable. |
| `TYPING_SOUND` / `TYPING_VOLUME` | `1` / `0.5` | Keyboard typing while a calendar lookup runs. |
| `NOISE_CANCELLATION` | `auto` | Krisp BVC on the caller's audio (BVCTelephony on phone lines); needs `livekit-plugins-noise-cancellation`. |
| `ENDPOINTING_MODE` | `fixed` | `dynamic` learns each caller's pause length. |
| `TURN_UNLIKELY_THRESHOLD` | LiveKit defaults | e.g. `it:0.15`: wait the full ENDPOINTING_MAX_S less often on short Italian answers. Test on real calls. |
| `LLM_WARM_ON_SPEECH` | `0` | Reopen the LLM connection after each of her lines. No gain measured from the laptop. |

Before every push, from `backend/`: `python -m pytest` and `python -m ai_sdr.agent.prompt_check` (the Italian and English prompts must stay in step).

## Tracing and the improvement loop (20 Oct)

- **Traces (Langfuse).** Every call is a Langfuse session named after its room: each turn, the LLM request (prompt, reply, tokens, time to first token), the voice and the tools, from LiveKit's own OpenTelemetry spans (`ai_sdr/voice/tracing.py`). Off until the keys are set.
- **Grades.** The web backend starts `ai_sdr.evals.watch` next to the voice supervisor. It grades every finished call (a judge model on 15 checks from the prompt and the Nooks calls, plus counted checks), writes the grade into the call report (`eval`), and puts the score, outcome, timings and failed checks on the call's Langfuse trace. Log: `/tmp/ai_sdr_evals.log`.
- **Simulated customers.** 14 scenarios (`ai_sdr/evals/scenarios.py`) played by a model against the real prompt and tools, in text, each call graded plus "did it end where it should".
- **Improve.** Reads the failures, proposes one change to both prompts, runs the scenarios on the old and new prompt, writes a report. A person decides; `--apply` copies it into the repo.
- **Quality page** (`/quality`): how calls are graded, the share of calls passing each check, how far the grader can be trusted, and every call with its verdicts, quotes and transcript.
  - Trust in the grader is measured two ways: people mark verdicts right or wrong, and "Grade again" checks the judge's consistency.
  - It uses the same token as `/calls`. Its "Share link" button copies a `?token=` link that opens for anyone who has it, and that link includes the transcripts.
- **Live timing** on the Talk page: each reply's steps as a flow and a waterfall against the 1.5 s target, plus tool durations and every reply so far.
  - The steps are heard, turn over, tools, thinking, voice, and Giulia audible.
  - The data comes from LiveKit's turn metrics, which the worker sends on `sdr.events` (`ai_sdr/voice/live.py`).
- **Langfuse links**:
  - **Langfuse** button: opens the project dashboard. Members sign in; the free plan has 2 seats.
  - **Trace** link, per call: test calls' traces are public (`TRACE_PUBLIC`), so they open for anyone, with no login.

From `backend/`, with its venv's python (`/root/.venv/bin/python` on the pod):

```
python -m ai_sdr.cli evals simulate [--scenario it_dnc,it_busy_callback] [--repeat 3] [--trace]
python -m ai_sdr.cli evals improve [--repeat 2]        # report: ~/.ai-sdr/evals/improve/<id>/report.md
python -m ai_sdr.cli evals improve --apply <candidate dir>
python -m ai_sdr.cli evals grade [--room demo-31e3d4b4]
python -m ai_sdr.cli evals scenarios
```

| Setting | Default | What it does |
|---|---|---|
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | — | Turn tracing and Langfuse scores on (project keys from cloud.langfuse.com). |
| `LANGFUSE_BASE_URL` (or `LANGFUSE_HOST`) | `https://cloud.langfuse.com` | EU region; `https://us.cloud.langfuse.com` for US. |
| `TRACE_CONTENT` | `masked` | `masked`: the conversation with emails and phone numbers replaced · `full` · `off`: timings, models and tokens only. |
| `TRACE_SPANS` | `turns` | `turns`: the call, turns, LLM requests, voice and tools, about 6 spans per turn (the free plan counts spans and scores: 50k units a month) · `all`: every span LiveKit emits. |
| `TRACE_PUBLIC` | `web,simulation` | Whose traces anyone with the link can open without a Langfuse login. Real customers' phone calls stay members-only unless listed. `all` · `none` · a comma list. |
| `EVALS_AUTO` | `1` | `0`: don't grade finished calls. |
| `EVAL_JUDGE_MODEL` / `EVAL_CUSTOMER_MODEL` / `EVAL_IMPROVE_MODEL` | `claude-sonnet-5-5` / `claude-haiku-4-5` / `claude-opus-5-5` | Models on the same gateway as the calls (LiteLLM names). |
| `EVAL_DIR` | `~/.ai-sdr/evals` | Where simulation runs and improvement reports go. |

## Models and voice-AI metrics (20 Oct)

- **Model picker** on the Talk page, next to the voice picker: the LLM that writes Giulia's replies for this test call (`ai_sdr/voice/llm_catalog.py`, `GET /api/llms`).
  - Only models that answer without thinking first (or think as little as the provider allows).
  - LiteLLM: GPT-4o, GPT-5.6 Terra, GPT-5.2, GPT-5.6 Luna and Claude Sonnet 5.5 (a quality reference). Each was measured on the pod with her real prompt, tools and opener; the numbers and the models left out, with reasons, are at the top of `llm_catalog.py`. Haiku 4.5 is still the steadiest (first token 0.63 s p50, 0.75 s p95). GPT-4o matches its median and gets the first sentence to the voice sooner (0.67 vs 0.80 s), but its slow replies are much slower (2.24 s p95).
  - Groq: GPT-OSS 20B and 120B and Qwen3.8 27B, the chat models our key can see (Llama 3.3 70B and 3.1 8B are enterprise-only now). On Groq's free plan every Giulia request is refused as too large (HTTP 413): it is 8.7–9.4k tokens, against 8K tokens a minute on GPT-OSS and 7K input tokens a minute on Qwen. Until the key's organisation is on the Developer plan, a Groq pick falls back to the default on the first reply.
  - The configured model (Claude Haiku 4.5 through LiteLLM) stays the default and stays behind every pick: a pick that errors or sends nothing for `LLM_ATTEMPT_TIMEOUT_S` (4 s) hands the reply to it. The page then shows "(fallback)" on the model chip and a line in "What Giulia did".
  - Groq models are listed but disabled until `GROQ_API_KEY` is in `backend/.env`; then restart the backend (`supervisorctl restart backend` on the pod; the worker reloads `.env` by itself). They go through LiveKit's OpenAI plugin at Groq's OpenAI-compatible address, so no new package.
  - Phone calls always use the configured model.
- **Voice-AI metrics**, all from LiveKit's per-turn metrics, counted from the moment the caller stops talking unless noted:

| Metric | What it measures |
|---|---|
| E2E (end-to-end) | caller stops → Giulia audible: the caller's wait |
| EOU (end of turn) | caller stops → the turn detector says the turn is over |
| STT (transcription) | caller stops → their words are written down |
| TTFT (LLM first token) | the model is asked → its first token |
| TTFS (LLM first sentence) | the model is asked → a whole sentence reaches the voice |
| TTFB (TTS first audio) | the voice gets the sentence → its first audio |
| TPS (LLM speed) | output tokens per second |

  - **Talk page:** this reply's numbers and the call's p50 / p95 under the waterfall; the flow's steps carry the same names.
  - **`/quality`:** p50 / p95 over the period, and a table per model (first token, first sentence, speed, end-to-end, checks passed, must-rules broken). Each reply counts for the model that actually wrote it.
  - **`/calls`:** the model and TTFT per call; the call page adds TTFS, TPS and STT.

| Setting | Default | What it does |
|---|---|---|
| `LLM_PROMPT_CACHE` | `1` | Claude through LiteLLM reads her tools and prompt (~10.7k of ~11.1k tokens a request) from Anthropic's cache. Pod A/B: first token p50 0.58 → 0.50 s. `0` turns it off. |
| `GROQ_API_KEY` | — | Offers the Groq models in the Talk page's model picker. |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Groq's OpenAI-compatible address. |
