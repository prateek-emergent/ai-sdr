import { useEffect, useMemo, useRef, useState } from "react";
import { MediaDeviceFailure, RoomEvent, TokenSource } from "livekit-client";
import {
  RoomAudioRenderer, SessionProvider, useAgent, useLocalParticipant, useSession, useSessionMessages, useStartAudio,
  useTrackVolume,
} from "@livekit/components-react";
import {
  ArrowDown, ArrowUpRight, Ban, CalendarCheck, CalendarClock, CalendarSearch, CalendarX, CircleAlert, ClipboardCheck,
  Languages, LifeBuoy, Moon, Phone, PhoneCall, PhoneOff, Send, Sun, TriangleAlert, Undo2, Volume2,
} from "lucide-react";
import Calls from "./Calls";
import "./App.css";

// "Talk to Giulia": one click = a fresh LiveKit room with the AI SDR agent in it. Built on LiveKit's own session
// components (17 Oct revamp): they handle connecting, the agent-join timeout, audio playback and agent state, which
// the hand-written page got wrong (stuck at "connecting", silent audio, no error shown).
// 20 Oct redesign: monochrome frosted glass, light and dark (direction in .impeccable/surfaces/, system in DESIGN.md).
// Source of truth: github.com/prateek-emergent/ai-sdr (pulled into the pod; never edit it there).
const API = process.env.REACT_APP_BACKEND_URL;
const JOIN_TIMEOUT_MS = 20000;
const THEME_KEY = "giulia-theme"; // also read by the inline script in public/index.html, before first paint
const LANGS = [["it", "Italiano"], ["en", "English"]];

const ACTIONS = {
  get_available_slots: [CalendarSearch, "Checked the calendar"],
  book_meeting: [CalendarCheck, "Meeting booked"],
  reschedule_meeting: [CalendarClock, "Meeting moved"],
  cancel_meeting: [CalendarX, "Meeting cancelled"],
  request_manual_scheduling: [Send, "Sent to the team to book by hand"],
  schedule_callback: [PhoneCall, "Callback scheduled"],
  cancel_callback: [Undo2, "Callback cancelled"],
  mark_do_not_call: [Ban, "Marked do-not-call"],
  record_qualification: [ClipboardCheck, "Qualification recorded"],
};

// One row of "What Giulia did" for an sdr.events message, or null for events the page doesn't show
function describe(ev) {
  if (ev.type === "language_switch") return { Icon: Languages, label: ev.to === "en" ? "Switched to English" : "Switched to Italian" };
  if (ev.type === "support_issue") return { Icon: LifeBuoy, label: "Support issue logged", detail: [ev.kind, ev.summary].filter(Boolean).join(" · ") };
  if (ev.type === "error") return { Icon: TriangleAlert, label: "Calendar problem", detail: ev.error || ev.where };
  if (ev.type !== "tool_call") return null;
  if (ev.tool === "schedule_callback" && ev.error) return { Icon: TriangleAlert, label: "Callback not scheduled", detail: ev.error };
  const [Icon, label] = ACTIONS[ev.tool] || [ClipboardCheck, ev.tool];
  const when = ev.start || ev.utc;
  const detail = when ? new Date(when).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
    : ev.preferred || ev.score || ev.reason || (typeof ev.free === "number" ? `${ev.free} free slots` : null);
  return { Icon, label, detail };
}

const clock = (ms) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
const smooth = () => (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");

// What the person's browser experienced, sent to the backend so it lands in the call report next to the server's
// own timeline (17 Oct: "stuck" calls could not be explained without it). Batched; never blocks the call.
function useClientEvents() {
  const room = useRef(null);
  const queue = useRef([]);
  const t0 = useRef(0);
  const flush = () => {
    if (!room.current || queue.current.length === 0) return;
    const events = queue.current.splice(0, 50);
    fetch(`${API}/api/client-events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ room: room.current, events }), keepalive: true }).catch(() => {});
  };
  useEffect(() => {
    const id = setInterval(flush, 2000);
    return () => clearInterval(id);
  }, []);
  return {
    begin: () => { t0.current = performance.now(); queue.current = []; room.current = null; },
    setRoom: (r) => { room.current = r; },
    add: (kind, data = {}) => queue.current.push({ kind, t_ms: Math.round(performance.now() - t0.current), at: new Date().toISOString(), ...data }),
    flush,
  };
}

// Light or dark: the system's choice until the toggle is used, then the toggle's (remembered per browser)
function useTheme() {
  const [chosen, setChosen] = useState(() => { try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; } });
  const [system, setSystem] = useState(() => (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = () => setSystem(mq.matches ? "dark" : "light");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  const theme = chosen === "light" || chosen === "dark" ? chosen : system;
  useEffect(() => {
    document.documentElement.dataset.talkTheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#0a0a0a" : "#f0f0f0");
  }, [theme]);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setChosen(next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* storage blocked: this visit only */ }
  };
  return [theme, toggle];
}

// Keeps a scroll area on its latest line until the reader scrolls up; `away` = they're reading back
function useStickToBottom(signature) {
  const ref = useRef(null);
  const stuck = useRef(true);
  const lastTop = useRef(0);
  const [away, setAway] = useState(false);
  const toEnd = () => ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: smooth() });
  const onScroll = () => {
    const el = ref.current;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 24) { stuck.current = true; setAway(false); }
    else if (el.scrollTop < lastTop.current) { stuck.current = false; setAway(true); } // only the reader scrolls up
    lastTop.current = el.scrollTop;
  };
  useEffect(() => { if (stuck.current) toEnd(); }, [signature]); // eslint-disable-line react-hooks/exhaustive-deps
  const jump = () => { stuck.current = true; setAway(false); toEnd(); };
  return { ref, onScroll, away, jump };
}

// /calls is the metrics page; everything else is the "Talk to Giulia" page
export default function App() {
  return window.location.pathname.startsWith("/calls") ? <Calls /> : <TalkPage />;
}

function TalkPage() {
  const nameRef = useRef("");
  const langRef = useRef("it"); // Italian for customers; English for the team's tests (she can switch mid-call)
  const appRef = useRef(""); // optional: an app for Giulia to talk about, as on a real call
  const report = useClientEvents();
  useEffect(() => { document.title = "Talk to Giulia"; }, []);
  const tokenSource = useMemo(() => TokenSource.literal(async () => {
    // a fresh room every time: an agent never rejoins a room that existed before
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const r = await fetch(`${API}/api/session`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: nameRef.current, tz, language: langRef.current, app: appRef.current }) });
    if (!r.ok) throw new Error(`the server answered ${r.status}`);
    const j = await r.json();
    report.setRoom(j.room);
    report.add("session_created", { room: j.room, agent: j.agent });
    return { serverUrl: j.url, participantToken: j.token };
  }), []); // eslint-disable-line react-hooks/exhaustive-deps
  const session = useSession(tokenSource, { agentConnectTimeoutMilliseconds: JOIN_TIMEOUT_MS });
  return (
    <SessionProvider session={session}>
      <Call session={session} nameRef={nameRef} langRef={langRef} appRef={appRef} report={report} />
    </SessionProvider>
  );
}

function Call({ session, nameRef, langRef, appRef, report }) {
  const agent = useAgent(session);
  const { messages } = useSessionMessages(session);
  const [theme, toggleTheme] = useTheme();
  const [name, setName] = useState("");
  const [lang, setLang] = useState("it");
  const [callLang, setCallLang] = useState("it"); // follows her mid-call switches
  const [app, setApp] = useState("");
  const [phase, setPhase] = useState("idle"); // idle | starting | live | ended
  const [error, setError] = useState(null);
  const [actions, setActions] = useState([]);
  const [duration, setDuration] = useState(null);
  const startedAt = useRef(null);
  const seenStates = useRef(new Set());
  const room = session.room;
  const { mergedProps: audioProps, canPlayAudio } = useStartAudio({ room, props: {} });

  // room-level events: what Giulia did (data topic sdr.events), audio playback, connection problems
  useEffect(() => {
    const onData = (payload, _p, _k, topic) => {
      if (topic !== "sdr.events") return;
      try {
        const ev = JSON.parse(new TextDecoder().decode(payload));
        if (ev.type === "language_switch" && (ev.to === "it" || ev.to === "en")) setCallLang(ev.to);
        const row = describe(ev);
        if (row) setActions((a) => [...a, { at: new Date(), ...row }]);
      } catch (e) { /* not ours */ }
    };
    const onPlayback = () => report.add("audio_playback", { allowed: room.canPlaybackAudio });
    const onReconnecting = () => report.add("reconnecting");
    const onReconnected = () => report.add("reconnected");
    const onDisconnected = (reason) => {
      report.add("disconnected", { reason }); report.flush();
      if (startedAt.current) setDuration(Date.now() - startedAt.current);
      setPhase((p) => (p === "idle" ? p : "ended"));
    };
    const onMediaError = (e) => { const f = MediaDeviceFailure.getFailure(e); report.add("media_error", { failure: f }); setError(f === "PermissionDenied" ? "Microphone blocked: allow it in the browser's address bar, then start again." : "Your microphone couldn't be opened."); };
    room.on(RoomEvent.DataReceived, onData);
    room.on(RoomEvent.AudioPlaybackStatusChanged, onPlayback);
    room.on(RoomEvent.Reconnecting, onReconnecting);
    room.on(RoomEvent.Reconnected, onReconnected);
    room.on(RoomEvent.Disconnected, onDisconnected);
    room.on(RoomEvent.MediaDevicesError, onMediaError);
    return () => {
      room.off(RoomEvent.DataReceived, onData);
      room.off(RoomEvent.AudioPlaybackStatusChanged, onPlayback);
      room.off(RoomEvent.Reconnecting, onReconnecting);
      room.off(RoomEvent.Reconnected, onReconnected);
      room.off(RoomEvent.Disconnected, onDisconnected);
      room.off(RoomEvent.MediaDevicesError, onMediaError);
    };
  }, [room]); // eslint-disable-line react-hooks/exhaustive-deps

  // agent state: report each state the first time it is reached (joined, first listening, first speaking...)
  useEffect(() => {
    if (phase === "idle") return;
    if (!seenStates.current.has(agent.state)) {
      seenStates.current.add(agent.state);
      report.add("agent_state", { state: agent.state });
    }
    if (agent.state === "failed") {
      const why = (agent.failureReasons || []).join(" ") || "Giulia didn't join.";
      report.add("agent_failed", { reasons: agent.failureReasons });
      report.flush();
      setError(`${why} Please try again in a moment.`);
      session.end();
    }
  }, [agent.state, phase]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start() {
    setError(null); setActions([]); setDuration(null); seenStates.current = new Set();
    startedAt.current = null;
    nameRef.current = name.trim();
    langRef.current = lang;
    appRef.current = app.trim();
    setCallLang(lang);
    report.begin();
    report.add("start_clicked", { ua: navigator.userAgent.slice(0, 120) });
    setPhase("starting");
    try {
      room.startAudio().catch(() => {}); // still inside the click: lets the browser play Giulia's voice
      await session.start({ tracks: { microphone: { enabled: true } } });
      report.add("connected", { can_play_audio: room.canPlaybackAudio });
      startedAt.current = Date.now();
      setPhase("live");
    } catch (e) {
      report.add("start_failed", { error: String(e?.message || e).slice(0, 200) });
      report.flush();
      setError(`Couldn't start the call: ${e?.message || e}`);
      setPhase("idle");
    }
  }

  async function stop() {
    report.add("hung_up_by_person");
    report.flush();
    await session.end();
    if (startedAt.current) setDuration(Date.now() - startedAt.current);
    setPhase("ended");
  }

  const live = phase === "starting" || phase === "live";
  const status = phase === "starting" ? ["connecting", "Connecting…"]
    : agent.state === "speaking" ? ["speaking", "Giulia is speaking"]
    : agent.state === "listening" ? ["listening", "Listening"]
    : agent.state === "thinking" ? ["thinking", "Thinking…"]
    : ["waiting", "Waiting for Giulia…"];
  // One bubble per spoken segment: each draft of the same segment arrives as a new message (new id), so key by
  // lk.segment_id and keep the latest text in the position the segment first appeared (17 Oct: bubbles jumped).
  // The person's drafts show as outlines until Deepgram's final version arrives, as on the old page; Giulia's final
  // flag only comes at the end of her line, so hers are never drafts.
  const lines = [];
  const bySegment = new Map();
  for (const m of messages) {
    if (m.type !== "userTranscript" && m.type !== "agentTranscript") continue;
    const seg = m.attributes?.["lk.segment_id"] || m.id;
    const line = { key: seg, user: m.type === "userTranscript", text: m.message,
      draft: m.type === "userTranscript" && m.attributes?.["lk.transcription_final"] !== "true" };
    if (bySegment.has(seg)) lines[bySegment.get(seg)] = line;
    else { bySegment.set(seg, lines.length); lines.push(line); }
  }

  return (
    <div className="talk">
      <VoiceField room={room} agentTrack={agent.microphoneTrack} live={live} />
      <header className="topbar">
        <div className="brand">
          <h1>Talk to Giulia</h1>
          <span className="brand-sub">Emergent's AI SDR</span>
        </div>
        <nav className="topbar-nav">
          <a className="nav-link" href="/calls" target="_blank" rel="noreferrer">Calls<ArrowUpRight aria-hidden="true" /></a>
          <button type="button" className="icon-btn" onClick={toggleTheme} aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
            {theme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
          </button>
        </nav>
      </header>

      <main className="console glass">
        {error && <div className="alert" role="alert"><CircleAlert aria-hidden="true" /><span>{error}</span></div>}
        <div className="controls">
          {live ? (
            <>
              <div className="status" data-state={status[0]}>
                <span className="dot" aria-hidden="true" />
                <span className="status-text" aria-live="polite">{status[1]}</span>
                {phase === "live" && <Elapsed since={startedAt.current} />}
                <span className="chip">{callLang === "en" ? "English" : "Italiano"}</span>
              </div>
              <div className="control-actions">
                {/* while the browser blocks her audio, hearing her is the main action; the tap is the gesture it wants */}
                {!canPlayAudio && <button type="button" className="btn btn-primary" onClick={audioProps.onClick}><Volume2 aria-hidden="true" />Tap to hear Giulia</button>}
                <button type="button" className={`btn ${canPlayAudio ? "btn-primary" : "btn-quiet"}`} onClick={stop}><PhoneOff aria-hidden="true" />End call</button>
              </div>
            </>
          ) : (
            <form className="setup" onSubmit={(e) => { e.preventDefault(); start(); }}>
              <input className="input in-name" placeholder="Your first name (optional)" aria-label="Your first name (optional)" value={name} maxLength={60} autoComplete="given-name" onChange={(e) => setName(e.target.value)} />
              <div className="segmented" role="radiogroup" aria-label="Call language">
                {LANGS.map(([value, label]) => (
                  <label key={value}>
                    <input type="radio" name="call-language" value={value} checked={lang === value} onChange={() => setLang(value)} />
                    <span>{label}</span>
                  </label>
                ))}
              </div>
              <input className="input in-app" placeholder="App for Giulia to ask about (optional)" aria-label="An app you built, for Giulia to ask about (optional)" value={app} maxLength={60} onChange={(e) => setApp(e.target.value)} />
              <button type="submit" className="btn btn-primary"><Phone aria-hidden="true" />Start talking</button>
            </form>
          )}
        </div>

        <div className="panes">
          <Transcript lines={lines} phase={phase} duration={duration} />
          <Actions actions={actions} />
        </div>
      </main>
      <RoomAudioRenderer room={room} />
    </div>
  );
}

function Transcript({ lines, phase, duration }) {
  const last = lines[lines.length - 1];
  const { ref, onScroll, away, jump } = useStickToBottom(`${lines.length}:${last?.text.length || 0}:${phase}`);
  const live = phase === "starting" || phase === "live";
  return (
    <section className="pane transcript" aria-labelledby="transcript-title">
      <div className="pane-head"><h2 id="transcript-title">Live transcript</h2></div>
      <div className="scroll" ref={ref} onScroll={onScroll}>
        {lines.length === 0 ? (
          <div className="empty">
            {live ? <p>Giulia will start speaking in a second. Allow the microphone when asked.</p> : (
              <>
                <p className="empty-lead">She speaks first, then it's a normal phone-style conversation.</p>
                <p>Pick a language, press Start talking and allow the microphone.</p>
              </>
            )}
          </div>
        ) : (
          <ol className="lines">
            {lines.map((l, i) => {
              const first = i === 0 || lines[i - 1].user !== l.user;
              const lastOfRun = i === lines.length - 1 || lines[i + 1].user !== l.user;
              const cls = ["line", l.user ? "you" : "her", first && "first", lastOfRun && "last", l.draft && "draft"].filter(Boolean).join(" ");
              return (
                <li key={l.key} className={cls}>
                  {first ? <span className="who">{l.user ? "You" : "Giulia"}</span> : <span className="sr-only">{l.user ? "You" : "Giulia"}: </span>}
                  <p className="bubble">{l.text}</p>
                </li>
              );
            })}
            {phase === "ended" && <li className="ended">Call ended{duration ? ` · ${clock(duration)}` : ""}</li>}
          </ol>
        )}
      </div>
      {away && <button type="button" className="jump" onClick={jump}><ArrowDown aria-hidden="true" />Latest</button>}
    </section>
  );
}

function Actions({ actions }) {
  const { ref, onScroll } = useStickToBottom(actions.length);
  return (
    <aside className="pane actions" aria-labelledby="actions-title">
      <div className="pane-head">
        <h2 id="actions-title">What Giulia did</h2>
        {actions.length > 0 && <span className="count">{actions.length}</span>}
      </div>
      <div className="scroll" ref={ref} onScroll={onScroll}>
        {actions.length === 0 ? <p className="empty-note">Bookings, callbacks and do-not-call show up here.</p> : (
          <ol className="acts">
            {actions.map((a, i) => (
              <li key={i} className="act">
                <a.Icon className="act-icon" aria-hidden="true" />
                <div className="act-body">
                  <span className="act-label">{a.label}</span>
                  {a.detail && <span className="act-detail">{a.detail}</span>}
                </div>
                <time className="act-time" dateTime={a.at.toISOString()}>{a.at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
              </li>
            ))}
          </ol>
        )}
      </div>
    </aside>
  );
}

function Elapsed({ since }) {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  return <span className="timer" role="timer">{clock(Date.now() - since)}</span>;
}

// The light behind the glass: Giulia's side (left) and yours (right) swell with each voice's level. Its own
// component, so 30 level updates a second re-render two divs, not the transcript.
function VoiceField({ room, agentTrack, live }) {
  const { microphoneTrack } = useLocalParticipant({ room });
  const her = useTrackVolume(live ? agentTrack : undefined);
  const you = useTrackVolume(live ? microphoneTrack?.track : undefined);
  const level = (v) => Math.min(1, Math.max(0, (v - 0.08) * 3)).toFixed(3); // below 0.08 = room noise; tune on real calls
  return (
    <div className="field" aria-hidden="true" style={{ "--her": level(her), "--you": level(you) }}>
      <div className="light light-her" />
      <div className="light light-you" />
    </div>
  );
}
