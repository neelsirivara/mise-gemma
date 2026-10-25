// Cook mode on the phone: the same session as apps/mise/cook.py and core/state.py. It narrates each
// step ("say" events the UI speaks), starts timers for hands-off steps, suggests prep during waits,
// warns before timers end, and records how long each step took, which feeds the next revision.
import * as book from "./book.js";

const t = () => Date.now() / 1000;
const id6 = () => Math.random().toString(16).slice(2, 8);

// ------------------------------------------------------------------ shared session: timers, action log, event feed
export const SESSION = {
  timers: [], log: [], events: [],
  emit(kind, data = {}) {
    this.events.push({ id: id6(), t: t(), kind, ...data });
    this.events = this.events.slice(-200);
  },
  tick() { // fire finished timers, and clear them away 20 s later
    for (const x of this.timers) if (!x.fired && x.ends_at - t() <= 0) { x.fired = true; x.fired_at = t(); this.emit("timer_done", { label: x.label }); }
    this.timers = this.timers.filter((x) => !x.fired || t() - x.fired_at < 20);
  },
  clearFired() { this.timers = this.timers.filter((x) => !x.fired); },
  snapshot() {
    return { timers: this.timers.map((x) => ({ id: x.id, label: x.label, remaining: Math.max(0, Math.round((x.ends_at - t()) * 10) / 10),
                                              seconds: x.seconds, fired: x.fired })),
             log: this.log.slice(-20), seen: [] };
  },
};

export function setTimer(label, minutes) {
  const x = { id: id6(), label, seconds: minutes * 60, ends_at: t() + minutes * 60, fired: false };
  SESSION.timers.push(x);
  SESSION.emit("timer_set", { label, seconds: x.seconds });
  return x;
}

export function logAction(text) {
  SESSION.log.push({ t: t(), text });
  SESSION.emit("log", { text });
}

export const remaining = (x) => Math.max(0, x.ends_at - t());

// ------------------------------------------------------------------ wording
export function mins(m) {
  if (m < 1) return `${Math.round(m * 60)} seconds`;
  const v = m >= 2 ? Math.round(m) : Math.round(m * 10) / 10;
  return `${v} minute${v !== 1 ? "s" : ""}`;
}
function minsAdj(m) { // "an 8-minute timer", "a 30-second timer"
  const s = m < 1 ? `${Math.round(m * 60)}-second` : `${m >= 2 ? Math.round(m) : Math.round(m * 10) / 10}-minute`;
  return (s[0] === "8" || s.startsWith("11-") || s.startsWith("18-") ? "an " : "a ") + s;
}
const short = (text, n = 4) => { const w = text.replace(/\.$/, "").split(/\s+/); return w.slice(0, n).join(" ") + (w.length > n ? "…" : ""); };
export const clock = (sec) => new Date(sec * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

// ------------------------------------------------------------------ the cook session
export const COOK = {
  recipe: null, step: 0, startedAt: 0, stepStartedAt: 0, stepSeconds: [], cues: new Set(), stepTimers: {},
  active: false, awaitingFeedback: null, lastSaid: "", makeTips: null, // makeTips(recipe) → Promise<tips>, set by the hub

  say(text, tone = "narration") { this.lastSaid = text; SESSION.emit("say", { text, tone }); },

  stepLine(i) {
    const r = this.recipe, s = r.steps[i], n = r.steps.length;
    const parts = [i < n - 1 ? `Step ${i + 1} of ${n}.` : `Last step, ${i + 1} of ${n}.`, s.text];
    if (s.timer) {
      parts.push(`I've started ${minsAdj(s.minutes)} timer.`);
      const nxt = r.steps[i + 1];
      if (s.minutes >= 3 && nxt && !nxt.timer) parts.push(`While that's going, you can get ahead on the next step: ${nxt.text}`);
    } else if (s.minutes >= 1) parts.push(`This takes about ${mins(s.minutes)}.`);
    const tip = r.tips?.[String(i)];
    if (tip) parts.push(`Tip: ${tip}`);
    return parts.join(" ");
  },

  eta() {
    const r = this.recipe, rest = r.steps.slice(this.step + 1).reduce((a, s) => a + s.minutes, 0);
    const cur = r.steps[this.step].minutes * 60 - (t() - this.stepStartedAt);
    return t() + Math.max(cur, 0) + rest * 60;
  },

  async start(id) {
    this.recipe = await book.get(id);
    Object.assign(this, { step: 0, active: true, awaitingFeedback: null, startedAt: t(), stepStartedAt: t(),
                          stepSeconds: this.recipe.steps.map(() => 0), cues: new Set(), stepTimers: {} });
    SESSION.timers = [];
    const r = this.recipe;
    const intro = [`Let's make ${r.title}` + (r.version > 1 ? `, version ${r.version}.` : ".")];
    if (r.note_for_next_time) intro.push(r.note_for_next_time);
    intro.push(`It takes about ${mins(r.total_minutes)}, so you'll be eating around ${clock(t() + r.total_minutes * 60)}.`);
    const waits = r.steps.map((s, k) => [s.minutes, k, s.timer]).filter((w) => w[2]);
    if (waits.length) {
      const [m, k] = waits.reduce((a, b) => (b[0] > a[0] ? b : a));
      intro.push(`The longest wait is step ${k + 1}, about ${mins(m)}; I'll tell you what to prep while it cooks.`);
    }
    intro.push(`You need ${r.ingredients.length} ingredients; they're on screen. Say next when you're ready to move on, or ask me anything.`);
    this.say(intro.join(" "), "intro");
    this.enter(0);
    if (!r.tips && this.makeTips) this._tips(r.id, r.version);
    return this.state();
  },

  async _tips(id, version) { // chef's tips per step, written once per recipe version, saved
    try {
      const tips = await this.makeTips(this.recipe);
      const r = await book.get(id);
      if (r.version === version) { r.tips = tips; await book.write(r); }
      if (this.recipe?.id === id) this.recipe.tips = tips;
    } catch {} // tips are a bonus
  },

  enter(i) {
    this.step = i;
    this.stepStartedAt = t();
    SESSION.clearFired(); // finished timers from earlier steps don't follow you into this one
    const s = this.recipe.steps[i];
    if (s.timer && !(i in this.stepTimers)) this.stepTimers[i] = setTimer(`Step ${i + 1}: ${short(s.text)}`, s.minutes).id;
    SESSION.emit("cook", { step: i });
    this.say(this.stepLine(i));
  },

  leave() { this.stepSeconds[this.step] += t() - this.stepStartedAt; },

  goto(i) {
    if (!this.active) return this.state();
    i = Math.max(0, Math.min(this.recipe.steps.length - 1, i));
    this.leave();
    this.enter(i);
    return this.state();
  },
  next() {
    if (!this.active) return this.state();
    if (this.step >= this.recipe.steps.length - 1) {
      this.say("That was the last step. When you've plated up, say finished and tell me how it went.", "cue");
      return this.state();
    }
    return this.goto(this.step + 1);
  },
  back() { return this.goto(this.step - 1); },
  repeat() { if (this.active) this.say(this.stepLine(this.step)); return this.state(); },

  async finish() {
    if (!this.recipe) return this.state();
    if (this.active) { this.leave(); await book.logCook(this.recipe.id, this.stepSeconds, true); }
    const total = Math.round((t() - this.startedAt) / 60);
    this.active = false;
    this.awaitingFeedback = this.recipe.id;
    SESSION.timers = []; // the meal is done; so are its timers
    this.say(`Nice work. That took ${total} minutes. How did it turn out? Tell me what you'd change, and I'll improve the recipe for next time.`, "feedback");
    SESSION.emit("cook", { step: this.step, finished: true });
    return this.state();
  },
  stop() { this.active = false; this.recipe = null; SESSION.timers = []; },

  tick() { // time cues, ~1/s
    if (!this.active) return;
    const s = this.recipe.steps[this.step];
    for (const [i, tid] of Object.entries(this.stepTimers)) {
      const x = SESSION.timers.find((y) => y.id === tid);
      if (x && !x.fired && x.seconds >= 180 && remaining(x) <= 60 && !this.cues.has(`warn${i}`)) {
        this.cues.add(`warn${i}`);
        this.say(`One minute left on step ${+i + 1}.`, "cue");
      }
      if (x?.fired && !this.cues.has(`done${i}`)) {
        this.cues.add(`done${i}`);
        if (+i === this.step) this.say("Time's up on this step. Check it, then say next.", "cue");
        else this.say(`Heads up: the timer from step ${+i + 1} is done. ${this.recipe.steps[i].text.replace(/\.$/, "")}. Check it when you can.`, "cue");
      }
    }
    const planned = Math.max(s.minutes, 1) * 60;
    if (!s.timer && t() - this.stepStartedAt > Math.max(2 * planned, planned + 120) && !this.cues.has(`slow${this.step}`)) {
      this.cues.add(`slow${this.step}`);
      this.say("No rush. Say next when you're ready, or ask me if you're stuck.", "cue");
    }
  },

  state() {
    if (!this.recipe) return { active: false, awaiting_feedback: this.awaitingFeedback };
    const r = this.recipe;
    return {
      active: this.active, awaiting_feedback: this.awaitingFeedback,
      recipe: Object.fromEntries(["id", "title", "version", "servings", "total_minutes", "ingredients", "steps", "note_for_next_time", "changes"].map((k) => [k, r[k]])),
      step: this.step, step_elapsed: Math.round(t() - this.stepStartedAt), elapsed: Math.round(t() - this.startedAt),
      eta: this.active ? clock(this.eta()) : null, step_seconds: this.stepSeconds.map(Math.round), last_said: this.lastSaid,
    };
  },

  summary() {
    if (!this.recipe) return "";
    const r = this.recipe;
    const lines = [`COOKING: ${r.title} v${r.version} (${this.active ? "in progress" : "finished"})`];
    r.steps.forEach((s, i) => {
      const mark = i === this.step && this.active ? ">> NOW" : i < this.step ? "done" : "todo";
      lines.push(`[${mark}] step ${i + 1}: ${s.text} (${s.minutes} min${s.timer ? ", timer" : ""})`);
    });
    lines.push("INGREDIENTS: " + r.ingredients.map((i) => `${i.qty} ${i.item}`.trim()).join("; "));
    if (this.awaitingFeedback) lines.push("The cook just finished. Ask how it went.");
    return lines.join("\n");
  },
};
