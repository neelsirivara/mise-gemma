// One recipe: what changed since last time, mise en place checklist, timed steps, version history.
import { del, getJSON, postJSON } from "/lib/api.js";
import { $, ago, html, mins, mount, raw, stars, toast } from "../ui.js";

export async function enter(root, params, app) {
  let r;
  try {
    r = await getJSON(`/api/mise/book/${params.id}`);
  } catch (e) {
    mount(root, html`<button class="back" id="back">← Recipe book</button><p class="error">${e.message}</p>`);
    $("#back").onclick = () => app.go("home");
    return;
  }
  const lastFb = r.feedback.at(-1);
  mount(root, html`
    <button class="back" id="back">← Recipe book</button>
    <header class="recipe-head">
      <div class="stack" style="gap:6px;min-width:0">
        <p class="label">${r.source === "pantry" ? "Made from your cupboard" : r.source === "starter" ? "Starter recipe" : "Your recipe"}</p>
        <h1>${r.title}</h1>
        <p class="muted" style="max-width:60ch">${r.summary}</p>
        <div class="meta">
          <span class="time">${r.total_minutes} min</span>
          <span>serves ${r.servings}</span>
          <span>${r.cooks.length ? `cooked ${r.cooks.length}× · last ${ago(r.cooks.at(-1).t)}` : "not cooked yet"}</span>
          ${raw(lastFb?.rating ? html`<span class="stars" aria-label="${lastFb.rating} of 5">${stars(lastFb.rating)}</span>` : "")}
        </div>
      </div>
      <span class="stamp" title="Version ${r.version}" style="width:64px;height:64px;font-size:22px">v${r.version}</span>
    </header>

    ${raw(r.version > 1 ? html`
      <section class="since" aria-label="What changed">
        <p class="label">Version ${r.version}: improved from your feedback</p>
        ${raw(r.note_for_next_time ? html`<p><b>${r.note_for_next_time}</b></p>` : "")}
        <ul>${raw(r.changes.map((c) => html`<li>${c}</li>`).join(""))}</ul>
      </section>` : params.fresh ? html`
      <section class="since"><p class="label">Saved to your recipe book</p>
        <p>Cook it now, then tell Mise how it went. Each time, it saves a better version.</p></section>` : "")}

    <div class="row"><button class="btn primary big" id="cook">Start cooking</button>
      <span class="muted">Steps are read aloud. Say “next” or tap. Hold the mic to ask anything.</span></div>

    <section class="detail">
      <div class="card stack">
        <h2>Get ready</h2>
        <ul class="ing">${raw(r.ingredients.map((i, n) => html`
          <li><label><input type="checkbox" id="ing${n}"><span><span class="qty">${i.qty}</span> ${i.item}</span></label></li>`).join(""))}</ul>
      </div>
      <div class="card stack">
        <h2>Steps</h2>
        <ol class="steps">${raw(r.steps.map((s) => html`
          <li><span>${s.text}</span><span class="mins ${s.timer ? "timer" : ""}">${s.timer ? "⏱ " : ""}${mins(s.minutes)}</span></li>`).join(""))}</ol>
      </div>
    </section>

    ${raw(r.history.length || r.feedback.length ? html`
      <section class="card stack">
        <h2>How this recipe has changed</h2>
        <ol class="history" reversed>
          ${raw(versionRows(r))}
        </ol>
      </section>` : "")}

    <div class="row"><button class="btn ghost danger" id="del">Delete recipe</button></div>`);

  $("#back").onclick = () => app.go("home");
  $("#cook").onclick = async (e) => {
    if (e.currentTarget.disabled) return;
    e.currentTarget.disabled = true; // a double tap would start (and narrate) it twice
    // unlock mic + speaker inside the tap (iOS requires a gesture) so cook mode can listen and talk at once
    app.speaker.unlock();
    app.mic.init().catch(() => {});
    try { await postJSON("/api/mise/cook/start", { id: r.id }); app.go("cook"); }
    catch (err) { toast(err.message); if ($("#cook")) $("#cook").disabled = false; }
  };
  let armed = 0;
  $("#del").onclick = async (e) => {
    // two separate taps: the second must come after a short pause, so a double tap can't delete by accident
    if (!armed || Date.now() - armed < 500) {
      if (!armed) { armed = Date.now(); e.target.textContent = "Tap again to delete"; setTimeout(() => { armed = 0; if ($("#del")) $("#del").textContent = "Delete recipe"; }, 3000); }
      return;
    }
    e.target.disabled = true;
    try {
      await del(`/api/mise/book/${r.id}`);
      toast(`Deleted “${r.title}”`);
      app.go("home");
    } catch (err) { toast(err.message); e.target.disabled = false; }
  };
}

function versionRows(r) {
  const fbFor = (v) => r.feedback.filter((f) => f.version === v);
  const fbLine = (f) => html`<li>You said: ${f.heard || [f.rating ? stars(f.rating) : "", ...(f.tags || []), f.notes].filter(Boolean).join(" · ")}</li>`;
  const rows = [];
  rows.push(html`<li><span class="stamp">v${r.version}</span><div><b>Current</b>
    ${raw(r.changes.length ? html`<ul>${raw(r.changes.map((c) => html`<li>${c}</li>`).join(""))}</ul>` : "")}
    ${raw(fbFor(r.version).length ? html`<ul>${raw(fbFor(r.version).map(fbLine).join(""))}</ul>` : "")}</div></li>`);
  for (const h of [...r.history].reverse()) {
    rows.push(html`<li><span class="stamp">v${h.version}</span><div><b>${h.total_minutes} min · ${h.steps.length} steps</b>
      ${raw(h.changes?.length ? html`<ul>${raw(h.changes.map((c) => html`<li>${c}</li>`).join(""))}</ul>` : "")}
      ${raw(fbFor(h.version).length ? html`<ul>${raw(fbFor(h.version).map(fbLine).join(""))}</ul>` : "")}</div></li>`);
  }
  return rows.join("");
}
