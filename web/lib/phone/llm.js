// Gemma 4 running on the phone itself. Two engines behind one interface:
//   native: the Mise iOS app (ios/) runs LiteRT-LM on the iPhone's GPU and exposes it as window.MiseNative
//   web:    MediaPipe's LLM Inference in the browser on WebGPU, with the model kept in the Cache API
// Both answer status(), load(), generate({system, parts, maxTokens}, onChunk) → full text.
// parts: [{text}] | [{image: Blob}] | [{audio: Blob (16 kHz WAV)}]

const GENAI = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-genai@0.10.29";
export const MODEL = {
  name: "gemma-4-E2B-it-gpu.litertlm",
  label: "Gemma 4 E2B",
  bytes: 2_008_432_640, // refreshed from the server's Content-Length when the download starts
  url: "https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/gemma-4-E2B-it-gpu.litertlm",
};
const CACHE = "mise-model-v1";
const CHUNK = 32 << 20; // download in 32 MB pieces, so a dropped connection or a backgrounded tab resumes

// ------------------------------------------------------------------ prompt format (Gemma 4 chat template)
const turn = (role, body) => `<|turn>${role}\n${body}<turn|>\n`;
const clean = (t) => t.replace(/<turn\|>[\s\S]*$/, "").replace(/<\|turn>model\n?/g, "");

// ------------------------------------------------------------------ one-at-a-time queue (engines are exclusive)
function serial() {
  let tail = Promise.resolve();
  return (fn) => { const run = tail.then(fn, fn); tail = run.catch(() => {}); return run; };
}

const b64 = (blob) => new Promise((ok, bad) => {
  const r = new FileReader();
  r.onload = () => ok(String(r.result).split(",")[1]);
  r.onerror = () => bad(r.error);
  r.readAsDataURL(blob);
});

// ================================================================== native (iOS app)
class NativeLLM {
  kind = "native";
  #n = 0;
  #pending = new Map();
  #listeners = new Set();
  st = { ready: false, downloading: false, progress: 0, model: MODEL.label, backend: "gpu", vision: true, audio: true };

  constructor() {
    window.MiseNative.onMessage = (m) => {
      if (m.type === "status") { this.st = { ...this.st, ...m.status }; this.#listeners.forEach((f) => f(this.st)); return; }
      const p = this.#pending.get(m.id);
      if (!p) return;
      if (m.type === "chunk") { p.text += m.text; p.onChunk(m.text); }
      else if (m.type === "done") { this.#pending.delete(m.id); p.ok(clean(m.cancelled || !m.text ? p.text : m.text)); }
      else if (m.type === "error") { this.#pending.delete(m.id); p.bad(new Error(m.message)); }
      else { this.#pending.delete(m.id); if (m.status) this.st = { ...this.st, ...m.status }; p.ok(m); }
    };
  }

  #call(msg, onChunk = () => {}) {
    const id = `m${++this.#n}`;
    return new Promise((ok, bad) => {
      this.#pending.set(id, { ok, bad, onChunk, text: "" });
      window.MiseNative.post({ ...msg, id });
    });
  }

  onStatus(fn) { this.#listeners.add(fn); return () => this.#listeners.delete(fn); }
  async status() { const r = await this.#call({ op: "status" }); return (this.st = { ...this.st, ...r.status }); }
  async load() { await this.#call({ op: "load" }); return this.status(); }

  async generate({ system = "", parts, maxTokens = 512, temperature = 0.6 }, onChunk = () => {}) {
    const wire = [];
    for (const p of parts) {
      if (p.text != null) wire.push({ text: p.text });
      else if (p.image) wire.push({ image: await b64(p.image) });
      else if (p.audio) wire.push({ audio: await b64(p.audio) });
    }
    return this.#call({ op: "generate", system, parts: wire, maxTokens, temperature }, onChunk);
  }
}

// ================================================================== web (MediaPipe + WebGPU)
class WebLLM {
  kind = "web";
  #llm = null;
  #queue = serial();
  #listeners = new Set();
  st = { ready: false, downloading: false, progress: 0, bytes: 0, total: MODEL.bytes, model: MODEL.label,
         backend: "webgpu", vision: false, audio: false, cached: false, error: null };

  #set(patch) { this.st = { ...this.st, ...patch }; this.#listeners.forEach((f) => f(this.st)); }
  onStatus(fn) { this.#listeners.add(fn); return () => this.#listeners.delete(fn); }

  static supported() { return !!navigator.gpu; }

  async #pieces() {
    const c = await caches.open(CACHE);
    const meta = await c.match("/__model/meta").then((r) => r?.json()).catch(() => null);
    return { c, meta };
  }

  async status() {
    if (!this.st.ready && !this.st.downloading) {
      const { c, meta } = await this.#pieces();
      if (meta) {
        const have = (await c.keys()).filter((k) => k.url.includes("/__model/part-")).length;
        const bytes = Math.min(meta.total, have * CHUNK);
        this.#set({ total: meta.total, bytes, progress: bytes / meta.total, cached: have >= meta.parts });
      }
    }
    return this.st;
  }

  // The model comes from the laptop when one is paired (fast, local Wi-Fi), otherwise from Hugging Face.
  async download(sources = [MODEL.url]) {
    if (this.st.downloading) return;
    this.#set({ downloading: true, error: null });
    try { await navigator.storage?.persist?.(); } catch {}
    try {
      const { c } = await this.#pieces();
      let src = null, total = 0;
      for (const s of sources) {
        try {
          const r = await fetch(s, { headers: { Range: "bytes=0-0" } });
          const m = /\/(\d+)$/.exec(r.headers.get("Content-Range") || "");
          if (r.ok && m) { src = s; total = +m[1]; break; }
        } catch {}
      }
      if (!src) throw new Error("Couldn't reach the model download. Check the internet connection (or that Mise is running on the laptop).");
      const parts = Math.ceil(total / CHUNK);
      await c.put("/__model/meta", new Response(JSON.stringify({ total, parts, name: MODEL.name })));
      const have = new Set((await c.keys()).map((k) => new URL(k.url).pathname));
      let done = [...have].filter((p) => p.startsWith("/__model/part-")).length * CHUNK;
      this.#set({ total, bytes: Math.min(done, total), progress: Math.min(done, total) / total });
      for (let i = 0; i < parts; i++) {
        const key = `/__model/part-${String(i).padStart(4, "0")}`;
        if (have.has(key)) continue;
        const a = i * CHUNK, b = Math.min(total, a + CHUNK) - 1;
        let buf = null;
        for (let attempt = 0; attempt < 6 && !buf; attempt++) {
          try {
            const r = await fetch(src, { headers: { Range: `bytes=${a}-${b}` } });
            if (r.status !== 206) throw new Error(`HTTP ${r.status}`);
            const got = await r.arrayBuffer();
            if (got.byteLength !== b - a + 1) throw new Error("short read");
            buf = got;
          } catch (e) {
            if (attempt === 5) throw e;
            await new Promise((ok) => setTimeout(ok, 1500 * (attempt + 1)));
          }
        }
        await c.put(key, new Response(buf));
        done += buf.byteLength;
        this.#set({ bytes: Math.min(done, total), progress: Math.min(done, total) / total });
      }
      this.#set({ downloading: false, cached: true, progress: 1 });
    } catch (e) {
      this.#set({ downloading: false, error: e.message || String(e) });
      throw e;
    }
  }

  // Stream the cached pieces straight into the engine (never holds 2 GB in JS memory at once).
  async #modelReader() {
    const { c, meta } = await this.#pieces();
    let i = 0;
    return new ReadableStream({
      async pull(ctl) {
        if (i >= meta.parts) return ctl.close();
        const r = await c.match(`/__model/part-${String(i++).padStart(4, "0")}`);
        if (!r) return ctl.error(new Error("The downloaded model is incomplete. Download it again."));
        ctl.enqueue(new Uint8Array(await r.arrayBuffer()));
      },
    }).getReader();
  }

  async load(sources) {
    if (this.#llm) return this.st;
    await this.status();
    if (!this.st.cached) await this.download(sources);
    this.#set({ loading: true, error: null });
    try {
      const { FilesetResolver, LlmInference } = await import(`${GENAI}/genai_bundle.mjs`);
      const fs = await FilesetResolver.forGenAiTasks(`${GENAI}/wasm`);
      const opts = (vision) => ({ baseOptions: { modelAssetBuffer: null }, maxTokens: 4096, topK: 40, temperature: 0.6,
                                  randomSeed: 7, maxNumImages: vision ? 1 : 0 });
      // vision when this build of the model and runtime support it; otherwise text only
      for (const vision of [true, false]) {
        try {
          const o = opts(vision);
          o.baseOptions.modelAssetBuffer = await this.#modelReader();
          this.#llm = await LlmInference.createFromOptions(fs, o);
          this.#set({ vision });
          break;
        } catch (e) {
          if (!vision) throw e;
        }
      }
      this.#set({ ready: true, loading: false });
    } catch (e) {
      this.#set({ loading: false, error: `Gemma couldn't start on this phone: ${e.message || e}` });
      throw e;
    }
    return this.st;
  }

  async forget() {
    try { this.#llm?.close(); } catch {}
    this.#llm = null;
    await caches.delete(CACHE);
    this.#set({ ready: false, cached: false, bytes: 0, progress: 0 });
  }

  generate({ system = "", parts, maxTokens = 512 }, onChunk = () => {}) {
    return this.#queue(async () => {
      if (!this.#llm) await this.load();
      const prompt = [];
      if (system) prompt.push(turn("system", system));
      prompt.push("<|turn>user\n");
      for (const p of parts) {
        if (p.text != null) prompt.push(p.text);
        else if (p.image && this.st.vision) prompt.push({ imageSource: await createImageBitmap(p.image) });
      }
      prompt.push("<turn|>\n<|turn>model\n");
      // MediaPipe has no per-call output cap: stop it ourselves (about 4 characters per token)
      let out = "", stopped = false;
      const cap = maxTokens * 4.5;
      await this.#llm.generateResponse(prompt.every((p) => typeof p === "string") ? prompt.join("") : prompt, (part) => {
        if (stopped) return;
        out += part;
        onChunk(part);
        if (out.length > cap || out.includes("<turn|>")) { stopped = true; try { this.#llm.cancelProcessing(); } catch {} }
      }).catch((e) => { if (!stopped) throw e; });
      try { this.#llm.clearCancelSignals?.(); } catch {}
      return clean(out);
    });
  }
}

// ------------------------------------------------------------------ pick the engine
let engine = null;
export function phoneLLM() {
  if (!engine) engine = window.MiseNative?.available ? new NativeLLM() : new WebLLM();
  return engine;
}

export const phoneSupported = () => !!window.MiseNative?.available || WebLLM.supported();
