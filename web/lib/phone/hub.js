// The Mise hub, running inside the phone's browser. It answers the same /api paths as the laptop
// (core/server.py + apps/mise/routes.py) with Response objects, so every view works unchanged:
// web/lib/api.js sends requests here instead of over the network when the phone engine is on.
import * as book from "./book.js";
import * as chef from "./chef.js";
import * as companion from "./companion.js";
import { COOK, SESSION } from "./cook.js";
import { phoneLLM } from "./llm.js";

const llm = phoneLLM();
COOK.makeTips = (r) => chef.stepTips(llm, r);
let seeded = null;
const stats = { turns: 0 };

const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const fail = (e) => json({ detail: e.message || String(e) }, e.status || 500);

// NDJSON stream from an async generator; a failure becomes an {"type":"error"} line, as on the laptop.
function ndjson(gen) {
  const enc = new TextEncoder();
  return new Response(new ReadableStream({
    async start(ctl) {
      try { for await (const ev of gen) ctl.enqueue(enc.encode(JSON.stringify(ev) + "\n")); }
      catch (e) { ctl.enqueue(enc.encode(JSON.stringify({ type: "error", error: e.message || String(e) }) + "\n")); }
      ctl.close();
    },
  }), { headers: { "Content-Type": "application/x-ndjson" } });
}

const latestStepSeconds = (r) => r.cooks.filter((c) => c.version === r.version).at(-1)?.step_seconds ?? [];

async function* reviseStream(id, { rating, tags = [], notes = "", audio = null, improve = true }) {
  const r = await book.addFeedback(id, { rating, tags, notes, voice_note: !!audio });
  if (COOK.awaitingFeedback === id) COOK.awaitingFeedback = null;
  if (!improve) { yield { type: "done", recipe: r, changes: [], heard: notes }; return; }
  let result = null;
  for await (const ev of withProgress((onChars) => chef.revise(llm, { recipe: r, rating, tags, notes, stepSeconds: latestStepSeconds(r), audio }, onChars))) {
    if (ev.type === "result") result = ev.value;
    else yield ev;
  }
  const fresh = await book.revise(id, result.recipe, result.changes, result.note_for_next_time, result.heard);
  fresh.feedback.at(-1).heard = result.heard;
  await book.write(fresh);
  yield { type: "done", recipe: fresh, changes: result.changes, heard: result.heard };
}

function reviseInBackground(id, rating, notes) {
  (async () => {
    try {
      for await (const ev of reviseStream(id, { rating, notes })) {
        if (ev.type === "done") {
          const ch = ev.changes;
          SESSION.emit("say", { tone: "revised", text: `I've saved version ${ev.recipe.version}. ` + (ch.length ? `Main change: ${ch[0]}` : "") });
          SESSION.emit("book", { id });
        }
      }
    } catch (e) { SESSION.emit("say", { tone: "error", text: `I couldn't update the recipe: ${e.message}` }); }
  })();
}

// Run a promise-returning model call while streaming {"type":"progress"} as characters arrive.
async function* withProgress(run) {
  let chars = 0, wake = null, out = null, err = null;
  run((n) => { chars = n; wake?.(); }).then((v) => (out = v), (e) => (err = e)).finally(() => wake?.());
  let shown = 0;
  while (out === null && !err) {
    await new Promise((ok) => (wake = ok));
    if (chars !== shown) { shown = chars; yield { type: "progress", chars }; }
  }
  if (err) throw err;
  yield { type: "result", value: out };
}

const engineInfo = () => ({ talk: `${llm.st.model} · on this phone`, watch: "off", ready: !!llm.st.ready, phone: true,
                            kind: llm.kind, load_error: llm.st.error || undefined, ...stats });

async function route(method, path, query, body) {
  seeded ??= book.seed();
  await seeded;
  const match = (re) => path.match(re);
  let m;

  if (path === "/api/meta") return json({ id: "mise", name: "Mise", tts: false, engine: "phone", phone: llm.st });
  if (path === "/api/state") {
    SESSION.tick();
    COOK.tick();
    const since = parseFloat(query.get("since") || "0");
    return json({ ...SESSION.snapshot(), panels: [], events: SESSION.events.filter((e) => e.t > since), engine: engineInfo() });
  }
  if (path === "/api/watch") return json({ skipped: true });
  if (path === "/api/chat") {
    const text = body.get("text") || "", image = body.get("image"), audio = body.get("audio");
    return ndjson((async function* () {
      const t0 = performance.now();
      let first = null, reply = "";
      const evs = companion.active() ? companion.handle(llm, { text, image, audio }, reviseInBackground)
        : companion.chat(llm, { text, image });
      for await (const ev of evs) {
        if (ev.type === "text") { first ??= (performance.now() - t0) / 1000; reply += ev.text; }
        yield ev;
      }
      stats.turns++;
      const total = (performance.now() - t0) / 1000;
      yield { type: "done", noop: /^\s*NOOP/i.test(reply), ttft_s: first ?? total, total_s: total, image: !!image, audio: !!audio };
    })());
  }

  // ------------------------------------------------ recipe book
  if (path === "/api/mise/book" && method === "GET") return json((await book.all()).map(book.summaryRow));
  if ((m = match(/^\/api\/mise\/book\/([a-z0-9-]{1,64})$/))) {
    if (method === "DELETE") { await book.get(m[1]); await book.remove(m[1]); return json({ ok: true }); }
    return json(await book.get(m[1]));
  }

  // ------------------------------------------------ pantry → ideas → recipe
  if (path === "/api/mise/pantry/scan") {
    const t0 = performance.now();
    const items = await chef.scanPantry(llm, body.getAll("images").slice(0, 4));
    return json({ items, seconds: Math.round((performance.now() - t0) / 100) / 10 });
  }
  if (path === "/api/mise/pantry/ideas") {
    if (!body.items?.length) return json({ detail: "Add at least one ingredient first." }, 400);
    const t0 = performance.now();
    const avoid = (await book.all()).map((r) => r.title).slice(0, 12);
    const ideas = await chef.suggest(llm, { ...defaults(body), avoid });
    return json({ ideas, seconds: Math.round((performance.now() - t0) / 100) / 10 });
  }
  if (path === "/api/mise/pantry/recipe") {
    const b = defaults(body);
    return ndjson((async function* () {
      const t0 = performance.now();
      for await (const ev of withProgress((onChars) => chef.writeRecipe(llm, { ...b, idea: body.idea }, onChars))) {
        if (ev.type !== "result") { yield ev; continue; }
        const r = await book.add(ev.value, "pantry", b.items);
        yield { type: "done", recipe: r, seconds: Math.round((performance.now() - t0) / 100) / 10, over_time: r.total_minutes > b.minutes };
      }
    })());
  }

  // ------------------------------------------------ cook mode
  if (path === "/api/mise/cook/state") return json(COOK.state());
  if ((m = match(/^\/api\/mise\/cook\/(\w+)$/))) {
    const a = m[1];
    if (a === "start") return json(await COOK.start(body.id));
    if (a === "goto") return json(COOK.goto(body?.step ?? 0));
    if (a === "stop") { COOK.stop(); return json(COOK.state()); }
    if (a === "finish") return json(await COOK.finish());
    const fn = { next: () => COOK.next(), back: () => COOK.back(), repeat: () => COOK.repeat() }[a];
    if (!fn) return json({ detail: `Unknown cook action '${a}'.` }, 404);
    return json(fn());
  }

  // ------------------------------------------------ feedback → new version
  if (path === "/api/mise/feedback") {
    const id = body.get("id");
    await book.get(id);
    const tags = String(body.get("tags") || "").split(",").map((s) => s.trim()).filter(Boolean);
    return ndjson(reviseStream(id, { rating: parseInt(body.get("rating")) || null, tags, notes: String(body.get("notes") || "").trim(),
                                     audio: body.get("audio"), improve: body.get("improve") !== "false" }));
  }
  return json({ detail: `Not found: ${path}` }, 404);
}

function defaults(b) {
  return { items: b.items || [], minutes: Math.min(240, Math.max(5, b.minutes || 30)), servings: Math.min(12, Math.max(1, b.servings || 2)), notes: b.notes || "" };
}

// fetch()-shaped entry point used by web/lib/api.js
export async function phoneFetch(path, opts = {}) {
  const u = new URL(path, location.origin);
  const method = (opts.method || "GET").toUpperCase();
  let body = opts.body ?? null;
  if (typeof body === "string") { try { body = JSON.parse(body); } catch {} }
  try {
    return await route(method, u.pathname, u.searchParams, body ?? {});
  } catch (e) {
    return fail(e);
  }
}

export { llm };
