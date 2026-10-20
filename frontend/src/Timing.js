import { useEffect, useReducer, useRef, useState } from "react";
import { AudioLines, Brain, CalendarSearch, ChevronDown, Ear, Hourglass, Mic, Volume2, Wrench } from "lucide-react";
import { METRICS, metricValue, percentile } from "./shared";
import "./Timing.css";

// The live timing strip on the Talk page (20 Oct: "I want to see the time each step takes, live, as a flow chart").
// The worker sends each turn's timings on the sdr.events topic (backend voice/live.py): the person's turn when it
// ends (speech written down, turn judged over), each tool's duration while it runs, Giulia's reply when her line is
// added (LLM first word, first sentence to the voice, first audio, total). Everything is counted from the moment the
// person stopped talking. While she prepares the reply the page runs its own clock from the moment the turn-over
// arrives until she is audible: the caller's wait is then turn-over + that clock, live, before the server's numbers
// (not from "thinking": with early replies on, she can be "thinking" while the person is still talking).

export const TARGET_S = 1.5; // under this a reply feels like a person answering (the /calls page's green line)
const MAX_TURNS = 40;
const OPEN_KEY = "giulia-timing-open"; // the strip's open/closed state, remembered per browser

const TOOLS = {
  available_slots: [CalendarSearch, "Calendar"], book_meeting: [CalendarSearch, "Booking"],
  reschedule_meeting: [CalendarSearch, "Moving it"], cancel_meeting: [CalendarSearch, "Cancelling"],
  schedule_callback: [CalendarSearch, "Callback"], cancel_callback: [CalendarSearch, "Callback off"],
  request_manual_scheduling: [Wrench, "Hand-off"], mark_do_not_call: [Wrench, "Do-not-call"],
  log_support_issue: [Wrench, "Support issue"], record_qualification: [Wrench, "Qualification"],
};

const sec = (v) => (v === null || v === undefined ? "–" : `${v.toFixed(2)} s`);
const model = (m) => (m ? m.replace(/^claude-/, "").replace(/^aura-2-/, "aura ").replace(/-\d{8}$/, "") : null);
const tagged = (abbr, m) => [abbr, model(m)].filter(Boolean).join(" · "); // the metric's standard name, and who did it

// turns: finished replies; pending: the reply being made (the person's part and tools so far)
function reducer(state, action) {
  if (action.type === "reset") return { turns: [], pending: null };
  const ev = action.ev;
  if (ev.role === "user") return { ...state, pending: { user: ev, tools: [] } };
  if (ev.role === "tool") {
    const p = state.pending || { user: null, tools: [] };
    return { ...state, pending: { ...p, tools: [...p.tools, ev] } };
  }
  if (ev.role === "agent") {
    const turn = { ...(state.pending || { user: null, tools: [] }), agent: ev, n: state.turns.length + 1 };
    return { turns: [...state.turns, turn].slice(-MAX_TURNS), pending: null };
  }
  return state;
}

export function useTurnTimings() {
  const [state, dispatch] = useReducer(reducer, { turns: [], pending: null });
  // `at`: when the event reached the page (the turn-over starts the page's own clock)
  return { ...state, add: (ev) => dispatch({ type: "add", ev: { ...ev, at: performance.now() } }), reset: () => dispatch({ type: "reset" }) };
}

// The page's clock for the current wait: from the turn-over arriving to Giulia being audible
function useStopwatch(startAt, agentState) {
  const [stopped, setStopped] = useState({ at: null, time: null }); // when she became audible, for which turn-over
  const [, tick] = useState(0);
  const prev = useRef(agentState);
  const stop = stopped.at === startAt ? stopped.time : null;
  useEffect(() => {
    // a change INTO speaking: a line still playing when the turn-over arrives (a barge-in) doesn't count
    if (startAt != null && stop === null && agentState === "speaking" && prev.current !== "speaking") {
      setStopped({ at: startAt, time: performance.now() });
    }
    prev.current = agentState;
  }, [agentState, startAt, stop]);
  const running = startAt != null && stop === null;
  useEffect(() => {
    if (!running) return undefined;
    const id = setInterval(() => tick((n) => n + 1), 50);
    return () => clearInterval(id);
  }, [running]);
  if (startAt == null) return { running: false, seconds: null };
  return { running, seconds: ((stop ?? performance.now()) - startAt) / 1000 };
}

// Where each step sits on the turn's timeline (seconds after the person stopped talking)
function lanes(turn) {
  const u = turn?.user || {};
  const a = turn?.agent || {};
  const out = [];
  if (u.stt_s != null) out.push({ key: "heard", label: "Heard", from: 0, to: u.stt_s, kind: "line" });
  if (u.eot_s != null) out.push({ key: "turn", label: "Turn over", from: 0, to: u.eot_s, kind: "wait" });
  if (a.e2e_s != null) {
    const toVoice = a.ttfs_s ?? a.ttft_s ?? 0;
    const llmFrom = Math.max(0, a.e2e_s - toVoice - (a.ttfb_s ?? 0));
    if (a.ttft_s != null) out.push({ key: "think", label: "Thinking", from: llmFrom, to: llmFrom + a.ttft_s, tail: llmFrom + toVoice, kind: "llm" });
    if (a.ttfb_s != null) out.push({ key: "voice", label: "Voice", from: a.e2e_s - a.ttfb_s, to: a.e2e_s, kind: "voice" });
  }
  return out;
}

function useOpen() {
  // open unless closed before; on a phone it starts closed (the transcript needs the room)
  const [open, setOpen] = useState(() => {
    let saved = null;
    try { saved = localStorage.getItem(OPEN_KEY); } catch (e) { /* storage blocked */ }
    return saved === null ? window.innerWidth > 760 : saved !== "0";
  });
  const toggle = () => setOpen((o) => { try { localStorage.setItem(OPEN_KEY, o ? "0" : "1"); } catch (e) { /* this visit only */ } return !o; });
  return [open, toggle];
}

export default function Timing({ turns, pending, agentState, live }) {
  const watch = useStopwatch(live ? pending?.user?.at ?? null : null, agentState);
  const [open, toggleOpen] = useOpen();
  const waiting = live && watch.running;
  const speakingNow = live && agentState === "speaking";
  const current = pending || turns[turns.length - 1] || null;
  const u = current?.user || {};
  const a = current?.agent || {};
  const tools = current?.tools || [];
  const inProgress = Boolean(pending) || waiting;

  // she is audible but her own timings come only when her line ends: until then the page's clock stands in
  const heardHer = a.e2e_s == null && pending && watch.seconds != null && !watch.running;
  const yourTurn = live && agentState === "listening" && !pending;
  const nodes = [
    { key: "you", Icon: Mic, label: "You", value: yourTurn ? "your turn" : "0 s", state: yourTurn ? "active" : current ? "done" : "idle" },
    { key: "heard", Icon: Ear, label: "Heard", sub: tagged("STT", u.stt_model), value: sec(u.stt_s), state: u.stt_s != null ? "done" : "idle" },
    { key: "turn", Icon: Hourglass, label: "Turn over", sub: "EOU", value: sec(u.eot_s), state: u.eot_s != null ? "done" : "idle" },
    ...tools.map((t, i) => {
      const [Icon, label] = TOOLS[t.tool] || [Wrench, t.tool];
      return { key: `tool${i}`, Icon, label, value: sec(t.took_s), state: "done", tool: true };
    }),
    { key: "think", Icon: Brain, label: "Thinking", sub: tagged("TTFT", a.llm_model), state: a.ttft_s != null || heardHer ? "done" : waiting ? "active" : "idle",
      value: a.ttft_s != null ? sec(a.ttft_s) : waiting ? "thinking…" : heardHer ? "…" : "–" },
    { key: "voice", Icon: AudioLines, label: "Voice", sub: tagged("TTFB", a.tts_model), value: a.ttfb_s != null ? sec(a.ttfb_s) : heardHer ? "…" : "–",
      state: a.ttfb_s != null || heardHer ? "done" : "idle" },
    { key: "giulia", Icon: Volume2, label: "Giulia speaks", sub: "E2E", end: true,
      value: a.e2e_s != null ? sec(a.e2e_s) : heardHer ? `≈ ${(watch.seconds + (u.eot_s ?? 0)).toFixed(2)} s` : "–",
      state: a.e2e_s != null || heardHer ? "done" : speakingNow && pending ? "active" : "idle" },
  ];

  // the caller's wait: the server's measure once it arrives; before that turn-over + the page's clock
  const total = a.e2e_s ?? (pending && watch.seconds != null ? watch.seconds + (u.eot_s ?? 0) : null);
  const heardWait = heardHer ? watch.seconds : null;
  return (
    <section className="timing" data-open={open} aria-label="How long each step of Giulia's reply took">
      <div className="timing-head">
        <div className="timing-total" aria-live="polite">
          <span className="timing-label">{inProgress ? "This reply" : turns.length ? `Reply ${turns[turns.length - 1].n}` : "Reply timing"}</span>
          <span className="timing-value" data-over={total != null && total > TARGET_S ? "true" : "false"}>
            {total != null ? `${total.toFixed(2)} s` : "–"}{inProgress && !a.e2e_s && total != null ? "…" : ""}
          </span>
          <span className="timing-note">
            {total == null ? "each step appears here as she answers"
              : heardWait != null ? `she was audible ${heardWait.toFixed(2)} s after your turn ended · exact steps when her line ends`
              : total <= TARGET_S ? `within the ${TARGET_S} s target` : `${(total - TARGET_S).toFixed(2)} s over the ${TARGET_S} s target`}
          </span>
        </div>
        <div className="timing-side">
          <History turns={turns} />
          <button type="button" className="icon-btn timing-toggle" onClick={toggleOpen} aria-expanded={open} aria-label={open ? "Hide the step-by-step timing" : "Show the step-by-step timing"}><ChevronDown aria-hidden="true" /></button>
        </div>
      </div>
      {open && <>
      <ol className="flow">
        {nodes.map((n) => (
          <li key={n.key} className={`node${n.tool ? " tool" : ""}${n.end ? " end" : ""}`} data-state={n.state}>
            <span className="node-dot"><n.Icon aria-hidden="true" /></span>
            <span className="node-label">{n.label}</span>
            <span className="node-value">{n.value}</span>
            {n.sub && <span className="node-sub">{n.sub}</span>}
          </li>
        ))}
      </ol>
      <Waterfall turn={current} liveWait={waiting ? { from: u.eot_s ?? 0, seconds: watch.seconds } : null} />
      <Metrics turns={turns} current={current} heardAfter={heardHer ? watch.seconds + (u.eot_s ?? 0) : null} />
      </>}
    </section>
  );
}

function Waterfall({ turn, liveWait }) {
  const rows = lanes(turn);
  if (liveWait && liveWait.seconds != null) {
    rows.push({ key: "live", label: "Thinking", from: liveWait.from, to: liveWait.from + liveWait.seconds, kind: "llm live" });
  }
  const end = Math.max(TARGET_S + 0.5, ...rows.map((r) => r.tail ?? r.to), turn?.agent?.e2e_s ?? 0);
  const scale = Math.ceil(end * 2) / 2; // round up to the next half second
  const frac = (v) => Math.min(Math.max(v, 0), scale) / scale;
  const pct = (v) => `${100 * frac(v)}%`;
  const ticks = [];
  for (let t = 0; t <= scale + 1e-9; t += scale > 4 ? 1 : 0.5) ticks.push(t);
  return (
    <div className="waterfall" aria-hidden={rows.length === 0}>
      <div className="wf-plot">
        <span className="wf-target" style={{ "--x": frac(TARGET_S) }}><span>{TARGET_S} s target</span></span>
        {turn?.agent?.e2e_s != null && <span className="wf-mark" style={{ "--x": frac(turn.agent.e2e_s) }} title="Giulia audible" />}
        {rows.length === 0 ? <div className="wf-empty">The timeline of her next reply will draw here.</div> : rows.map((r) => (
          <div className="wf-row" key={r.key}>
            <span className="wf-name">{r.label}</span>
            <span className="wf-track">
              {r.tail != null && r.tail > r.to && <span className="wf-bar tail" style={{ left: pct(r.to), width: `calc(${pct(r.tail)} - ${pct(r.to)})` }} />}
              <span className={`wf-bar ${r.kind}`} style={{ left: pct(r.from), width: `calc(${pct(r.to)} - ${pct(r.from)})` }} />
            </span>
          </div>
        ))}
      </div>
      <div className="wf-axis">{ticks.map((t) => <span key={t} style={{ left: pct(t) }}>{t === 0 ? "0" : `${t} s`}</span>)}</div>
    </div>
  );
}

// The standard voice-AI numbers: this reply's (the person's part shows as soon as their turn ends), and the call's
// median and 95th percentile over every reply so far. heardAfter: the page's own E2E while her line still plays.
function Metrics({ turns, current, heardAfter }) {
  const now = { ...(current?.user || {}), ...(current?.agent || {}) };
  return (
    <dl className="metrics" aria-label="Voice AI metrics: this reply, and the call's median and 95th percentile">
      {METRICS.map((m) => {
        const values = turns.map((t) => (m.user ? t.user : t.agent)?.[m.field]).filter((v) => v != null);
        const p50 = percentile(values, 0.5);
        return (
          <div className="metric" key={m.key} title={`${m.abbr} · ${m.name}: ${m.what}`}>
            <dt><abbr>{m.abbr}</abbr><span>{m.name}</span></dt>
            <dd className="metric-now">{m.key === "e2e" && now.e2e_s == null && heardAfter != null ? `≈ ${heardAfter.toFixed(2)} s` : metricValue(m, now[m.field])}</dd>
            <dd className="metric-call">{values.length === 0 ? "call: –"
              : m.unit ? `call p50 ${metricValue(m, p50)}`
              : `p50 ${metricValue(m, p50, false)} · p95 ${metricValue(m, percentile(values, 0.95))}`}</dd>
          </div>
        );
      })}
    </dl>
  );
}

function History({ turns }) {
  const last = turns.slice(-14);
  if (last.length === 0) return null;
  const values = last.map((t) => t.agent?.e2e_s).filter((v) => v != null);
  const sorted = [...values].sort((x, y) => x - y);
  const median = sorted.length ? sorted[Math.floor((sorted.length - 1) / 2)] : null;
  const top = Math.max(3, ...values);
  return (
    <div className="history" title="Every reply so far: how long the caller waited">
      <div className="history-bars">
        <span className="history-target" style={{ bottom: `${(100 * TARGET_S) / top}%` }} />
        {last.map((t, i) => (
          <span key={t.n} className={`history-bar${i === last.length - 1 ? " latest" : ""}${t.agent?.interrupted ? " cut" : ""}`}
            style={{ height: `${Math.max(6, (100 * (t.agent?.e2e_s || 0)) / top)}%` }} title={`Reply ${t.n}: ${sec(t.agent?.e2e_s)}`} />
        ))}
      </div>
      <span className="history-note">{values.length} {values.length === 1 ? "reply" : "replies"}{median != null ? ` · median ${median.toFixed(2)} s` : ""}</span>
    </div>
  );
}
