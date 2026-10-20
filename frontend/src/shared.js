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
