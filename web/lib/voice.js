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
    this.blocked = () => false; // e.g. while the app is speaking or thinking
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
    const { blob, seconds } = this.#wav();
    if (send && seconds > 0.4) this.onUtterance(blob, seconds);
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
      this.voiced = rms > Math.max(0.02, this.noise * 4) ? this.voiced + 1 : 0;
      if (this.voiced >= 3) this.start("vad");
    }
  }

  #wav() {
    const len = this.chunks.reduce((a, b) => a + b.length, 0);
    const pcm = new Float32Array(len);
    let o = 0;
    for (const c of this.chunks) { pcm.set(c, o); o += c.length; }
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
  }
}

export class Speaker {
  constructor() {
    this.enabled = true;
    this.voice = null;
    this.speaking = false;
    this.onSpeak = () => {};
    const pick = () => {
      const vs = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
      // local voices only: the cloud ones need the internet
      this.voice = vs.find((v) => v.localService && /aria|jenny|samantha|natural|zira/i.test(v.name))
        || vs.find((v) => v.localService) || null;
    };
    speechSynthesis.onvoiceschanged = pick;
    pick();
    // iOS only lets speechSynthesis talk after it has spoken once inside a tap
    addEventListener("pointerdown", () => speechSynthesis.speak(new SpeechSynthesisUtterance("")), { once: true });
  }

  say(text, { interrupt = false } = {}) {
    text = (text || "").trim();
    if (!text) return;
    this.onSpeak(text);
    if (!this.enabled) return;
    if (interrupt) speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    if (this.voice) u.voice = this.voice;
    u.rate = 1.03;
    u.onstart = () => (this.speaking = true);
    u.onend = u.onerror = () => (this.speaking = speechSynthesis.speaking || speechSynthesis.pending);
    speechSynthesis.speak(u);
  }

  stop() {
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
