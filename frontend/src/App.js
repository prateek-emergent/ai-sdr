import { useEffect, useMemo, useRef, useState } from "react";
import { MediaDeviceFailure, RoomEvent, TokenSource } from "livekit-client";
import { RoomAudioRenderer, SessionProvider, StartAudio, useAgent, useSession, useSessionMessages } from "@livekit/components-react";
import Calls from "./Calls";

// "Talk to Giulia": one click = a fresh LiveKit room with the AI SDR agent in it. Built on LiveKit's own session
// components (17 Oct revamp): they handle connecting, the agent-join timeout, audio playback and agent state, which
// the hand-written page got wrong (stuck at "connecting", silent audio, no error shown).
// Source of truth: ai-sdr/pipeline/deploy/emergent/frontend (synced to the pod; never edit it there).
const API = process.env.REACT_APP_BACKEND_URL;
const JOIN_TIMEOUT_MS = 20000;

const ACTION_LABELS = {
  get_available_slots: "📅 Checked the calendar",
  book_meeting: "✅ Meeting booked",
  reschedule_meeting: "🔁 Meeting moved",
  cancel_meeting: "❌ Meeting cancelled",
  request_manual_scheduling: "📨 Sent to the team to book by hand",
  schedule_callback: "📞 Callback scheduled",
  cancel_callback: "↩️ Callback cancelled",
  mark_do_not_call: "⛔ Marked do-not-call",
  record_qualification: "📝 Qualification recorded",
};

function describe(ev) {
  const label = ACTION_LABELS[ev.tool] || ev.tool || ev.type;
  const when = ev.start || ev.utc;
  const extra = when ? ` · ${new Date(when).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`
    : ev.preferred ? ` · ${ev.preferred}` : ev.score ? ` · ${ev.score}` : ev.reason ? ` · ${ev.reason}` : "";
  return label + extra;
}

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

// /calls is the metrics page; everything else is the "Talk to Giulia" page
export default function App() {
  return window.location.pathname.startsWith("/calls") ? <Calls /> : <TalkPage />;
}

function TalkPage() {
  const nameRef = useRef("");
  const langRef = useRef("it"); // Italian for customers; English for the team's tests (she can switch mid-call)
  const appRef = useRef(""); // optional: an app for Giulia to talk about, as on a real call
  const report = useClientEvents();
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
  const [name, setName] = useState("");
  const [lang, setLang] = useState("it");
  const [app, setApp] = useState("");
  const [phase, setPhase] = useState("idle"); // idle | starting | live | ended
  const [error, setError] = useState(null);
  const [actions, setActions] = useState([]);
  const bottomRef = useRef(null);
  const seenStates = useRef(new Set());
  const room = session.room;

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  // room-level events: what Giulia did (data topic sdr.events), audio playback, connection problems
  useEffect(() => {
    const onData = (payload, _p, _k, topic) => {
      if (topic !== "sdr.events") return;
      try {
        const ev = JSON.parse(new TextDecoder().decode(payload));
        if (ev.type === "tool_call") setActions((a) => [...a, { at: new Date(), text: describe(ev) }]);
      } catch (e) { /* not ours */ }
    };
    const onPlayback = () => report.add("audio_playback", { allowed: room.canPlaybackAudio });
    const onReconnecting = () => report.add("reconnecting");
    const onReconnected = () => report.add("reconnected");
    const onDisconnected = (reason) => { report.add("disconnected", { reason }); report.flush(); setPhase((p) => (p === "idle" ? p : "ended")); };
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
    setError(null); setActions([]); seenStates.current = new Set();
    nameRef.current = name.trim();
    langRef.current = lang;
    appRef.current = app.trim();
    report.begin();
    report.add("start_clicked", { ua: navigator.userAgent.slice(0, 120) });
    setPhase("starting");
    try {
      room.startAudio().catch(() => {}); // still inside the click: lets the browser play Giulia's voice
      await session.start({ tracks: { microphone: { enabled: true } } });
      report.add("connected", { can_play_audio: room.canPlaybackAudio });
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
    setPhase("ended");
  }

  const live = phase === "starting" || phase === "live";
  const badge = !live ? (phase === "ended" ? ["call ended", "#6b7280"] : ["ready", "#6b7280"])
    : agent.state === "speaking" ? ["Giulia is speaking", "#16a34a"]
    : agent.state === "listening" ? ["listening", "#16a34a"]
    : agent.state === "thinking" ? ["thinking…", "#0ea5e9"]
    : ["waiting for Giulia…", "#ca8a04"];
  // One bubble per spoken segment: each draft of the same segment arrives as a new message (new id), so key by
  // lk.segment_id and keep the latest text in the position the segment first appeared (17 Oct: bubbles jumped).
  // The person's drafts are dimmed until Deepgram's final version arrives, as on the old page; Giulia's final flag
  // only comes at the end of her line, so hers are never dimmed.
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
    <div style={S.page}>
      <div style={S.card}>
        <div style={S.header}>
          <div style={S.avatar}>G</div>
          <div>
            <div style={S.title}>Talk to Giulia</div>
            <div style={S.sub}>Emergent's AI SDR · she speaks first, then it's a normal phone-style conversation</div>
          </div>
          <div style={{ ...S.badge, background: badge[1] }}>{badge[0]}</div>
        </div>

        {error && <div style={S.error}>{error}</div>}
        {!live && (
          <>
            <div style={S.row}>
              <input style={S.input} placeholder="Your first name (optional)" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
              <select style={S.select} value={lang} onChange={(e) => setLang(e.target.value)} aria-label="Call language">
                <option value="it">Italiano</option>
                <option value="en">English</option>
              </select>
            </div>
            <div style={S.row}>
              <input style={S.input} placeholder="An app you built, for Giulia to ask about (optional)" value={app} maxLength={60} onChange={(e) => setApp(e.target.value)} />
              <button style={S.start} onClick={start}>▶ Start talking</button>
            </div>
          </>
        )}
        {live && <div style={S.row}>
          <StartAudio room={room} label="🔊 Tap to hear Giulia" style={S.start} />
          <button style={S.stop} onClick={stop}>■ End call</button>
        </div>}

        <div style={S.cols}>
          <div style={S.transcript}>
            <div style={S.colTitle}>Live transcript</div>
            {lines.length === 0 && <div style={S.empty}>{live ? "Giulia will start speaking in a second. Allow the microphone when asked." : "Press Start and allow the microphone."}</div>}
            {lines.map((l) => (
              <div key={l.key} style={{ ...S.bubble, ...(l.user ? S.you : S.giulia), opacity: l.draft ? 0.55 : 1, fontStyle: l.draft ? "italic" : "normal" }}>
                <span style={S.who}>{l.user ? "You" : "Giulia"}</span>{l.text}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
          <div style={S.actions}>
            <div style={S.colTitle}>What Giulia did</div>
            {actions.length === 0 && <div style={S.empty}>Bookings, callbacks and do-not-call show up here.</div>}
            {actions.map((a, i) => (
              <div key={i} style={S.action}><span style={S.time}>{a.at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>{a.text}</div>
            ))}
          </div>
        </div>
        <RoomAudioRenderer room={room} />
      </div>
    </div>
  );
}

const S = {
  page: { minHeight: "100vh", background: "linear-gradient(160deg,#0f172a,#1e293b)", display: "flex", alignItems: "center", justifyContent: "center", padding: 24, fontFamily: "Inter, system-ui, sans-serif" },
  card: { width: "100%", maxWidth: 980, background: "#f8fafc", borderRadius: 18, padding: 24, boxShadow: "0 20px 60px rgba(0,0,0,.35)" },
  header: { display: "flex", alignItems: "center", gap: 14, marginBottom: 18 },
  avatar: { width: 46, height: 46, borderRadius: "50%", background: "linear-gradient(135deg,#f97316,#ec4899)", color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 20 },
  title: { fontSize: 22, fontWeight: 700, color: "#0f172a" },
  sub: { fontSize: 13, color: "#64748b" },
  badge: { marginLeft: "auto", color: "#fff", fontSize: 12, padding: "6px 10px", borderRadius: 999 },
  error: { background: "#fef2f2", border: "1px solid #fecaca", color: "#991b1b", borderRadius: 10, padding: "10px 12px", marginBottom: 12, fontSize: 14 },
  row: { display: "flex", gap: 10, marginBottom: 16 },
  input: { flex: 1, padding: "12px 14px", borderRadius: 10, border: "1px solid #cbd5e1", fontSize: 15 },
  select: { padding: "12px 14px", borderRadius: 10, border: "1px solid #cbd5e1", fontSize: 15, background: "#fff" },
  start: { padding: "12px 20px", borderRadius: 10, border: 0, background: "#16a34a", color: "#fff", fontWeight: 600, fontSize: 15, cursor: "pointer" },
  stop: { padding: "12px 20px", borderRadius: 10, border: 0, background: "#dc2626", color: "#fff", fontWeight: 600, fontSize: 15, cursor: "pointer" },
  cols: { display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 },
  transcript: { background: "#fff", borderRadius: 12, padding: 14, height: 440, overflowY: "auto", border: "1px solid #e2e8f0" },
  actions: { background: "#fff", borderRadius: 12, padding: 14, height: 440, overflowY: "auto", border: "1px solid #e2e8f0" },
  colTitle: { fontSize: 12, textTransform: "uppercase", letterSpacing: 1, color: "#94a3b8", marginBottom: 10 },
  empty: { color: "#94a3b8", fontSize: 14 },
  bubble: { padding: "10px 12px", borderRadius: 12, marginBottom: 8, fontSize: 15, lineHeight: 1.4, maxWidth: "85%" },
  you: { background: "#e0f2fe", marginLeft: "auto" },
  giulia: { background: "#fef3c7" },
  who: { display: "block", fontSize: 11, fontWeight: 700, color: "#64748b", marginBottom: 2 },
  action: { fontSize: 14, padding: "8px 0", borderBottom: "1px solid #f1f5f9", color: "#0f172a" },
  time: { color: "#94a3b8", fontSize: 12, marginRight: 8 },
};
