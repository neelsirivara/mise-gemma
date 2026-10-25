// The cook-mode voice companion on the phone, ported from apps/mise/companion.py: hear first
// (a focused transcription pass, or the phone's own speech recognizer), then ONE structured call
// that picks an intent from a fixed list; the app carries the intent out deterministically.
import { generateJSON } from "./json.js";
import { COOK, SESSION, logAction, remaining, setTimer } from "./cook.js";

const INTENTS = ["next", "back", "repeat", "time_left", "finish", "set_timer", "question", "feedback", "log", "ignore"];
const SCHEMA = { type: "object", properties: {
  heard: { type: "string" }, intent: { type: "string", enum: INTENTS }, timer_seconds: { type: "integer" },
  timer_label: { type: "string" }, rating: { type: "integer", minimum: 0, maximum: 5 }, answer: { type: "string" } },
  required: ["heard", "intent", "timer_seconds", "timer_label", "rating", "answer"] };

const GUIDE = `Classify what the cook just said and answer if needed. Intents:
- next: they finished the step or want to move on ("done", "okay what's next", "ready", "next").
- back: they want the previous step.
- repeat: they didn't catch it ("say that again", "what?", "repeat").
- time_left: they ask about timers or when food will be ready ("how long", "is the pasta done yet").
- finish: they're done cooking or eating ("we're finished", "plating up", "that's it").
- set_timer: they ask for a timer; timer_seconds = the duration in SECONDS (30 seconds = 30, 2 minutes = 120), plus a short timer_label.
- question: a cooking question (substitutions, doneness, heat, technique, "does this look right?"). Put a concrete
  one- or two-sentence spoken answer in "answer", grounded in the recipe and the photo if one is attached. Be a
  proactive coach: give the exact amount, heat or cue, and if it helps, add what to do next.
- feedback: they describe how the dish turned out (only after cooking). Set rating 1-5 from their words.
- log: they report adding something ("I added the salt") so it can be remembered. A QUESTION about the past
  ("did I already add the salt?") is a question, never back.
- ignore: background talk not meant for you.
"heard" = what they said, short. "answer" is spoken aloud: plain words, no markdown. For next/back/repeat/finish
leave answer empty; the app narrates the step itself. Unused fields: 0 or empty string.`;

const TRANSCRIBE = "Transcribe exactly what the person says in this audio. Output only their words, with normal "
  + "punctuation. If there is no speech, output nothing.";

const memory = []; // [what the cook said, what Mise answered], for follow-ups
let memoryFor = null;

export const active = () => COOK.active || !!COOK.awaitingFeedback;

export function dur(sec) {
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return `${sec} seconds`;
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${m} minute${m !== 1 ? "s" : ""}` + (s && m < 5 ? ` ${s} seconds` : "");
}

// what a small model says instead of a transcript when there's no speech (apps/mise/companion.py has the same list)
const NOT_SPEECH = /(cannot|can't|unable to) transcribe|^\W*(there is |there's )?no (speech|spoken words)|(audio|recording) (is|was) (not provided|empty|silent)|please provide (the )?audio|^\W*i'?m (a |an )?(speech )?transcriber|\[(silence|inaudible|no speech|noise|music)\]/i;

export async function transcribe(llm, audio) {
  const out = (await llm.generate({ system: "You are a precise speech transcriber.", parts: [{ audio }, { text: TRANSCRIBE }], maxTokens: 120 }))
    .trim().replace(/^"|"$/g, "").trim();
  return NOT_SPEECH.test(out) ? "" : out;
}

const FOLLOW = /\b(it|that|this|them|those|one|how much|how many|what heat|how long|instead)\b/i;

async function followUp(llm, last, heard) {
  const dish = COOK.recipe?.title || "this dish";
  try {
    return (await llm.generate({ system: "You are Mise, a concise kitchen coach.", maxTokens: 120, parts: [{ text:
      `We're cooking ${dish}. Earlier the cook asked: "${last[0]}"\nYou answered: "${last[1]}"\nNow they ask: "${heard}"\n`
      + "'It' means the thing from the earlier question, so answer about that thing. Answer in one or two short spoken "
      + "sentences with a concrete amount, heat or cue. No markdown." }] })).trim();
  } catch { return ""; }
}

// Yields the same event shapes the laptop's /api/chat streams: {type: "heard"|"tool"|"text", ...}
export async function* handle(llm, { text, image, audio }, reviseInBackground) {
  const t0 = performance.now();
  const spoken = !!audio;
  if (audio && !text) {
    text = llm.st.audio ? await transcribe(llm, audio) : "";
    if (!text) {
      yield { type: "heard", text: "", intent: "ignore", seconds: (performance.now() - t0) / 1000 };
      yield { type: "text", text: "NOOP" };
      return;
    }
  }
  const timers = SESSION.timers.filter((x) => !x.fired).map((x) => `${x.label}: ${Math.round(remaining(x))}s left`).join("; ") || "none";
  const rid = COOK.recipe?.id ?? null;
  if (memoryFor !== rid) { memory.length = 0; memoryFor = rid; } // new dish, fresh conversation
  const convo = memory.slice(-4).map(([h, a]) => `Cook: ${h}\nMise: ${a || "(acted)"}`).join("\n");
  const last = memory.at(-1);
  const prompt = `${GUIDE}\n\nCURRENT STATE:\n${COOK.summary()}\nRUNNING TIMERS: ${timers}\n`
    + (convo ? `\nRECENT CONVERSATION:\n${convo}\n` : "")
    + (last ? `\nThe previous question was "${last[0]}". If the cook now says 'it', 'that', 'how much' or 'what heat' without `
      + "naming the thing, they mean what that previous question was about; answer for that thing, not for the recipe in general.\n" : "")
    + `\nThe cook said: ${text}`;
  const out = await generateJSON(llm, { prompt, schema: SCHEMA, images: image && llm.st.vision ? [image] : [], maxTokens: 220 });
  if (spoken) out.heard = text; // what was actually said, not the router's paraphrase
  const intent = out.intent;
  let answer = out.answer.trim();
  if (intent === "question" && last && out.heard.split(/\s+/).length <= 7 && FOLLOW.test(out.heard)) answer = (await followUp(llm, last, out.heard)) || answer;
  if (intent !== "ignore") { memory.push([out.heard, answer]); memory.splice(0, Math.max(0, memory.length - 8)); }
  yield { type: "heard", text: out.heard, intent, seconds: (performance.now() - t0) / 1000 };
  yield { type: "tool", name: intent, args: Object.fromEntries(["timer_seconds", "timer_label", "rating"].filter((k) => out[k]).map((k) => [k, out[k]])), result: { ok: true } };

  if (intent === "next") COOK.next();
  else if (intent === "back") COOK.back();
  else if (intent === "repeat") COOK.repeat();
  else if (intent === "finish") { if (COOK.active) await COOK.finish(); }
  else if (intent === "time_left") {
    const parts = SESSION.timers.filter((x) => !x.fired).map((x) => `${x.label.split(":")[0]} has ${dur(remaining(x))} left`);
    const st = COOK.state();
    if (st.eta) parts.push(`you'll be eating around ${st.eta}`);
    yield { type: "text", text: (parts.join(", and ") || "No timers are running") + "." };
  } else if (intent === "set_timer") {
    const sec = Math.max(5, out.timer_seconds || 60);
    setTimer(out.timer_label || "timer", sec / 60);
    yield { type: "text", text: `Timer set for ${dur(sec)}.` };
  } else if (intent === "log") {
    logAction(out.heard);
    yield { type: "text", text: answer || "Noted." };
  } else if (intent === "feedback") {
    const id = COOK.awaitingFeedback || COOK.recipe?.id;
    if (id) {
      reviseInBackground(id, out.rating || null, out.heard);
      yield { type: "text", text: "Thanks. I'm updating the recipe for next time; it'll be ready in a moment." };
    }
  } else if (intent === "question") yield { type: "text", text: answer || "I'm not sure. Could you ask that another way?" };
  else yield { type: "text", text: "NOOP" };
}

// Outside cook mode: a plain kitchen question.
export async function* chat(llm, { text, image }) {
  const reply = await llm.generate({ system: "You are Mise, a friendly, concise home-cooking assistant. Answer in one to three "
    + "short spoken sentences, plain words, no markdown.", maxTokens: 220,
    parts: [...(image && llm.st.vision ? [{ image }] : []), { text: text || "Say hello and offer to help me cook." }] });
  yield { type: "text", text: reply.trim() };
}
