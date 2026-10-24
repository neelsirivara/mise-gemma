// After cooking: how did it go? Rating, quick tags, typed or spoken notes, and the real
// step timings → Mise writes the next version of the recipe and shows what changed.
import { getJSON, stream } from "/lib/api.js";
import { Mic } from "/lib/voice.js";
import { $, MIC_ICON, html, mins, mount, raw, toast } from "../ui.js";

const TAGS = ["Perfect", "Too salty", "Too bland", "Too spicy", "Needs more heat", "Overcooked", "Undercooked",
  "Took too long", "Too many dishes", "Hard to follow"];

export async function enter(root, params, app) {
  const r = await getJSON(`/api/mise/book/${params.id}`).catch(() => null);
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
          <button class="btn" id="voiceBtn" style="touch-action:none">${raw(MIC_ICON.replace("<svg", '<svg width="20" height="20"'))} Hold to record a voice note</button>
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

  // voice note: its own mic instance so cook-mode hands-free doesn't fire here
  app.mic.handsFree = false;
  const mic = new Mic();
  mic.onUtterance = (blob, s) => { F.voice = blob; $("#voiceState").textContent = `Voice note ${s.toFixed(1)}s ✓`; };
  mic.onState = (m) => { if (m) $("#voiceState").textContent = "Recording…"; };
  const vb = $("#voiceBtn");
  vb.addEventListener("pointerdown", (e) => { e.preventDefault(); app.speaker.stop(); mic.start("ptt"); });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => vb.addEventListener(ev, () => mic.mode && mic.stop(true)));

  async function submit(improve) {
    const notes = $("#notes").value.trim();
    if (!F.rating && !F.tags.size && !notes && !F.voice) { toast("Add a rating, a quick note, or a few words first."); return; }
    const fd = new FormData();
    fd.append("id", r.id);
    fd.append("rating", F.rating);
    fd.append("tags", [...F.tags].join(","));
    fd.append("notes", notes);
    fd.append("improve", improve);
    if (F.voice) fd.append("audio", F.voice, "note.wav");
    const res = $("#result");
    res.hidden = false;
    res.innerHTML = improve ? `<h2>Improving the recipe…</h2><div class="progress"><i></i></div><p class="muted">Gemma is rewriting it on this laptop.</p>` : `<p>Saving…</p>`;
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
      $("#view").onclick = () => app.go("recipe", { id: nr.id });
      $("#book").onclick = () => app.go("home");
    } catch (e) {
      res.innerHTML = html`<p class="error">${e.message}</p>`;
      $("#improve").disabled = $("#justSave").disabled = false;
    }
  }
  $("#improve").onclick = () => submit(true);
  $("#justSave").onclick = () => submit(false);
}
