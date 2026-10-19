"""LiveKit agent worker: places outbound calls (dispatched by the dialer), answers inbound callbacks, and serves the
browser demo. Every call gets the same pipeline (voice/factory.py), the same lifecycle (voice/lifecycle.py) and a
call report (voice/telemetry.py).

Run:  uv run ai-sdr agent start      (everywhere: laptop, preview, prod; behaviour comes from VoiceConfig, not the
                                      run mode. `dev` still works for local debugging.)
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from google.protobuf.duration_pb2 import Duration
from livekit import api, rtc
from livekit.agents import AgentServer, JobContext, JobProcess, NOT_GIVEN, cli
from livekit.agents.voice import room_io
from livekit.plugins import silero
from psycopg.rows import dict_row

from .. import db
from ..config import settings
from ..integrations.calendar import FakeCalendar, get_calendar
from ..integrations.hubspot import HubSpot
from ..voice import config as voice_config
from ..voice.factory import build_session
from ..voice.providers import elevenlabs_credits_left, tts_chain_for
from ..voice.lifecycle import CallController
from ..voice.line_watch import LineWatch
from ..voice.telemetry import CallTelemetry, save_report
from ..voice.transport import sample_during_call
from .actions import CallActions, CallState
from .prompts import build_instructions, inbound_greeting, opener
from .sdr_agent import SDRAgent

log = logging.getLogger("ai_sdr.agent")

# SIP status -> our outcome (anything else counts as 'failed')
SIP_OUTCOME = {"486": "busy", "600": "busy", "480": "no_answer", "408": "no_answer", "487": "no_answer",
               "404": "bad_number", "484": "bad_number", "410": "bad_number", "603": "declined"}

CFG = voice_config.load()   # validated at import: a misconfigured worker fails at boot, not on the first call

# the live call in this job process (one job per process), for the end-of-session report
_CALL: dict[str, Any] = {}
_STARTUP: dict[str, float] = {}   # seconds spent in each step before the session starts


class NullRecorder:
    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class Recorder:
    """Audio-only LiveKit egress to an S3-compatible bucket (R2/GCS-interop/S3). No-op unless enabled."""

    def __init__(self, ctx: JobContext, conn, call_id: int):
        self.ctx, self.conn, self.call_id, self.egress_id = ctx, conn, call_id, None

    async def start(self) -> None:
        s = settings()
        if not (s.recording_enabled and s.s3_bucket):
            return
        path = f"calls/{self.ctx.room.name}.mp3"
        info = await self.ctx.api.egress.start_room_composite_egress(api.RoomCompositeEgressRequest(
            room_name=self.ctx.room.name, audio_only=True,
            file_outputs=[api.EncodedFileOutput(
                file_type=api.EncodedFileType.MP3, filepath=path,
                s3=api.S3Upload(access_key=s.s3_access_key, secret=s.s3_secret, region=s.s3_region,
                                endpoint=s.s3_endpoint or "", bucket=s.s3_bucket, force_path_style=True))]))
        self.egress_id = info.egress_id
        await db.update_call(self.conn, self.call_id, egress_id=info.egress_id,
                             recording_uri=f"s3://{s.s3_bucket}/{path}")

    async def stop(self) -> None:
        if self.egress_id:
            try:
                await self.ctx.api.egress.stop_egress(api.StopEgressRequest(egress_id=self.egress_id))
            except Exception:
                log.exception("stop egress failed")
            self.egress_id = None


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()
    if "elevenlabs" in CFG.tts_chain and CFG.elevenlabs_api_key:
        proc.userdata["elevenlabs_left"] = elevenlabs_credits_left(CFG.elevenlabs_api_key)
    # imports that otherwise happen on the first call and block its event loop (pod logs, 16 Oct: 150-350 ms)
    import openai.lib.streaming.chat  # noqa: F401
    import openai.pagination  # noqa: F401  (preview, 17 Oct: imported on the first reply, blocked the loop 121 ms)
    for tz in ("Europe/Rome", "Asia/Kolkata", "UTC"):
        ZoneInfo(tz)


def _load(server: AgentServer) -> float:
    """Load = calls in progress / MAX_SESSIONS. The default (CPU of the whole container, where the web backend and
    the page's dev server also run) made the worker report itself full and stop taking calls (root cause 2)."""
    return min(1.0, len(server.active_jobs) / CFG.max_sessions)


server = AgentServer(setup_fnc=prewarm, load_fnc=_load, load_threshold=1.0,
                     # imported once in the forkserver and shared/frozen, instead of on a call's event loop
                     preload_modules=["openai", "openai.lib.streaming.chat", "openai.pagination"],
                     num_idle_processes=CFG.idle_processes, port=CFG.health_port,
                     drain_timeout=CFG.drain_timeout, initialize_process_timeout=CFG.initialize_process_timeout,
                     job_memory_warn_mb=CFG.memory_warn_mb)


def _start_call(ctx: JobContext, channel: str, call_id: Any = None, tts_request: list[str] | None = None):
    """Session + controller + telemetry for one call, wired the same way for every channel."""
    room = ctx.job.room.name   # known before the room connection (web calls start the session first)
    ctx.log_context_fields = {"room": room, "job_id": ctx.job.id, "channel": channel,
                              "agent_name": CFG.agent_name, "version": CFG.version}
    t = time.monotonic()
    el_left = ctx.proc.userdata.get("elevenlabs_left")
    chain = tts_chain_for(CFG, tts_request, el_left)
    built = build_session(CFG, ctx.proc.userdata["vad"], chain, channel=channel)
    _STARTUP["build_session_s"] = round(time.monotonic() - t, 3)
    telemetry = CallTelemetry(CFG, room=room, job_id=ctx.job.id, channel=channel, call_id=call_id)
    telemetry.turn_detector = built.turn_detector
    telemetry.attach(built.session)
    # where the time before the first word went (17 Oct: 2 s on preview vs 0.5 s on the laptop)
    telemetry.event("startup", **_STARTUP)
    telemetry.event("voice", chain=list(chain), override=bool(tts_request), elevenlabs_credits_left=el_left)
    if hasattr(built.session.tts, "on"):  # a fallback chain: record every switch (shows on the metrics page)
        built.session.tts.on("tts_availability_changed", lambda ev: telemetry.event(
            "voice_switch", voice=type(ev.tts).__module__.split(".")[-2], available=ev.available))
    controller = CallController(built.session, telemetry, CFG.language)
    controller.attach()
    _CALL.update(session=built.session, telemetry=telemetry, controller=controller, extra=dict)
    log.info("call starting: %s", json.dumps(CFG.describe()))
    controller.scope.spawn(sample_during_call(ctx.room, telemetry.transport_sample), "transport-stats")
    return built.session, controller, telemetry


async def on_session_end(ctx: JobContext) -> None:
    """Runs after the session has closed: build the call report and save it (never lets an error escape)."""
    call = _CALL.get("telemetry")
    if call is None:
        return
    try:
        report = call.build(ctx, _CALL["session"], _CALL["extra"]())
        call.detach_logs()
        call.log_summary(report)
        where = await save_report(CFG, report)
        log.info("call report saved: %s", where)
    except Exception:
        log.exception("could not save the call report")


@server.rtc_session(agent_name=CFG.agent_name, on_session_end=on_session_end)
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or "{}")
    if meta.get("direction") == "web":  # dispatched by /api/session: everything the call needs is in the metadata
        await web_demo(ctx, meta)
        return
    outbound = meta.get("direction") == "outbound"
    t = time.monotonic()
    await ctx.connect()
    _STARTUP["connect_s"] = round(time.monotonic() - t, 3)
    if not outbound:
        t = time.monotonic()
        participant = await ctx.wait_for_participant()
        _STARTUP["wait_participant_s"] = round(time.monotonic() - t, 3)
        if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_SIP:  # an old demo link without metadata
            await web_demo(ctx, {**meta, **json.loads(participant.metadata or "{}")}, connected=True)
            return
    await phone_call(ctx, meta, outbound, None if outbound else participant)


async def web_demo(ctx: JobContext, meta: dict, connected: bool = False) -> None:
    """Someone opened the browser demo: the agent behaves exactly as on an outbound call (it speaks first with the
    opener, same prompt, same tools and rules) but nothing touches the database, HubSpot or the calendar.

    The session starts BEFORE the room connection (LiveKit's own order): the name and time zone come with the job, so
    nothing waits for the browser to appear. 17 Oct, preview: connect 0.5 s + waiting for the participant 0.4-1.1 s
    ran one after the other before the opener could start."""
    first = (meta.get("first_name") or "").strip() or None
    tz = meta.get("tz") or "Europe/Rome"
    prospect = {"first_name": first, "tz": tz, "email": meta.get("email") or None,
                "context": meta.get("context") or {}}
    state = CallState(call_id=0, prospect=prospect, phone=None, tz=tz)
    actions = CallActions(None, state, FakeCalendar(), None)

    async def publish(type_: str, payload: dict) -> None:  # the "Talk to Giulia" page shows these live
        await ctx.room.local_participant.publish_data(
            json.dumps({"type": type_, **payload}, default=str), reliable=True, topic="sdr.events")

    actions.notify = publish
    session, controller, telemetry = _start_call(ctx, "web", tts_request=meta.get("tts_chain"))
    _CALL["extra"] = lambda: _outcome(state)
    agent = SDRAgent(actions, build_instructions(prospect), NullRecorder(), controller)
    t = time.monotonic()
    # links to the first person who joins; agent audio waits for them to be subscribed
    await session.start(agent=agent, room=ctx.room, record=False,
                        room_options=room_io.RoomOptions(delete_room_on_close=True))
    telemetry.event("session_started", took_s=round(time.monotonic() - t, 3))
    if not connected:
        t = time.monotonic()
        await ctx.connect()
        telemetry.event("connected", took_s=round(time.monotonic() - t, 3))
    LineWatch(controller, actions).attach()
    controller.greet(opener(prospect))
    _arm_duration_cap(controller, settings().demo_max_call_seconds)


def _outcome(state: CallState, **more: Any) -> dict:
    """What the call achieved, read when the report is built (after the session closed), so it is final."""
    return {"disposition": state.disposition, "qualification": state.qualification,
            "qual_reasons": state.qual_reasons, "meeting": state.booked_start, "callback": state.callback_at,
            "manual_schedule": state.manual_schedule, "voicemail": state.voicemail, **more}


def _arm_duration_cap(controller: CallController, limit_s: int) -> None:
    """Hard cap on call length (0 = none). A minute before, the agent is asked to wrap up; at the cap the call ends
    through the controller, which lets the current sentence finish."""
    if limit_s <= 0:
        return
    s = settings()

    def wrap_up():
        if not controller.closing:
            controller.session.generate_reply(instructions=(
                "Time is almost up: in one sentence, sum up the next step, thank them, say goodbye, then call end_call."
                if s.agent_language == "en" else
                "Il tempo sta finendo: in una frase riassumi il prossimo passo, ringrazia, saluta e chiama end_call."))

    controller.scope.timer(max(60, limit_s - 60), wrap_up, "duration-wrap-up")
    controller.scope.timer(limit_s, lambda: controller.end("max_duration"), "duration-cap")


async def phone_call(ctx: JobContext, meta: dict, outbound: bool, participant: rtc.RemoteParticipant | None) -> None:
    """Outbound (dialer) and inbound SIP calls. Same core as the web demo; verified end to end once the SIP trunk
    exists (plan: phone phase)."""
    s = settings()
    conn = await psycopg.AsyncConnection.connect(s.database_url, row_factory=dict_row, autocommit=True,
                                                 connect_timeout=5)
    job_id = meta.get("job_id")
    if outbound:
        call_id, phone = meta["call_id"], meta["phone"]
        prospect = await db.get_prospect(conn, meta["prospect_id"])
    else:
        phone = participant.attributes.get("sip.phoneNumber")
        prospect = await db.find_prospect_by_phone(conn, phone) if phone else None
        call_id = await db.create_call(conn, job_id=None, prospect_id=prospect["id"] if prospect else None,
                                       direction="inbound", room_name=ctx.room.name, phone=phone)

    state = CallState(call_id=call_id, prospect=prospect, phone=phone,
                      tz=(prospect or {}).get("tz") or "Europe/Rome")
    actions = CallActions(conn, state, get_calendar(), HubSpot())
    recorder = Recorder(ctx, conn, call_id)
    session, controller, telemetry = _start_call(ctx, "phone", call_id)
    _CALL["extra"] = lambda: _outcome(state, outcome=status["outcome"])
    agent = SDRAgent(actions, build_instructions(prospect, inbound=not outbound), recorder, controller)
    status: dict[str, Any] = {"outcome": "dialing" if outbound else "in_progress", "answered": not outbound}

    async def finalize() -> None:
        await recorder.stop()
        if state.voicemail:
            status["outcome"] = "voicemail"
        elif status["answered"]:
            status["outcome"] = "completed"
        disposition = state.disposition or ("hung_up" if status["outcome"] == "completed" else None)
        try:
            await db.update_call(conn, call_id, ended_at=datetime.now(timezone.utc), outcome=status["outcome"],
                                 disposition=disposition,
                                 transcript=session.history.to_dict(exclude_function_call=False))
            if job_id:
                await db.finish_job(conn, job_id, "done", status["outcome"])
        finally:
            await conn.close()

    ctx.add_shutdown_callback(finalize)

    identity = f"sip_{phone}"
    if outbound:
        try:
            await ctx.api.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                room_name=ctx.room.name, sip_trunk_id=s.sip_outbound_trunk_id, sip_call_to=phone,
                sip_number=s.caller_number or "", participant_identity=identity,
                wait_until_answered=True, ringing_timeout=Duration(seconds=s.ringing_timeout_s),
                max_call_duration=Duration(seconds=s.max_call_seconds + 60)))
        except api.TwirpError as e:
            code = str(e.metadata.get("sip_status_code", ""))
            status["outcome"] = SIP_OUTCOME.get(code, "failed")
            await db.log_event(conn, call_id, "sip_error", {"code": code, "status": e.metadata.get("sip_status"),
                                                            "message": e.message})
            ctx.shutdown(reason=f"dial failed: {code}")
            return
        except Exception as e:  # anything else: record it instead of leaving the call 'dialing'
            status["outcome"] = "failed"
            await db.log_event(conn, call_id, "sip_error", {"error": repr(e)[:300]})
            ctx.shutdown(reason="dial failed")
            return
    # the session starts only once someone is on the line (LiveKit's outbound pattern)
    await session.start(agent=agent, room=ctx.room, record=False,
                        room_options=room_io.RoomOptions(participant_identity=identity if outbound else NOT_GIVEN,
                                                         delete_room_on_close=True))
    if outbound:
        status["answered"] = True
        status["outcome"] = "in_progress"
        await db.update_call(conn, call_id, answered_at=datetime.now(timezone.utc), outcome="in_progress")
    try:
        await recorder.start()
    except Exception:  # a recording problem must never leave the call silent
        log.exception("could not start the recording")
    LineWatch(controller, actions).attach()
    controller.greet(opener(prospect) if outbound else inbound_greeting())
    _arm_duration_cap(controller, s.max_call_seconds)


def run() -> None:
    cli.run_app(server)


if __name__ == "__main__":
    run()
