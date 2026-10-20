"""20 Oct: call traces for Langfuse (voice/tracing.py). No Langfuse account needed: spans go to an in-memory
exporter, and the wire format is checked against a local HTTP server standing in for Langfuse."""
import base64
import dataclasses
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from ai_sdr.config import settings
from ai_sdr.voice import tracing


def test_masking_keeps_dates_times_and_ids():
    text = ("Mi scriva a mario.rossi@studio.it o al +39 333 123 4567, oppure 333 1234567 o 02 1234 5678. "
            "Giovedì 2026-10-22 alle 10:30, room demo-31e3d4b4, created_at 1792494093.3, 5 crediti.")
    out = tracing._mask_text(text)
    assert "mario.rossi" not in out and out.count("<email>") == 1
    assert out.count("<phone>") == 3
    for kept in ("2026-10-22", "10:30", "demo-31e3d4b4", "1792494093.3", "5 crediti"):
        assert kept in out, kept
    assert tracing._mask_value("lk.pii.sip.phoneNumber", "+393331234567") == "<redacted>"
    assert tracing._mask_value("lk.pii.participant_identity", "sip_+39333") == "<redacted>"


def _provider(monkeypatch, *, mask=True, keep=tracing.READABLE_SPANS):
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(tracing.CallLabels(keep))
    provider.add_span_processor(SimpleSpanProcessor(tracing.LangfuseExporter(memory, mask=mask, keep=keep)))
    monkeypatch.setattr(tracing, "_provider", provider)   # call_started only labels when tracing is on
    return provider, memory


def test_spans_are_labelled_filtered_and_masked(monkeypatch):
    provider, memory = _provider(monkeypatch)
    tracer = provider.get_tracer("test")
    tracing.call_started("demo-abc", channel="web", language="it", version="7a2475a", environment="ai-sdr-local",
                         tags=["voice:it-deepgram-maia"], voice="it-deepgram-maia")
    with tracer.start_as_current_span("agent_session"):
        with tracer.start_as_current_span("agent_turn"):
            with tracer.start_as_current_span("llm_node"), tracer.start_as_current_span("llm_fallback_adapter"):
                with tracer.start_as_current_span("llm_request") as llm:
                    llm.set_attribute("gen_ai.output.messages", "Le scrivo a mario@example.com")
            with tracer.start_as_current_span("publish_audio_output"):
                pass
    spans = {s.name: s for s in memory.get_finished_spans()}
    assert set(spans) == {"agent_session", "agent_turn", "llm_request"}   # wrappers and plumbing left out
    assert spans["llm_request"].parent.span_id == spans["agent_turn"].context.span_id   # hung under its turn
    attrs = spans["llm_request"].attributes
    assert attrs["langfuse.session.id"] == "demo-abc" and attrs["langfuse.environment"] == "ai-sdr-local"
    assert tuple(attrs["langfuse.trace.tags"]) == ("web", "it", "voice:it-deepgram-maia")
    assert attrs["langfuse.trace.metadata.voice"] == "it-deepgram-maia"
    assert attrs["gen_ai.output.messages"] == "Le scrivo a <email>"
    root = spans["agent_session"]
    assert tracing.trace_id("demo-abc") == format(root.context.trace_id, "032x")
    assert tracing.call_ended("demo-abc") == format(root.context.trace_id, "032x")


def test_full_content_and_all_spans(monkeypatch):
    provider, memory = _provider(monkeypatch, mask=False, keep=None)
    tracing.call_started("demo-xyz", channel="phone", language="en", version="v")
    with provider.get_tracer("test").start_as_current_span("publish_audio_output") as s:
        s.set_attribute("lk.pii.user_input", "call me on +44 7700 900123")
    (span,) = memory.get_finished_spans()
    assert span.attributes["lk.pii.user_input"] == "call me on +44 7700 900123"
    tracing.call_ended("demo-xyz")


def test_off_without_keys():
    s = dataclasses.replace(settings(), langfuse_public_key=None, langfuse_secret_key=None)
    assert tracing.setup(service="test", version="v", s=s) is False


def test_wire_format_matches_langfuse():
    """Path, auth and the ingestion-version header, as Langfuse's OTLP endpoint expects them."""
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"] = self.path
            seen["headers"] = self.headers   # case-insensitive lookups
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()
    s = dataclasses.replace(settings(), langfuse_public_key="pk-lf-test", langfuse_secret_key="sk-lf-test",
                            langfuse_host=f"http://127.0.0.1:{server.server_port}")
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(tracing.exporter_for(s)))
    with provider.get_tracer("test").start_as_current_span("agent_session"):
        pass
    server.server_close()
    assert seen["path"] == "/api/public/otel/v1/traces"
    assert seen["headers"]["Authorization"] == "Basic " + base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
    assert seen["headers"]["x-langfuse-ingestion-version"] == "4"
    assert seen["headers"]["Content-Type"] == "application/x-protobuf"


def test_host_from_either_name(monkeypatch):
    from ai_sdr.config import Settings
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com/")   # the name Langfuse's setup page uses
    assert Settings().langfuse_host == "https://us.cloud.langfuse.com"
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example.org")
    assert Settings().langfuse_host == "https://langfuse.example.org"
