"""21 Oct: LiveKit's end-of-turn decisions kept in the call timeline (voice/telemetry.py EotLogger). LiveKit's logger has
extra methods (trace()); swapping in a plain logger broke speech-to-text on a test call, so it must be wrapped."""
from livekit.agents.voice import audio_recognition

from ai_sdr.voice.telemetry import EotLogger, capture_eot


class _T:
    def __init__(self):
        self.events = []

    def event(self, kind, **data):
        self.events.append((kind, data))


def test_decision_is_kept_and_everything_else_passes_through():
    original = audio_recognition.logger
    try:
        t = _T()
        capture_eot(t)
        capture_eot(t)   # a second call wraps the original, not the wrapper
        lg = audio_recognition.logger
        assert isinstance(lg, EotLogger) and not isinstance(lg._inner, EotLogger)
        lg.trace("holding STT event during agent speech", extra={"event": "final_transcript"})
        lg.debug("eot prediction", extra={"probability": 0.12, "unlikely_threshold": 0.386, "endpointing_delay": 1.2,
                                          "language": "en", "trigger": "vad"})
        lg.debug("something else")
        assert t.events == [("eot", {"probability": 0.12, "threshold": 0.386, "delay": 1.2, "language": "en",
                                     "trigger": "vad"})]
    finally:
        audio_recognition.logger = original
