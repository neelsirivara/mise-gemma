// Generic front-end for every scaffold: camera + mic capture, streaming chat,
// spoken replies, an always-on watch loop, and app-specific panels from /api/state.
const $ = (id) => document.getElementById(id);

// Where the models run. Empty = this page's own server (the laptop). When the page is hosted
// elsewhere (e.g. Vercel), point it at the laptop with ?hub=https://<laptop-ip>:8443 or the ⚙ button.
const HUB = (() => {
  const q = new URLSearchParams(location.search).get("hub");
  try {
    if (q !== null) q ? localStorage.setItem("hub", q) : localStorage.removeItem("hub");
    return (q ?? localStorage.getItem("hub") ?? "").replace(/\/$/, "");
  } catch { return (q || "").replace(/\/$/, ""); }
})();
const api = (path) => HUB + path;
const isPhone = matchMedia("(pointer: coarse)").matches;
const S = {
  meta: null, since: 0, busy: false, speaking: false, stillBlob: null,
  watchTimer: null, lastSee: "", recording: false,
};

// ------------------------------------------------------------------ boot
async function boot() {
  try {
    S.meta = await (await fetch(api("/api/meta"))).json();
  } catch {
    // no hub reachable yet: say where we looked, offer the hub dialog, keep retrying
    $("talkPill").textContent = `no Mise hub at ${HUB || location.host}`;
    $("talkPill").style.color = "var(--bad)";
    if (!S.askedHub) { S.askedHub = true; openHub(); }
    setTimeout(boot, 3000);
    return;
  }
  document.title = S.meta.name;
  $("appName").textContent = S.meta.name;
  $("tagline").textContent = S.meta.tagline;
  document.documentElement.style.setProperty("--accent", S.meta.accent);
  $("watchToggle").checked = false;
  $("frameToggle").checked = S.meta.attach_frame;
  for (const q of S.meta.quick_prompts) {
    const b = document.createElement("button");
    b.textContent = q;
    b.onclick = () => send({ text: q });
    $("quick").appendChild(b);
  }
  await startCamera();
  // demo safety net: http://127.0.0.1:8000/?still=test/Guacamole_IMGP1271.jpg pins a known-good frame
  const still = new URLSearchParams(location.search).get("still");
  if (still) {
    const blob = await (await fetch(api("/assets/" + still))).blob();
    useStill(new File([blob], still.split("/").pop(), { type: blob.type }));
  }
  pollState();
  setInterval(pollState, 1000);
  updateNet();
  addEventListener("online", updateNet);
  addEventListener("offline", updateNet);
  sys(`${S.meta.name} ready. Hold Space or the mic to talk. Everything runs on this laptop.`);
}

function openHub() {
  $("hubInput").value = HUB;
  if (!$("hubDialog").open) $("hubDialog").showModal();
}
$("hubBtn").onclick = openHub;
$("hubDialog").addEventListener("close", () => {
  if ($("hubDialog").returnValue !== "save") return;
  const v = $("hubInput").value.trim();
  const u = new URL(location.href);
  u.searchParams.set("hub", v);
  location.href = u.toString(); // reload against the new hub (empty = this server)
});

if ("serviceWorker" in navigator && isSecureContext) navigator.serviceWorker.register("sw.js").catch(() => {});

function updateNet() {
  const p = $("netPill");
  p.textContent = navigator.onLine ? "network on (not used)" : "✈ fully offline";
  p.className = "pill " + (navigator.onLine ? "online" : "offline");
}

// ------------------------------------------------------------------ camera
async function startCamera(deviceId) {
  try {
    // phones default to the back camera, pointed at the counter; fall back to any camera
    const want = deviceId ? { deviceId: { exact: deviceId }, width: 1280, height: 720 }
      : isPhone ? { facingMode: { ideal: "environment" }, width: 1280, height: 720 } : { width: 1280, height: 720 };
    const stream = await navigator.mediaDevices.getUserMedia({ video: want, audio: false })
      .catch(() => navigator.mediaDevices.getUserMedia({ video: true, audio: false }));
    const v = $("video");
    if (v.srcObject) v.srcObject.getTracks().forEach((t) => t.stop());
    v.srcObject = stream;
    $("caption").textContent = "camera live";
    const devs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
    const sel = $("camSelect");
    const cur = stream.getVideoTracks()[0].getSettings().deviceId;
    sel.innerHTML = "";
    devs.forEach((d, i) => {
      const o = document.createElement("option");
      o.value = d.deviceId;
      o.textContent = d.label || `Camera ${i + 1}`;
      o.selected = d.deviceId === cur;
      sel.appendChild(o);
    });
  } catch (e) {
    $("caption").textContent = "No camera: use 🖼️ to load an image instead (" + e.name + ")";
  }
}
$("camSelect").onchange = (e) => startCamera(e.target.value);

function grabFrame(maxW = 768) {
  if (S.stillBlob) return Promise.resolve(S.stillBlob);
  const v = $("video");
  if (!v.videoWidth) return Promise.resolve(null);
  const scale = Math.min(1, maxW / v.videoWidth);
  const c = document.createElement("canvas");
  c.width = Math.round(v.videoWidth * scale);
  c.height = Math.round(v.videoHeight * scale);
  c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
  return new Promise((r) => c.toBlob(r, "image/jpeg", 0.85));
}

// Demo safety net: freeze on a known-good image instead of the live camera.
$("fileInput").onchange = (e) => e.target.files[0] && useStill(e.target.files[0]);
function useStill(f) {
  S.stillBlob = f;
  $("still").src = URL.createObjectURL(f);
  $("still").hidden = false;
  $("video").hidden = true;
  $("liveBtn").hidden = false;
  $("caption").textContent = "using still image: " + f.name;
}
$("liveBtn").onclick = () => {
  S.stillBlob = null;
  $("still").hidden = true;
  $("video").hidden = false;
  $("liveBtn").hidden = true;
  $("caption").textContent = "camera live";
};
$("camWrap").addEventListener("dragover", (e) => e.preventDefault());
$("camWrap").addEventListener("drop", (e) => {
  e.preventDefault();
  const f = e.dataTransfer.files[0];
  if (f) useStill(f);
});

// ------------------------------------------------------------------ microphone (16 kHz mono WAV)
const Mic = {
  ctx: null, node: null, rate: 48000, chunks: [], preroll: [], noise: 0.01,
  voiced: 0, silentMs: 0, startedAt: 0,
  async init() {
    if (this.ctx) return;
    // iOS: the AudioContext must be created inside the tap, before any await
    this.ctx = new AudioContext();
    this.rate = this.ctx.sampleRate;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    await this.ctx.resume();
    const src = this.ctx.createMediaStreamSource(stream);
    this.node = this.ctx.createScriptProcessor(2048, 1, 1);
    src.connect(this.node);
    this.node.connect(this.ctx.destination);
    this.node.onaudioprocess = (e) => this.onFrame(new Float32Array(e.inputBuffer.getChannelData(0)));
  },
  onFrame(buf) {
    const frameMs = (buf.length / this.rate) * 1000;
    let rms = 0;
    for (const x of buf) rms += x * x;
    rms = Math.sqrt(rms / buf.length);
    if (S.recording) {
      this.chunks.push(buf);
      if (S.recording === "vad") {
        const thr = Math.max(0.012, this.noise * 3);
        this.silentMs = rms < thr ? this.silentMs + frameMs : 0;
        const dur = performance.now() - this.startedAt;
        if (this.silentMs > 900 || dur > 15000) stopRecording(true);
      }
      return;
    }
    // idle: track noise floor + keep a short pre-roll; hands-free VAD trigger
    this.noise = 0.95 * this.noise + 0.05 * Math.min(rms, 0.05);
    this.preroll.push(buf);
    if (this.preroll.length > 8) this.preroll.shift();
    if ($("handsFree").checked && !S.busy && !S.speaking) {
      const thr = Math.max(0.02, this.noise * 4);
      this.voiced = rms > thr ? this.voiced + 1 : 0;
      if (this.voiced >= 3) startRecording("vad");
    }
  },
  wav() {
    const all = [...this.chunks];
    const len = all.reduce((a, b) => a + b.length, 0);
    const pcm = new Float32Array(len);
    let o = 0;
    for (const c of all) { pcm.set(c, o); o += c.length; }
    // naive decimation to 16 kHz with box filter
    const ratio = this.rate / 16000;
    const n = Math.floor(pcm.length / ratio);
    const out = new Int16Array(n);
    for (let i = 0; i < n; i++) {
      let s = 0, k = 0;
      for (let j = Math.floor(i * ratio); j < Math.floor((i + 1) * ratio) && j < pcm.length; j++) { s += pcm[j]; k++; }
      out[i] = Math.max(-1, Math.min(1, s / (k || 1))) * 0x7fff;
    }
    const buf = new ArrayBuffer(44 + out.length * 2);
    const dv = new DataView(buf);
    const w = (p, s) => [...s].forEach((ch, i) => dv.setUint8(p + i, ch.charCodeAt(0)));
    w(0, "RIFF"); dv.setUint32(4, 36 + out.length * 2, true); w(8, "WAVE"); w(12, "fmt ");
    dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
    dv.setUint32(24, 16000, true); dv.setUint32(28, 32000, true); dv.setUint16(32, 2, true);
    dv.setUint16(34, 16, true); w(36, "data"); dv.setUint32(40, out.length * 2, true);
    new Int16Array(buf, 44).set(out);
    return { blob: new Blob([buf], { type: "audio/wav" }), seconds: n / 16000 };
  },
};

async function startRecording(mode = "ptt") {
  if (S.recording || S.busy) return;
  await Mic.init();
  speechSynthesis.cancel();
  Mic.chunks = [...Mic.preroll];
  Mic.silentMs = 0;
  Mic.startedAt = performance.now();
  S.recording = mode;
  $("micBtn").classList.add("rec");
  $("listening").hidden = false;
}

function stopRecording(sendIt = true) {
  if (!S.recording) return;
  S.recording = false;
  $("micBtn").classList.remove("rec");
  $("listening").hidden = true;
  const { blob, seconds } = Mic.wav();
  if (sendIt && seconds > 0.4) send({ audio: blob, seconds });
}

const mic = $("micBtn");
mic.addEventListener("pointerdown", (e) => { e.preventDefault(); startRecording("ptt"); });
mic.addEventListener("pointerup", () => stopRecording(true));
mic.addEventListener("pointerleave", () => S.recording === "ptt" && stopRecording(true));
mic.addEventListener("pointercancel", () => S.recording === "ptt" && stopRecording(true));
mic.addEventListener("contextmenu", (e) => e.preventDefault()); // long-press menu on phones
// iOS only lets speechSynthesis talk after it has spoken once inside a tap
addEventListener("pointerdown", () => speechSynthesis.speak(new SpeechSynthesisUtterance("")), { once: true });
addEventListener("keydown", (e) => {
  if (e.code === "Space" && document.activeElement !== $("text") && !e.repeat) { e.preventDefault(); startRecording("ptt"); }
});
addEventListener("keyup", (e) => {
  if (e.code === "Space" && document.activeElement !== $("text")) { e.preventDefault(); stopRecording(true); }
});
$("handsFree").onchange = async (e) => { if (e.target.checked) await Mic.init(); };

// ------------------------------------------------------------------ speech out (local voices only)
let voice = null;
function pickVoice() {
  const vs = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
  voice = vs.find((v) => v.localService && /aria|jenny|zira|natural/i.test(v.name)) || vs.find((v) => v.localService) || null;
}
speechSynthesis.onvoiceschanged = pickVoice;
pickVoice();

function speak(text, { interrupt = false } = {}) {
  if (!$("speakToggle").checked || !text.trim()) return;
  if (interrupt) speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  if (voice) u.voice = voice;
  u.rate = 1.05;
  u.onstart = () => (S.speaking = true);
  u.onend = u.onerror = () => (S.speaking = speechSynthesis.speaking);
  speechSynthesis.speak(u);
}

function beep() {
  try {
    const c = Mic.ctx || new AudioContext();
    [0, 0.25, 0.5].forEach((t) => {
      const o = c.createOscillator(), g = c.createGain();
      o.frequency.value = 880; o.connect(g); g.connect(c.destination);
      g.gain.setValueAtTime(0.2, c.currentTime + t); g.gain.exponentialRampToValueAtTime(0.001, c.currentTime + t + 0.2);
      o.start(c.currentTime + t); o.stop(c.currentTime + t + 0.2);
    });
  } catch {}
}

// ------------------------------------------------------------------ chat
function addMsg(cls, html) {
  const d = document.createElement("div");
  d.className = "msg " + cls;
  d.innerHTML = html;
  $("chat").appendChild(d);
  $("chat").scrollTop = 1e9;
  return d;
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const sys = (t) => addMsg("sys", esc(t));

const queue = [];
async function send(msg) {
  if (S.busy) { queue.push(msg); return; } // typed/spoken while the model is answering: run next
  await sendNow(msg);
  while (queue.length) await sendNow(queue.shift());
}

async function sendNow({ text = "", audio = null, seconds = 0 }) {
  S.busy = true;
  mic.classList.add("busy");
  const fd = new FormData();
  if (text) fd.append("text", text);
  if (audio) fd.append("audio", audio, "speech.wav");
  const frame = $("frameToggle").checked ? await grabFrame() : null;
  if (frame) fd.append("image", frame, "frame.jpg");
  const um = addMsg("user", text ? esc(text) : `🎙️ <i>${seconds.toFixed(1)}s of speech</i>`);
  if (frame) um.innerHTML += ` <span class="chip">+frame</span>`;
  const bot = addMsg("bot", "…");
  let full = "", spoken = 0, chips = "";
  try {
    const res = await fetch(api("/api/chat"), { method: "POST", body: fd });
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 1);
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.type === "text") {
          full += ev.text;
          // speak sentence-by-sentence as text streams in
          const m = full.slice(spoken).match(/^[\s\S]*?[.!?](\s|$)/);
          if (m && !/^\s*NOOP/i.test(full)) { speak(m[0]); spoken += m[0].length; }
        } else if (ev.type === "tool") {
          chips += `<span class="chip">⚙ ${esc(ev.name)}(${esc(JSON.stringify(ev.args))})</span>`;
        } else if (ev.type === "error") {
          full += `\n[error] ${ev.error}`;
        } else if (ev.type === "done") {
          if (ev.noop) { bot.remove(); um.innerHTML += ' <span class="chip">ignored</span>'; }
          $("metrics").textContent = `last turn: first token ${ev.ttft_s}s · total ${ev.total_s}s · ${ev.audio ? "audio " : ""}${ev.image ? "image " : ""}in · ${$("metrics").dataset.mem || ""}`;
        }
        bot.innerHTML = (chips ? chips + "<br>" : "") + esc(full || "…");
        $("chat").scrollTop = 1e9;
      }
    }
    if (!/^\s*NOOP/i.test(full)) speak(full.slice(spoken));
  } catch (e) {
    bot.textContent = e instanceof TypeError
      ? `Can't reach the server at ${location.host}. Check that run.cmd is still running in its window and that this tab's address matches the port it printed (default 8000).`
      : "Error: " + e;
  } finally {
    S.busy = false;
    mic.classList.remove("busy");
    pollState();
  }
}

$("form").onsubmit = (e) => {
  e.preventDefault();
  const t = $("text").value.trim();
  if (t) { $("text").value = ""; send({ text: t }); }
};
$("resetBtn").onclick = async () => { await fetch(api("/api/reset"), { method: "POST" }); $("chat").innerHTML = ""; sys("Reset."); };

// ------------------------------------------------------------------ watch loop
$("watchToggle").onchange = (e) => {
  clearInterval(S.watchTimer);
  if (e.target.checked) { watchTick(); S.watchTimer = setInterval(watchTick, S.meta.watch_interval_s * 1000); }
  else $("caption").textContent = S.stillBlob ? "using still image" : "camera live";
};

async function watchTick() {
  if (S.busy) return; // conversation has priority on a shared engine
  const frame = await grabFrame(640);
  if (!frame) return;
  const fd = new FormData();
  fd.append("image", frame, "frame.jpg");
  try {
    const r = await (await fetch(api("/api/watch"), { method: "POST", body: fd })).json();
    if (r.skipped) return;
    $("caption").innerHTML = `<b>sees</b> ${esc(r.see)} <small style="opacity:.6">· ${r.latency_s}s</small>`;
    if (S.meta.speak_watch && r.see && novel(r.see, S.lastSee) && !S.busy && !S.recording) speak(r.see);
    S.lastSee = r.see;
  } catch {}
}

// only narrate scene descriptions that actually changed (word overlap < 50%)
function novel(a, b) {
  const wa = new Set(a.toLowerCase().match(/[a-z]{3,}/g) || []), wb = new Set((b || "").toLowerCase().match(/[a-z]{3,}/g) || []);
  if (!wb.size) return true;
  const inter = [...wa].filter((w) => wb.has(w)).length;
  return inter / Math.max(1, Math.min(wa.size, wb.size)) < 0.5;
}

// ------------------------------------------------------------------ state poll
let alertTimer = null;
async function pollState() {
  let st;
  try {
    st = await (await fetch(api("/api/state?since=" + S.since))).json();
  } catch {
    $("talkPill").textContent = `server not reachable at ${location.host}: is run.cmd still running?`;
    $("talkPill").style.color = "var(--bad)";
    return;
  }
  $("talkPill").style.color = "";
  const e = st.engine;
  $("talkPill").textContent = "talk: " + (e.load_error ? "ERROR" : e.talk + (e.ready ? "" : " (warming up…)"));
  $("watchPill").textContent = "watch: " + e.watch;
  if (e.load_error && !S.shownErr) { S.shownErr = true; sys("Model load failed: " + e.load_error); }

  $("panels").innerHTML = st.panels.map((p) => {
    const tag = p.kind === "steps" ? "ol" : "ul";
    return `<div class="panel"><h2>${esc(p.title)}</h2><${tag}>${p.items.map((i) => `<li class="${i.state}">${esc(i.text)}</li>`).join("")}</${tag}></div>`;
  }).join("");

  $("timers").innerHTML = st.timers.filter((t) => !t.fired || t.remaining > -30).map((t) => {
    const r = Math.ceil(t.remaining), pct = 100 * (1 - t.remaining / t.seconds);
    return `<div class="timer ${t.fired ? "fired" : ""}"><small>${esc(t.label)}</small><b>${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}</b><div class="bar" style="width:${pct}%"></div></div>`;
  }).join("");

  $("metrics").dataset.mem = `memory: ${e.memory} moments (${e.embedder})`;
  const first = !S.polled;
  S.polled = true;
  for (const ev of st.events) {
    S.since = Math.max(S.since, ev.t);
    if (first) continue; // don't replay old events after a page reload
    if (ev.kind === "recall") {
      addMsg("sys", `🧠 recalled for “${esc(ev.query)}”<br>` + ev.ids.map((id) => `<img class="thumb" src="${api(`/api/memory/${id}.jpg`)}">`).join(""));
    }
    if (ev.kind === "timer_done") { beep(); speak(`${ev.label} timer is done.`, { interrupt: true }); toast(`⏰ ${ev.label} done`); }
    if (ev.kind === "alert") showAlert(ev.text);
    if (ev.kind === "suggest") toast(ev.text);
  }
}

function showAlert(text) {
  $("alert").textContent = "⚠ " + text;
  $("alert").hidden = false;
  speak(text, { interrupt: true });
  clearTimeout(alertTimer);
  alertTimer = setTimeout(() => ($("alert").hidden = true), 6000);
}

function toast(t) {
  $("toast").textContent = t;
  $("toast").hidden = false;
  clearTimeout(S.toastT);
  S.toastT = setTimeout(() => ($("toast").hidden = true), 4000);
}

boot();
