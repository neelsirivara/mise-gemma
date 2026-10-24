// Tiny DOM helpers shared by the views.
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// html`...` with auto-escaped interpolations; pass raw(...) to skip escaping
const RAW = Symbol("raw");
export const raw = (s) => ({ [RAW]: String(s) });
export function html(strings, ...vals) {
  return strings.reduce((out, s, i) => {
    if (i >= vals.length) return out + s;
    const v = vals[i];
    const str = Array.isArray(v) ? v.map((x) => (x && x[RAW] !== undefined ? x[RAW] : esc(x))).join("")
      : v && v[RAW] !== undefined ? v[RAW] : esc(v);
    return out + s + str;
  }, "");
}

export function mount(root, markup) {
  root.innerHTML = markup;
  return root;
}

let toastT;
export function toast(text, ms = 3500) {
  const t = $("#toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastT);
  toastT = setTimeout(() => (t.hidden = true), ms);
}

export const mins = (m) => (m < 1 ? `${Math.round(m * 60)} sec` : `${Math.round(m * 10) / 10} min`);
export const clock = (sec) => `${Math.floor(Math.max(0, sec) / 60)}:${String(Math.floor(Math.max(0, sec) % 60)).padStart(2, "0")}`;
export const stars = (n) => (n ? "★".repeat(n) + "☆".repeat(5 - n) : "");
export const ago = (t) => {
  if (!t) return "";
  const d = (Date.now() / 1000 - t) / 86400;
  return d < 1 ? "today" : d < 2 ? "yesterday" : `${Math.floor(d)} days ago`;
};

export const MIC_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 15a3.5 3.5 0 0 0 3.5-3.5v-6a3.5 3.5 0 1 0-7 0v6A3.5 3.5 0 0 0 12 15Zm6-3.5a1 1 0 1 0-2 0 4 4 0 0 1-8 0 1 1 0 1 0-2 0 6 6 0 0 0 5 5.9V20H8.5a1 1 0 1 0 0 2h7a1 1 0 1 0 0-2H13v-2.6a6 6 0 0 0 5-5.9Z"/></svg>`;
