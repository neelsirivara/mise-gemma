// Mise app shell: routing between views, the hub event loop (spoken cues, timers),
// and the voice companion (hold-to-talk / hands-free → Gemma → spoken reply).
import { HUB, ON_PHONE, getJSON, normalizeHub, recoverHub, stream, switchEngine, url } from "/lib/api.js";
import { Mic, Recognizer, Speaker, SentenceSpeaker, beep } from "/lib/voice.js";
import { $, $$, toast } from "./ui.js";
import * as capture from "./views/capture.js";
import * as home from "./views/home.js";
import * as pantry from "./views/pantry.js";
import * as recipe from "./views/recipe.js";
import * as cook from "./views/cook.js";
import * as feedback from "./views/feedback.js";
import * as phone from "./views/phone.js";

const VIEWS = { capture, home, pantry, recipe, cook, feedback, phone };
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
    document.body.classList.toggle("capturing", name === "capture");
    $$(".nav button, .tabbar button").forEach((b) => b.setAttribute("aria-current", b.dataset.go === name || (b.dataset.go === "pantry" && name === "capture") ? "page" : "false"));
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
    // on-phone mode without audio input: send what the phone's speech recognizer heard instead
    if (audio?.transcript !== undefined) {
      if (!audio.transcript) return null;
      text = audio.transcript;
      audio = null;
    }
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

// The hub status is a small dot: solid when connected to the laptop's models, pulsing while they warm up,
// hollow when the hub can't be reached. On-phone mode draws it as a tiny phone. Details live in the
// tooltip / accessible label; tap it to choose where Gemma runs.
function setHub(ok, engine) {
  const p = $("#hubPill");
  const [state, label] = engine?.phone
    ? (engine.load_error ? ["bad", "Gemma couldn't start on this phone. Tap for options."]
      : engine.ready ? ["ok", "Gemma 4 is running on this phone."] : ["warm", "Gemma isn't loaded on this phone yet."])
    : !ok ? ["bad", `No Mise hub at ${HUB || location.host}. Tap to connect.`]
    : engine?.load_error ? ["bad", "The models failed to load on the laptop."]
    : engine?.ready ? ["ok", "Connected: Gemma 4 is running on your laptop."]
    : ["warm", "Connected; the models are warming up."];
  p.dataset.engine = ON_PHONE ? "phone" : "laptop";
  p.dataset.state = state;
  p.setAttribute("aria-label", label);
  p.title = label;
}

// ---------------------------------------------------------------- hub picker (for a page hosted elsewhere)
function openHub() {
  $("#hubInput").value = HUB;
  $("#engLaptop").setAttribute("aria-pressed", String(!ON_PHONE));
  $("#engPhone").setAttribute("aria-pressed", String(ON_PHONE));
  $("#hubFields").hidden = ON_PHONE;
  $("#hubSave").hidden = ON_PHONE;
  $("#engNote").textContent = ON_PHONE
    ? "Gemma runs inside this phone: no laptop or internet needed once it's downloaded."
    : "The laptop runs Gemma and this phone is its camera, mic and screen. Choose this phone to cook without the laptop.";
  if (!$("#hubDialog").open) $("#hubDialog").showModal();
}
$("#engPhone").onclick = () => (ON_PHONE ? $("#hubDialog").close() : switchEngine("phone"));
$("#engLaptop").onclick = () => (ON_PHONE ? switchEngine("laptop") : null);
$("#hubPill").onclick = openHub;
$("#hubDialog").addEventListener("close", () => {
  if ($("#hubDialog").returnValue !== "save") return;
  const u = new URL(location.href);
  u.searchParams.set("hub", normalizeHub($("#hubInput").value));
  location.href = u.toString();
});

// ---------------------------------------------------------------- boot
$$(".nav button, .tabbar button").forEach((b) => (b.onclick = () => app.go(b.dataset.go)));
$("#homeBtn").onclick = () => app.go("pantry");
if ("serviceWorker" in navigator && isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});

// The laptop announces itself as mise.local on the Wi-Fi (core/mdns.py), so a page that isn't served by
// the hub (the hosted Vercel page) can find it without anyone typing an address.
const AUTO_HUBS = ["https://mise.local:8443"];
async function findHub() {
  for (const h of AUTO_HUBS) {
    try {
      const r = await fetch(h + "/api/meta", { cache: "no-store", signal: AbortSignal.timeout(3000) });
      if (r.ok) {
        const u = new URL(location.href);
        u.searchParams.set("hub", h);
        location.replace(u.toString());
        return true;
      }
    } catch {}
  }
  return false;
}

function showUnreachable() {
  root.innerHTML = `
    <section class="card stack" style="max-width:560px;margin:24px auto">
      <h2>Can't find Mise on your laptop</h2>
      <p class="muted">Mise's AI runs on your laptop, so your phone needs to reach it.</p>
      <ol style="margin:0;padding-left:22px;display:grid;gap:8px">
        <li>On the laptop, double-click the <b>Mise</b> icon (or check its Hub page says it's ready).</li>
        <li>Put this phone on the <b>same Wi-Fi</b> as the laptop.</li>
        <li>First time on this phone? Scan the code on the laptop's <b>Mise Hub</b> page to pair it.</li>
      </ol>
      <div class="row"><button class="btn primary" id="retryHub">Try again</button>
        <button class="btn ghost" id="manualHub">Enter the address</button>
        <button class="btn ghost" id="phoneHub">Run on this phone instead</button></div>
      <p class="muted" style="font-size:14px">Still trying in the background…</p>
    </section>`;
  $("#retryHub").onclick = () => { app.unreachableShown = false; clearTimeout(app.retryT); boot(); };
  $("#manualHub").onclick = openHub;
  $("#phoneHub").onclick = () => switchEngine("phone");
}

async function boot() {
  if (ON_PHONE) return bootPhone();
  try {
    const meta = await getJSON("/api/meta");
    // neural voice (Kokoro) synthesized on the laptop; falls back to the browser's voice per sentence
    if (meta.tts) app.speaker.useHub((text) => fetch(url("/api/tts"), {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }),
    }).then((r) => (r.ok ? r.arrayBuffer() : null)));
  } catch {
    if (await recoverHub()) { location.replace(location.pathname); return; } // stale remembered hub
    if (!HUB && await findHub()) return; // e.g. the hosted page on first visit: look for the laptop by name
    setHub(false);
    if (!app.unreachableShown) { app.unreachableShown = true; showUnreachable(); }
    clearTimeout(app.retryT);
    app.retryT = setTimeout(boot, 3000); // one retry loop, even when "Try again" is tapped
    return;
  }
  app.unreachableShown = false;
  await resume();
}

// On-phone mode: the hub runs inside this page (web/lib/phone/hub.js). Until Gemma is downloaded and
// loaded, the setup screen comes first; the recipe book and cook mode then work with no network at all.
async function bootPhone() {
  const { llm } = await import("/lib/phone/hub.js");
  const st = await llm.status();
  // hearing: Gemma itself when the engine takes audio (the iOS app), else the phone's speech recognizer
  const hear = () => { app.mic.recognizer = !llm.st.audio && Recognizer.supported() ? new Recognizer() : null; };
  hear();
  llm.onStatus(hear);
  if (!st.ready) {
    app.polling = true;
    await app.poll();
    setInterval(() => app.poll(), 1000);
    app.go("phone", { then: "pantry" });
    return;
  }
  await resume();
}

async function resume() {
  if (!app.polling) {
    app.polling = true;
    await app.poll();
    setInterval(() => app.poll(), 1000);
  }
  // resume where you were (and always resume an active cook session)
  let last = null;
  try { last = JSON.parse(sessionStorage.getItem("mise:view")); } catch {}
  const cs = await getJSON("/api/mise/cook/state").catch(() => ({}));
  if (cs.active) app.go("cook");
  else if (cs.awaiting_feedback) app.go("feedback", { id: cs.awaiting_feedback });
  else if (last && VIEWS[last.name] && last.name !== "cook") app.go(last.name, last.params);
  else app.go("pantry"); // first screen: the four steps, camera live in step 1
}
boot();
window.mise = app; // handy in devtools and for the UI tests

// A home-screen web app keeps its page alive for days, so it would never pick up a new version. When Mise comes
// back to the foreground and its code has changed on the server, reload, unless you're in the middle of cooking.
const CODE = ["/mise/index.html", "/mise/mise.css", "/mise/js/main.js", "/mise/js/ui.js", "/mise/js/mum.js", "/mise/js/scenes.js",
  ...["capture", "home", "pantry", "recipe", "cook", "feedback", "phone"].map((v) => `/mise/js/views/${v}.js`),
  "/lib/api.js", "/lib/voice.js", "/lib/camera.js", "/lib/phone/hub.js", "/lib/phone/llm.js", "/lib/phone/cook.js"];
const stamp = async () => (await Promise.all(CODE.map((p) => fetch(p, { method: "HEAD", cache: "no-store" })
  .then((r) => r.headers.get("etag") || r.headers.get("last-modified") || "").catch(() => "")))).join("|");
let codeStamp = null;
stamp().then((s) => (codeStamp = s));
document.addEventListener("visibilitychange", async () => {
  if (document.visibilityState !== "visible" || !codeStamp || app.view === VIEWS.cook || app.busy) return;
  const now = await stamp();
  if (now && now !== codeStamp && !now.includes("||")) location.reload();
});
export { url };
