// Landing page and "what can I cook?": all four steps on one screen (fridge photo, time, people,
// anything to add) → ingredients → ideas → full recipe.
import { ON_PHONE, postForm, postJSON, stream } from "/lib/api.js";
import { shrink, snapshot, startCamera, stopCamera } from "/lib/camera.js";
import { $, html, mount, raw, toast } from "../ui.js";

const TIMES = [15, 20, 30, 45, 60, 90];
const MAX = 4; // the scan reads up to four photos at once
const EXPAND = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
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
    <section class="landing">
      <header class="intro">
        <p class="tagline">COOK<i>•</i>LEARN<i>•</i>SHARE</p>
        <h1>Cooking teacher like your mum</h1>
        <p class="lead">Tells you what you can cook from what you have in the fridge.</p>
      </header>
      <div class="landing-grid">
        <div class="step-list">
          <section class="card step" aria-labelledby="s1">
            <div class="step-head"><span class="step-n n1" aria-hidden="true">1</span><h2 id="s1">Take a photo of your fridge</h2></div>
            <div class="viewfinder" id="vf">
              <video id="vfVideo" playsinline muted autoplay></video>
              <div class="vf-corners" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
              <div class="vf-off" id="vfOff" hidden>
                <p id="vfWhy">The camera is off.</p>
                <button class="btn" id="vfOn">Turn on the camera</button>
              </div>
              <div class="cap-flash" id="vfFlash" aria-hidden="true"></div>
              <button class="vf-expand" id="vfExpand" aria-label="Open the full-screen camera">${raw(EXPAND)}</button>
              <button class="shutter vf-shutter" id="vfShutter" aria-label="Take photo"><span></span></button>
            </div>
            <div class="photos" id="photos"></div>
            <div class="row between">
              <button class="link" id="upload">or upload a photo</button>
              <span class="muted" id="photoHint"></span>
            </div>
          </section>
          <section class="card step" aria-labelledby="s2">
            <div class="step-head"><span class="step-n n2" aria-hidden="true">2</span><h2 id="s2">How long to cook?</h2></div>
            <div class="seg" id="times" role="group" aria-labelledby="s2">
              ${raw(TIMES.map((m) => html`<button data-m="${m}" aria-pressed="${m === S.minutes}">${m} min</button>`).join(""))}
            </div>
          </section>
          <section class="card step step-row" aria-labelledby="s3">
            <div class="step-head"><span class="step-n n3" aria-hidden="true">3</span><h2 id="s3">Cooking for</h2></div>
            <span class="stepper"><button id="less" aria-label="Fewer people">−</button><output id="serv" aria-labelledby="s3">${S.servings}</output><span class="unit" id="ppl">${S.servings === 1 ? "person" : "people"}</span><button id="more" aria-label="More people">+</button></span>
          </section>
          <section class="card step" aria-labelledby="s4">
            <div class="step-head"><span class="step-n n4" aria-hidden="true">4</span><h2 id="s4"><label for="notes">Anything to add?</label></h2></div>
            <input class="text-in" id="notes" placeholder="Dietary needs, allergies, no oven…" value="${S.notes}" />
          </section>
          <button class="btn primary big" id="find">See what I can cook</button>
        </div>
        <div class="stack results" id="results"></div>
      </div>
    </section>`);

  const go = (v, p) => app.go(v, p);
  const video = $("#vfVideo");
  let cam = "starting"; // starting | live | none

  // ---- step 1: live camera in the page; upload is the secondary way in
  const pick = (camera) => {
    const input = Object.assign(document.createElement("input"), { type: "file", accept: "image/*", multiple: !camera });
    if (camera) input.setAttribute("capture", "environment"); // phones open the camera app
    input.onchange = async () => {
      for (const f of input.files) { if (S.photos.length >= MAX) break; S.photos.push(await shrink(f)); }
      drawPhotos(); scan();
    };
    input.click();
  };
  function drawPhotos() {
    const n = S.photos.length;
    $("#photos").innerHTML = S.photos.map((p, i) => html`<div class="photo"><img alt="Fridge photo ${i + 1}" src="${URL.createObjectURL(p)}"><button aria-label="Remove photo ${i + 1}" data-i="${i}">×</button></div>`).join("");
    $("#photos").querySelectorAll(".photo button").forEach((b) => (b.onclick = () => { S.photos.splice(+b.dataset.i, 1); drawPhotos(); }));
    $("#photoHint").textContent = !n ? "Two or three photos work best" : n >= MAX ? `${n} photos, that's plenty` : `${n} photo${n > 1 ? "s" : ""}`;
    $("#vfShutter").disabled = n >= MAX;
  }
  drawPhotos();
  $("#upload").onclick = () => pick(false);
  $("#vfExpand").onclick = () => go("capture");
  $("#vfShutter").onclick = async () => {
    if (S.photos.length >= MAX) return;
    if (cam === "none") return pick(true);
    if (cam === "starting") return toast("The camera is starting…");
    const b = await snapshot(video, 1280);
    if (!b) return toast("The camera isn't ready yet.");
    S.photos.push(b);
    const f = $("#vfFlash"); f.classList.remove("go"); void f.offsetWidth; f.classList.add("go");
    drawPhotos(); scan();
  };
  async function camOn() {
    cam = "starting";
    $("#vf").classList.remove("off"); $("#vfOff").hidden = true;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("no camera API here");
      await startCamera(video);
      if (!video.isConnected) { stopCamera(video); return; } // left the page while it was starting
      cam = "live";
    } catch (e) {
      if (!video.isConnected) return;
      cam = "none";
      $("#vf").classList.add("off"); $("#vfOff").hidden = false;
      $("#vfWhy").textContent = e?.name === "NotAllowedError"
        ? "Camera permission is off. The shutter opens your camera app instead."
        : "No live camera here. The shutter opens your camera app or files instead.";
    }
  }
  $("#vfOn").onclick = camOn;

  // ---- steps 2-4
  root.querySelectorAll("#times button").forEach((b) => (b.onclick = () => {
    S.minutes = +b.dataset.m;
    root.querySelectorAll("#times button").forEach((x) => x.setAttribute("aria-pressed", x === b));
  }));
  const serv = (d) => {
    S.servings = Math.max(1, Math.min(12, S.servings + d));
    $("#serv").textContent = S.servings;
    $("#ppl").textContent = S.servings === 1 ? "person" : "people";
  };
  $("#less").onclick = () => serv(-1);
  $("#more").onclick = () => serv(1);
  $("#notes").oninput = (e) => (S.notes = e.target.value);

  // ---- scan: read new photos as soon as they're taken, so the ingredients are
  // ready by the time steps 2-4 are filled in. Resolves true unless the scan failed.
  function scan() {
    if (S.scanP) return S.scanP;
    const todo = S.photos.filter((p) => !S.scanned.has(p));
    if (!todo.length) return Promise.resolve(true);
    const st = S;
    st.scanning = true; st.ideas = []; drawResults();
    st.scanP = (async () => {
      let ok = false;
      try {
        const fd = new FormData();
        todo.forEach((p, i) => fd.append("images", p, `photo${i}.jpg`));
        const r = await postForm("/api/mise/pantry/scan", fd);
        todo.forEach((p) => st.scanned.add(p));
        st.items = [...new Set([...r.items, ...st.items])];
        ok = true;
      } catch (e) { toast(e.message); }
      st.scanning = false; st.scanP = null;
      if (S === st) drawResults();
      return ok;
    })();
    return st.scanP;
  }

  // ---- find: finish reading every photo (including ones taken mid-scan), then ideas
  $("#find").onclick = async () => {
    if (!S.photos.length && !S.items.length) { toast("Take a photo of your fridge first, or add ingredients by hand."); drawResults(true); return; }
    while (S.photos.some((p) => !S.scanned.has(p))) { if (!(await scan())) break; }
    if (S.scanP) await S.scanP;
    requestAnimationFrame(() => $("#results")?.scrollIntoView({ behavior: "smooth", block: "start" }));
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
    if (S.scanning) { el.innerHTML = `<div class="card stack"><h2>Looking in your fridge…</h2><div class="progress"><i style="width:40%"></i></div><p class="muted">Gemma is reading the photos on this ${ON_PHONE ? "phone" : "laptop"}.</p></div>`; return; }
    if (!S.items.length && !forceItems && !S.ideas.length) {
      el.innerHTML = ""; // nothing yet: the four steps are the whole screen
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
  camOn(); // last, so every button works while the permission prompt is up
}

export function leave() { stopCamera(document.getElementById("vfVideo")); }
