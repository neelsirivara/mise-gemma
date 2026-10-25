// Structured output without a grammar: show the model the JSON shape, parse, check, repair.
// Mirrors core/llm.py (skeleton, matches, extract_json); the laptop also has grammar-constrained
// decoding as a fallback, the phone retries with a stricter prompt instead.

export function skeleton(s) {
  if (s.enum) return `<one of: ${s.enum.join(" | ")}>`;
  if (s.type === "object") return Object.fromEntries(Object.entries(s.properties || {}).map(([k, v]) => [k, skeleton(v)]));
  if (s.type === "array") return [skeleton(s.items || {})];
  return { string: "<string>", integer: 0, number: 0, boolean: false }[s.type] ?? null;
}

export function matches(o, s) {
  if (s.enum && !s.enum.includes(o)) return false;
  switch (s.type) {
    case "object":
      if (!o || typeof o !== "object" || Array.isArray(o) || (s.required || []).some((k) => !(k in o))) return false;
      return Object.entries(s.properties || {}).every(([k, v]) => !(k in o) || matches(o[k], v));
    case "array":
      return Array.isArray(o) && o.length >= (s.minItems || 0) && o.every((x) => matches(x, s.items || {}));
    case "string": return typeof o === "string" && o.length >= (s.minLength || 0);
    case "integer": return Number.isInteger(o) && o >= (s.minimum ?? -1e18) && o <= (s.maximum ?? 1e18);
    case "number": return typeof o === "number" && isFinite(o);
    case "boolean": return typeof o === "boolean";
    default: return true;
  }
}

// Nudge near-misses into shape: "5" → 5, "true" → true, missing optional-looking fields → empty, extra items cut.
export function repair(o, s) {
  switch (s.type) {
    case "object": {
      if (!o || typeof o !== "object" || Array.isArray(o)) return o;
      const out = { ...o };
      for (const [k, v] of Object.entries(s.properties || {})) {
        if (k in out) out[k] = repair(out[k], v);
        else if (v.type === "string" && !v.minLength && !v.enum) out[k] = "";
        else if (v.type === "integer" || v.type === "number") out[k] = v.minimum ?? 0;
        else if (v.type === "boolean") out[k] = false;
        else if (v.type === "array" && !v.minItems) out[k] = [];
      }
      return out;
    }
    case "array":
      if (!Array.isArray(o)) return o;
      return o.slice(0, s.maxItems ?? o.length).map((x) => repair(x, s.items || {}));
    case "integer": {
      const n = typeof o === "string" ? parseFloat(o) : o;
      return typeof n === "number" && isFinite(n) ? Math.round(n) : o;
    }
    case "number": {
      const n = typeof o === "string" ? parseFloat(o) : o;
      return typeof n === "number" && isFinite(n) ? n : o;
    }
    case "boolean": return typeof o === "string" ? /^(true|yes)$/i.test(o) : o;
    case "string": return o == null ? "" : typeof o === "string" ? o : String(o);
    default: return o;
  }
}

export function extractJSON(text) {
  const a = text.indexOf("{"), b = text.lastIndexOf("}");
  if (a < 0 || b <= a) return null;
  const raw = text.slice(a, b + 1);
  for (const t of [raw, raw.replace(/,\s*([}\]])/g, "$1").replace(/[“”]/g, '"')]) {
    try { return JSON.parse(t); } catch {}
  }
  return null;
}

// Ask for JSON, stream progress, validate; one retry with the bad answer pointed out.
export async function generateJSON(llm, { prompt, schema, system = "", images = [], audio = null, maxTokens = 800 }, onChunk = () => {}) {
  const shape = JSON.stringify(skeleton(schema));
  const media = [...images.map((image) => ({ image })), ...(audio ? [{ audio }] : [])];
  let ask = `${prompt}\n\nReply with ONLY one JSON object in exactly this shape, no prose, no code fences:\n${shape}`;
  for (let attempt = 0; attempt < 2; attempt++) {
    const text = await llm.generate({ system, parts: [...media, { text: ask }], maxTokens }, onChunk);
    let obj = extractJSON(text);
    if (obj) obj = repair(obj, schema);
    if (obj && matches(obj, schema)) return obj;
    ask = `${prompt}\n\nYour previous answer was not valid. Output ONLY valid JSON (double quotes, no comments, no trailing `
      + `commas) with every field filled, exactly this shape:\n${shape}`;
  }
  throw new Error("Gemma's answer didn't come out right. Try again.");
}
