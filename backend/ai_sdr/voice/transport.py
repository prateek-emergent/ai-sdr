"""How the worker's media actually travels to LiveKit, sampled during the call (plan round 2, phase C: the
"is Emergent's network the problem?" question gets numbers instead of a guess).

- route: the selected ICE candidate pair. host/srflx over UDP is the normal direct path; relay (TURN) or TCP
  means UDP is blocked or NATed badly, which adds latency and jitter.
- rtt, jitter, loss and concealed audio for the caller's mic as received here, and loss for Giulia's audio as the
  LiveKit server reports it.
Only the worker-to-LiveKit leg: the browser-to-LiveKit leg is measured in the browser, if at all."""
from __future__ import annotations

import asyncio
from typing import Any

from livekit import rtc
from livekit.rtc import stats as S


def _type_name(candidate: Any) -> str:
    # an unset field reads as 0 = HOST: only trust it when the candidate actually carries the field
    if candidate is None or not candidate.HasField("candidate_type"):
        return "unknown"
    return S.IceCandidateType.Name(candidate.candidate_type).lower()


def _side(reports) -> dict:
    groups: dict[str, list] = {}
    for r in reports:
        kind = r.WhichOneof("stats")
        if kind:
            groups.setdefault(kind, []).append(getattr(r, kind))
    local = {w.rtc.id: w.candidate for w in groups.get("local_candidate", [])}
    remote = {w.rtc.id: w.candidate for w in groups.get("remote_candidate", [])}
    pairs = {w.rtc.id: w.candidate_pair for w in groups.get("candidate_pair", [])}
    selected = next((t.transport.selected_candidate_pair_id for t in groups.get("transport", [])
                     if t.transport.selected_candidate_pair_id), None)
    pair = pairs.get(selected) or next((p for p in pairs.values()
                                        if p.nominated and p.state == S.PAIR_SUCCEEDED), None)
    out: dict[str, Any] = {}
    if pair is not None:
        out["rtt_ms"] = round(pair.current_round_trip_time * 1000, 1)
        lc, rc = local.get(pair.local_candidate_id), remote.get(pair.remote_candidate_id)
        out["local"], out["remote"] = _type_name(lc), _type_name(rc)
        if lc is not None:
            out["protocol"] = lc.protocol
            if lc.HasField("candidate_type") and lc.candidate_type == S.RELAY:
                out["relay_protocol"] = S.IceServerTransportProtocol.Name(lc.relay_protocol).lower()
    for w in groups.get("inbound_rtp", []):        # the caller's mic, received by the worker
        if w.stream.kind == "audio":
            total = max(1, w.inbound.total_samples_received)
            out.update(in_jitter_ms=round(w.received.jitter * 1000, 1), in_packets=w.received.packets_received,
                       in_lost=w.received.packets_lost,
                       in_concealed_pct=round(100 * w.inbound.concealed_samples / total, 2))
    for w in groups.get("remote_inbound_rtp", []):  # Giulia's audio, as LiveKit's server received it
        if w.stream.kind == "audio":
            out.update(out_rtt_ms=round(w.remote_inbound.round_trip_time * 1000, 1),
                       out_fraction_lost=round(w.remote_inbound.fraction_lost, 4))
    return out


async def snapshot(room: rtc.Room) -> dict | None:
    """One sample of both directions; None if the room is not connected (never call after disconnect)."""
    if not room.isconnected():
        return None
    st = await asyncio.wait_for(room.get_rtc_stats(), 3)
    return {"publisher": _side(st.publisher_stats), "subscriber": _side(st.subscriber_stats)}


async def sample_during_call(room: rtc.Room, record, first_after_s: float = 20.0, every_s: float = 30.0) -> None:
    """Runs inside the call's CallScope (cancelled when the call ends): a sample ~20 s in, then every 30 s."""
    await asyncio.sleep(first_after_s)
    while True:
        try:
            snap = await snapshot(room)
            if snap is not None:
                record(snap)
        except (asyncio.TimeoutError, RuntimeError):
            pass  # a missed sample is not worth failing anything for
        await asyncio.sleep(every_s)
