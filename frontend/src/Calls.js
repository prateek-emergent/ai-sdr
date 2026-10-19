import { useCallback, useEffect, useMemo, useState } from "react";

// Metrics page (/calls): every conversation with Giulia, browser demos and phone calls, with per-turn latency, the
// call's timeline, what the browser saw and the worker's log lines. Reads the call reports the voice worker writes
// at the end of every call. Protected by the debug token (transcripts are customer data).
const API = process.env.REACT_APP_BACKEND_URL;
const TARGET = { reply: [1.5, 2.5], opener: [3, 4] }; // green below the first number, amber below the second

function tone(v, [good, ok]) {
  if (v === null || v === undefined) return "#94a3b8";
  return v < good ? "#16a34a" : v < ok ? "#d97706" : "#dc2626";
}
const s = (v, d = 2) => (v === null || v === undefined ? "–" : `${Number(v).toFixed(d)}s`);
const when = (iso) => (iso ? new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "–");

async function get(path, token) {
  const r = await fetch(`${API}${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`);
  if (r.status === 404 && path.startsWith("/api/calls?")) throw new Error("wrong token");
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

export default function Calls() {
  const [token, setToken] = useState(localStorage.getItem("aisdr_token") || "");
  const [room, setRoom] = useState(window.location.hash.slice(1));
  useEffect(() => {
    const onHash = () => setRoom(window.location.hash.slice(1));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  if (!token) return <TokenGate onToken={(t) => { localStorage.setItem("aisdr_token", t); setToken(t); }} />;
  return (
    <div style={S.page}>
      <div style={S.head}>
        <a href="/calls#" style={S.brand}>Giulia · calls</a>
        <a href="/" style={S.link}>Talk to Giulia →</a>
        <button style={S.ghost} onClick={() => { localStorage.removeItem("aisdr_token"); setToken(""); }}>sign out</button>
      </div>
      {room ? <Detail room={room} token={token} /> : <List token={token} />}
    </div>
  );
}

function TokenGate({ onToken }) {
  const [v, setV] = useState("");
  return (
    <div style={{ ...S.page, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={S.card}>
        <div style={S.h2}>Call metrics</div>
        <p style={S.muted}>Enter the access token (AI_SDR_DEBUG_TOKEN in pipeline/.env).</p>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={S.input} type="password" value={v} onChange={(e) => setV(e.target.value)} onKeyDown={(e) => e.key === "Enter" && v && onToken(v)} />
          <button style={S.btn} onClick={() => v && onToken(v)}>Open</button>
        </div>
      </div>
    </div>
  );
}

function List({ token }) {
  const [calls, setCalls] = useState([]);
  const [stats, setStats] = useState(null);
  const [hours, setHours] = useState(24);
  const [channel, setChannel] = useState("");
  const [auto, setAuto] = useState(true);
  const [error, setError] = useState(null);
  const load = useCallback(async () => {
    try {
      const [l, st] = await Promise.all([get(`/api/calls?limit=100${channel ? `&channel=${channel}` : ""}`, token), get(`/api/calls/stats?hours=${hours}`, token)]);
      setCalls(l.calls); setStats(st); setError(null);
    } catch (e) { setError(String(e.message || e)); }
  }, [token, hours, channel]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!auto) return undefined;
    const id = setInterval(load, 15000);
    return () => clearInterval(id);
  }, [auto, load]);

  return (
    <>
      {error && <div style={S.error}>Couldn't load: {error}</div>}
      <div style={S.toolbar}>
        <select style={S.select} value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          <option value={24}>last 24 hours</option><option value={168}>last 7 days</option><option value={720}>last 30 days</option>
        </select>
        <select style={S.select} value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="">all channels</option><option value="web">browser</option><option value="phone">phone</option>
        </select>
        <label style={S.muted}><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> refresh every 15 s</label>
        <button style={S.ghost} onClick={load}>refresh now</button>
      </div>
      {stats && (
        <div style={S.tiles}>
          <Tile label="calls" value={stats.calls} />
          <Tile label="typical reply (median of calls)" value={s(stats.per_call_e2e_p50?.p50)} color={tone(stats.per_call_e2e_p50?.p50, TARGET.reply)} />
          <Tile label="slow calls' reply (p95)" value={s(stats.per_call_e2e_p50?.p95)} color={tone(stats.per_call_e2e_p50?.p95, TARGET.reply)} />
          <Tile label="dead-air turns (> 5 s)" value={stats.dead_air_turns} color={stats.dead_air_turns ? "#dc2626" : "#16a34a"} />
          <Tile label="errors" value={stats.errors} color={stats.errors ? "#d97706" : "#16a34a"} />
          <Tile label="hidden task failures" value={stats.task_failures} color={stats.task_failures ? "#dc2626" : "#16a34a"} />
          <Tile label="turn model fell back" value={stats.turn_detector_fallbacks} color={stats.turn_detector_fallbacks ? "#d97706" : "#16a34a"} />
        </div>
      )}
      {stats && Object.keys(stats.close_reasons || {}).length > 0 && (
        <div style={{ ...S.muted, margin: "4px 0 14px" }}>How calls ended: {Object.entries(stats.close_reasons).map(([k, v]) => `${k.replace("/None", "")} ${v}`).join(" · ")}</div>
      )}
      <div style={S.tableWrap}>
        <table style={S.table}>
          <thead><tr>{["when", "channel", "length", "turns", "opener", "reply p50", "p95", "max", "dead air", "stuck", "errors", "ended by", "outcome", "version"].map((h) => <th key={h} style={S.th}>{h}</th>)}</tr></thead>
          <tbody>
            {calls.map((c) => {
              const m = c.summary || {};
              return (
                <tr key={c.room} style={S.tr} onClick={() => { window.location.hash = c.room; }}>
                  <td style={S.td}>{when(c.started_at)}</td>
                  <td style={S.td}>{c.channel === "phone" ? "📞 phone" : "🌐 browser"}</td>
                  <td style={S.td}>{c.duration_s ? `${Math.round(c.duration_s)}s` : "–"}</td>
                  <td style={S.td}>{m.turns ?? "–"}</td>
                  <td style={{ ...S.td, color: tone(m.opener_audio_s, TARGET.opener) }}>{s(m.opener_audio_s)}</td>
                  <td style={{ ...S.td, color: tone(m.e2e_p50, TARGET.reply), fontWeight: 600 }}>{s(m.e2e_p50)}</td>
                  <td style={{ ...S.td, color: tone(m.e2e_p95, TARGET.reply) }}>{s(m.e2e_p95)}</td>
                  <td style={{ ...S.td, color: tone(m.e2e_max, TARGET.reply) }}>{s(m.e2e_max)}</td>
                  <td style={{ ...S.td, color: m.dead_air_turns ? "#dc2626" : "#94a3b8" }}>{m.dead_air_turns ?? "–"}</td>
                  <td style={{ ...S.td, color: m.agent_mid_line_stops ? "#dc2626" : "#94a3b8" }} title="times Giulia went quiet mid-line">{m.agent_mid_line_stops ?? "–"}</td>
                  <td style={{ ...S.td, color: (m.errors || m.task_failures) ? "#dc2626" : "#94a3b8" }}>{(m.errors || 0) + (m.task_failures || 0)}</td>
                  <td style={S.td}>{closeLabel(c.close)}</td>
                  <td style={S.td}>{c.extra?.disposition || "–"}</td>
                  <td style={{ ...S.td, ...S.mono }}>{c.version}</td>
                </tr>
              );
            })}
            {calls.length === 0 && <tr><td style={S.td} colSpan={14}>No calls yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

function closeLabel(close) {
  if (!close) return "–";
  if (close.requested) return close.requested.replace("end_call:", "Giulia: ");
  return { participant_disconnected: "person hung up", user_initiated: "ended", error: "⚠ error", job_shutdown: "server shutdown" }[close.reason] || close.reason;
}

function Tile({ label, value, color }) {
  return <div style={S.tile}><div style={{ ...S.tileValue, color: color || "#0f172a" }}>{value ?? "–"}</div><div style={S.tileLabel}>{label}</div></div>;
}

const text = (item) => (item.content || []).map((c) => (typeof c === "string" ? c : "")).join(" ");

function Detail({ room, token }) {
  const [r, setR] = useState(null);
  const [error, setError] = useState(null);
  const [logLevel, setLogLevel] = useState("INFO");
  const [logQuery, setLogQuery] = useState("");
  useEffect(() => {
    setR(null);
    get(`/api/calls/${room}/report`, token).then(setR).catch((e) => setError(String(e.message || e)));
  }, [room, token]);
  const items = useMemo(() => (r?.livekit?.chat_history?.items || []), [r]);
  if (error) return <div style={S.error}>Couldn't load {room}: {error === "404" ? "no report (yet) for this call" : error}</div>;
  if (!r) return <div style={S.muted}>Loading {room}…</div>;
  const m = r.summary || {};
  const startup = m.startup || {};
  const prompt = items.find((i) => i.type === "agent_config_update")?.instructions;
  const logs = (r.logs || []).filter((l) => (logLevel === "INFO" || l.level !== "INFO")
    && (!logQuery || `${l.logger} ${l.msg}`.toLowerCase().includes(logQuery.toLowerCase())));
  return (
    <>
      <a href="/calls#" style={S.link}>← all calls</a>
      <div style={S.h2}>{r.channel === "phone" ? "📞" : "🌐"} {when(r.started_at)} · {Math.round(r.duration_s || 0)}s · {closeLabel(r.close)}{r.extra?.disposition ? ` · outcome: ${r.extra.disposition}` : ""}</div>
      <div style={S.muted}>{r.room} · {r.agent_name} · code {r.version} · language {r.extra?.language || r.config?.language} · STT {r.config?.stt} · voice {(r.config?.tts_chain || []).join(" → ")} · LLM {(r.config?.llm_routes || []).join(" → ")} · turn model {r.turn_detector_used}</div>

      <div style={S.tiles}>
        <Tile label="opener audio" value={s(m.opener_audio_s)} color={tone(m.opener_audio_s, TARGET.opener)} />
        <Tile label="reply p50" value={s(m.e2e_p50)} color={tone(m.e2e_p50, TARGET.reply)} />
        <Tile label="reply p95" value={s(m.e2e_p95)} color={tone(m.e2e_p95, TARGET.reply)} />
        <Tile label="reply max" value={s(m.e2e_max)} color={tone(m.e2e_max, TARGET.reply)} />
        <Tile label="LLM first word p50 / p95" value={`${s(m.llm_ttft_p50)} / ${s(m.llm_ttft_p95)}`} />
        <Tile label="voice first audio p50" value={s(m.tts_ttfb_p50)} />
        <Tile label="end-of-turn wait p50 / p95" value={`${s(m.eot_p50)} / ${s(m.eot_p95)}`} />
        <Tile label="dead-air turns" value={m.dead_air_turns} color={m.dead_air_turns ? "#dc2626" : "#16a34a"} />
        <Tile label="errors · task failures" value={`${m.errors || 0} · ${m.task_failures || 0}`} color={(m.errors || m.task_failures) ? "#dc2626" : "#16a34a"} />
        <Tile label="stopped mid-line (longest pause)" value={`${m.agent_mid_line_stops ?? 0}${m.agent_pause_max_s ? ` (${s(m.agent_pause_max_s)})` : ""}`} color={m.agent_mid_line_stops ? "#dc2626" : "#16a34a"} />
        <Tile label="false interruptions" value={m.false_interruptions ?? 0} color={m.false_interruptions ? "#d97706" : "#16a34a"} />
        <Tile label="process freezes (worst)" value={`${m.stalls ?? 0}${m.stall_worst_ms ? ` (${m.stall_worst_ms} ms, cpu ${m.stall_worst_cpu_ms} / gc ${m.stall_worst_gc_ms})` : ""}`} color={m.stall_worst_ms > 200 ? "#d97706" : "#16a34a"} />
      </div>
      {m.transport && <div style={S.muted}>Media path to LiveKit: {["publisher", "subscriber"].map((side) => { const x = m.transport[side] || {}; return `${side === "publisher" ? "Giulia → LiveKit" : "caller → Giulia"}: ${x.local || "?"}/${x.remote || "?"} ${x.protocol || ""}${x.relay_protocol ? ` via relay ${x.relay_protocol}` : ""}, RTT ${x.rtt_ms ?? "?"} ms${x.in_jitter_ms !== undefined ? `, jitter ${x.in_jitter_ms} ms, lost ${x.in_lost}/${x.in_packets}` : ""}${x.out_fraction_lost !== undefined ? `, loss ${(100 * x.out_fraction_lost).toFixed(1)}%` : ""}`; }).join(" · ")}</div>}
      {Object.keys(startup).length > 0 && <div style={S.muted}>Before the session started: {Object.entries(startup).map(([k, v]) => `${k.replace(/_s$/, "").replace(/_/g, " ")} ${s(v, 3)}`).join(" · ")}</div>}

      <Section title="Conversation (latency per turn)">
        {items.filter((i) => i.type === "message" || i.type === "function_call" || i.type === "function_call_output").map((i) => <Turn key={i.id} item={i} />)}
      </Section>

      {(r.errors?.length > 0 || r.task_failures?.length > 0) && (
        <Section title="Errors">
          {[...(r.errors || []), ...(r.task_failures || [])].map((e, k) => <pre key={k} style={S.pre}>{JSON.stringify(e, null, 1)}</pre>)}
        </Section>
      )}

      <Section title="Timeline (call events)">
        <table style={S.table}><tbody>
          {(r.events || []).map((e, k) => (
            <tr key={k}><td style={{ ...S.td, ...S.mono, width: 70 }}>{e.t.toFixed(2)}s</td><td style={{ ...S.td, width: 160 }}>{e.kind}</td>
              <td style={{ ...S.td, ...S.mono }}>{Object.entries(e).filter(([k2]) => !["t", "kind"].includes(k2)).map(([k2, v]) => `${k2}=${typeof v === "object" ? JSON.stringify(v) : v}`).join("  ")}</td></tr>
          ))}
        </tbody></table>
      </Section>

      <Section title={`What the browser saw (${(r.client_events || []).length})`}>
        {(r.client_events || []).length === 0 ? <div style={S.muted}>No browser events (phone call, an old page, or the probe).</div> : (
          <table style={S.table}><tbody>
            {r.client_events.map((e, k) => (
              <tr key={k}><td style={{ ...S.td, ...S.mono, width: 80 }}>{(e.t_ms / 1000).toFixed(2)}s</td><td style={{ ...S.td, width: 160 }}>{e.kind}</td>
                <td style={{ ...S.td, ...S.mono }}>{Object.entries(e).filter(([k2]) => !["t_ms", "kind", "at", "received_at"].includes(k2)).map(([k2, v]) => `${k2}=${typeof v === "object" ? JSON.stringify(v) : v}`).join("  ")}</td></tr>
            ))}
          </tbody></table>
        )}
      </Section>

      <Section title={`Logs (${(r.logs || []).length}${r.logs_dropped ? `, ${r.logs_dropped} more not kept` : ""})`}>
        <div style={S.toolbar}>
          <select style={S.select} value={logLevel} onChange={(e) => setLogLevel(e.target.value)}>
            <option value="INFO">info and up</option><option value="WARNING">warnings and errors</option>
          </select>
          <input style={{ ...S.input, maxWidth: 320 }} placeholder="search logs" value={logQuery} onChange={(e) => setLogQuery(e.target.value)} />
        </div>
        <div style={S.logBox}>
          {logs.map((l, k) => (
            <div key={k} style={{ ...S.mono, color: l.level === "ERROR" || l.level === "CRITICAL" ? "#f87171" : l.level === "WARNING" ? "#fbbf24" : "#cbd5e1" }}>
              {l.t.toFixed(2).padStart(7)}s {l.level.padEnd(7)} {l.logger}: {l.msg}
            </div>
          ))}
          {logs.length === 0 && <div style={{ color: "#94a3b8" }}>No log lines{r.logs ? " match" : " (report from before logs were captured)"}.</div>}
        </div>
      </Section>

      <Section title="Settings used for this call" collapsed>
        <pre style={S.pre}>{JSON.stringify(r.config, null, 1)}</pre>
      </Section>
      {prompt && <Section title="Instructions Giulia had" collapsed><pre style={S.pre}>{prompt}</pre></Section>}
    </>
  );
}

function Turn({ item }) {
  if (item.type === "function_call") {
    return <div style={S.tool}>🔧 {item.name}({item.arguments})</div>;
  }
  if (item.type === "function_call_output") {
    return <div style={{ ...S.tool, color: item.is_error ? "#dc2626" : "#64748b" }}>↳ {String(item.output || "").slice(0, 300)}</div>;
  }
  const m = item.metrics || {};
  const user = item.role === "user";
  const chips = user
    ? [["end-of-turn wait", m.end_of_turn_delay], ["transcript", m.transcription_delay]]
    : [["reply", m.e2e_latency], ["LLM first word", m.llm_node_ttft], ["voice first audio", m.tts_node_ttfb]];
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: user ? "flex-end" : "flex-start", marginBottom: 10 }}>
      <div style={{ ...S.bubble, background: user ? "#e0f2fe" : "#fef3c7" }}>
        <span style={S.who}>{user ? "Person" : "Giulia"}{item.interrupted ? " · interrupted" : ""}</span>{text(item)}
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 3 }}>
        {chips.filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => (
          <span key={k} style={{ ...S.chip, color: k === "reply" ? tone(v, TARGET.reply) : "#475569" }}>{k} {s(v)}</span>
        ))}
      </div>
    </div>
  );
}

function Section({ title, children, collapsed }) {
  const [open, setOpen] = useState(!collapsed);
  return (
    <div style={S.section}>
      <div style={S.sectionTitle} onClick={() => setOpen(!open)}>{open ? "▾" : "▸"} {title}</div>
      {open && children}
    </div>
  );
}

const S = {
  page: { minHeight: "100vh", background: "#f1f5f9", padding: "20px 28px", fontFamily: "Inter, system-ui, sans-serif", color: "#0f172a" },
  head: { display: "flex", alignItems: "center", gap: 16, marginBottom: 16 },
  brand: { fontWeight: 700, fontSize: 20, color: "#0f172a", textDecoration: "none" },
  link: { color: "#2563eb", textDecoration: "none", fontSize: 14 },
  ghost: { marginLeft: "auto", background: "transparent", border: "1px solid #cbd5e1", borderRadius: 8, padding: "6px 10px", cursor: "pointer", fontSize: 13 },
  card: { background: "#fff", borderRadius: 14, padding: 24, width: 380, boxShadow: "0 10px 30px rgba(0,0,0,.08)" },
  h2: { fontSize: 18, fontWeight: 700, margin: "10px 0 4px" },
  muted: { color: "#64748b", fontSize: 13 },
  input: { flex: 1, padding: "8px 10px", borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 14 },
  btn: { padding: "8px 14px", borderRadius: 8, border: 0, background: "#0f172a", color: "#fff", cursor: "pointer" },
  select: { padding: "6px 8px", borderRadius: 8, border: "1px solid #cbd5e1", fontSize: 13, background: "#fff" },
  toolbar: { display: "flex", gap: 12, alignItems: "center", margin: "8px 0 12px", flexWrap: "wrap" },
  error: { background: "#fef2f2", border: "1px solid #fecaca", color: "#991b1b", borderRadius: 10, padding: "10px 12px", margin: "8px 0" },
  tiles: { display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(150px,1fr))", gap: 10, margin: "12px 0" },
  tile: { background: "#fff", borderRadius: 12, padding: "12px 14px", border: "1px solid #e2e8f0" },
  tileValue: { fontSize: 20, fontWeight: 700 },
  tileLabel: { fontSize: 12, color: "#64748b", marginTop: 2 },
  tableWrap: { background: "#fff", borderRadius: 12, border: "1px solid #e2e8f0", overflowX: "auto" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13 },
  th: { textAlign: "left", padding: "8px 10px", color: "#64748b", fontWeight: 600, borderBottom: "1px solid #e2e8f0", whiteSpace: "nowrap" },
  tr: { cursor: "pointer" },
  td: { padding: "7px 10px", borderBottom: "1px solid #f1f5f9", whiteSpace: "nowrap", verticalAlign: "top" },
  mono: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12 },
  section: { background: "#fff", borderRadius: 12, border: "1px solid #e2e8f0", padding: "12px 14px", margin: "12px 0" },
  sectionTitle: { fontWeight: 700, fontSize: 14, marginBottom: 10, cursor: "pointer", userSelect: "none" },
  bubble: { padding: "9px 12px", borderRadius: 12, fontSize: 14, lineHeight: 1.4, maxWidth: "75%" },
  who: { display: "block", fontSize: 11, fontWeight: 700, color: "#64748b", marginBottom: 2 },
  chip: { fontSize: 11, background: "#f1f5f9", borderRadius: 999, padding: "2px 8px" },
  tool: { fontFamily: "ui-monospace, Menlo, monospace", fontSize: 12, color: "#7c3aed", margin: "2px 0 8px 8px" },
  pre: { background: "#0f172a", color: "#e2e8f0", borderRadius: 8, padding: 12, fontSize: 12, overflowX: "auto", whiteSpace: "pre-wrap", maxHeight: 420 },
  logBox: { background: "#0f172a", borderRadius: 8, padding: 10, maxHeight: 460, overflowY: "auto", whiteSpace: "pre-wrap" },
};
