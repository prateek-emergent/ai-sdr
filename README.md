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

Before every push, from `backend/`: `python -m pytest` and `python -m ai_sdr.agent.prompt_check` (the Italian and English prompts must stay in step).
