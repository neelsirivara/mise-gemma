// Full-screen camera, opened from step 1 of the landing page. Snap the fridge or cupboard
// (or pick from the gallery); Done goes back to the steps, which start reading the photos straight away.
import { shrink, snapshot, startCamera, stopCamera } from "/lib/camera.js";
import { $, html, mount, raw, toast } from "../ui.js";
import { photos } from "./pantry.js";

const MAX = 4; // the scan reads up to four photos at once

const ICON = {
  close: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>`,
  help: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.3c-.6.3-1 .8-1 1.5v.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="17" r="1.2" fill="currentColor"/></svg>`,
  torch: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2L5 13.5h6L10 22l8-11.5h-6L13 2z" fill="currentColor"/></svg>`,
  gallery: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2.5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="9" cy="10" r="1.8" fill="currentColor"/><path d="M4 17l5-5 4 4 2.5-2.5L20 18" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>`,
  camera: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 5l1.4-2h4.2l1.4 2H19a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h3.5z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="12" cy="12.5" r="3.8" fill="none" stroke="currentColor" stroke-width="2"/></svg>`,
};

export async function enter(root, _params, app) {
  const shots = photos(); // shared with the pantry view, so photos survive going back and forth
  let cam = "starting"; // starting | live | none

  mount(root, html`
    <section class="capture" aria-label="Photograph your fridge or cupboard">
      <video id="capVideo" playsinline muted autoplay></video>
      <div class="cap-fallback" id="capFallback" hidden>
        <span class="cap-fallback-icon">${raw(ICON.camera)}</span>
        <h1>Show me your fridge or cupboard</h1>
        <p>Take a photo of each shelf. Two or three photos work best.</p>
        <p class="cap-why" id="capWhy"></p>
      </div>
      <div class="cap-frame" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      <div class="cap-flash" id="capFlash" aria-hidden="true"></div>

      <div class="cap-top">
        <button class="cap-round" id="capClose" aria-label="Close the camera">${raw(ICON.close)}</button>
        <p class="cap-hint" id="capHint" role="status" aria-live="polite"></p>
        <div class="cap-top-r">
          <button class="cap-round" id="capTorch" aria-label="Flashlight" aria-pressed="false" hidden>${raw(ICON.torch)}</button>
          <button class="cap-round" id="capHelp" aria-label="Photo tips" aria-expanded="false">${raw(ICON.help)}</button>
        </div>
      </div>

      <div class="cap-tips" id="capTips" hidden>
        <h2>Tips for a good scan</h2>
        <ul>
          <li>One photo per shelf, the fridge door, or the cupboard.</li>
          <li>Turn the label side of jars and packets toward you.</li>
          <li>Good light helps. Up to ${MAX} photos.</li>
        </ul>
        <p class="muted">Gemma reads the photos on this laptop. Nothing leaves the device.</p>
        <button class="btn primary" id="capTipsOk">Got it</button>
      </div>

      <div class="cap-bottom">
        <div class="cap-strip" id="capStrip"></div>
        <div class="cap-controls">
          <button class="cap-pill" id="capGallery">${raw(ICON.gallery)}<span>Gallery</span></button>
          <button class="shutter" id="capShutter" aria-label="Take photo"><span></span></button>
          <button class="cap-pill done" id="capDone" disabled>Done</button>
        </div>
      </div>
    </section>`);

  const video = $("#capVideo");

  function showFallback(e) {
    root.querySelector(".capture").classList.add("no-cam");
    $("#capFallback").hidden = false;
    $("#capWhy").textContent = e?.name === "NotAllowedError"
      ? "Camera permission is off, so the shutter opens your phone's camera app instead."
      : "No live camera here, so the shutter opens your camera app or files instead.";
  }

  function setupTorch() {
    const track = video.srcObject?.getVideoTracks?.()[0];
    if (!track?.getCapabilities?.().torch) return; // Android Chrome has it; iOS Safari doesn't
    const btn = $("#capTorch");
    btn.hidden = false;
    btn.onclick = async () => {
      const on = btn.getAttribute("aria-pressed") !== "true";
      try { await track.applyConstraints({ advanced: [{ torch: on }] }); btn.setAttribute("aria-pressed", on); } catch {}
    };
  }

  // ---- photos
  const picker = (camera) => {
    const input = Object.assign(document.createElement("input"), { type: "file", accept: "image/*", multiple: !camera });
    if (camera) input.setAttribute("capture", "environment");
    input.onchange = async () => {
      for (const f of input.files) { if (shots.length >= MAX) break; shots.push(await shrink(f)); }
      draw();
    };
    input.click();
  };

  function draw() {
    const n = shots.length;
    $("#capStrip").innerHTML = shots.map((p, i) => html`
      <div class="cap-thumb"><img alt="Photo ${i + 1}" src="${URL.createObjectURL(p)}">
        <button data-i="${i}" aria-label="Remove photo ${i + 1}">${raw(ICON.close)}</button></div>`).join("");
    $("#capStrip").querySelectorAll("button").forEach((b) => (b.onclick = () => { shots.splice(+b.dataset.i, 1); draw(); }));
    const done = $("#capDone");
    done.disabled = !n;
    done.textContent = n ? `Done (${n})` : "Done";
    $("#capShutter").disabled = n >= MAX;
    $("#capHint").textContent = !n ? (cam === "none" ? "" : "Point at your fridge or cupboard")
      : n >= MAX ? "That's plenty. Tap Done."
      : "Nice. Add another shelf, or tap Done.";
  }

  $("#capShutter").onclick = async () => {
    if (shots.length >= MAX) return;
    if (cam === "none") return picker(true);
    if (cam === "starting") return toast("The camera is starting…");
    const b = await snapshot(video, 1280);
    if (!b) return toast("The camera isn't ready yet.");
    shots.push(b);
    const f = $("#capFlash");
    f.classList.remove("go"); void f.offsetWidth; f.classList.add("go");
    draw();
  };
  $("#capGallery").onclick = () => picker(false);
  $("#capDone").onclick = () => app.go("pantry", { scan: true });
  $("#capClose").onclick = () => app.go("pantry");

  const tips = (open) => { $("#capTips").hidden = !open; $("#capHelp").setAttribute("aria-expanded", open); };
  $("#capHelp").onclick = () => tips($("#capTips").hidden);
  $("#capTipsOk").onclick = () => tips(false);

  draw();

  // ---- camera last, so the buttons work while the permission prompt is up.
  // Falls back to a plain "take a photo" screen when there's no camera or no permission.
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("this browser can't open the camera here");
    await startCamera(video);
    if (!video.isConnected) { stopCamera(video); return; } // left the screen while it was starting
    cam = "live";
    setupTorch();
  } catch (e) {
    if (!video.isConnected) return;
    cam = "none";
    showFallback(e);
  }
  draw();
}

export function leave() { stopCamera(document.getElementById("capVideo")); }
