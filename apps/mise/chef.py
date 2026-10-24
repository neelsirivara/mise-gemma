"""Everything Mise asks the model to *write*: pantry scans, recipe ideas, full recipes, and
revisions from feedback. Each call uses constrained decoding against a JSON schema, so
the output always parses; we still sanity-check the content (time budget, step totals).
"""
from __future__ import annotations

import json
import time
from typing import Iterator

from core import llm

STAPLES = "salt, pepper, cooking oil, water"

INGREDIENT = {"type": "object", "properties": {"item": {"type": "string"}, "qty": {"type": "string"}},
              "required": ["item", "qty"]}
STEP = {"type": "object", "properties": {"text": {"type": "string", "minLength": 8}, "minutes": {"type": "number"},
                                         "timer": {"type": "boolean"}}, "required": ["text", "minutes", "timer"]}
RECIPE = {"type": "object", "properties": {
    "title": {"type": "string"}, "summary": {"type": "string"}, "servings": {"type": "integer"},
    "total_minutes": {"type": "integer"}, "tags": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
    "ingredients": {"type": "array", "minItems": 2, "maxItems": 16, "items": INGREDIENT},
    "steps": {"type": "array", "minItems": 3, "maxItems": 9, "items": STEP}},
    "required": ["title", "summary", "servings", "total_minutes", "tags", "ingredients", "steps"]}
PANTRY = {"type": "object", "properties": {"items": {"type": "array", "minItems": 1, "maxItems": 30,
                                                       "items": {"type": "string", "minLength": 2}}},
          "required": ["items"]}
IDEAS = {"type": "object", "properties": {"ideas": {"type": "array", "minItems": 3, "maxItems": 3, "items": {
    "type": "object", "properties": {
        "title": {"type": "string"}, "summary": {"type": "string"}, "total_minutes": {"type": "integer"},
        "uses": {"type": "array", "maxItems": 10, "items": {"type": "string"}},
        "missing": {"type": "array", "maxItems": 3, "items": {"type": "string"}}},
    "required": ["title", "summary", "total_minutes", "uses", "missing"]}}}, "required": ["ideas"]}
REVISION = {"type": "object", "properties": {
    "heard": {"type": "string"},
    "changes": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "string"}},
    "note_for_next_time": {"type": "string"},
    "recipe": RECIPE}, "required": ["heard", "changes", "note_for_next_time", "recipe"]}

CHEF = ("You are Mise, a precise home-cooking assistant. Recipes are read aloud one step at a time to a cook "
        "with busy hands, so every step is one clear action with quantities, heat level and a doneness cue.")


def _engine():
    return llm.talk()


def scan_pantry(images: list[bytes]) -> list[str]:
    out = _engine().complete_json(
        "These photos show my cupboard, fridge or counter. List every distinct food ingredient you can actually see. "
        "Use short everyday names a recipe would use (for example 'canned chickpeas', 'eggs', 'basmati rice', "
        "'smoked paprika'). Read labels where you can. Skip non-food items and anything you cannot see. "
        "Do not list the same ingredient twice.",
        PANTRY, images=images, max_tokens=300)
    seen, items = set(), []
    for i in out["items"]:
        k = i.strip().lower()
        if k and k not in seen:
            seen.add(k)
            items.append(i.strip())
    return items


def suggest(items: list[str], minutes: int, servings: int, notes: str = "", avoid: list[str] = ()) -> list[dict]:
    prompt = (f"My ingredients: {', '.join(items)}. I also have {STAPLES}.\n"
              f"Time limit: {minutes} minutes total, prep included. Cooking for {servings}.\n"
              + (f"Preferences: {notes}\n" if notes else "")
              + (f"I already know these, suggest different ones: {', '.join(avoid)}\n" if avoid else "")
              + f"Suggest 3 different dishes made mostly from my ingredients. Each must really fit in {minutes} minutes. "
              "'uses' lists which of my ingredients it uses. 'missing' lists essential things I don't have "
              "(prefer none, at most two). Short titles, one-sentence summaries.")
    ideas = _engine().complete_json(prompt, IDEAS, system=CHEF, max_tokens=700)["ideas"]
    for i in ideas:  # the model sometimes stretches the budget; be honest about it in the UI
        i["over_time"] = i["total_minutes"] > minutes
    return sorted(ideas, key=lambda i: (i["over_time"], len(i["missing"])))


def write_recipe(idea: dict, items: list[str], minutes: int, servings: int, notes: str = "") -> Iterator[dict]:
    """Streams {"type":"progress","chars":n} while writing, then {"type":"recipe","recipe":{...}}."""
    prompt = (f"Write the full recipe for \"{idea['title']}\": {idea.get('summary', '')}\n"
              f"Ingredients I have: {', '.join(items)}, plus {STAPLES}. Serves {servings}.\n"
              + (f"Preferences: {notes}\n" if notes else "")
              + f"total_minutes must be at most {minutes}. Give each step realistic minutes (decimals for seconds: "
              "0.5 = 30 seconds). When a step is waiting "
              "(boiling, simmering, baking, toasting, resting) set timer=true; the app then suggests the next prep "
              "step during the wait. Active steps (chopping, mixing, stirring, plating) have timer=false. "
              "4 to 8 steps. Specific quantities in ingredients. Steps are spoken aloud: one clear action each with "
              "heat level or doneness cue, no numbering, no markdown, and don't start steps with 'while'.")
    t0, n = time.time(), 0
    for ev in _engine().stream_json(prompt, RECIPE, system=CHEF, max_tokens=1400):
        if "chunk" in ev:
            n += len(ev["chunk"])
            yield {"type": "progress", "chars": n}
        else:
            recipe = ev["result"]
    recipe["servings"] = recipe.get("servings") or servings
    yield {"type": "recipe", "recipe": recipe, "seconds": round(time.time() - t0, 1)}


def _timing_report(recipe: dict, step_seconds: list[float]) -> str:
    rows = []
    for i, (s, sec) in enumerate(zip(recipe["steps"], step_seconds)):
        planned, actual = s["minutes"], sec / 60
        if actual > planned * 1.5 and actual - planned >= 2:
            rows.append(f"step {i + 1} ('{s['text'][:50]}') planned {planned:g} min, took {actual:.0f} min")
        elif actual < planned * 0.5 and planned - actual >= 3:
            rows.append(f"step {i + 1} planned {planned:g} min, took only {actual:.0f} min")
    return "; ".join(rows) or "timings were close to the plan"


def revise(recipe: dict, rating: int | None, tags: list[str], notes: str, step_seconds: list[float],
           audio: bytes | None = None) -> Iterator[dict]:
    """Streams progress, then {"type":"revision", heard, changes, note_for_next_time, recipe}."""
    current = {k: recipe[k] for k in ("title", "summary", "servings", "total_minutes", "tags", "ingredients", "steps")}
    past = [f"v{f['version']}: {f.get('rating', '?')}/5 {', '.join(f.get('tags', []))} {f.get('notes', '')}".strip()
            for f in recipe.get("feedback", [])[-4:]]
    prompt = (f"My recipe, version {recipe['version']}:\n{json.dumps(current, ensure_ascii=False)}\n\n"
              f"I just cooked it. Rating: {rating or 'not given'}/5. Quick notes: {', '.join(tags) or 'none'}. "
              f"What I said: {notes or '(see the attached voice note)' if audio else notes or 'nothing else'}.\n"
              f"Timing: {_timing_report(recipe, step_seconds)}.\n"
              + (f"Feedback from earlier versions: {' | '.join(past)}\n" if past else "")
              + "Improve the recipe for next time. Keep it the same dish. Make specific, minimal changes that answer "
              "the feedback: quantities, heat, timing, order or technique. Make step minutes realistic for this cook. "
              "If the feedback is positive, keep what works and only polish. "
              "'heard' = one sentence restating my feedback (include what I said in the voice note, if any). "
              "'changes' = short notes like 'Salt 1 tsp → 1/2 tsp, because you found it too salty'. "
              "'note_for_next_time' = one friendly sentence to tell me when I start cooking it next time.")
    n = 0
    for ev in _engine().stream_json(prompt, REVISION, audio=audio, system=CHEF, max_tokens=1600):
        if "chunk" in ev:
            n += len(ev["chunk"])
            yield {"type": "progress", "chars": n}
        else:
            yield {"type": "revision", **ev["result"]}


TIPS = {"type": "object", "properties": {"tips": {"type": "array", "maxItems": 6, "items": {
    "type": "object", "properties": {"step": {"type": "integer"}, "tip": {"type": "string", "minLength": 8}},
    "required": ["step", "tip"]}}}, "required": ["tips"]}


def step_tips(recipe: dict) -> dict:
    """{step index (str): short spoken tip} for the steps where a pro tip really helps."""
    steps = "\n".join(f"{i + 1}. {s['text']}" for i, s in enumerate(recipe["steps"]))
    out = _engine().complete_json(
        f"Recipe: {recipe['title']}\n{steps}\n\nGive short chef's tips for at most 4 of these steps: only where a home "
        "cook commonly goes wrong, or where a sensory doneness cue (look, smell, sound) helps. Each tip at most 15 words, "
        "spoken aloud, no markdown. 'step' is the step number.", TIPS, system=CHEF, max_tokens=300)
    n = len(recipe["steps"])
    return {str(x["step"] - 1): x["tip"].strip() for x in out["tips"] if 1 <= x["step"] <= n}
