// Recipe book: every dish you've made, with its version stamp. The landing page is the pantry view.
import { getJSON } from "/lib/api.js";
import { ago, html, mount, raw, stars } from "../ui.js";

export async function enter(root, _params, app) {
  mount(root, html`
    <section class="book-page stack">
      <div class="book-head">
        <div><h1>Recipe book</h1><p class="muted" id="count"></p></div>
        <button class="btn primary" id="goPantry">What can I cook?</button>
      </div>
      <div class="book" id="book"><p class="muted">Loading your recipes…</p></div>
    </section>`);
  root.querySelector("#goPantry").onclick = () => app.go("pantry");

  const rows = await getJSON("/api/mise/book").catch(() => null);
  if (rows === null) {
    root.querySelector("#book").innerHTML = `<div class="empty">Can't reach Mise on your laptop, so the recipe book can't load. Check the laptop is running Mise, or run Gemma on this phone (tap the dot at the top).</div>`;
    return;
  }
  root.querySelector("#count").textContent = rows.length ? `${rows.length} recipe${rows.length > 1 ? "s" : ""}` : "";
  const book = root.querySelector("#book");
  if (!rows.length) {
    book.innerHTML = `<div class="empty">No recipes yet. Take a photo of your fridge to make the first one.</div>`;
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
