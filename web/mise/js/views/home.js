// Home: the recipe book, plus a way back to the camera ("what can I make?").
import { getJSON } from "/lib/api.js";
import { ago, html, mount, raw, stars } from "../ui.js";

export async function enter(root, _params, app) {
  mount(root, html`
    <section class="home">
      <div class="hero">
        <p class="label">Gemma 4 · runs on this laptop</p>
        <h1>Cook what you have, better every time.</h1>
        <p class="lead">Snap your cupboard, say how long you've got, and Mise talks you through it step by step.
          Tell it how it went and the recipe improves for next time.</p>
        <ol class="how">
          <li>Photograph your cupboard or fridge.</li>
          <li>Pick an idea that fits your time.</li>
          <li>Cook hands-free with spoken steps and timers.</li>
          <li>Give feedback; Mise saves a better version.</li>
        </ol>
        <div class="row"><button class="btn primary big" id="goPantry">What can I make?</button></div>
      </div>
      <div class="stack">
        <div class="book-head"><h2>Recipe book</h2><span class="muted" id="count"></span></div>
        <div class="book" id="book"><p class="muted">Loading your recipes…</p></div>
      </div>
    </section>`);
  root.querySelector("#goPantry").onclick = () => app.go("capture");

  const rows = await getJSON("/api/mise/book").catch(() => []);
  root.querySelector("#count").textContent = rows.length ? `${rows.length} recipe${rows.length > 1 ? "s" : ""}` : "";
  const book = root.querySelector("#book");
  if (!rows.length) {
    book.innerHTML = `<div class="empty">No recipes yet. Photograph your cupboard to make the first one.</div>`;
    return;
  }
  book.innerHTML = rows.map((r) => html`
    <button class="recipe-row" data-id="${r.id}">
      <h3>${r.title}</h3>
      <span class="stamp" title="Version ${r.version}">v${r.version}</span>
      <span class="meta">
        <span class="time">${r.total_minutes} min</span>
        <span>${r.steps} steps</span>
        ${raw(r.cooked ? html`<span>cooked ${r.cooked}× · ${ago(r.last_cooked)}</span>` : html`<span>not cooked yet</span>`)}
        ${raw(r.rating ? html`<span class="stars" aria-label="${r.rating} of 5 stars">${stars(r.rating)}</span>` : "")}
      </span>
    </button>`).join("");
  book.querySelectorAll(".recipe-row").forEach((b) => (b.onclick = () => app.go("recipe", { id: b.dataset.id })));
}
