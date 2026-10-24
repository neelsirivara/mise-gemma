// Talking to the Mise hub (the laptop running the models).
// Same origin when the laptop serves the page; when the page is hosted elsewhere (Vercel),
// ?hub=https://<laptop-ip>:8443 points it at the laptop and is remembered.
// "192.168.1.5:8443" → "https://192.168.1.5:8443"; a hub equal to this page's own origin is just "".
export function normalizeHub(v) {
  v = (v || "").trim().replace(/\/+$/, "");
  if (!v) return "";
  if (!/^https?:\/\//i.test(v)) v = "https://" + v;
  try {
    const u = new URL(v);
    return u.origin === location.origin ? "" : u.origin;
  } catch {
    return "";
  }
}

export const HUB = (() => {
  const q = new URLSearchParams(location.search).get("hub");
  try {
    if (q !== null) normalizeHub(q) ? localStorage.setItem("hub", normalizeHub(q)) : localStorage.removeItem("hub");
    return normalizeHub(q ?? localStorage.getItem("hub") ?? "");
  } catch {
    return normalizeHub(q || "");
  }
})();

// A remembered hub that no longer answers (new network, Tailscale off) shouldn't strand the app
// when the page itself was served by a working hub: forget it and use this origin.
export async function recoverHub() {
  if (!HUB) return false;
  try {
    const r = await fetch("/api/meta", { cache: "no-store", signal: AbortSignal.timeout(4000) });
    if (!r.ok) return false;
    try { localStorage.removeItem("hub"); } catch {}
    return true;
  } catch {
    return false;
  }
}

export const url = (path) => HUB + path;

export class HubError extends Error {}

async function check(res) {
  if (res.ok) return res;
  let msg = `${res.status} ${res.statusText}`;
  try { msg = (await res.json()).detail || msg; } catch {}
  throw new HubError(msg);
}

async function call(path, opts) {
  try {
    return await check(await fetch(url(path), opts));
  } catch (e) {
    if (e instanceof HubError) throw e;
    throw new HubError(`Can't reach the Mise hub at ${HUB || location.host}. Is run.cmd still running?`);
  }
}

// reads time out fast: an unreachable hub (wrong network, Tailscale off) otherwise hangs for ~a minute
export const getJSON = async (path, ms = 6000) => (await call(path, { signal: AbortSignal.timeout(ms) })).json();

export const postJSON = async (path, body = {}) =>
  (await call(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })).json();

export const postForm = async (path, form) => (await call(path, { method: "POST", body: form })).json();

export const del = async (path) => (await call(path, { method: "DELETE" })).json();

// POST that answers with newline-delimited JSON; calls onEvent for each event, returns them all.
export async function stream(path, { json, form } = {}, onEvent = () => {}) {
  const opts = { method: "POST" };
  if (json) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(json); }
  if (form) opts.body = form;
  const res = await call(path, opts);
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  const all = [];
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i);
      buf = buf.slice(i + 1);
      if (!line.trim()) continue;
      const ev = JSON.parse(line);
      all.push(ev);
      if (ev.type === "error") throw new HubError(ev.error);
      onEvent(ev);
    }
  }
  return all;
}
