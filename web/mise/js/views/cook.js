// Cook mode: one step at a time in huge type, narrated by the hub; timers, time cues and a
// voice companion (hold the mic or go hands-free) that can move steps and answer questions.
import { getJSON, postJSON } from "/lib/api.js";
import { snapshot, startCamera, stopCamera } from "/lib/camera.js";
import { $, MIC_ICON, clock, html, mins, mount, raw, toast } from "../ui.js";

let off = [];
let st = null;

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
        <p class="said" id="said" aria-live="polite"></p>
        <div class="row" style="align-items:flex-start;gap:16px">
          <div class="pip" id="pip" hidden><video id="cookCam" playsinline muted></video></div>
          <div class="stack" style="flex:1;min-width:220px;gap:8px">
            <div class="toggles">
              <label><input type="checkbox" id="handsFree"> Hands-free</label>
              <label><input type="checkbox" id="useCam"> Camera</label>
              <label><input type="checkbox" id="speak" checked> Read aloud</label>
            </div>
            <div class="convo" id="convo"></div>
          </div>
          <details class="card" style="padding:12px 16px;min-width:220px">
            <summary><b>Ingredients</b></summary>
            <ul class="ing" id="ings"></ul>
          </details>
        </div>
      </div>
      <div class="cook-bar">
        <div class="left">
          <button class="btn" id="backBtn" aria-label="Previous step">← Back</button>
          <button class="btn" id="repeatBtn">Repeat</button>
        </div>
        <div class="mic-wrap">
          <button class="mic" id="mic" aria-label="Hold to talk to Mise">${raw(MIC_ICON)}</button>
          <small id="micHint">Hold to talk</small>
        </div>
        <div class="right"><button class="btn primary big" id="nextBtn">Next →</button></div>
      </div>
    </section>`);

  const act = async (a) => { try { st = await postJSON(`/api/mise/cook/${a}`); draw(); } catch (e) { toast(e.message); } };
  $("#nextBtn").onclick = () => (st && st.step >= st.recipe.steps.length - 1 ? finish() : act("next"));
  $("#backBtn").onclick = () => act("back");
  $("#repeatBtn").onclick = () => act("repeat");
  let armed = false;
  $("#exit").onclick = async (e) => {
    if (!armed) { armed = true; toast("Tap ✕ again to stop cooking"); setTimeout(() => (armed = false), 3000); return; }
    await postJSON("/api/mise/cook/stop");
    app.speaker.stop();
    app.go("recipe", { id: st?.recipe?.id });
  };
  async function finish() {
    st = await postJSON("/api/mise/cook/finish");
    app.go("feedback", { id: st.awaiting_feedback });
  }

  // ---- voice companion
  const mic = app.mic;
  mic.blocked = () => app.busy || app.speaker.speaking;
  mic.onState = (mode) => {
    $("#mic")?.classList.toggle("rec", !!mode);
    if ($("#micHint")) $("#micHint").textContent = mode ? "Listening…" : app.busy ? "Thinking…" : mic.handsFree ? "Listening for you" : "Hold to talk";
  };
  mic.onUtterance = async (blob, seconds) => {
    const frame = $("#useCam").checked ? await snapshot($("#cookCam"), 768) : null;
    const reply = await app.ask({ audio: blob, frame }, (t) => log(`→ ${t.name.replace("_", " ")}`, "tool"),
      undefined, (h) => log(`You: “${h.text}”`, "me"));
    if (reply) log(reply);
  };
  const micBtn = $("#mic");
  micBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); app.speaker.stop(); mic.start("ptt"); });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => micBtn.addEventListener(ev, () => mic.mode === "ptt" && mic.stop(true)));
  micBtn.addEventListener("contextmenu", (e) => e.preventDefault());
  $("#handsFree").onchange = async (e) => {
    mic.handsFree = e.target.checked;
    if (mic.handsFree) await mic.init().catch((err) => toast("Microphone unavailable: " + err.message));
    mic.onState(mic.mode);
  };
  $("#useCam").onchange = async (e) => {
    $("#pip").hidden = !e.target.checked;
    if (e.target.checked) await startCamera($("#cookCam")).catch((err) => { toast("Camera unavailable: " + err.message); e.target.checked = false; $("#pip").hidden = true; });
    else stopCamera($("#cookCam"));
  };
  $("#speak").onchange = (e) => { app.speaker.enabled = e.target.checked; if (!e.target.checked) app.speaker.stop(); };
  $("#speak").checked = app.speaker.enabled;

  const keys = (e) => {
    if (e.target.closest("input, textarea")) return;
    if (e.code === "Space" && !e.repeat) { e.preventDefault(); app.speaker.stop(); mic.start("ptt"); }
    if (e.code === "ArrowRight") $("#nextBtn").click();
    if (e.code === "ArrowLeft") act("back");
    if (e.key === "r") act("repeat");
  };
  const keyup = (e) => { if (e.code === "Space" && mic.mode === "ptt") { e.preventDefault(); mic.stop(true); } };
  addEventListener("keydown", keys);
  addEventListener("keyup", keyup);

  // ---- hub events
  off = [
    app.on(async (ev) => {
      if (ev.kind === "cook") {
        st = await getJSON("/api/mise/cook/state");
        if (!st.active && st.awaiting_feedback) return app.go("feedback", { id: st.awaiting_feedback });
        draw();
      }
      if (ev.kind === "say") { $("#said").textContent = ev.text; }
      if (ev.kind === "tick") drawTimers(ev.timers);
      if (ev.kind === "busy") mic.onState(mic.mode);
    }),
    () => { removeEventListener("keydown", keys); removeEventListener("keyup", keyup); },
  ];

  function log(text, cls = "") {
    const c = $("#convo");
    if (!c) return;
    c.insertAdjacentHTML("beforeend", html`<p class="${cls}">${text}</p>`);
    c.scrollTop = c.scrollHeight;
  }

  st = await getJSON("/api/mise/cook/state");
  if (!st.recipe) return app.go("home");
  if (!st.active && st.awaiting_feedback) return app.go("feedback", { id: st.awaiting_feedback });
  draw();
  drawTimers(app.timers);
}

function draw() {
  if (!st?.recipe || !$("#stage")) return;
  const r = st.recipe, i = st.step, s = r.steps[i], n = r.steps.length;
  const next = r.steps[i + 1];
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
    ${raw(s.timer && next && !next.timer && s.minutes >= 3 ? html`<p class="ahead"><b>While that cooks:</b> ${next.text}</p>` : "")}`;
  $("#said").textContent = st.last_said || "";
  $("#nextBtn").textContent = i >= n - 1 ? "Finished ✓" : "Next →";
  $("#backBtn").disabled = i === 0;
  $("#ings").innerHTML = r.ingredients.map((x) => html`<li><span class="qty">${x.qty}</span> ${x.item}</li>`).join("");
}

function drawTimers(timers = []) {
  const el = $("#timers");
  if (!el) return;
  const live = timers.filter((t) => !t.fired || t.remaining > -20);
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
  stopCamera(document.getElementById("cookCam"));
}
