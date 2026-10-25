// What Mise asks Gemma to write, on the phone: pantry scans, ideas, recipes, revisions, tips.
// Same prompts and schemas as apps/mise/chef.py, so a recipe written on the phone and one written
// on the laptop look alike.
import { generateJSON } from "./json.js";

const STAPLES = "salt, pepper, cooking oil, water";
const CHEF = "You are Mise, a precise home-cooking assistant. Recipes are read aloud one step at a time to a cook "
  + "with busy hands, so every step is one clear action with quantities, heat level and a doneness cue.";

const INGREDIENT = { type: "object", properties: { item: { type: "string" }, qty: { type: "string" } }, required: ["item", "qty"] };
const STEP = { type: "object", properties: { text: { type: "string", minLength: 8 }, minutes: { type: "number" }, timer: { type: "boolean" } },
               required: ["text", "minutes", "timer"] };
const RECIPE = { type: "object", properties: {
  title: { type: "string" }, summary: { type: "string" }, servings: { type: "integer" }, total_minutes: { type: "integer" },
  tags: { type: "array", maxItems: 4, items: { type: "string" } },
  ingredients: { type: "array", minItems: 2, maxItems: 16, items: INGREDIENT },
  steps: { type: "array", minItems: 3, maxItems: 9, items: STEP } },
  required: ["title", "summary", "servings", "total_minutes", "tags", "ingredients", "steps"] };
const PANTRY = { type: "object", properties: { items: { type: "array", minItems: 1, maxItems: 30, items: { type: "string", minLength: 2 } } },
                 required: ["items"] };
const IDEAS = { type: "object", properties: { ideas: { type: "array", minItems: 3, maxItems: 3, items: { type: "object", properties: {
  title: { type: "string" }, summary: { type: "string" }, total_minutes: { type: "integer" },
  uses: { type: "array", maxItems: 10, items: { type: "string" } }, missing: { type: "array", maxItems: 3, items: { type: "string" } } },
  required: ["title", "summary", "total_minutes", "uses", "missing"] } } }, required: ["ideas"] };
const REVISION = { type: "object", properties: {
  heard: { type: "string" }, changes: { type: "array", minItems: 1, maxItems: 6, items: { type: "string" } },
  note_for_next_time: { type: "string" }, recipe: RECIPE }, required: ["heard", "changes", "note_for_next_time", "recipe"] };
const TIPS = { type: "object", properties: { tips: { type: "array", maxItems: 6, items: { type: "object",
  properties: { step: { type: "integer" }, tip: { type: "string", minLength: 8 } }, required: ["step", "tip"] } } }, required: ["tips"] };

export async function scanPantry(llm, images) {
  if (!llm.st.vision) {
    throw Object.assign(new Error("Gemma on this phone reads text only, so it can't see photos. Type or say your ingredients instead."),
      { status: 422 });
  }
  const out = await generateJSON(llm, { schema: PANTRY, images: images.slice(0, 1), maxTokens: 300, prompt:
    "These photos show my cupboard, fridge or counter. List every distinct food ingredient you can actually see. "
    + "Use short everyday names a recipe would use (for example 'canned chickpeas', 'eggs', 'basmati rice', "
    + "'smoked paprika'). Read labels where you can. Skip non-food items and anything you cannot see. "
    + "Do not list the same ingredient twice." });
  const seen = new Set();
  return out.items.map((i) => i.trim()).filter((i) => i && !seen.has(i.toLowerCase()) && seen.add(i.toLowerCase()));
}

export async function suggest(llm, { items, minutes, servings, notes = "", avoid = [] }) {
  const prompt = `My ingredients: ${items.join(", ")}. I also have ${STAPLES}.\n`
    + `Time limit: ${minutes} minutes total, prep included. Cooking for ${servings}.\n`
    + (notes ? `Preferences: ${notes}\n` : "")
    + (avoid.length ? `I already know these, suggest different ones: ${avoid.join(", ")}\n` : "")
    + `Suggest 3 different dishes made mostly from my ingredients. Each must really fit in ${minutes} minutes. `
    + "'uses' lists which of my ingredients it uses. 'missing' lists essential things I don't have "
    + "(prefer none, at most two). Short titles, one-sentence summaries.";
  const { ideas } = await generateJSON(llm, { prompt, schema: IDEAS, system: CHEF, maxTokens: 700 });
  for (const i of ideas) i.over_time = i.total_minutes > minutes; // be honest about a stretched budget
  return ideas.sort((a, b) => (a.over_time - b.over_time) || (a.missing.length - b.missing.length));
}

export async function writeRecipe(llm, { idea, items, minutes, servings, notes = "" }, onChars = () => {}) {
  const prompt = `Write the full recipe for "${idea.title}": ${idea.summary || ""}\n`
    + `Ingredients I have: ${items.join(", ")}, plus ${STAPLES}. Serves ${servings}.\n`
    + (notes ? `Preferences: ${notes}\n` : "")
    + `total_minutes must be at most ${minutes}. Give each step realistic minutes (decimals for seconds: `
    + "0.5 = 30 seconds). When a step is waiting (boiling, simmering, baking, toasting, resting) set timer=true; "
    + "the app then suggests the next prep step during the wait. Active steps (chopping, mixing, stirring, plating) "
    + "have timer=false. 4 to 8 steps. Specific quantities in ingredients. Steps are spoken aloud: one clear action "
    + "each with heat level or doneness cue, no numbering, no markdown, and don't start steps with 'while'.";
  let n = 0;
  const recipe = await generateJSON(llm, { prompt, schema: RECIPE, system: CHEF, maxTokens: 1400 }, (c) => onChars((n += c.length)));
  recipe.servings ||= servings;
  return recipe;
}

function timingReport(recipe, stepSeconds) {
  const rows = [];
  recipe.steps.forEach((s, i) => {
    if (stepSeconds[i] == null) return;
    const planned = s.minutes, actual = stepSeconds[i] / 60;
    if (actual > planned * 1.5 && actual - planned >= 2) rows.push(`step ${i + 1} ('${s.text.slice(0, 50)}') planned ${planned} min, took ${Math.round(actual)} min`);
    else if (actual < planned * 0.5 && planned - actual >= 3) rows.push(`step ${i + 1} planned ${planned} min, took only ${Math.round(actual)} min`);
  });
  return rows.join("; ") || "timings were close to the plan";
}

export async function revise(llm, { recipe, rating, tags, notes, stepSeconds, audio = null }, onChars = () => {}) {
  const current = Object.fromEntries(["title", "summary", "servings", "total_minutes", "tags", "ingredients", "steps"].map((k) => [k, recipe[k]]));
  const past = recipe.feedback.slice(-4).map((f) => `v${f.version}: ${f.rating ?? "?"}/5 ${(f.tags || []).join(", ")} ${f.notes || ""}`.trim());
  const said = notes || (audio && llm.st.audio ? "(see the attached voice note)" : "nothing else");
  const prompt = `My recipe, version ${recipe.version}:\n${JSON.stringify(current)}\n\n`
    + `I just cooked it. Rating: ${rating || "not given"}/5. Quick notes: ${tags.join(", ") || "none"}. What I said: ${said}.\n`
    + `Timing: ${timingReport(recipe, stepSeconds)}.\n`
    + (past.length ? `Feedback from earlier versions: ${past.join(" | ")}\n` : "")
    + "Improve the recipe for next time. Keep it the same dish. Make specific, minimal changes that answer "
    + "the feedback: quantities, heat, timing, order or technique. Make step minutes realistic for this cook. "
    + "If the feedback is positive, keep what works and only polish. "
    + "'heard' = one sentence restating my feedback (include what I said in the voice note, if any). "
    + "'changes' = short notes like 'Salt 1 tsp → 1/2 tsp, because you found it too salty'. "
    + "'note_for_next_time' = one friendly sentence to tell me when I start cooking it next time.";
  let n = 0;
  return generateJSON(llm, { prompt, schema: REVISION, system: CHEF, maxTokens: 1600, audio: llm.st.audio ? audio : null },
    (c) => onChars((n += c.length)));
}

export async function stepTips(llm, recipe) {
  const steps = recipe.steps.map((s, i) => `${i + 1}. ${s.text}`).join("\n");
  const out = await generateJSON(llm, { schema: TIPS, system: CHEF, maxTokens: 300, prompt:
    `Recipe: ${recipe.title}\n${steps}\n\nGive short chef's tips for at most 4 of these steps: only where a home `
    + "cook commonly goes wrong, or where a sensory doneness cue (look, smell, sound) helps. Each tip at most 15 words, "
    + "spoken aloud, no markdown. 'step' is the step number." });
  const n = recipe.steps.length;
  return Object.fromEntries(out.tips.filter((x) => x.step >= 1 && x.step <= n).map((x) => [String(x.step - 1), x.tip.trim()]));
}
