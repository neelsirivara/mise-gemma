// "Run Gemma on this phone": the one-time model download (2 GB) and start-up for on-phone mode.
// The model comes from the paired laptop over local Wi-Fi when it's reachable (seconds to minutes),
// otherwise from Hugging Face. After that Mise needs neither the laptop nor the internet.
import { HUB, switchEngine } from "/lib/api.js";
import { MODEL, phoneLLM, phoneSupported } from "/lib/phone/llm.js";
import { $, html, mount, raw } from "../ui.js";

const GB = (b) => (b / 1e9).toFixed(1);
let off = null;

// A laptop running Mise that has the phone build of the model, if one answers quickly.
async function laptopSource() {
  for (const hub of [HUB, "https://mise.local:8443"].filter(Boolean)) {
    try {
      const meta = await (await fetch(`${hub}/api/meta`, { cache: "no-store", signal: AbortSignal.timeout(2500) })).json();
      if (meta.phone_model) return `${hub}/models/${meta.phone_model}`;
    } catch {}
  }
  return null;
}

export async function enter(root, params, app) {
  const llm = phoneLLM();
  if (!phoneSupported()) {
    mount(root, html`
      <section class="card stack phone-setup">
        <h1>This browser can't run Gemma</h1>
        <p class="muted">Running Gemma on the phone needs WebGPU (Safari on iOS 26, or a recent Chrome), or the Mise iPhone app.
          You can still cook with Mise running on your laptop.</p>
        <div class="row"><button class="btn primary" id="useLaptop">Use my laptop</button></div>
      </section>`);
    $("#useLaptop").onclick = () => switchEngine("laptop");
    return;
  }
  mount(root, html`
    <section class="card stack phone-setup" aria-labelledby="phoneTitle">
      <p class="eyebrow">On this phone</p>
      <h1 id="phoneTitle">Run Gemma on this phone</h1>
      <p class="muted">Mise downloads ${MODEL.label} once (about 2 GB). After that it cooks with you right here:
        no laptop, no internet, nothing leaves your phone.</p>
      <div class="stack" id="progressBox" hidden>
        <div class="progress" aria-hidden="true"><i id="bar"></i></div>
        <p class="row between"><span id="pState">Downloading…</span><span class="muted" id="pBytes"></span></p>
      </div>
      <p class="muted" id="pSource"></p>
      <p class="error" id="pError" role="alert" hidden></p>
      <div class="row">
        <button class="btn primary big" id="go">Download Gemma (2 GB)</button>
        <button class="btn ghost" id="useLaptop">Use my laptop instead</button>
      </div>
      <p class="muted small" id="pHint">Keep Mise open while it downloads. Wi-Fi is best; plug in if your battery is low.</p>
    </section>`);
  $("#useLaptop").onclick = () => switchEngine("laptop");

  let wake = null;
  const draw = (st) => {
    if (!$("#go")) return;
    const busy = st.downloading || st.loading;
    $("#progressBox").hidden = !(busy || st.bytes > 0 || st.progress > 0);
    $("#bar").style.width = `${Math.round((st.progress || 0) * 100)}%`;
    $("#pBytes").textContent = st.total ? `${GB(st.bytes || 0)} of ${GB(st.total)} GB` : "";
    $("#pState").textContent = st.loading ? "Starting Gemma on this phone…" : st.downloading ? "Downloading…"
      : st.ready ? "Ready" : st.cached ? "Downloaded" : st.progress > 0 ? "Paused" : "";
    $("#pError").hidden = !st.error;
    $("#pError").textContent = st.error || "";
    $("#go").disabled = busy;
    $("#go").textContent = st.ready ? "Start cooking" : st.cached ? "Start Gemma" : st.progress > 0 ? "Resume download" : "Download Gemma (2 GB)";
  };
  off = llm.onStatus(draw);
  draw(await llm.status());

  const start = async () => {
    try { wake = await navigator.wakeLock?.request("screen"); } catch {}
    try {
      const src = llm.kind === "web" ? await laptopSource() : null;
      $("#pSource").textContent = llm.kind === "native" ? "" : src ? "Copying from your laptop over Wi-Fi." : "Downloading from Hugging Face.";
      await llm.load(src ? [src, MODEL.url] : [MODEL.url]);
      draw(llm.st);
      app.go(params.then || "pantry", params.thenParams || {});
    } catch {
      draw(llm.st);
    } finally {
      try { await wake?.release(); } catch {}
    }
  };
  $("#go").onclick = start;
  // already downloaded (or the iOS app has the model): just start it
  if (llm.st.ready) app.go(params.then || "pantry", params.thenParams || {});
  else if (llm.st.cached || llm.kind === "native") start();
}

export function leave() {
  off?.();
  off = null;
}
