// Cook mode: one step at a time in huge type, narrated by the hub; timers, time cues and a
// voice companion (hold the mic or go hands-free) that can move steps and answer questions.
import { getJSON, postForm, postJSON } from "/lib/api.js";
import { snapshot, startCamera, stopCamera } from "/lib/camera.js";
import { $, MIC_ICON, clock, html, mins, mount, raw, toast } from "../ui.js";
import { MUMS, mountMum, savedMum } from "../mum.js";
import { SCENES, VERB, sceneFor } from "../scenes.js";

let off = [];
let st = null;
let mum = null;   // the cooking teacher over the camera
let shown = -1;   // step index on screen, so mum hops when it changes

export async function enter(root, _params, app) {
  mount(root, html`
    <section class="cook">
      <div class="stack" style="gap:10px">
        <div class="cook-top">
          <button class="btn ghost" id="exit" aria-label="Stop cooking">✕</button>
          <span class="title" id="title"></span>
          <span class="eta num" id="eta"></span>
        </div>
        <div class="segbar" id="segbar" aria-hidden="true"></div>
        <div class="timers" id="timers" aria-live="polite"></div>
      </div>
      <div class="stack" style="justify-content:center;gap:18px">
        <div class="stage" id="stage"></div>
        <div class="row" style="align-items:flex-start;gap:16px">
          <div class="pip" id="pip" hidden><video id="cookCam" playsinline muted></video></div>
          <div class="stack" style="flex:1;min-width:220px;gap:8px">
            <div class="toggles">
              <label><input type="checkbox" id="handsFree"> Always listening</label>
              <label><input type="checkbox" id="useCam"> Camera</label>
              <label><input type="checkbox" id="speak" checked> Read aloud</label>
              <label>Mum <select id="mumPick">${raw(MUMS.map((m) => html`<option value="${m.id}">${m.label}</option>`).join(""))}</select></label>
            </div>
            <div class="convo" id="convo"></div>
          </div>
          <details class="card" style="padding:12px 16px;min-width:220px">
            <summary><b>Ingredients</b></summary>
            <ul class="ing" id="ings"></ul>
          </details>
        </div>
      </div>
      <div class="mum-dock" aria-live="polite">
        <p class="said mum-say" id="said"></p>
        <div class="mum" id="mum" aria-hidden="true"></div>
      </div>
      <div class="cook-bar">
        <div class="left">
          <button class="btn" id="backBtn" aria-label="Previous step">←<span class="wide-only"> Back</span></button>
          <button class="btn" id="repeatBtn">Repeat</button>
        </div>
        <div class="mic-wrap">
          <button class="mic" id="mic" aria-label="Hold to talk to Mise">${raw(MIC_ICON)}</button>
          <small id="micHint">Hold to talk</small>
        </div>
        <div class="right"><button class="btn primary big" id="nextBtn">Next →</button></div>
      </div>
    </section>`);

  // ---- mum: always a little alive; her mouth follows the voice; pick yours (remembered).
  // Sized from the screen: smaller on short phones and in landscape, re-sized when the phone rotates.
  const mumHeight = () => Math.round(Math.max(96, Math.min(innerWidth <= 820 ? 180 : 290, innerHeight * (innerWidth > innerHeight ? 0.34 : 0.2))));
  mum = mountMum($("#mum"), app.speaker, { id: savedMum(), height: mumHeight() });
  const onResize = () => mum?.resize(mumHeight());
  addEventListener("resize", onResize);
  $("#mumPick").value = mum.id;
  $("#mumPick").onchange = (e) => { mum.set(e.target.value); app.speaker.say(`Hi, ${mum.hello()}! I'm here. Let's cook.`, { interrupt: true }); };
  shown = -1;

  // one step change at a time: a double tap on Next used to skip a step (and start its timer)
  let acting = false;
  const act = async (a) => {
    if (acting) return;
    acting = true;
    try { st = await postJSON(`/api/mise/cook/${a}`); draw(); } catch (e) { toast(e.message); }
    finally { setTimeout(() => (acting = false), 350); }
  };
  $("#nextBtn").onclick = () => (st && st.step >= st.recipe.steps.length - 1 ? finish() : act("next"));
  $("#backBtn").onclick = () => act("back");
  $("#repeatBtn").onclick = () => act("repeat");
  let armed = false;
  $("#exit").onclick = async (e) => {
    if (!armed) { armed = true; toast("Tap ✕ again to stop cooking"); setTimeout(() => (armed = false), 3000); return; }
    app.speaker.stop();
    try { await postJSON("/api/mise/cook/stop"); } catch {}
    app.go("recipe", { id: st?.recipe?.id });
  };
  let finishing = false;
  async function finish() {
    if (finishing) return;
    finishing = true;
    try {
      st = await postJSON("/api/mise/cook/finish");
      app.go("feedback", { id: st.awaiting_feedback });
    } catch (e) { toast(e.message); finishing = false; }
  }

  // ---- voice companion
  const mic = app.mic;
  mic.blocked = () => app.busy; // while Mise thinks; while it talks, a louder voice interrupts it
  mic.isSpeaking = () => app.speaker.speaking;
  mic.onBargeIn = () => app.speaker.stop();
  mic.onState = (mode) => {
    $("#mic")?.classList.toggle("rec", !!mode);
    if ($("#micHint")) $("#micHint").textContent = mode ? "Listening…" : app.busy ? "Thinking…" : mic.handsFree ? "Listening for you" : "Hold to talk";
  };
  mic.onSilence = () => {};
  mic.onUtterance = async (blob, seconds) => {
    const frame = $("#useCam").checked ? await snapshot($("#cookCam"), 768) : null;
    const reply = await app.ask({ audio: blob, frame }, () => {}, undefined, (h) => { if (h.text) log(`You: “${h.text}”`, "me"); });
    if (reply) {
      log(reply);
      if ($("#said")) $("#said").textContent = reply; // Mum says the answer, not just the step
    }
  };
  const micBtn = $("#mic");
  const micFailed = () => toast("The microphone isn't available. Allow it for this site, or tap Next and Repeat.", 5000);
  micBtn.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    if (app.busy) { if ($("#micHint")) $("#micHint").textContent = "Still thinking… one moment"; return; } // it would be dropped
    try { micBtn.setPointerCapture(e.pointerId); } catch {}
    app.speaker.stop();
    mic.start("ptt").catch(micFailed);
  });
  // also when the mic is still starting (first tap: permission prompt), so a quick tap can't leave it recording
  ["pointerup", "pointercancel", "lostpointercapture"].forEach((ev) => micBtn.addEventListener(ev, () => (mic.mode === "ptt" || mic.starting) && mic.stop(true)));
  micBtn.addEventListener("contextmenu", (e) => e.preventDefault());
  $("#handsFree").onchange = async (e) => {
    mic.handsFree = e.target.checked;
    try { localStorage.setItem("mise:handsfree", mic.handsFree ? "1" : "0"); } catch {}
    if (mic.handsFree) await mic.init().catch(() => {
      // no mic (permission off, or none here): say so instead of claiming to listen
      mic.handsFree = false;
      if ($("#handsFree")) $("#handsFree").checked = false;
      toast("The microphone isn't available. Tap Next, or allow the mic and turn Always listening back on.", 5000);
    });
    mic.onState(mic.mode);
  };
  // always listening by default: a voice companion you don't have to touch with messy hands
  let pref = "1";
  try { pref = localStorage.getItem("mise:handsfree") ?? "1"; } catch {}
  $("#handsFree").checked = pref === "1";
  if (pref === "1") $("#handsFree").onchange({ target: $("#handsFree") });
  let watchT = null;
  $("#useCam").onchange = async (e) => {
    $("#pip").hidden = !e.target.checked;
    document.body.classList.toggle("camfull", e.target.checked); // the camera fills the screen behind mum
    clearInterval(watchT);
    if (e.target.checked) {
      await startCamera($("#cookCam")).catch((err) => { toast("Camera unavailable: " + err.message); e.target.checked = false; $("#pip").hidden = true; });
      // the watcher (second model, on the laptop CPU) checks the counter: hazards, "looks done"
      if (e.target.checked) watchT = setInterval(async () => {
        if (app.busy || mic.mode) return;
        const f = await snapshot($("#cookCam"), 640);
        if (!f) return;
        const fd = new FormData();
        fd.append("image", f, "frame.jpg");
        postForm("/api/watch", fd).catch(() => {});
      }, 8000);
      if (!e.target.checked) document.body.classList.remove("camfull");
    } else stopCamera($("#cookCam"));
  };
  $("#speak").onchange = (e) => { app.speaker.enabled = e.target.checked; if (!e.target.checked) app.speaker.stop(); };
  $("#speak").checked = app.speaker.enabled;

  const keys = (e) => {
    if (e.target.closest("input, textarea, select")) return;
    if (e.code === "Space" && !e.repeat) { e.preventDefault(); app.speaker.stop(); mic.start("ptt").catch(micFailed); }
    if (e.code === "ArrowRight") $("#nextBtn").click();
    if (e.code === "ArrowLeft") act("back");
    if (e.key === "r") act("repeat");
  };
  const keyup = (e) => { if (e.code === "Space" && (mic.mode === "ptt" || mic.starting)) { e.preventDefault(); mic.stop(true); } };
  addEventListener("keydown", keys);
  addEventListener("keyup", keyup);

  // ---- hub events
  let ticks = 0;
  off = [
    app.on(async (ev) => {
      if (ev.kind === "cook") {
        st = await getJSON("/api/mise/cook/state");
        if (!st.active && st.awaiting_feedback) return app.go("feedback", { id: st.awaiting_feedback });
        draw();
      }
      if (ev.kind === "say") { $("#said").textContent = ev.text; }
      if (ev.kind === "tick") {
        drawTimers(ev.timers);
        if (++ticks % 20 === 0) getJSON("/api/mise/cook/state").then((s) => { if (s.active && $("#eta")) $("#eta").textContent = s.eta ? `Eat around ${s.eta}` : ""; }).catch(() => {});
      }
      if (ev.kind === "busy") mic.onState(mic.mode);
    }),
    () => { removeEventListener("keydown", keys); removeEventListener("keyup", keyup); removeEventListener("resize", onResize); clearInterval(watchT); mic.handsFree = false; },
  ];

  function log(text, cls = "") {
    const c = $("#convo");
    if (!c) return;
    c.insertAdjacentHTML("beforeend", html`<p class="${cls}">${text}</p>`);
    c.scrollTop = c.scrollHeight;
  }

  st = await getJSON("/api/mise/cook/state");
  if (!root.isConnected) return; // you moved on while it loaded
  if (!st.recipe) return app.go("home");
  if (!st.active && st.awaiting_feedback) return app.go("feedback", { id: st.awaiting_feedback });
  draw();
  drawTimers(app.timers);
}

function draw() {
  if (!st?.recipe || !$("#stage")) return;
  const r = st.recipe, i = st.step, s = r.steps[i], n = r.steps.length;
  const next = r.steps[i + 1];
  const scene = sceneFor(s.text);
  $("#title").textContent = `${r.title}${r.version > 1 ? ` · v${r.version}` : ""}`;
  $("#eta").textContent = st.eta ? `Eat around ${st.eta}` : "";
  $("#segbar").innerHTML = r.steps.map((_, k) => `<i class="${k < i ? "done" : k === i ? "now" : ""}"></i>`).join("");
  $("#stage").innerHTML = html`
    <span class="n" aria-hidden="true">${i + 1}</span>
    <p class="text"><span class="label" style="display:block">Step ${i + 1} of ${n}</span>${s.text}</p>
    <div class="sub">
      <span class="time">${mins(s.minutes)}</span>
      ${raw(s.timer ? `<span class="muted">Timer running</span>` : "")}
      ${raw(s.check ? html`<span class="muted">Done when: ${s.check}</span>` : "")}
    </div>
    ${raw(s.timer && next && !next.timer && s.minutes >= 3 ? html`<p class="ahead"><b>While that cooks:</b> ${next.text}</p>` : "")}
    ${raw(scene ? `<div class="scene" data-kind="${scene}"><span class="verb">${VERB[scene]}</span>${SCENES[scene]}</div>` : "")}`;
  if (i !== shown) { if (shown >= 0) mum?.hop(); shown = i; }
  $("#said").textContent = st.last_said || "";
  $("#nextBtn").textContent = i >= n - 1 ? "Finished ✓" : "Next →";
  $("#backBtn").disabled = i === 0;
  $("#ings").innerHTML = r.ingredients.map((x) => html`<li><span class="qty">${x.qty}</span> ${x.item}</li>`).join("");
}

function drawTimers(timers = []) {
  const el = $("#timers");
  if (!el) return;
  const live = timers; // the hub clears finished timers 20 s after they ring, and when the step changes
  const C = 2 * Math.PI * 15;
  el.innerHTML = live.map((t) => {
    const frac = t.seconds ? Math.max(0, t.remaining) / t.seconds : 0;
    return html`<div class="tm ${t.fired ? "fired" : ""}">
      <svg viewBox="0 0 38 38" aria-hidden="true"><circle class="bg" cx="19" cy="19" r="15"/><circle class="fg" cx="19" cy="19" r="15" stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - frac)}"/></svg>
      <span><b class="num">${t.fired ? "Done" : clock(t.remaining)}</b><br><small class="muted">${t.label}</small></span></div>`;
  }).join("");
}

export function leave() {
  off.forEach((f) => f());
  off = [];
  mum?.destroy();
  mum = null;
  document.body.classList.remove("camfull");
  stopCamera(document.getElementById("cookCam"));
}
