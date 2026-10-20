"""Command line: `uv run ai-sdr <command>`. Run `uv run ai-sdr -h` for the list."""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from datetime import datetime, timezone

from . import db
from .config import settings
from .timeutil import next_business_time


def _phone(raw: str) -> str:
    p = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
    if p.startswith("00"):
        p = "+" + p[2:]
    if not p.startswith("+"):
        # Italian numbers keep their leading 0 (landlines) or 3 (mobiles); a leading 39 + 11 digits is a country code
        p = "+" + p if p.startswith("39") and len(p) >= 11 else "+39" + p
    return p


async def cmd_init_db(_):
    await db.init_schema()
    print("schema ready")


async def cmd_import(args):
    """CSV columns: phone (required), first_name, last_name, email, company, segment, external_id,
    hubspot_contact_id, tz, and any other column -> context (e.g. what_they_built, plan, signup_date)."""
    core = {"phone", "first_name", "last_name", "email", "company", "segment", "external_id",
            "hubspot_contact_id", "tz"}
    n = 0
    async with db.connect() as conn:
        with open(args.csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not row.get("phone"):
                    continue
                await db.upsert_prospect(conn, {
                    **{k: (row.get(k) or None) for k in core - {"phone"}},
                    "phone_e164": _phone(row["phone"]),
                    "context": {k: v for k, v in row.items() if k not in core and v}})
                n += 1
    print(f"imported {n} prospects")


async def cmd_enqueue(args):
    """Queue a first call for every active prospect that has no queued job and was never called."""
    s = settings()
    async with db.connect() as conn:
        rows = await (await conn.execute(
            """SELECT p.id, p.tz FROM prospects p
               WHERE p.status = 'active' AND NOT p.dnc AND p.attempts = 0
                 AND NOT EXISTS (SELECT 1 FROM call_jobs j WHERE j.prospect_id = p.id AND j.status = 'queued')
               ORDER BY p.id LIMIT %s""", [args.limit])).fetchall()
        now = datetime.now(timezone.utc)
        for r in rows:
            await db.enqueue_job(conn, r["id"], "first", next_business_time(now, r["tz"], s.business_hours))
    print(f"queued {len(rows)} first calls")


async def cmd_call(args):
    """Call one prospect right now (testing). --ignore-hours only for team test numbers."""
    from .dialer import dial_job
    async with db.connect() as conn:
        job_id = await db.enqueue_job(conn, args.prospect_id, "first", datetime.now(timezone.utc),
                                      reason="manual", created_by="ops")
        if job_id is None:
            sys.exit("prospect is DNC or not active")
        job = await (await conn.execute(
            """SELECT j.*, p.phone_e164, p.tz, p.dnc, p.status AS prospect_status, p.attempts
               FROM call_jobs j JOIN prospects p ON p.id = j.prospect_id WHERE j.id = %s""", [job_id])).fetchone()
        await db.finish_job(conn, job_id, "dialing")
        print(await dial_job(conn, job, ignore_hours=args.ignore_hours))


async def cmd_kill(args):
    async with db.connect() as conn:
        await db.set_kill_switch(conn, args.state == "on")
    print(f"kill switch {args.state}")


async def cmd_stats(_):
    async with db.connect() as conn:
        funnel = await (await conn.execute(
            """SELECT count(*) FILTER (WHERE direction='outbound') AS dialed,
                      count(*) FILTER (WHERE answered_at IS NOT NULL) AS connected,
                      count(*) FILTER (WHERE outcome='completed') AS human,
                      count(*) FILTER (WHERE outcome='completed' AND ended_at - answered_at > interval '30 seconds') AS over_30s,
                      count(*) FILTER (WHERE outcome='completed' AND ended_at - answered_at > interval '2 minutes') AS over_2m,
                      count(*) FILTER (WHERE qualification='qualified') AS qualified,
                      count(*) FILTER (WHERE disposition='meeting_booked') AS booked,
                      count(*) FILTER (WHERE disposition='dnc') AS dnc,
                      count(*) FILTER (WHERE review_status='flagged') AS flagged
               FROM calls""")).fetchone()
        queue = await (await conn.execute(
            "SELECT kind, count(*) AS n FROM call_jobs WHERE status='queued' GROUP BY kind")).fetchall()
    print(json.dumps({"funnel": funnel, "queued": {r["kind"]: r["n"] for r in queue}}, indent=2, default=str))


async def cmd_setup_livekit(args):
    from .setup_livekit import setup
    print(json.dumps(await setup(args.termination_uri, args.username, args.password), indent=2))


async def cmd_demo_link(args):
    """A browser link to talk to the agent: LiveKit's hosted meet page + a token that dispatches our agent."""
    import secrets
    from datetime import timedelta
    from urllib.parse import urlencode
    from livekit import api
    s = settings()
    room = f"demo-{secrets.token_hex(4)}"
    meta = {"direction": "web", "first_name": args.name, "tz": args.tz, "email": args.email,
            "context": {"note": args.context} if args.context else {}}
    token = (api.AccessToken(s.livekit_api_key, s.livekit_api_secret)
             .with_identity(f"demo-{secrets.token_hex(3)}").with_name(args.name or "Ospite")
             .with_grants(api.VideoGrants(room_join=True, room=room))
             .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(
                 agent_name=s.agent_name, metadata=json.dumps(meta))]))
             .with_ttl(timedelta(hours=args.hours)).to_jwt())
    print("https://meet.livekit.io/custom?" + urlencode({"liveKitUrl": s.livekit_url, "token": token}))


async def cmd_demo_watch(args):
    """Reopening a demo link right after a call recreates the room without an agent (the link's built-in dispatch
    only fires once). Every few seconds, send the agent into any demo room that has a person but no agent."""
    import json as _json
    import time
    from livekit import api
    s = settings()
    lk = api.LiveKitAPI()
    sent: dict[str, float] = {}
    try:
        while True:
            try:
                rooms = (await lk.room.list_rooms(api.ListRoomsRequest())).rooms
            except Exception:
                logging.exception("could not list rooms")
                rooms = []
            for room in rooms:
                if not room.name.startswith("demo-") or time.time() - room.creation_time < 6:
                    continue  # the link's own dispatch may still be arriving
                try:  # a room can vanish between calls (the call just ended): skip it, never crash
                    people = (await lk.room.list_participants(
                        api.ListParticipantsRequest(room=room.name))).participants
                    # LiveKit adds an empty-name placeholder dispatch to every room: only ours counts
                    pending = [d for d in await lk.agent_dispatch.list_dispatch(room_name=room.name)
                               if d.agent_name == s.agent_name]
                    has_agent = any(p.kind == api.ParticipantInfo.Kind.AGENT for p in people)
                    if people and not has_agent and not pending and \
                            asyncio.get_running_loop().time() - sent.get(room.sid, -1e9) > 20:
                        meta = room.metadata or _json.dumps({"direction": "web", "tz": args.tz})
                        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                            agent_name=s.agent_name, room=room.name, metadata=meta))
                        sent[room.sid] = asyncio.get_running_loop().time()
                        logging.info("sent the agent into %s", room.name)
                except api.TwirpError as e:
                    logging.info("skipped %s: %s", room.name, e.message)
            await asyncio.sleep(2)
    finally:
        await lk.aclose()


def cmd_evals(args) -> int:
    """The improvement loop's commands (ai_sdr/evals/__init__.py). Exit 1 when a simulation broke a MUST check."""
    from .evals import reports
    from .evals.scenarios import BY_ID, SCENARIOS
    ids = None if getattr(args, "scenario", "all") == "all" else args.scenario.split(",")
    if ids and (unknown := [i for i in ids if i not in BY_ID]):
        print(f"unknown scenario(s): {', '.join(unknown)}; see `python -m ai_sdr.cli evals scenarios`")
        return 2
    if args.evals_cmd == "scenarios":
        for sc in SCENARIOS:
            print(f"{sc.id:20} {sc.language}  ends as {'/'.join(sc.outcomes):40} {sc.persona[:70]}")
        return 0
    if args.evals_cmd == "watch":
        from .evals.watch import run_forever
        asyncio.run(run_forever())
        return 0
    if args.evals_cmd == "grade":
        from .evals.watch import grade_report

        async def grade_all() -> int:
            todo = [reports.get(r) for r in args.room] if args.room else list(reports.ungraded())
            for report in todo:
                if report is None:
                    print("no such call")
                    continue
                g = await grade_report(report)
                print(f"{report['room']}: score {g.get('score')}  failed {g.get('failed') or g.get('skipped') or '-'}")
            return 0
        return asyncio.run(grade_all())
    if args.evals_cmd == "simulate":
        from .evals.simulate import suite
        s = asyncio.run(suite(ids, repeat=args.repeat, concurrency=args.concurrency, label=args.label,
                              trace=args.trace))
        print(f"\n{s['runs']} calls · outcome reached {s['outcome_pass_rate']} · score {s['score']} · "
              f"must-checks failed in {s['must_failed_runs']} · errors {s['errors']}\nreport: {s['dir']}/summary.md")
        return 1 if s["must_failed_runs"] else 0
    if args.evals_cmd == "improve":
        from pathlib import Path
        from .evals.improve import apply_candidate, improve
        if args.apply:
            changed = apply_candidate(Path(args.apply))
            print(f"updated {', '.join(changed) or 'nothing (same prompts)'}; next: python -m ai_sdr.agent.prompt_check, "
                  "pytest, commit, push, pull on the pod")
            return 0
        r = asyncio.run(improve(days=args.days, scenarios=ids, repeat=args.repeat, max_edits=args.max_edits))
        print(f"\nverdict: {r['verdict']}\nreport: {r['dir']}/report.md")
        return 0
    return 2


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "agent":  # hand over to LiveKit's own CLI: dev | start | console
        from .agent.worker import run
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        run()
        return

    ap = argparse.ArgumentParser(prog="ai-sdr")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="create tables")
    p = sub.add_parser("import", help="load prospects from a CSV you exported from our DB")
    p.add_argument("csv")
    p = sub.add_parser("enqueue", help="queue first calls for new prospects")
    p.add_argument("--limit", type=int, default=100)
    sub.add_parser("dialer", help="run the dialer loop")
    sub.add_parser("postcall", help="run the post-call loop")
    p = sub.add_parser("call", help="call one prospect now (testing)")
    p.add_argument("prospect_id", type=int)
    p.add_argument("--ignore-hours", action="store_true")
    p = sub.add_parser("kill", help="stop/start all new dials")
    p.add_argument("state", choices=["on", "off"])
    sub.add_parser("stats", help="funnel numbers")
    p = sub.add_parser("setup-livekit", help="create LiveKit SIP trunks + inbound dispatch rule")
    p.add_argument("--termination-uri", required=True)
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    sub.add_parser("agent", help="run the LiveKit agent worker: ai-sdr agent dev|start")
    p = sub.add_parser("demo-watch", help="keep demo links working when reopened (sends the agent back in)")
    p.add_argument("--tz", default="Asia/Kolkata", help="time zone used if the room carries none")
    p = sub.add_parser("demo-link", help="browser link to talk to the agent (agent speaks first)")
    p.add_argument("--name", default="Marco", help="first name the agent greets")
    p.add_argument("--context", default="", help="what the pretend user built, e.g. 'gestionale per palestre'")
    p.add_argument("--hours", type=int, default=24, help="how long the link works")
    p.add_argument("--tz", default="Europe/Rome", help="tester's time zone, e.g. Asia/Kolkata (greetings, dates)")
    p.add_argument("--email", default="", help="tester's email, so the agent only confirms it (as on real calls)")
    p = sub.add_parser("probe", help="place scripted voice calls against an app and check the reliability targets")
    p.add_argument("--target", default="preview", help="preview | prod | a base URL")
    p.add_argument("--scenario", default="all", help="comma list, or 'all'")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--gap", type=float, default=3.0, help="seconds between calls")
    p = sub.add_parser("evals", help="grade calls, simulate customers, propose prompt improvements (ai_sdr/evals)")
    ev = p.add_subparsers(dest="evals_cmd", required=True)
    e = ev.add_parser("grade", help="grade finished calls now (default: every ungraded call of the last 24 h)")
    e.add_argument("--room", action="append", help="one call's room, e.g. demo-31e3d4b4 (repeatable; regrades it)")
    ev.add_parser("watch", help="keep grading calls as they end, in the foreground (the web backend starts one)")
    ev.add_parser("scenarios", help="list the simulated customers")
    e = ev.add_parser("simulate", help="simulated customers talk to Giulia (text); every call is graded")
    e.add_argument("--scenario", default="all", help="comma list of scenario ids, or 'all'")
    e.add_argument("--repeat", type=int, default=1)
    e.add_argument("--concurrency", type=int, default=4)
    e.add_argument("--label", default="", help="a name for this run, e.g. the change you're testing")
    e.add_argument("--trace", action="store_true", help="also send the simulated calls to Langfuse")
    e = ev.add_parser("improve", help="propose a prompt change from the failures and test it on the scenarios")
    e.add_argument("--days", type=float, default=7, help="graded calls from this many days back")
    e.add_argument("--scenario", default="all", help="comma list of scenario ids, or 'all'")
    e.add_argument("--repeat", type=int, default=1, help="runs per scenario per side (2-3 for a steadier verdict)")
    e.add_argument("--max-edits", type=int, default=4)
    e.add_argument("--apply", metavar="CANDIDATE_DIR", help="copy an accepted candidate's prompts into the repo")
    args = ap.parse_args()

    if args.cmd == "evals":
        sys.exit(cmd_evals(args))
    if args.cmd == "probe":
        from .probe.run import run as run_probe
        from .probe.scenarios import SCENARIOS
        names = list(SCENARIOS) if args.scenario == "all" else args.scenario.split(",")
        summary = asyncio.run(run_probe(args.target, names, args.repeat, args.gap))
        sys.exit(1 if summary["failed_checks"] else 0)
    if args.cmd == "dialer":
        from .dialer import run_forever
        asyncio.run(run_forever())
    elif args.cmd == "postcall":
        from .postcall import run_forever
        asyncio.run(run_forever())
    else:
        handler = {"init-db": cmd_init_db, "import": cmd_import, "enqueue": cmd_enqueue, "call": cmd_call,
                   "kill": cmd_kill, "stats": cmd_stats, "setup-livekit": cmd_setup_livekit,
                   "demo-link": cmd_demo_link, "demo-watch": cmd_demo_watch}[args.cmd]
        asyncio.run(handler(args))


if __name__ == "__main__":
    main()
