"""What the Talk page shows live while a browser call runs (20 Oct: "I want to see the time each step takes, live"):
each turn's timings from LiveKit's own turn metrics, and the call's Langfuse trace (a public link for test calls).
Sent on the page's data topic (sdr.events) next to "what Giulia did"; tool durations come from the agent itself
(sdr_agent.py). Phone calls have no page, so nothing here runs for them.

Per turn, counted from the moment the person stopped talking:
- user: stt_s (their words written down), eot_s (the turn judged over: Giulia may answer);
- agent: ttft_s (the LLM's first word, from when it started), ttfs_s (its first sentence handed to the voice),
  ttfb_s (the voice's first audio after that), e2e_s (Giulia audible: what the caller waited)."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from livekit.agents import AgentSession

log = logging.getLogger("ai_sdr.voice")

Publish = Callable[[str, dict], Awaitable[None]]


def _s(metrics: dict, key: str) -> float | None:
    value = metrics.get(key)
    return round(float(value), 3) if isinstance(value, (int, float)) else None


def _model(metrics: dict, key: str) -> str | None:
    meta = metrics.get(key) or {}
    return (meta.get("model_name") if isinstance(meta, dict) else getattr(meta, "model_name", None)) or None


def turn_payload(role: str, metrics: dict, *, interrupted: bool = False) -> dict | None:
    """The timing event for one finished turn, or None when the turn carries no timings (the opener, a line the
    code said)."""
    if role == "user" and metrics.get("end_of_turn_delay") is not None:
        return {"role": "user", "stt_s": _s(metrics, "transcription_delay"), "eot_s": _s(metrics, "end_of_turn_delay"),
                "stt_model": _model(metrics, "stt_metadata")}
    if role == "assistant" and metrics.get("e2e_latency") is not None:
        return {"role": "agent", "e2e_s": _s(metrics, "e2e_latency"), "ttft_s": _s(metrics, "llm_node_ttft"),
                "ttfs_s": _s(metrics, "llm_node_ttfs"), "ttfb_s": _s(metrics, "tts_node_ttfb"),
                "tps": _s(metrics, "llm_node_tps"), "interrupted": interrupted,
                "llm_model": _model(metrics, "llm_metadata"), "tts_model": _model(metrics, "tts_metadata")}
    return None


def stream_timings(session: AgentSession, publish: Publish) -> None:
    """Send each turn's timings to the page as the turn is added to the conversation."""
    def on_item(ev) -> None:
        item = ev.item
        payload = turn_payload(getattr(item, "role", ""), getattr(item, "metrics", None) or {},
                               interrupted=bool(getattr(item, "interrupted", False)))
        if payload is not None:
            asyncio.get_event_loop().create_task(_send(publish, "timing", payload))

    session.on("conversation_item_added", on_item)


async def _send(publish: Publish, type_: str, payload: dict) -> None:
    try:
        await publish(type_, payload)
    except Exception:  # noqa: BLE001 - the page missing a timing never matters to the call
        log.debug("live event not sent", exc_info=True)


def send_soon(publish: Publish | None, type_: str, payload: dict) -> None:
    """Fire-and-forget from code that must not wait (a tool, an event handler)."""
    if publish is not None:
        asyncio.get_event_loop().create_task(_send(publish, type_, payload))
