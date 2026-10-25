// After cooking: how did it go? Rating, quick tags, typed or spoken notes, and the real
// step timings → Mise writes the next version of the recipe and shows what changed.
import { ON_PHONE, getJSON, postForm, stream } from "/lib/api.js";
import { $, MIC_ICON, html, mins, mount, raw, toast } from "../ui.js";

const TAGS = ["Perfect", "Too salty", "Too bland", "Too spicy", "Needs more heat", "Overcooked", "Undercooked",
  "Took too long", "Too many dishes", "Hard to follow"];

export async function enter(root, params, app) {
  const r = await getJSON(`/api/mise/book/${params.id}`).catch(() => null);
  if (!root.isConnected) return; // you moved on while it loaded
  if (!r) return app.go("home");
  const cook = r.cooks.filter((c) => c.version === r.version).at(-1);
  const F = { rating: 0, tags: new Set(), voice: null };

  mount(root, html`
    <section class="fb">
      <div class="stack" style="gap:6px">
        <p class="label">${r.title} · version ${r.version}</p>
        <h1>How did it turn out?</h1>
        <p class="muted">Mise rewrites the recipe from what you say. Next time you cook it, you'll hear what changed.</p>
      </div>

      ${raw(cook ? html`<div class="card stack">
        <h2>Your timing</h2>
        <div class="timing">${raw(r.steps.map((s, i) => {
          const actual = (cook.step_seconds[i] || 0) / 60;
          const slow = actual > s.minutes * 1.5 && actual - s.minutes >= 2;
          return html`<div><span>Step ${i + 1}: ${s.text.slice(0, 60)}${s.text.length > 60 ? "…" : ""}</span>
            <span class="muted num">planned ${mins(s.minutes)}</span><span class="num ${slow ? "slow" : ""}">took ${mins(actual)}</span></div>`;
        }).join(""))}</div>
      </div>` : "")}

      <div class="card stack">
        <h2>Rating</h2>
        <div class="rating" role="group" aria-label="Rating out of 5">
          ${raw([1, 2, 3, 4, 5].map((n) => html`<button data-n="${n}" aria-pressed="false" aria-label="${n} star${n > 1 ? "s" : ""}">★</button>`).join(""))}
        </div>
        <h2>Quick notes</h2>
        <div class="items" id="tags">${raw(TAGS.map((t) => html`<button class="chip" aria-pressed="false" data-t="${t}">${t}</button>`).join(""))}</div>
        <div class="field">
          <label class="label" for="notes">Tell Mise more</label>
          <textarea id="notes" placeholder="The sauce split a little, and I'd like it spicier next time."></textarea>
        </div>
        <div class="row">
          <button class="btn hold" id="voiceBtn">${raw(MIC_ICON.replace("<svg", '<svg width="20" height="20"'))} Hold to record a voice note</button>
          <span class="muted" id="voiceState"></span>
        </div>
      </div>

      <div class="row">
        <button class="btn primary big" id="improve">Save and improve recipe</button>
        <button class="btn ghost" id="justSave">Just save my notes</button>
      </div>
      <div class="card stack" id="result" hidden></div>
    </section>`);

  root.querySelectorAll(".rating button").forEach((b) => (b.onclick = () => {
    F.rating = +b.dataset.n;
    root.querySelectorAll(".rating button").forEach((x) => x.setAttribute("aria-pressed", +x.dataset.n <= F.rating));
  }));
  root.querySelectorAll("#tags button").forEach((b) => (b.onclick = () => {
    F.tags.has(b.dataset.t) ? F.tags.delete(b.dataset.t) : F.tags.add(b.dataset.t);
    b.setAttribute("aria-pressed", F.tags.has(b.dataset.t));
  }));

  // voice note: hold to record, and Gemma writes what you said into the notes box. Uses the app's one
  // microphone (iOS doesn't like two at once), with hands-free off so nothing else reacts to it here.
  const mic = app.mic;
  mic.handsFree = false;
  mic.blocked = () => true;
  const state = (t) => { if ($("#voiceState")) $("#voiceState").textContent = t; };
  mic.onState = (m) => { $("#voiceBtn")?.classList.toggle("rec", !!m); if (m) state("Recording… let go when you're done"); };
  mic.onUtterance = async (blob, s) => {
    state("Writing down what you said…");
    let text = blob.transcript; // on-phone mode without audio input: the phone's speech recognizer already heard it
    if (text === undefined) {
      try {
        const fd = new FormData();
        fd.append("audio", blob, "note.wav");
        text = (await postForm("/api/mise/transcribe", fd)).text;
      } catch { text = ""; }
    }
    if (!$("#notes")) return; // left the page meanwhile
    if (text) {
      const box = $("#notes");
      box.value = (box.value.trim() ? box.value.trim() + " " : "") + text;
      box.dispatchEvent(new Event("input"));
      F.voice = null; // the words are in the notes now
      state("Added to your notes ✓");
    } else {
      F.voice = blob; // couldn't transcribe: send the recording itself
      state(`Voice note ${s.toFixed(1)}s saved (couldn't write it down)`);
    }
  };
  mic.onSilence = (s) => state(s <= 0.4 ? "Hold the button while you talk." : "I didn't catch anything. Hold the button and speak up a little.");
  const vb = $("#voiceBtn");
  vb.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    vb.setPointerCapture?.(e.pointerId);
    app.speaker.stop();
    mic.start("ptt").catch(() => state("The microphone isn't available. Allow it for this site, or type instead."));
  });
  ["pointerup", "pointercancel", "lostpointercapture"].forEach((ev) => vb.addEventListener(ev, () => mic.stop(true)));
  vb.addEventListener("contextmenu", (e) => e.preventDefault());

  let sending = false;
  async function submit(improve) {
    if (sending) return;
    const notes = $("#notes").value.trim();
    if (!F.rating && !F.tags.size && !notes && !F.voice) { toast("Add a rating, a quick note, or a few words first."); return; }
    const fd = new FormData();
    fd.append("id", r.id);
    fd.append("rating", F.rating);
    fd.append("tags", [...F.tags].join(","));
    fd.append("notes", notes);
    fd.append("improve", improve);
    if (F.voice) fd.append("audio", F.voice, "note.wav");
    sending = true;
    const res = $("#result");
    res.hidden = false;
    requestAnimationFrame(() => res.scrollIntoView({ behavior: "smooth", block: "center" })); // it's below the fold on a phone
    res.innerHTML = improve ? `<h2>Improving the recipe…</h2><div class="progress"><i></i></div><p class="muted">Gemma is rewriting it on this ${ON_PHONE ? "phone" : "laptop"}.</p>` : `<p>Saving…</p>`;
    $("#improve").disabled = $("#justSave").disabled = true;
    try {
      const evs = await stream("/api/mise/feedback", { form: fd }, (ev) => {
        if (ev.type === "progress") res.querySelector(".progress i").style.width = `${Math.min(95, ev.chars / 22)}%`;
      });
      const done = evs.find((e) => e.type === "done");
      const nr = done.recipe;
      res.innerHTML = html`
        ${raw(improve ? html`<div class="row"><span class="stamp" style="width:58px;height:58px;font-size:20px">v${nr.version}</span>
          <div><h2>Saved version ${nr.version}</h2>${raw(done.heard ? html`<p class="muted">You said: ${done.heard}</p>` : "")}</div></div>
          <h3>What changes next time</h3>
          <ul class="changes">${raw(done.changes.map((c) => html`<li>${c}</li>`).join(""))}</ul>
          ${raw(nr.note_for_next_time ? html`<p>Next time you'll hear: <b>${nr.note_for_next_time}</b></p>` : "")}`
          : html`<h2>Notes saved</h2><p class="muted">The recipe stays as it is.</p>`)}
        <div class="row"><button class="btn primary" id="view">View recipe</button><button class="btn ghost" id="book">Recipe book</button></div>`;
      if (improve) app.speaker.say(`Saved version ${nr.version}. ${done.changes[0] || ""}`);
      if ($(".fb .label")) $(".fb .label").textContent = `${nr.title} · version ${nr.version}`;
      requestAnimationFrame(() => res.scrollIntoView({ behavior: "smooth", block: "start" }));
      $("#view").onclick = () => app.go("recipe", { id: nr.id });
      $("#book").onclick = () => app.go("home");
    } catch (e) {
      res.innerHTML = html`<p class="error">${e.message}</p>`;
      $("#improve").disabled = $("#justSave").disabled = false;
      sending = false;
    }
  }
  $("#improve").onclick = () => submit(true);
  $("#justSave").onclick = () => submit(false);
}
