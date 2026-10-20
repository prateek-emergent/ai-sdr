import { useEffect, useState } from "react";

// Shared by the Talk page (App.js) and the Quality page (Quality.js).
export const API = process.env.REACT_APP_BACKEND_URL;
const THEME_KEY = "giulia-theme"; // also read by the inline script in public/index.html, before first paint

// Light or dark: the system's choice until the toggle is used, then the toggle's (remembered per browser)
export function useTheme() {
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

// Langfuse links for the page (GET /api/observability): the project's dashboard for members, and the base of a
// trace's address (test calls' traces open for anyone with the link). null until loaded or when tracing is off.
export function useLangfuse() {
  const [links, setLinks] = useState(null);
  useEffect(() => {
    fetch(`${API}/api/observability`).then((r) => (r.ok ? r.json() : {})).then((j) => setLinks(j.langfuse?.enabled ? j.langfuse : null)).catch(() => {});
  }, []);
  return links;
}

// The standard voice-AI numbers (20 Oct: "I want the metrics of TTFT, etc."), per reply, all from LiveKit's own turn
// metrics. field: the key in the Talk page's live timing events (backend voice/live.py); key: the Quality page's speed
// data (evals/quality.py SPEED). user: measured on the person's turn rather than Giulia's reply.
export const METRICS = [
  { key: "e2e", abbr: "E2E", name: "End-to-end", what: "you stop talking → Giulia is audible: the caller's wait", field: "e2e_s" },
  { key: "eou", abbr: "EOU", name: "End of turn", what: "you stop talking → your turn is judged over", field: "eot_s", user: true },
  { key: "stt", abbr: "STT", name: "Transcription", what: "you stop talking → your words are written down", field: "stt_s", user: true },
  { key: "ttft", abbr: "TTFT", name: "LLM first token", what: "the model is asked → its first token", field: "ttft_s" },
  { key: "ttfs", abbr: "TTFS", name: "LLM first sentence", what: "the model is asked → a whole sentence reaches the voice", field: "ttfs_s" },
  { key: "ttfb", abbr: "TTFB", name: "TTS first audio", what: "the voice gets the sentence → its first audio", field: "ttfb_s" },
  { key: "tps", abbr: "TPS", name: "LLM speed", what: "tokens per second while the model writes", field: "tps", unit: "tok/s" },
];

export const metricValue = (m, v, unit = true) => {
  if (v === null || v === undefined) return "–";
  if (m.unit) return unit ? `${Math.round(v)} ${m.unit}` : `${Math.round(v)}`;
  return unit ? `${v.toFixed(2)} s` : v.toFixed(2);
};

// q (0-1) of the values, interpolated like the backend's statistics.quantiles(method="inclusive")
export function percentile(values, q) {
  if (!values.length) return null;
  const s = [...values].sort((x, y) => x - y);
  const at = (s.length - 1) * q;
  const lo = Math.floor(at);
  return s[lo] + (s[Math.min(lo + 1, s.length - 1)] - s[lo]) * (at - lo);
}

// The models the Talk page offers (GET /api/llms): {default: the configured model's label, defaultModel: its id,
// llms: [...]}, and name(model id) for the pages that show a model by its id
export function useLlms() {
  const [data, setData] = useState({ default: null, defaultModel: null, llms: [] });
  useEffect(() => {
    fetch(`${API}/api/llms`).then((r) => (r.ok ? r.json() : {}))
      .then((j) => setData({ default: j.default || null, defaultModel: j.default_model || null, llms: j.llms || [] })).catch(() => {});
  }, []);
  const name = (model) => (model && model === data.defaultModel ? data.default : data.llms.find((m) => m.model === model)?.label) || model;
  return { ...data, name };
}
