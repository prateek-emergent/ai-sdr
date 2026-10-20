"""LLMs the team can pick on the Talk page before a test call (20 Oct: "identify the best lowest latency LLMs ... add
them as a drop down", "try the Groq models as well since they work on LPUs"). Only models that answer without
thinking first, or think as little as the provider allows: a reasoning model spends its first second where the caller
hears silence.

LiteLLM entries were measured on the preview pod on 20 Oct the way Giulia uses them: her Italian prompt, her 14
tools, the real opener, three turns, five runs each, the proxy's response cache bypassed. First token p50 / p95, first
sentence p50, calendar called when asked:
  claude-haiku-4-5 (the default) 0.63 / 0.75, 0.80, 5/5 · gpt-4o 0.64 / 2.24, 0.67, 4/5 · gpt-5.6-luna 0.87 / 1.10,
  0.90, 2/5 · gpt-5.2 0.92 / 1.13, 0.97, 5/5 · gpt-5.6-terra 0.95 / 1.35, 0.98, 5/5 · claude-sonnet-5-5 1.18 / 2.32,
  1.54, 5/5.
The GPT models get ~8k prompt tokens cached by OpenAI on their own; Haiku through LiteLLM gets none.
Left out: gpt-5.4-mini (called record_qualification instead of speaking on every turn), gpt-5.6-sol (read its tool
arguments aloud), gpt-6-astra and ultima-alpha (always reason), every vertex_ai Gemini and smart-router (the proxy's
Vertex credentials fail: "invalid_grant"), jev-latest (no healthy deployment).

Groq entries are the chat models our key can see (20 Oct; Llama 3.3 70B and 3.1 8B are enterprise-only now). On
the free plan every Giulia request is refused as too large (HTTP 413): 8.7-9.4k tokens against 8K tokens per minute
on GPT-OSS and 7K input tokens per minute on Qwen. Until the key's organisation is on Groq's Developer plan a Groq
pick falls back to the default on the first reply, and the page says so.

The configured model (LITELLM_MODEL, Claude Haiku 4.5) stays the default and stays behind every pick as the fallback,
so a pick that fails or stalls past the attempt timeout never leaves the caller in silence; the page is told when
that happens. Groq entries are offered once GROQ_API_KEY is set (backend/.env, then restart the backend).

No LiveKit imports here: the web backend reads this list too (server.py, GET /api/llms)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ..config import settings

PROVIDERS = {"litellm": "LiteLLM", "groq": "Groq"}
KEY_NAMES = {"litellm": "LITELLM_API_KEY", "groq": "GROQ_API_KEY"}


@dataclass(frozen=True)
class CatalogLLM:
    id: str                          # what the page sends
    provider: str                    # litellm (Emergent's proxy) | groq (Groq's LPUs)
    model: str                       # the provider's model id
    label: str                       # what the page shows
    note: str                        # one line: what it's good or bad at
    reasoning_effort: str | None = None          # a model that thinks by default: the setting that turns it off
    extra_body: tuple[tuple[str, Any], ...] = ()  # other request fields the provider needs


HIDE_REASONING = (("include_reasoning", False),)   # Groq: think, but don't send the thinking back

CATALOG: tuple[CatalogLLM, ...] = (
    CatalogLLM("litellm-gpt-4o", "litellm", "gpt-4o", "GPT-4o", "as quick as Haiku to start, slow tail"),
    CatalogLLM("litellm-gpt-5.6-terra", "litellm", "gpt-5.6-terra", "GPT-5.6 Terra", "no reasoning, reliable tools",
               reasoning_effort="none"),
    CatalogLLM("litellm-gpt-5.2", "litellm", "gpt-5.2", "GPT-5.2", "no reasoning, silent before a tool",
               reasoning_effort="none"),
    CatalogLLM("litellm-gpt-5.6-luna", "litellm", "gpt-5.6-luna", "GPT-5.6 Luna", "cheapest, skips the calendar",
               reasoning_effort="none"),
    CatalogLLM("litellm-claude-sonnet-5-5", "litellm", "claude-sonnet-5-5", "Claude Sonnet 5.5",
               "quality reference, slowest"),
    CatalogLLM("groq-gpt-oss-20b", "groq", "openai/gpt-oss-20b", "GPT-OSS 20B", "~1000 tok/s, thinks briefly",
               reasoning_effort="low", extra_body=HIDE_REASONING),
    CatalogLLM("groq-gpt-oss-120b", "groq", "openai/gpt-oss-120b", "GPT-OSS 120B", "~500 tok/s, smarter, thinks briefly",
               reasoning_effort="low", extra_body=HIDE_REASONING),
    CatalogLLM("groq-qwen3.8-27b", "groq", "qwen/qwen3.8-27b", "Qwen3.8 27B", "no thinking, ~450 tok/s, preview",
               reasoning_effort="none"),
)
BY_ID: dict[str, CatalogLLM] = {m.id: m for m in CATALOG}


def api_key(provider: str) -> str | None:
    s = settings()
    return {"litellm": s.litellm_api_key, "groq": s.groq_api_key}.get(provider)


def available(choice: CatalogLLM) -> bool:
    return bool(api_key(choice.provider))


def default_model() -> str:
    """The configured model: the litellm route's (voice/config.py)."""
    return os.environ.get("LITELLM_MODEL") or "claude-haiku-4-5"


def default_label() -> str:
    return {"claude-haiku-4-5": "Claude Haiku 4.5"}.get(default_model(), default_model())


def public() -> list[dict]:
    """What the page needs to show the choice: no keys, no request settings."""
    return [{"id": m.id, "provider": m.provider, "provider_label": PROVIDERS[m.provider], "label": m.label,
             "note": m.note, "model": m.model, "available": available(m),
             "needs": None if available(m) else KEY_NAMES[m.provider]} for m in CATALOG]
