// The recipe book on the phone: same records and version history as apps/mise/book.py,
// kept in IndexedDB instead of JSON files. A recipe changes only through revise(), which
// snapshots the current version into `history` first.

const VERSIONED = ["title", "summary", "servings", "total_minutes", "ingredients", "steps"];
const STARTERS = ["caprese_salad", "carbonara", "guacamole", "shakshuka"]; // web/mise/starters/*.json

const now = () => Math.round(Date.now() / 100) / 10;
export const slug = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "recipe";

let dbp = null;
function db() {
  dbp ??= new Promise((ok, bad) => {
    const r = indexedDB.open("mise", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("recipes", { keyPath: "id" });
    r.onsuccess = () => ok(r.result);
    r.onerror = () => bad(r.error);
  });
  return dbp;
}

async function tx(mode, fn) {
  const d = await db();
  return new Promise((ok, bad) => {
    const t = d.transaction("recipes", mode);
    const req = fn(t.objectStore("recipes"));
    t.oncomplete = () => ok(req?.result);
    t.onerror = () => bad(t.error);
  });
}

export function normalize(r) {
  const ings = (r.ingredients || []).map((i) => typeof i === "string" ? { item: i, qty: "" }
    : { item: String(i.item ?? "").trim(), qty: String(i.qty ?? "").trim() });
  const steps = (r.steps || []).map((s) => {
    if (typeof s === "string") s = { text: s };
    const minutes = Number(s.minutes ?? s.timer_min ?? 2) || 0;
    return { text: String(s.text ?? "").trim(), minutes: Math.round(minutes * 10) / 10,
             timer: Boolean(s.timer ?? !!s.timer_min), check: String(s.check || "") };
  });
  const total = Number(r.total_minutes) || Math.round(steps.reduce((a, s) => a + s.minutes, 0));
  if (total) for (const s of steps) {  // a step can't outlast the recipe (usually "30 seconds" written as 30 minutes)
    if (s.minutes > total) s.minutes = s.minutes >= 20 ? Math.round((s.minutes / 60) * 10) / 10 : total;
  }
  return {
    title: String(r.title || "Untitled").trim(),
    summary: String(r.summary || "").trim(),
    servings: parseInt(r.servings) || 2,
    total_minutes: Math.round(total),
    tags: (r.tags || []).map(String).slice(0, 6),
    ingredients: ings.filter((i) => i.item),
    steps: steps.filter((s) => s.text),
  };
}

export const write = (r) => tx("readwrite", (s) => s.put(r));
export const get = async (id) => {
  const r = await tx("readonly", (s) => s.get(id));
  if (!r) throw Object.assign(new Error("That recipe isn't in the book anymore."), { status: 404 });
  return r;
};
export const remove = (id) => tx("readwrite", (s) => s.delete(id));

export async function all() {
  const rows = await tx("readonly", (s) => s.getAll());
  const last = (r) => Math.max(r.updated, ...r.cooks.map((c) => c.t));
  return rows.sort((a, b) => last(b) - last(a));
}

export async function add(recipe, source = "generated", pantry = [], when = now()) {
  const base = normalize(recipe);
  const r = { id: `${slug(base.title)}-${Math.random().toString(16).slice(2, 6)}`, ...base, version: 1, source, pantry,
              created: when, updated: when, changes: [], note_for_next_time: "", history: [], feedback: [], cooks: [] };
  await write(r);
  return r;
}

export function summaryRow(r) {
  const ratings = r.feedback.map((f) => f.rating).filter(Boolean);
  return { id: r.id, title: r.title, summary: r.summary, total_minutes: r.total_minutes, servings: r.servings,
           version: r.version, tags: r.tags, source: r.source, cooked: r.cooks.length,
           rating: ratings.at(-1) ?? null, last_cooked: r.cooks.at(-1)?.t ?? null, steps: r.steps.length };
}

export async function logCook(id, stepSeconds, finished) {
  const r = await get(id);
  r.cooks.push({ t: now(), version: r.version, step_seconds: stepSeconds.map(Math.round), finished });
  await write(r);
  return r;
}

export async function addFeedback(id, fb) {
  const r = await get(id);
  r.feedback.push({ t: now(), version: r.version, ...fb });
  await write(r);
  return r;
}

export async function revise(id, recipe, changes, note, reason) {
  const r = await get(id);
  r.history.push({ version: r.version, t: r.updated, changes: r.changes, ...Object.fromEntries(VERSIONED.map((k) => [k, r[k]])) });
  const base = normalize(recipe);
  base.title = r.title; // the dish keeps its name across versions
  for (const k of VERSIONED) r[k] = base[k];
  r.tags = base.tags.length ? base.tags : r.tags;
  r.version += 1;
  r.changes = changes.filter(Boolean).slice(0, 8);
  r.note_for_next_time = note;
  r.revision_reason = reason;
  r.updated = now();
  await write(r);
  return r;
}

// First run: the same starter recipes the laptop seeds, so the book isn't empty.
export async function seed() {
  if ((await tx("readonly", (s) => s.count())) > 0) return;
  for (const name of STARTERS) {
    try {
      const src = await (await fetch(`/mise/starters/${name}.json`)).json();
      await add(src, "starter", [], now() - 86400); // sort below anything you make today
    } catch {}
  }
}
