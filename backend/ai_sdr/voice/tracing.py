"""Call traces in Langfuse (20 Oct: "we need observability and tracing"). LiveKit already traces every call with
OpenTelemetry: the session, each user turn with its end-of-turn decision, each agent turn with the LLM request
(prompt, reply, tokens, time to first token), the voice (time to first audio) and every tool call. This sends those
spans to Langfuse's OTLP endpoint and labels them so that one call is one Langfuse session (the room name), tagged
with its channel, language and code version. The call's grade and timings are added after it ends (evals/watch.py).

Off unless LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set: then nothing is installed and nothing leaves the
process. TRACE_CONTENT says what a trace may carry: masked (default: the conversation, with emails and phone
numbers replaced), full, or off (LiveKit drops every content attribute; timings, models and token counts stay).

Langfuse's free plan counts every span as a unit (50k a month). LiveKit emits many spans per turn, most of them
plumbing (audio publishing, activity start/stop, retries, the wrappers around each LLM request: with early replies
on, a turn often makes two or three requests). TRACE_SPANS=turns (default) sends only the spans a person reads a
call with, and hangs each one under its nearest sent ancestor (an LLM request under its agent turn): a local 5-turn
call went from 56 spans to about 30. TRACE_SPANS=all sends everything."""
from __future__ import annotations

import base64
import logging
import re
from collections.abc import Sequence
from contextvars import ContextVar
from typing import Any

from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import format_trace_id

from ..config import Settings, settings

log = logging.getLogger("ai_sdr.voice")

CONTENT_MODES = ("masked", "full", "off")
SPAN_MODES = ("turns", "all")
# TRACE_SPANS=turns: the call, each turn, the LLM request (prompt, reply, tokens), the voice and the tools
READABLE_SPANS = frozenset({"agent_session", "user_turn", "agent_turn", "llm_request", "tts_node", "function_tool"})
MAX_DROPPED = 50_000   # the left-out spans remembered for re-attaching their children (one call needs a few hundred)
EXPORT_TIMEOUT_S = 10
FLUSH_TIMEOUT_MS = 5000   # at the end of a call: what is still queued gets this long to leave

_provider: TracerProvider | None = None
# the labels of the call this code runs for: a context variable, so simulated calls running side by side in one
# process keep theirs apart; _last["labels"] covers spans started outside the call's context (one call per job process)
_call: ContextVar[dict | None] = ContextVar("traced_call", default=None)
_last: dict[str, dict | None] = {"labels": None}
_calls: dict[str, dict] = {}   # room -> labels (and the call's trace id, once its first span starts)
_dropped: dict[int, Any] = {}  # span id -> its parent, for spans TRACE_SPANS leaves out

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# not inside a longer number or a decimal (1792494093.3), but a full stop after the number is fine
_EDGE_L, _EDGE_R = r"(?<!\d)(?<!\d\.)", r"(?!\d|\.\d)"
PHONE = re.compile(
    r"\+\d{1,3}(?:[ .-]?\d){6,12}" + _EDGE_R +                    # international: +39 333 123 4567
    r"|" + _EDGE_L + r"3\d{2}(?:[ .-]?\d){6,7}" + _EDGE_R +        # Italian mobile without the prefix
    r"|" + _EDGE_L + r"0\d{1,3}(?:[ .-]?\d){5,8}" + _EDGE_R)       # Italian landline
WHOLE_VALUE = ("phone", "participant_identity")   # attributes that ARE a phone number or identity: replaced whole


def _mask_text(text: str) -> str:
    return PHONE.sub("<phone>", EMAIL.sub("<email>", text))


def _mask_value(key: str, value: Any) -> Any:
    if any(k in key.lower() for k in WHOLE_VALUE):
        return "<redacted>"
    if isinstance(value, str):
        return _mask_text(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_mask_text(v) if isinstance(v, str) else v for v in value)
    return value


def _sent_parent(span: ReadableSpan):
    """The nearest ancestor that is sent: a left-out span's children hang under its own parent instead."""
    parent, hops = span.parent, 0
    while parent is not None and parent.span_id in _dropped and hops < 64:
        parent, hops = _dropped[parent.span_id], hops + 1
    return parent


def _rebuilt(span: ReadableSpan, *, mask: bool, reparent: bool) -> ReadableSpan:
    from opentelemetry.sdk.trace import Event

    parent = _sent_parent(span) if reparent else span.parent
    if not mask and parent is span.parent:
        return span
    attributes, events = span.attributes, span.events
    if mask:
        attributes = {k: _mask_value(k, v) for k, v in (span.attributes or {}).items()}
        events = tuple(Event(e.name, {k: _mask_value(k, v) for k, v in (e.attributes or {}).items()}, e.timestamp)
                       for e in span.events)
    return ReadableSpan(
        name=span.name, context=span.context, parent=parent, resource=span.resource, attributes=attributes,
        events=events, links=span.links, kind=span.kind, status=span.status, start_time=span.start_time,
        end_time=span.end_time, instrumentation_scope=span.instrumentation_scope)


class LangfuseExporter(SpanExporter):
    """Only the spans worth reading (TRACE_SPANS) and, with TRACE_CONTENT=masked, no email or phone number in them,
    whichever attribute holds it."""

    def __init__(self, inner: SpanExporter, *, mask: bool, keep: frozenset[str] | None):
        self.inner, self.mask, self.keep = inner, mask, keep

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        chosen = [s for s in spans if self.keep is None or s.name in self.keep]
        if not chosen:
            return SpanExportResult.SUCCESS
        return self.inner.export([_rebuilt(s, mask=self.mask, reparent=self.keep is not None) for s in chosen])

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self.inner.shutdown()


class CallLabels(SpanProcessor):
    """Puts the call's Langfuse labels on every span as it starts, notes the call's trace id, and remembers the
    parent of every span that won't be sent (keep), so its children can hang under that parent."""

    def __init__(self, keep: frozenset[str] | None = None):
        self.keep = keep

    def on_start(self, span, parent_context=None) -> None:
        if self.keep is not None and span.name not in self.keep:
            if len(_dropped) > MAX_DROPPED:
                _dropped.clear()
            _dropped[span.context.span_id] = span.parent
        labels = _call.get() or _last["labels"]
        if not labels:
            return
        for key, value in labels["attributes"].items():
            span.set_attribute(key, value)
        if labels.get("trace_id") is None or span.name == "agent_session":   # the call's own span wins
            labels["trace_id"] = format_trace_id(span.context.trace_id)

    def on_end(self, span) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def exporter_for(s: Settings) -> SpanExporter:
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    auth = base64.b64encode(f"{s.langfuse_public_key}:{s.langfuse_secret_key}".encode()).decode()
    # the ingestion-version header makes spans show up at once (without it Langfuse may take up to 10 minutes)
    return OTLPSpanExporter(endpoint=f"{s.langfuse_host}/api/public/otel/v1/traces", timeout=EXPORT_TIMEOUT_S,
                            headers={"Authorization": f"Basic {auth}", "x-langfuse-ingestion-version": "4"})


def setup(*, service: str, version: str, s: Settings | None = None,
          exporter: SpanExporter | None = None) -> bool:
    """Install the tracer for this process (once). Returns whether tracing is on. exporter: for tests."""
    global _provider
    if _provider is not None:
        return True
    s = s or settings()
    if s.trace_content not in CONTENT_MODES:
        raise ValueError(f"TRACE_CONTENT must be one of {', '.join(CONTENT_MODES)}, not {s.trace_content!r}")
    if s.trace_spans not in SPAN_MODES:
        raise ValueError(f"TRACE_SPANS must be one of {', '.join(SPAN_MODES)}, not {s.trace_spans!r}")
    if exporter is None and not s.langfuse_enabled:
        return False
    from livekit.agents.telemetry import set_tracer_provider

    keep = READABLE_SPANS if s.trace_spans == "turns" else None
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service, "service.version": version}))
    provider.add_span_processor(CallLabels(keep))
    out = LangfuseExporter(exporter or exporter_for(s), mask=s.trace_content == "masked", keep=keep)
    provider.add_span_processor(BatchSpanProcessor(out, schedule_delay_millis=2000))
    # allow_pii=False makes LiveKit drop the conversation from every span before any exporter sees it
    set_tracer_provider(provider, allow_pii=s.trace_content != "off")
    _provider = provider
    log.info("tracing to %s (content: %s, spans: %s)", s.langfuse_host if exporter is None else "a test exporter",
             s.trace_content, s.trace_spans)
    return True


def enabled() -> bool:
    return _provider is not None


def call_started(room: str, *, channel: str, language: str, version: str, environment: str = "",
                 user: str | None = None, tags: list[str] | None = None, **metadata: Any) -> None:
    """Label everything this call traces from here on (call before session.start)."""
    if _provider is None:
        return
    attributes: dict[str, Any] = {
        "langfuse.session.id": room,
        "langfuse.trace.name": f"call:{channel}",
        "langfuse.trace.tags": [t for t in [channel, language, *(tags or [])] if t],
        "langfuse.release": version,
        "langfuse.trace.metadata.channel": channel,
        "langfuse.trace.metadata.language": language,
    }
    if environment:
        attributes["langfuse.environment"] = environment
    if user:
        attributes["langfuse.user.id"] = user
    for key, value in metadata.items():
        if value is not None:
            attributes[f"langfuse.trace.metadata.{key}"] = value if isinstance(value, (str, int, float, bool)) \
                else str(value)
    labels = {"room": room, "attributes": attributes, "trace_id": None}
    _calls[room] = labels
    _call.set(labels)
    _last["labels"] = labels


def trace_id(room: str) -> str | None:
    """The Langfuse trace id of the call (its agent_session span), once the call has started tracing."""
    labels = _calls.get(room)
    return (labels or {}).get("trace_id")


def call_ended(room: str) -> str | None:
    """Forget the call's labels; returns its trace id."""
    tid = trace_id(room)
    labels = _calls.pop(room, None)
    if labels is not None and _last["labels"] is labels:
        _last["labels"] = None
    return tid


def flush() -> None:
    """Send what is queued (end of a call, end of a simulation suite). Never raises."""
    if _provider is None:
        return
    try:
        _provider.force_flush(FLUSH_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 - tracing must never break a call
        log.warning("trace flush failed", exc_info=True)
