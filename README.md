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
| `ELEVENLABS_VOICE_ID_IT` / `_EN` | `ELEVENLABS_VOICE_ID` | Giulia's voice per language. A language without one uses Deepgram's voice. |
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
