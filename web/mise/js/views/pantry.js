// "What can I make?": photos of the cupboard + time you have → ingredients → ideas → full recipe.
import { postForm, postJSON, stream } from "/lib/api.js";
import { shrink } from "/lib/camera.js";
import { $, html, mount, raw, toast } from "../ui.js";

const TIMES = [15, 20, 30, 45, 60, 90];
let S = null; // kept while the app is open, so going back doesn't lose your photos

function fresh() {
  return { photos: [], scanned: new Set(), scanP: null, minutes: 30, servings: 2, notes: "", items: [], ideas: [], scanning: false, thinking: false };
}

// The camera screen adds its photos straight into this list.
export function photos() {
  S = S || fresh();
  return S.photos;
}

export function enter(root, params, app) {
  S = S && !params.reset ? S : fresh();
  mount(root, html`
    <button class="back" id="back">← Back to the camera</button>
    <section class="pantry">
      <div class="stack">
        <div class="card stack">
          <div><p class="label">Step 1</p><h2>Your photos</h2></div>
          <div class="photos" id="photos"></div>
          <div class="row">
            <button class="btn ghost" id="liveCam">Open the camera</button>
            <span class="muted" id="photoHint"></span>
          </div>
        </div>
        <div class="card stack">
          <div><p class="label">Step 2</p><h2>How long do you have?</h2></div>
          <div class="seg" id="times" role="group" aria-label="Time available, in minutes">
            ${raw(TIMES.map((m) => html`<button data-m="${m}" aria-pressed="${m === S.minutes}">${m} min</button>`).join(""))}
          </div>
          <div class="row">
            <span class="label">Cooking for</span>
            <span class="stepper"><button id="less" aria-label="Fewer people">−</button><output id="serv">${S.servings}</output><button id="more" aria-label="More people">+</button></span>
          </div>
          <div class="field">
            <label class="label" for="notes">Anything to know? (optional)</label>
            <input id="notes" placeholder="vegetarian, no oven, kid-friendly…" value="${S.notes}" />
          </div>
          <button class="btn primary big" id="find">See what I can make</button>
        </div>
      </div>
      <div class="stack" id="results"></div>
    </section>`);

  const go = (v, p) => app.go(v, p);
  $("#back").onclick = () => go("capture");

  // ---- photos
  const fileInput = Object.assign(document.createElement("input"), { type: "file", accept: "image/*", multiple: true });
  fileInput.setAttribute("capture", "environment"); // phones open the camera straight away
  fileInput.onchange = async () => {
    for (const f of fileInput.files) S.photos.push(await shrink(f));
    fileInput.value = "";
    drawPhotos();
  };
  function drawPhotos() {
    const el = $("#photos");
    el.innerHTML = S.photos.map((p, i) => html`<div class="photo"><img alt="Cupboard photo ${i + 1}" src="${URL.createObjectURL(p)}"><button aria-label="Remove photo ${i + 1}" data-i="${i}">×</button></div>`).join("")
      + (S.photos.length < 4 ? `<button class="add-photo" id="addPhoto">+ Add photo</button>` : "");
    el.querySelectorAll(".photo button").forEach((b) => (b.onclick = () => { S.photos.splice(+b.dataset.i, 1); drawPhotos(); }));
    $("#addPhoto") && ($("#addPhoto").onclick = () => fileInput.click());
    $("#photoHint").textContent = S.photos.length ? `${S.photos.length} photo${S.photos.length > 1 ? "s" : ""}` : "";
  }
  drawPhotos();
  $("#liveCam").onclick = () => go("capture");

  // ---- time + servings
  root.querySelectorAll("#times button").forEach((b) => (b.onclick = () => {
    S.minutes = +b.dataset.m;
    root.querySelectorAll("#times button").forEach((x) => x.setAttribute("aria-pressed", x === b));
  }));
  const serv = (d) => { S.servings = Math.max(1, Math.min(12, S.servings + d)); $("#serv").textContent = S.servings; };
  $("#less").onclick = () => serv(-1);
  $("#more").onclick = () => serv(1);
  $("#notes").oninput = (e) => (S.notes = e.target.value);

  // ---- scan: read any photos not read yet. Runs as soon as you arrive from the camera,
  // so the ingredients are ready by the time you've picked how long you have.
  function scan() {
    if (S.scanP) return S.scanP;
    const todo = S.photos.filter((p) => !S.scanned.has(p));
    if (!todo.length) return Promise.resolve();
    const st = S;
    st.scanning = true; st.ideas = []; drawResults();
    st.scanP = (async () => {
      try {
        const fd = new FormData();
        todo.forEach((p, i) => fd.append("images", p, `photo${i}.jpg`));
        const r = await postForm("/api/mise/pantry/scan", fd);
        todo.forEach((p) => st.scanned.add(p));
        st.items = [...new Set([...r.items, ...st.items])];
      } catch (e) { toast(e.message); }
      st.scanning = false; st.scanP = null;
      if (S === st) drawResults();
    })();
    return st.scanP;
  }

  // ---- find: finish the scan, then ideas
  $("#find").onclick = async () => {
    if (!S.photos.length && !S.items.length) { toast("Add a photo of your cupboard, or type ingredients below."); drawResults(true); return; }
    await scan();
    await ideas();
  };

  async function ideas() {
    if (!S.items.length) { drawResults(true); return; }
    S.thinking = true; drawResults();
    try {
      const r = await postJSON("/api/mise/pantry/ideas", { items: S.items, minutes: S.minutes, servings: S.servings, notes: S.notes });
      S.ideas = r.ideas;
    } catch (e) { toast(e.message); }
    S.thinking = false; drawResults();
  }

  function drawResults(forceItems = false) {
    const el = $("#results");
    if (!el) return; // the scan finished after you left this page
    if (S.scanning) { el.innerHTML = `<div class="card stack"><h2>Looking in your cupboard…</h2><div class="progress"><i style="width:40%"></i></div><p class="muted">Gemma is reading the photos on this laptop.</p></div>`; return; }
    if (!S.items.length && !forceItems && !S.ideas.length) {
      el.innerHTML = `<div class="empty">Your ingredients and recipe ideas will show up here.</div>`;
      return;
    }
    el.innerHTML = html`
      <div class="card stack">
        <div class="row" style="justify-content:space-between"><h2>What you have</h2><span class="muted">${S.items.length} items</span></div>
        <p class="muted">Remove anything that's wrong and add what the photo missed. Salt, pepper and oil are assumed.</p>
        <div class="items" id="items">${raw(S.items.map((it, i) => html`<span class="chip">${it}<button class="x" data-i="${i}" aria-label="Remove ${it}">×</button></span>`).join(""))}</div>
        <form class="row" id="addForm"><input id="addItem" class="chip" style="flex:1;min-width:160px" placeholder="Add an ingredient" aria-label="Add an ingredient" /><button class="btn">Add</button></form>
        <button class="btn" id="reIdeas" ${S.thinking ? "disabled" : ""}>Update ideas</button>
      </div>
      <div class="stack">
        <h2>${S.thinking ? "Thinking of dishes…" : S.ideas.length ? `Ideas for ${S.minutes} minutes` : ""}</h2>
        ${raw(S.thinking ? `<div class="progress"><i style="width:60%"></i></div>` : "")}
        <div class="ideas">${raw(S.ideas.map((d, i) => html`
          <article class="card idea">
            <div class="row" style="justify-content:space-between;align-items:baseline"><h3>${d.title}</h3><span class="time">${d.total_minutes} min</span></div>
            <p>${d.summary}</p>
            ${raw(d.uses.length ? html`<p class="uses">Uses: ${d.uses.join(", ")}</p>` : "")}
            ${raw(d.missing.length ? html`<p class="missing">You'd need: ${d.missing.join(", ")}</p>` : "")}
            ${raw(d.over_time ? `<p class="missing">A little over your time limit.</p>` : "")}
            <div class="row"><button class="btn primary" data-idea="${i}">Write this recipe</button></div>
            <div class="progress" hidden><i></i></div>
          </article>`).join(""))}</div>
      </div>`;
    el.querySelectorAll("#items .x").forEach((b) => (b.onclick = () => { S.items.splice(+b.dataset.i, 1); drawResults(true); }));
    $("#addForm").onsubmit = (e) => {
      e.preventDefault();
      const v = $("#addItem").value.trim();
      if (v) { S.items.push(v); drawResults(true); $("#addItem").focus(); }
    };
    $("#reIdeas").onclick = ideas;
    el.querySelectorAll("[data-idea]").forEach((b) => (b.onclick = () => write(+b.dataset.idea, b)));
  }

  async function write(i, btn) {
    const card = btn.closest(".idea");
    const bar = card.querySelector(".progress");
    bar.hidden = false;
    btn.disabled = true;
    btn.textContent = "Writing the recipe…";
    el_disable(true);
    try {
      const evs = await stream("/api/mise/pantry/recipe",
        { json: { idea: S.ideas[i], items: S.items, minutes: S.minutes, servings: S.servings, notes: S.notes } },
        (ev) => { if (ev.type === "progress") bar.firstElementChild.style.width = `${Math.min(95, ev.chars / 18)}%`; });
      const done = evs.find((e) => e.type === "done");
      toast(`Saved “${done.recipe.title}” to your recipe book`);
      S = fresh();
      go("recipe", { id: done.recipe.id, fresh: true });
    } catch (e) {
      toast(e.message);
      btn.disabled = false;
      btn.textContent = "Write this recipe";
      el_disable(false);
    }
  }
  function el_disable(on) { root.querySelectorAll("[data-idea]").forEach((b) => (b.disabled = on || b.disabled)); }

  drawResults();
  if (params.scan) scan();
}

