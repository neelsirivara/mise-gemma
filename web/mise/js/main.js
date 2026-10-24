// Mise app shell: routing between views, the hub event loop (spoken cues, timers),
// and the voice companion (hold-to-talk / hands-free → Gemma → spoken reply).
import { HUB, getJSON, stream, url } from "/lib/api.js";
import { Mic, Speaker, SentenceSpeaker, beep } from "/lib/voice.js";
import { $, $$, toast } from "./ui.js";
import * as home from "./views/home.js";
import * as pantry from "./views/pantry.js";
import * as recipe from "./views/recipe.js";
import * as cook from "./views/cook.js";
import * as feedback from "./views/feedback.js";

const VIEWS = { home, pantry, recipe, cook, feedback };
const root = $("#app");

export const app = {
  view: null,
  params: {},
  speaker: new Speaker(),
  mic: new Mic(),
  busy: false,
  since: 0,
  timers: [],
  listeners: new Set(), // views subscribe to hub events (cook state, timers)

  go(name, params = {}) {
    this.view?.leave?.();
    this.params = params;
    this.view = VIEWS[name];
    document.body.classList.toggle("cooking", name === "cook");
    $$(".nav button").forEach((b) => b.setAttribute("aria-current", b.dataset.go === name ? "page" : "false"));
    root.innerHTML = "";
    this.view.enter(root, params, this);
    root.focus({ preventScroll: true });
    scrollTo(0, 0);
    try { sessionStorage.setItem("mise:view", JSON.stringify({ name, params })); } catch {}
  },

  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); },

  // ---------------------------------------------------------------- voice companion
  async ask({ text = "", audio = null, frame = null }, onTool = () => {}, onText = () => {}, onHeard = () => {}) {
    if (this.busy) return null;
    this.busy = true;
    this.emit({ kind: "busy", busy: true });
    const fd = new FormData();
    if (text) fd.append("text", text);
    if (audio) fd.append("audio", audio, "speech.wav");
    if (frame) fd.append("image", frame, "frame.jpg");
    const voice = new SentenceSpeaker(this.speaker);
    let reply = "", noop = false;
    try {
      await stream("/api/chat", { form: fd }, (ev) => {
        if (ev.type === "text") { reply += ev.text; if (!/^\s*NOOP/i.test(reply)) voice.push(ev.text); onText(reply); }
        if (ev.type === "tool") onTool(ev);
        if (ev.type === "heard") onHeard(ev);
        if (ev.type === "done") noop = ev.noop;
      });
      if (!noop) voice.flush();
    } catch (e) {
      toast(e.message);
    } finally {
      this.busy = false;
      this.emit({ kind: "busy", busy: false });
      this.poll();
    }
    return noop ? null : reply;
  },

  emit(ev) { this.listeners.forEach((fn) => fn(ev)); },

  // ---------------------------------------------------------------- hub event loop
  async poll() {
    let st;
    try {
      st = await getJSON(`/api/state?since=${this.since}`);
    } catch {
      setHub(false);
      return;
    }
    setHub(true, st.engine);
    this.timers = st.timers;
    const first = !this.polled;
    this.polled = true;
    for (const ev of st.events) {
      this.since = Math.max(this.since, ev.t);
      if (first) continue; // don't replay old events after a reload
      // a new step's narration cuts off the previous one (fast "next, next")
      if (ev.kind === "say") this.speaker.say(ev.text, { interrupt: ev.tone === "narration" || ev.tone === "intro" });
      if (ev.kind === "timer_done") { beep(); toast(`⏰ ${ev.label} is done`); }
      if (ev.kind === "alert") { this.speaker.say(ev.text, { interrupt: true }); toast(`⚠ ${ev.text}`, 6000); }
      if (ev.kind === "suggest") toast(ev.text);
      this.emit(ev);
    }
    this.emit({ kind: "tick", timers: st.timers });
  },
};

function setHub(ok, engine) {
  const p = $("#hubPill");
  if (!ok) {
    p.textContent = `no hub at ${HUB || location.host}`;
    p.className = "pill pill-btn bad";
    return;
  }
  const ready = engine?.ready;
  p.textContent = engine?.load_error ? "model failed to load" : ready ? "Gemma 4 · on this laptop" : "warming up…";
  p.className = "pill pill-btn " + (engine?.load_error ? "bad" : ready ? "ok" : "");
  p.title = `${engine?.talk || ""}\n${engine?.watch || ""}`;
}

function updateNet() {
  const p = $("#netPill");
  p.textContent = navigator.onLine ? "internet not used" : "✈ fully offline";
  p.className = "pill " + (navigator.onLine ? "" : "ok");
}

// ---------------------------------------------------------------- hub picker (for a page hosted elsewhere)
function openHub() {
  $("#hubInput").value = HUB;
  if (!$("#hubDialog").open) $("#hubDialog").showModal();
}
$("#hubPill").onclick = openHub;
$("#hubDialog").addEventListener("close", () => {
  if ($("#hubDialog").returnValue !== "save") return;
  const u = new URL(location.href);
  u.searchParams.set("hub", $("#hubInput").value.trim());
  location.href = u.toString();
});

// ---------------------------------------------------------------- boot
$$(".nav button").forEach((b) => (b.onclick = () => app.go(b.dataset.go)));
$("#homeBtn").onclick = () => app.go("home");
addEventListener("online", updateNet);
addEventListener("offline", updateNet);
updateNet();
if ("serviceWorker" in navigator && isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});

async function boot() {
  try {
    await getJSON("/api/meta");
  } catch {
    setHub(false);
    if (!app.askedHub) { app.askedHub = true; if (HUB || location.port === "") openHub(); }
    root.innerHTML = `<div class="empty"><h2>Waiting for the Mise hub</h2><p>Start <b>run.cmd mise</b> on the laptop, or set the hub address with the button at the top.</p></div>`;
    setTimeout(boot, 3000);
    return;
  }
  await app.poll();
  setInterval(() => app.poll(), 1000);
  // resume where you were (and always resume an active cook session)
  let last = null;
  try { last = JSON.parse(sessionStorage.getItem("mise:view")); } catch {}
  const cs = await getJSON("/api/mise/cook/state").catch(() => ({}));
  if (cs.active) app.go("cook");
  else if (cs.awaiting_feedback) app.go("feedback", { id: cs.awaiting_feedback });
  else if (last && VIEWS[last.name] && last.name !== "cook") app.go(last.name, last.params);
  else app.go("home");
}
boot();
window.mise = app; // handy in devtools and for the UI tests
export { url };
