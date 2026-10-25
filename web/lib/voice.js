// Voice in and out, all on-device.
//   Mic: hold-to-talk or hands-free (simple energy VAD) → 16 kHz mono WAV for Gemma's audio input.
//   Speaker: queued speechSynthesis with a local voice, sentence by sentence.

export class Mic {
  constructor() {
    this.ctx = null;
    this.rate = 48000;
    this.chunks = [];
    this.preroll = [];
    this.noise = 0.01;
    this.voiced = 0;
    this.silentMs = 0;
    this.mode = null; // null | "ptt" | "vad"
    this.handsFree = false;
    this.blocked = () => false; // e.g. while the app is thinking
    this.isSpeaking = () => false; // while true, hands-free needs a louder voice (barge-in)
    this.onBargeIn = () => {}; // called when the cook talks over the app
    this.onUtterance = () => {};
    this.onLevel = () => {};
    this.onState = () => {};
  }

  async init() {
    if (this.ctx) return;
    // iOS: create the AudioContext inside the tap, before any await
    this.ctx = new AudioContext();
    this.rate = this.ctx.sampleRate;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    await this.ctx.resume();
    const src = this.ctx.createMediaStreamSource(stream);
    const node = this.ctx.createScriptProcessor(2048, 1, 1);
    src.connect(node);
    node.connect(this.ctx.destination);
    node.onaudioprocess = (e) => this.#frame(new Float32Array(e.inputBuffer.getChannelData(0)));
  }

  async start(mode = "ptt") {
    if (this.mode) return;
    await this.init();
    this.chunks = [...this.preroll];
    this.silentMs = 0;
    this.startedAt = performance.now();
    this.mode = mode;
    this.onState(mode);
  }

  stop(send = true) {
    if (!this.mode) return;
    this.mode = null;
    this.onState(null);
    const chunks = this.chunks;
    this.chunks = [];
    this.#wav(chunks).then(({ blob, seconds }) => { if (send && seconds > 0.4) this.onUtterance(blob, seconds); });
  }

  #frame(buf) {
    const ms = (buf.length / this.rate) * 1000;
    let rms = 0;
    for (const x of buf) rms += x * x;
    rms = Math.sqrt(rms / buf.length);
    this.onLevel(rms);
    if (this.mode) {
      this.chunks.push(buf);
      if (this.mode === "vad") {
        const thr = Math.max(0.012, this.noise * 3);
        this.silentMs = rms < thr ? this.silentMs + ms : 0;
        if (this.silentMs > 900 || performance.now() - this.startedAt > 15000) this.stop(true);
      }
      return;
    }
    this.noise = 0.95 * this.noise + 0.05 * Math.min(rms, 0.05);
    this.preroll.push(buf);
    if (this.preroll.length > 8) this.preroll.shift();
    if (this.handsFree && !this.blocked()) {
      // while Mise is talking, only a clearly louder voice counts: that's the cook interrupting
      const talking = this.isSpeaking();
      const thr = talking ? Math.max(0.06, this.noise * 8) : Math.max(0.02, this.noise * 4);
      this.voiced = rms > thr ? this.voiced + 1 : 0;
      if (this.voiced >= (talking ? 4 : 3)) {
        if (talking) this.onBargeIn();
        this.start("vad");
      }
    }
  }

  // 16 kHz mono WAV for Gemma. The browser's own resampler (OfflineAudioContext) low-pass filters properly;
  // naive decimation from 48 kHz aliases and smears consonants, which hurts recognition.
  async #wav(chunks) {
    const len = chunks.reduce((a, b) => a + b.length, 0);
    let pcm = new Float32Array(len);
    let o = 0;
    for (const c of chunks) { pcm.set(c, o); o += c.length; }
    let out16 = null;
    if (this.rate !== 16000 && typeof OfflineAudioContext !== "undefined" && len) {
      try {
        const off = new OfflineAudioContext(1, Math.ceil((len * 16000) / this.rate), 16000);
        const buf = off.createBuffer(1, len, this.rate);
        buf.copyToChannel(pcm, 0);
        const src = off.createBufferSource();
        src.buffer = buf;
        src.connect(off.destination);
        src.start();
        out16 = (await off.startRendering()).getChannelData(0);
      } catch {}
    }
    if (!out16) { // fallback: box-filter decimation
      const ratio = this.rate / 16000, n = Math.floor(len / ratio);
      out16 = new Float32Array(n);
      for (let i = 0; i < n; i++) {
        let s = 0, k = 0;
        for (let j = Math.floor(i * ratio); j < Math.floor((i + 1) * ratio) && j < len; j++) { s += pcm[j]; k++; }
        out16[i] = s / (k || 1);
      }
    }
    // level: bring quiet/far speech up to a consistent peak (never above 0.7, never more than 8x gain)
    let peak = 0;
    for (const x of out16) peak = Math.max(peak, Math.abs(x));
    const gain = peak > 0 ? Math.min(8, 0.7 / peak) : 1;
    const n = out16.length;
    const out = new Int16Array(n);
    for (let i = 0; i < n; i++) out[i] = Math.max(-1, Math.min(1, out16[i] * gain)) * 0x7fff;
    const wbuf = new ArrayBuffer(44 + n * 2);
    const dv = new DataView(wbuf);
    const w = (p, str) => [...str].forEach((ch, i) => dv.setUint8(p + i, ch.charCodeAt(0)));
    w(0, "RIFF"); dv.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt ");
    dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
    dv.setUint32(24, 16000, true); dv.setUint32(28, 32000, true); dv.setUint16(32, 2, true);
    dv.setUint16(34, 16, true); w(36, "data"); dv.setUint32(40, n * 2, true);
    new Int16Array(wbuf, 44).set(out);
    return { blob: new Blob([wbuf], { type: "audio/wav" }), seconds: n / 16000 };
  }

}

export class Speaker {
  // Queue of sentences. With a hub voice (Kokoro on the laptop) each sentence is fetched as WAV
  // and prefetched while the previous one plays; otherwise the browser's local voice is used.
  constructor() {
    this.enabled = true;
    this.voice = null;
    this.speaking = false;
    this.hub = null; // async (text) => ArrayBuffer | null
    this.queue = [];
    this.playing = null;
    this.gen = 0; // bumps on stop(), so stale fetches never play
    this.onSpeak = () => {};
    const pick = () => {
      const vs = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
      // local voices only: the cloud ones need the internet
      this.voice = vs.find((v) => v.localService && /aria|jenny|samantha|natural|zira/i.test(v.name))
        || vs.find((v) => v.localService) || null;
    };
    speechSynthesis.onvoiceschanged = pick;
    pick();
    // iOS: audio may only start after a tap; unlock both speech paths on the first one
    addEventListener("pointerdown", () => this.unlock(), { once: true });
  }

  useHub(fetchWav) { this.hub = fetchWav; }

  unlock() {
    try {
      speechSynthesis.speak(new SpeechSynthesisUtterance(""));
      this.ctx = this.ctx || new AudioContext();
      this.ctx.resume();
      const b = this.ctx.createBuffer(1, 1, 22050), s = this.ctx.createBufferSource();
      s.buffer = b; s.connect(this.ctx.destination); s.start();
    } catch {}
  }

  say(text, { interrupt = false } = {}) {
    text = (text || "").trim();
    if (!text) return;
    this.onSpeak(text);
    if (!this.enabled) return;
    if (interrupt) this.stop();
    const item = { text, gen: this.gen };
    if (this.hub) item.audio = this.hub(text).catch(() => null); // start synthesis now (prefetch)
    this.queue.push(item);
    this.speaking = true;
    if (!this.playing) this.#next();
  }

  async #next() {
    const item = this.queue.shift();
    if (!item) { this.playing = null; this.speaking = false; return; }
    this.playing = item;
    const buf = item.audio ? await item.audio : null;
    if (item.gen !== this.gen) return; // stopped while fetching
    if (buf) {
      try {
        this.ctx = this.ctx || new AudioContext();
        const audio = await this.ctx.decodeAudioData(buf.slice(0));
        if (item.gen !== this.gen) return;
        const src = this.ctx.createBufferSource();
        src.buffer = audio;
        src.connect(this.#meter()); // -> analyser -> speakers, so the mum's mouth can follow the voice
        this.source = src;
        this.mode = "hub";
        src.onended = () => { if (item.gen === this.gen) this.#next(); };
        src.start();
        return;
      } catch {}
    }
    // browser voice fallback (no level meter: the mum's mouth just flaps while it talks)
    this.mode = "browser";
    const u = new SpeechSynthesisUtterance(item.text);
    if (this.voice) u.voice = this.voice;
    u.rate = 1.03;
    u.onend = u.onerror = () => { if (item.gen === this.gen) this.#next(); };
    speechSynthesis.speak(u);
  }

  #meter() {
    if (!this.analyser) {
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.connect(this.ctx.destination);
      this.levelBuf = new Float32Array(this.analyser.fftSize);
    }
    return this.analyser;
  }

  // Loudness of the hub voice right now, 0..1 (null when the browser voice is talking: no meter there)
  level() {
    if (!this.speaking) return 0;
    if (this.mode !== "hub" || !this.analyser) return null;
    this.analyser.getFloatTimeDomainData(this.levelBuf);
    let sum = 0;
    for (const x of this.levelBuf) sum += x * x;
    return Math.min(1, Math.sqrt(sum / this.levelBuf.length) * 7);
  }

  stop() {
    this.gen++;
    this.queue = [];
    this.playing = null;
    try { this.source?.stop(); } catch {}
    speechSynthesis.cancel();
    this.speaking = false;
  }
}

// Speak streamed text sentence by sentence as it arrives.
export class SentenceSpeaker {
  constructor(speaker) { this.speaker = speaker; this.buf = ""; }
  push(text) {
    this.buf += text;
    let m;
    while ((m = this.buf.match(/^[\s\S]*?[.!?](\s|$)/))) {
      this.speaker.say(m[0]);
      this.buf = this.buf.slice(m[0].length);
    }
  }
  flush() { this.speaker.say(this.buf); this.buf = ""; }
}

export function beep(times = 3) {
  try {
    const c = new AudioContext();
    for (let i = 0; i < times; i++) {
      const t = c.currentTime + i * 0.25;
      const o = c.createOscillator(), g = c.createGain();
      o.frequency.value = 880;
      o.connect(g); g.connect(c.destination);
      g.gain.setValueAtTime(0.2, t);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.2);
      o.start(t); o.stop(t + 0.2);
    }
  } catch {}
}
