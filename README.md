# AI SDR · LLM relay

Forwards the AI SDR pipeline's OpenAI-format chat calls to the Emergent LLM proxy
(`integrations.emergentagent.com/llm`), which only accepts traffic from Emergent's servers.

- `POST /api/llm/chat/completions`: needs `Authorization: Bearer <EMERGENT_LLM_KEY>` (the same key this app holds). Streaming supported.
- `GET /api/health`

Pipeline side: `LLM_PROVIDER=emergent`, `EMERGENT_LLM_KEY=...`, `INTEGRATION_PROXY_URL=https://<this app>/api`.
