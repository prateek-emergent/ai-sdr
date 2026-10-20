import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Check, Copy, Minus, Moon, RefreshCw, Sun, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { API, useLangfuse, useTheme } from "./shared";
import "./App.css";
import "./Quality.css";

// Quality (/quality, 20 Oct): how every call is graded, where Giulia slips, and how far the grader can be trusted.
// Reads the grades the backend's grader writes into each call report (ai_sdr/evals). Same token as /calls
// (transcripts are customer data); a link with ?token= opens it straight away, so the page can be shared.

const TOKEN_KEY = "aisdr_token";
const PERIODS = [[24, "24 h"], [168, "7 days"], [720, "30 days"]];
const CHANNELS = [["", "All calls"], ["web", "Browser"], ["phone", "Phone"], ["simulation", "Simulated"]];
export const CHECK_LABELS = {
  ai_disclosure: "Says she's an AI", allowed_claims: "Only approved claims", respects_no: "Respects a no",
  honest_actions: "Only claims what she did", listens_first: "Listens first", no_echo: "Doesn't echo",
  short_turns: "Short turns", spoken_register: "Sounds like a person", mood_match: "Matches their mood",
  problem_first: "Problems first", meeting_offer: "Offers the expert call", books_the_yes: "Books the yes",
  callback_done: "Books the callback", language: "Right language", clean_close: "Clean close",
};
const label = (key) => CHECK_LABELS[key] || key;
const pct = (v) => (v === null || v === undefined ? "–" : `${Math.round(100 * v)}%`);
const sec = (v) => (v === null || v === undefined ? "–" : `${Number(v).toFixed(2)} s`);
const when = (iso) => (iso ? new Date(iso).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–");

function useToken() {
  const [token, setToken] = useState(() => {
    const fromLink = new URLSearchParams(window.location.search).get("token");
    if (fromLink) {
      try { localStorage.setItem(TOKEN_KEY, fromLink); } catch (e) { /* this visit only */ }
      window.history.replaceState(null, "", window.location.pathname + window.location.hash); // keep it out of the address bar
      return fromLink;
    }
    try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
  });
  const save = (t) => { try { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ } setToken(t); };
  return [token, save];
}

async function api(path, token, options) {
  const r = await fetch(`${API}${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`, options);
  if (r.status === 404 && path.startsWith("/api/quality/summary")) throw new Error("wrong token");
  if (!r.ok) throw new Error(`the server answered ${r.status}`);
  return r.json();
}

export default function Quality() {
  const [theme, toggleTheme] = useTheme();
  const [token, setToken] = useToken();
  const langfuse = useLangfuse();
  const [copied, setCopied] = useState(false);
  useEffect(() => { document.title = "Giulia · Quality"; }, []);
  const share = async () => {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/quality?token=${encodeURIComponent(token)}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2400);
    } catch (e) { /* clipboard blocked */ }
  };
  return (
    <div className="talk quality">
      <div className="field" aria-hidden="true"><div className="light light-her" /><div className="light light-you" /></div>
      <header className="topbar">
        <div className="brand">
          <h1>Quality</h1>
          <span className="brand-sub">How Giulia's calls are graded</span>
        </div>
        <nav className="topbar-nav">
          <a className="nav-link" href="/">Talk</a>
          <a className="nav-link" href="/calls" target="_blank" rel="noreferrer">Calls<ArrowUpRight aria-hidden="true" /></a>
          {langfuse && <a className="nav-link" href={langfuse.dashboard_url} target="_blank" rel="noreferrer" title="Langfuse dashboard (team members sign in)">Langfuse<ArrowUpRight aria-hidden="true" /></a>}
          {token && <button type="button" className="nav-link" onClick={share} title="Anyone with this link can open this page">{copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}{copied ? "Link copied" : "Share link"}</button>}
          <button type="button" className="icon-btn" onClick={toggleTheme} aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
            {theme === "dark" ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
          </button>
        </nav>
      </header>
      {token ? <Board token={token} langfuse={langfuse} onWrongToken={() => setToken("")} /> : <Gate onToken={setToken} />}
    </div>
  );
}

function Gate({ onToken }) {
  const [v, setV] = useState("");
  return (
    <main className="q-gate glass">
      <h2>Call quality is for the team</h2>
      <p>Enter the access token (DEBUG_TOKEN in the backend's .env), or open a shared link.</p>
      <form onSubmit={(e) => { e.preventDefault(); if (v.trim()) onToken(v.trim()); }}>
        <input className="input" type="password" placeholder="Access token" aria-label="Access token" value={v} onChange={(e) => setV(e.target.value)} autoFocus />
        <button type="submit" className="btn btn-primary">Open</button>
      </form>
    </main>
  );
}

function Board({ token, langfuse, onWrongToken }) {
  const [hours, setHours] = useState(168);
  const [channel, setChannel] = useState("");
  const [check, setCheck] = useState("");
  const [data, setData] = useState(null);
  const [calls, setCalls] = useState(null);
  const [rubric, setRubric] = useState(null);
  const [open, setOpen] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(async () => {
    try {
      const q = `hours=${hours}${channel ? `&channel=${channel}` : ""}`;
      const [s, c] = await Promise.all([api(`/api/quality/summary?${q}`, token), api(`/api/quality/calls?${q}${check ? `&check=${check}` : ""}&limit=150`, token)]);
      setData(s); setCalls(c.calls); setError(null);
    } catch (e) {
      if (e.message === "wrong token") onWrongToken(); else setError(String(e.message || e));
    }
  }, [token, hours, channel, check]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [load]);
  useEffect(() => { const id = setInterval(load, 30000); return () => clearInterval(id); }, [load]);
  useEffect(() => { fetch(`${API}/api/quality/rubric`).then((r) => r.json()).then(setRubric).catch(() => {}); }, []);

  return (
    <main className="q-main">
      {error && <div className="alert" role="alert"><span>Couldn't load the grades: {error}</span></div>}
      <section className="q-panel glass">
        <div className="q-toolbar">
          <div className="segmented" role="radiogroup" aria-label="Period">
            {PERIODS.map(([h, name]) => (
              <label key={h}><input type="radio" name="period" checked={hours === h} onChange={() => setHours(h)} /><span>{name}</span></label>
            ))}
          </div>
          <div className="segmented" role="radiogroup" aria-label="Which calls">
            {CHANNELS.map(([value, name]) => (
              <label key={value || "all"}><input type="radio" name="channel" checked={channel === value} onChange={() => setChannel(value)} /><span>{name}</span></label>
            ))}
          </div>
          <button type="button" className="icon-btn q-refresh" onClick={load} aria-label="Refresh"><RefreshCw aria-hidden="true" /></button>
        </div>
        {data ? <Overview data={data} calls={calls} /> : <p className="q-loading">Loading the grades…</p>}
      </section>

      {data && (
        <div className="q-columns">
          <section className="q-panel glass" aria-labelledby="slips">
            <div className="q-head"><h2 id="slips">Where Giulia slips</h2><span className="q-hint">share of calls passing each check · click to see the calls</span></div>
            <Checks checks={data.checks} reviews={data.reviews} selected={check} onSelect={(k) => setCheck(k === check ? "" : k)} />
          </section>
          <div className="q-stack">
            <section className="q-panel glass" aria-labelledby="trust">
              <div className="q-head"><h2 id="trust">How the grader is doing</h2><span className="q-hint">check its verdicts from any call below</span></div>
              <GraderHealth data={data} />
            </section>
            <section className="q-panel glass" aria-labelledby="how">
              <div className="q-head"><h2 id="how">How the grader works</h2></div>
              <HowGraded rubric={rubric} />
            </section>
          </div>
        </div>
      )}

      <section className="q-panel glass" aria-labelledby="calls">
        <div className="q-head">
          <h2 id="calls">{check ? `Calls where "${label(check)}" failed` : "Calls"}</h2>
          {check && <button type="button" className="q-clear" onClick={() => setCheck("")}><X aria-hidden="true" />Show all calls</button>}
        </div>
        <CallList calls={calls} langfuse={langfuse} onOpen={setOpen} />
      </section>
      {open && <CallDrawer room={open} token={token} langfuse={langfuse} onClose={() => setOpen(null)} onChanged={load} />}
    </main>
  );
}

function Overview({ data, calls }) {
  const r = data.reviews || {};
  const tiles = [
    ["Calls graded", `${data.graded}`, `of ${data.calls}${data.skipped ? ` · ${data.skipped} with nobody speaking` : ""}`],
    ["Checks passed", pct(data.score), "average across graded calls"],
    ["Broke a must-rule", `${data.must_failed_calls}`, data.must_failed_calls === 1 ? "call (AI disclosure, claims, a no, honesty)" : "calls (AI disclosure, claims, a no, honesty)"],
    ["Typical reply", sec(data.reply_s_p50), "median wait for her answer"],
    ["People agree with the grader", pct(r.rate), r.reviewed ? `${r.agree} of ${r.reviewed} verdicts checked` : "no verdicts checked yet"],
  ];
  return (
    <>
      <div className="q-tiles">
        {tiles.map(([name, value, note]) => (
          <div className="q-tile" key={name}><span className="q-tile-name">{name}</span><span className="q-tile-value">{value}</span><span className="q-tile-note">{note}</span></div>
        ))}
      </div>
      <Timeline calls={calls} trend={data.trend} average={data.score} />
    </>
  );
}

// Every graded call in order, oldest left: bar height = share of checks passed; a call that broke a must-rule is an
// outlined bar (shape, not colour); the dashed line is the period's average. Days underneath.
function Timeline({ calls, trend, average }) {
  const graded = (calls || []).filter((c) => c.score != null).slice(0, 80).reverse();
  if (graded.length === 0) return null;
  return (
    <figure className="q-timeline">
      <div className="q-timeline-plot" role="img" aria-label={`Share of checks passed in each of the last ${graded.length} graded calls`}>
        {average != null && <span className="q-timeline-avg" style={{ bottom: `${100 * average}%` }}><span>average {pct(average)}</span></span>}
        {graded.map((c) => (
          <span key={c.room} className={`q-timeline-bar${c.must_failed.length ? " broke" : ""}`} style={{ height: `${Math.max(4, 100 * c.score)}%` }}
            title={`${when(c.started_at)} · ${pct(c.score)}${c.must_failed.length ? ` · broke ${c.must_failed.map(label).join(", ")}` : ""}`} />
        ))}
      </div>
      <figcaption>
        <span>{graded.length} graded calls, oldest first · outlined = broke a must-rule</span>
        {(trend || []).slice(-7).map((d) => <span key={d.day}>{new Date(`${d.day}T12:00:00`).toLocaleDateString([], { day: "numeric", month: "short" })}<b>{pct(d.score)}</b>{d.calls} calls</span>)}
      </figcaption>
    </figure>
  );
}

function Checks({ checks, reviews, selected, onSelect }) {
  const rows = Object.entries(checks || {}).sort(([, a], [, b]) => {
    if (a.pass_rate === null) return 1;
    if (b.pass_rate === null) return -1;
    return a.pass_rate - b.pass_rate;
  });
  return (
    <ol className="q-checks">
      {rows.map(([key, c]) => {
        const agree = reviews?.per_check?.[key];
        return (
          <li key={key}>
            <button type="button" className="q-check" data-selected={selected === key} onClick={() => onSelect(key)} disabled={!c.failed} title={c.question}>
              <span className="q-check-name">{label(key)}{c.must && <span className="q-must">must</span>}</span>
              <span className="q-meter" aria-hidden="true"><span style={{ width: `${100 * (c.pass_rate ?? 0)}%` }} /></span>
              <span className="q-check-value">{c.applied ? pct(c.pass_rate) : "n/a"}</span>
              <span className="q-check-note">{c.applied ? `${c.failed} of ${c.applied} failed` : "didn't come up"}{agree ? ` · people agree ${pct(agree.rate)}` : ""}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function HowGraded({ rubric }) {
  if (!rubric) return <p className="q-loading">Loading…</p>;
  return (
    <div className="q-how">
      <p>After every call, about 20 seconds after it ends, <b>{rubric.judge}</b> reads the whole transcript, Giulia's tool calls and how the call ended, and answers <b>{rubric.checks.length} checks</b> with pass, fail or n/a, a reason and her own words as evidence. The score is {rubric.score}. A failed <span className="q-must">must</span> check flags the call whatever its score.</p>
      <p>The checks come from her prompt (listen first, no echoing, spoken register) and from what made 1,016 human sales calls work or fail. Grader <b>{rubric.grader}</b>; scores also go onto the call's Langfuse trace.</p>
      <details>
        <summary>All {rubric.checks.length} checks</summary>
        <dl className="q-rubric">
          {rubric.checks.map((c) => <div key={c.key}><dt>{label(c.key)}{c.must && <span className="q-must">must</span>}</dt><dd>{c.question}</dd></div>)}
        </dl>
      </details>
      <details>
        <summary>Counted without a model</summary>
        <dl className="q-rubric">{rubric.counted.map((c) => <div key={c.key}><dt>{c.key.replace(/_/g, " ")}</dt><dd>{c.what}</dd></div>)}</dl>
      </details>
    </div>
  );
}

function GraderHealth({ data }) {
  const r = data.reviews || {};
  const g = data.regrades || {};
  const keys = Array.from(new Set([...Object.keys(r.per_check || {}), ...Object.keys(g.per_check || {})]));
  return (
    <>
      <div className="q-tiles q-tiles-4">
        <div className="q-tile"><span className="q-tile-name">Graded</span><span className="q-tile-value">{data.graded}</span><span className="q-tile-note">{data.ungraded ? `${data.ungraded} waiting` : "none waiting"}{data.skipped ? ` · ${data.skipped} skipped` : ""}</span></div>
        <div className="q-tile"><span className="q-tile-name">Agrees with people</span><span className="q-tile-value">{pct(r.rate)}</span><span className="q-tile-note">{r.reviewed ? `${r.reviewed} verdicts checked by a person` : "check a few verdicts below"}</span></div>
        <div className="q-tile"><span className="q-tile-name">Consistent with itself</span><span className="q-tile-value">{pct(g.rate)}</span><span className="q-tile-note">{g.compared ? `same verdict on ${g.same} of ${g.compared} when graded again` : "grade a call again to measure it"}</span></div>
        <div className="q-tile"><span className="q-tile-name">Time per grade</span><span className="q-tile-value">{data.grader?.took_s_p50 != null ? `${data.grader.took_s_p50.toFixed(0)} s` : "–"}</span><span className="q-tile-note">{(data.grader?.judges || []).join(", ") || "–"}</span></div>
      </div>
      {keys.length > 0 && (
        <table className="q-table">
          <thead><tr><th>Check</th><th>People agree</th><th>Same when graded again</th></tr></thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k}><td>{label(k)}</td>
                <td>{r.per_check?.[k] ? `${pct(r.per_check[k].rate)} of ${r.per_check[k].reviewed}` : "–"}</td>
                <td>{g.per_check?.[k] ? `${pct(g.per_check[k].rate)} of ${g.per_check[k].compared}` : "–"}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function CallList({ calls, langfuse, onOpen }) {
  if (!calls) return <p className="q-loading">Loading…</p>;
  if (calls.length === 0) return <p className="q-loading">No calls in this period.</p>;
  return (
    <ol className="q-calls">
      {calls.map((c) => (
        <li key={c.room} className="q-call">
          <button type="button" className="q-call-main" onClick={() => onOpen(c.room)}>
            <span className="q-call-when">{when(c.started_at)}<small>{c.channel}{c.language ? ` · ${c.language}` : ""}</small></span>
            <span className="q-call-score">
              {c.graded && c.score != null ? <><span className="q-meter small" aria-hidden="true"><span style={{ width: `${100 * c.score}%` }} /></span>{pct(c.score)}</>
                : <span className="q-muted">{c.skipped ? "nobody spoke" : "not graded yet"}</span>}
            </span>
            <span className="q-call-fails">
              {c.must_failed.map((k) => <span key={k} className="q-tag must">{label(k)}</span>)}
              {c.failed.filter((k) => !c.must_failed.includes(k)).map((k) => <span key={k} className="q-tag">{label(k)}</span>)}
            </span>
            <span className="q-call-meta">{c.outcome ? c.outcome.replace(/_/g, " ") : "–"}<small>reply {sec(c.e2e_p50)}{c.reviewed ? ` · ${c.reviewed} checked` : ""}</small></span>
          </button>
          {langfuse && c.trace_id ? <a className="q-trace" href={`${langfuse.trace_url_prefix}${c.trace_id}`} target="_blank" rel="noreferrer" aria-label="Open this call in Langfuse">Trace<ArrowUpRight aria-hidden="true" /></a>
            : <span className="q-trace-none" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

const VerdictIcon = ({ verdict }) => (verdict === "pass" ? <Check aria-hidden="true" /> : verdict === "fail" ? <X aria-hidden="true" /> : <Minus aria-hidden="true" />);

function CallDrawer({ room, token, langfuse, onClose, onChanged }) {
  const [call, setCall] = useState(null);
  const [error, setError] = useState(null);
  const [regrading, setRegrading] = useState(false);
  const [again, setAgain] = useState(null);
  const load = useCallback(() => api(`/api/quality/calls/${room}`, token).then(setCall).catch((e) => setError(String(e.message || e))), [room, token]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const regrade = async () => {
    setRegrading(true); setAgain(null);
    try { setAgain(await api(`/api/quality/calls/${room}/regrade`, token, { method: "POST" })); load(); onChanged(); }
    catch (e) { setError(String(e.message || e)); }
    setRegrading(false);
  };
  const g = call?.eval;
  return (
    <div className="q-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="q-drawer glass" role="dialog" aria-modal="true" aria-label={`Call ${room}`}>
        <div className="q-drawer-head">
          <div>
            <h2>{call ? when(call.started_at) : room}</h2>
            <span className="q-muted">{call ? `${call.channel}${call.language ? ` · ${call.language}` : ""} · ${call.outcome ? call.outcome.replace(/_/g, " ") : "no outcome"} · reply ${sec(call.e2e_p50)}` : "Loading…"}</span>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close"><X aria-hidden="true" /></button>
        </div>
        {error && <div className="alert" role="alert"><span>{error}</span></div>}
        {call && (
          <div className="q-drawer-body">
            <div className="q-drawer-actions">
              {g?.score != null && <span className="q-big">{pct(g.score)}<small>checks passed</small></span>}
              {langfuse && call.trace_id && <a className="btn btn-quiet" href={`${langfuse.trace_url_prefix}${call.trace_id}`} target="_blank" rel="noreferrer">Open in Langfuse<ArrowUpRight aria-hidden="true" /></a>}
              {g?.checks && <button type="button" className="btn btn-quiet" onClick={regrade} disabled={regrading}><RefreshCw aria-hidden="true" className={regrading ? "spin" : ""} />{regrading ? "Grading again…" : "Grade again"}</button>}
            </div>
            {again && (
              <p className="q-note">Graded again: same verdict on {again.same} of {again.total} checks{again.flipped.length ? `; changed: ${again.flipped.map(label).join(", ")}` : ""} · score {pct(again.original_score)} → {pct(again.score)}.</p>
            )}
            {!g && <p className="q-note">Not graded yet: the grader picks a call up about 20 seconds after it ends.</p>}
            {g?.skipped && <p className="q-note">Not graded: {g.skipped}.</p>}
            {g?.checks && (
              <>
                <h3>The verdicts</h3>
                <ol className="q-verdicts">
                  {Object.entries(g.checks).sort(([, a], [, b]) => ["fail", "pass", "n/a"].indexOf(a.verdict) - ["fail", "pass", "n/a"].indexOf(b.verdict)).map(([key, c]) => (
                    <Verdict key={key} room={room} token={token} check={key} c={c} must={(g.must_failed || []).includes(key) || ["ai_disclosure", "allowed_claims", "respects_no", "honest_actions"].includes(key)}
                      review={call.reviews?.[key]} onSaved={() => { load(); onChanged(); }} />
                  ))}
                </ol>
                {(g.notes?.worst_moment || g.notes?.fix) && (
                  <div className="q-notes">
                    {g.notes.worst_moment && <p><b>Worst moment.</b> {g.notes.worst_moment}</p>}
                    {g.notes.fix && <p><b>Suggested fix.</b> {g.notes.fix}</p>}
                  </div>
                )}
                {g.counted && (
                  <dl className="q-counted">
                    {[["Words per turn", g.counted.turn_words_avg], ["Long turns", g.counted.long_turns], ["Two-question turns", g.counted.multi_question_turns],
                      ["“Perfetto” & co.", g.counted.enthusiasm_words], ["“So…” starts", g.counted.echo_starts], ["Her share of words", g.counted.agent_talk_share != null ? pct(g.counted.agent_talk_share) : null],
                      ["Banned words", (g.counted.stock_phrases || []).join(", ") || "none"], ["Opener says AI", g.counted.opener_says_ai ? "yes" : "no"]].map(([k, v]) => (
                      <div key={k}><dt>{k}</dt><dd>{v ?? "–"}</dd></div>
                    ))}
                  </dl>
                )}
              </>
            )}
            <h3>The call</h3>
            <Transcript items={call.items} />
          </div>
        )}
      </aside>
    </div>
  );
}

function Verdict({ room, token, check, c, must, review, onSaved }) {
  const [mode, setMode] = useState(null); // null | "wrong"
  const [verdict, setVerdict] = useState(c.verdict === "fail" ? "pass" : "fail");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const send = async (agree) => {
    setSaving(true);
    try {
      await api(`/api/quality/calls/${room}/review`, token, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(agree ? { check, agree: true } : { check, agree: false, verdict, note }) });
      setMode(null); onSaved();
    } catch (e) { /* the next load shows the state */ }
    setSaving(false);
  };
  return (
    <li className="q-verdict" data-verdict={c.verdict}>
      <span className="q-verdict-icon"><VerdictIcon verdict={c.verdict} /></span>
      <div className="q-verdict-body">
        <span className="q-verdict-name">{label(check)}{must && <span className="q-must">must</span>}<span className="q-muted"> · {c.verdict}</span></span>
        <span className="q-verdict-reason">{c.reason}</span>
        {c.quote && <q className="q-quote">{c.quote}</q>}
        {review && <span className="q-reviewed">{review.agree ? "A person agreed" : `A person disagreed${review.verdict ? `: should be ${review.verdict}` : ""}${review.note ? ` (${review.note})` : ""}`}</span>}
        {mode === "wrong" && (
          <form className="q-review-form" onSubmit={(e) => { e.preventDefault(); send(false); }}>
            <div className="segmented small" role="radiogroup" aria-label="What it should be">
              {["pass", "fail", "n/a"].filter((v) => v !== c.verdict).map((v) => (
                <label key={v}><input type="radio" name={`v-${check}`} checked={verdict === v} onChange={() => setVerdict(v)} /><span>{v}</span></label>
              ))}
            </div>
            <input className="input small" placeholder="Why (optional)" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
            <button type="submit" className="btn btn-primary small" disabled={saving}>Save</button>
          </form>
        )}
      </div>
      {mode !== "wrong" && (
        <div className="q-verdict-review" role="group" aria-label={`Is the grader right about "${label(check)}"?`}>
          <button type="button" className="icon-btn" onClick={() => send(true)} disabled={saving} aria-label="The grader is right" title="The grader is right" data-on={review?.agree === true}><ThumbsUp aria-hidden="true" /></button>
          <button type="button" className="icon-btn" onClick={() => setMode("wrong")} disabled={saving} aria-label="The grader is wrong" title="The grader is wrong" data-on={review?.agree === false}><ThumbsDown aria-hidden="true" /></button>
        </div>
      )}
    </li>
  );
}

function Transcript({ items }) {
  const lines = useMemo(() => (items || []).map((it, i) => {
    if (it.type === "function_call") return { i, kind: "tool", text: `${it.name}(${it.arguments || ""})` };
    if (it.type === "function_call_output") return { i, kind: "result", text: String(it.output || "").slice(0, 240) };
    const text = (it.content || []).filter((x) => typeof x === "string").join(" ").trim();
    return text ? { i, kind: it.role === "user" ? "you" : "her", text, cut: it.interrupted } : null;
  }).filter(Boolean), [items]);
  return (
    <ol className="q-transcript">
      {lines.map((l) => (
        <li key={l.i} className={`q-line ${l.kind}`}>
          {l.kind === "tool" || l.kind === "result" ? <code>{l.kind === "tool" ? "→ " : "↳ "}{l.text}</code>
            : <><span className="who">{l.kind === "you" ? "Person" : "Giulia"}{l.cut ? " · cut off" : ""}</span><p className="bubble">{l.text}</p></>}
        </li>
      ))}
    </ol>
  );
}
