"""Mise - a hands-free, fully offline sous-chef.
The laptop camera watches the counter; you talk with messy hands; Gemma tracks
the recipe, runs timers, and catches mistakes (double salting, raw chicken on
the veggie board, a pan about to boil over)."""
from __future__ import annotations

import json
from pathlib import Path

from core.app import App
from core.state import COMMON_TOOLS, SESSION

RECIPES_DIR = Path(__file__).parent / "recipes"


class Kitchen:
    recipe: dict | None = None
    step = 0  # 0-based
    scale = 1.0
    done_streak = 0


K = Kitchen()


def recipe_names() -> list[str]:
    return sorted(p.stem for p in RECIPES_DIR.glob("*.json"))


def current_step() -> str:
    if not K.recipe:
        return "(no recipe loaded)"
    steps = K.recipe["steps"]
    return steps[K.step]["text"] if K.step < len(steps) else "(recipe finished)"


# ---------------------------------------------------------------- tools
def load_recipe(name: str) -> dict:
    """Loads a saved recipe by name so the cook can follow it step by step.

    Args:
        name: Recipe name, e.g. "carbonara" or "guacamole".
    """
    key = name.lower().strip().replace(" ", "_")
    for p in RECIPES_DIR.glob("*.json"):
        r = json.loads(p.read_text())
        if key in p.stem or key in r["title"].lower():
            with SESSION.lock:
                K.recipe, K.step, K.scale = r, 0, 1.0
                SESSION.emit("recipe", title=r["title"])
            return {"ok": True, "title": r["title"], "steps": len(r["steps"]), "first_step": r["steps"][0]["text"]}
    return {"ok": False, "available": recipe_names()}


def create_recipe(title: str, ingredients: list[str], steps: list[str]) -> dict:
    """Creates a new recipe (e.g. from ingredients seen on the counter) and loads it.

    Args:
        title: Name of the dish.
        ingredients: Ingredient lines with quantities, e.g. ["2 eggs", "100 g spaghetti"].
        steps: Short imperative cooking steps, in order.
    """
    if K.recipe and K.recipe["title"].lower() in title.lower() and K.step == 0:
        return {"ok": False, "note": f"'{K.recipe['title']}' is already loaded from saved recipes; use it"}
    asked = f"{title} {SESSION.last_user}".lower()
    saved = next((n for n in recipe_names() if n.replace("_", " ") in asked), None)
    if saved:  # the model sometimes improvises a recipe we already have; use the tested one
        return load_recipe(saved)
    with SESSION.lock:
        K.recipe = {"title": title, "servings": 2, "ingredients": ingredients, "steps": [{"text": s} for s in steps]}
        K.step, K.scale = 0, 1.0
        SESSION.emit("recipe", title=title)
    return {"ok": True, "steps": len(steps)}


def go_to_step(step_number: int) -> dict:
    """Moves the recipe to a specific step. Call this when the cook finishes a step or asks to go forward or back.

    Args:
        step_number: 1-based step number to show next.
    """
    if not K.recipe:
        return {"ok": False, "error": "no recipe loaded"}
    n = len(K.recipe["steps"])
    with SESSION.lock:
        K.step = max(0, min(n, step_number - 1))
        SESSION.emit("step", step=K.step)
    s = K.recipe["steps"][K.step] if K.step < n else {}
    return {"ok": True, "step": K.step + 1, "text": s.get("text", "recipe finished"),
            "suggested_timer_minutes": s.get("timer_min")}


def scale_recipe(multiplier: float) -> dict:
    """Scales ingredient quantities, e.g. 2 to double or 0.5 to halve.

    Args:
        multiplier: Factor to scale the recipe by.
    """
    K.scale = multiplier
    SESSION.emit("scale", multiplier=multiplier)
    return {"ok": True}


# ---------------------------------------------------------------- hooks
def summary() -> str:
    if not K.recipe:
        return "RECIPE: none loaded. Saved recipes: " + ", ".join(recipe_names())
    r = K.recipe
    lines = [f"RECIPE: {r['title']} (serves {r.get('servings', '?')}, scaled x{K.scale:g})",
             "INGREDIENTS: " + "; ".join(r["ingredients"])]
    for i, s in enumerate(r["steps"]):
        mark = ">> NOW" if i == K.step else ("done" if i < K.step else "todo")
        extra = f" [timer {s['timer_min']} min]" if s.get("timer_min") else ""
        lines.append(f"[{mark}] step {i + 1}: {s['text']}{extra}")
    return "\n".join(lines)


def panels() -> list[dict]:
    if not K.recipe:
        return [{"title": "Recipes", "items": [{"text": n.replace("_", " ").title(), "state": "todo"} for n in recipe_names()]}]
    r = K.recipe
    steps = [{"text": s["text"], "state": "done" if i < K.step else "active" if i == K.step else "todo"}
             for i, s in enumerate(r["steps"])]
    ings = [{"text": i if K.scale == 1 else f"{i}  (×{K.scale:g})", "state": "todo"} for i in r["ingredients"]]
    return [{"title": r["title"], "kind": "steps", "items": steps}, {"title": "Ingredients", "items": ings}]


def watch_context() -> str:
    actions = "; ".join(e["text"] for e in SESSION.log[-5:]) or "none"
    check = ""
    if K.recipe and K.step < len(K.recipe["steps"]):
        check = K.recipe["steps"][K.step].get("check", "")
    return f"Current recipe step: {current_step()}\nWhat 'done' looks like: {check or 'use judgement'}\nRecent actions: {actions}"


def on_watch(data: dict):
    # require two consecutive "done" frames before nudging, the small watcher is optimistic
    K.done_streak = K.done_streak + 1 if data.get("done") else 0
    if K.done_streak == 2 and K.recipe and K.step < len(K.recipe["steps"]):
        SESSION.emit("suggest", text=f"Looks like step {K.step + 1} is done. Say 'next' to continue.")


def reset():
    K.recipe, K.step, K.scale = None, 0, 1.0


SYSTEM = """You are Mise, a hands-free sous-chef running fully offline on this laptop.
The cook has messy hands, so they talk to you and you see their counter through a camera.

Rules:
- After calling tools, always say one short sentence confirming what you did.
- For questions about the past ("did I already...", "where did I leave/see..."), check RECENT ACTIONS first, then call recall.
- Replies are spoken aloud: 1-3 short sentences, no markdown, no lists, no emoji.
- Use tools to change anything: timers, steps, recipes, logging. Never claim you did something without calling the tool.
- When the cook says they finished a step ("done", "next"), call go_to_step with the next number and read the new step.
  If the new step has a timer, offer to start it (start it right away if they asked).
- When you see or hear them add a seasoning or ingredient, call log_action. Use RECENT ACTIONS to catch mistakes
  (e.g. salting twice) and warn them.
- If the cook names a dish that is in the saved recipes list, call load_recipe (never create_recipe for it).
- If asked what to make, look at the image and call create_recipe with a simple dish using what is visible; pass steps as a list.
- When an image is attached, ground answers in what is actually visible. Say when you're unsure.
- Flag food-safety issues: undercooked poultry, cross-contamination, unattended hot oil.
- If the audio is clearly not directed at you (background chatter), reply with exactly: NOOP

{state}
"""

WATCH_PROMPT = """You are the eyes of a kitchen assistant. Look at this camera frame of the cook's counter or stove.
{context}

Reply with ONLY a JSON object:
{{"see": "<at most 10 words describing what the cook is doing>",
  "objects": ["<visible ingredients and tools>"],
  "done": <true if the current step looks complete, else false>,
  "alert": "<short spoken warning ONLY for a real problem (burning, boiling over, smoke, knife near edge, raw meat touching other food), else empty string>"}}"""

APP = App(
    id="mise",
    name="Mise",
    tagline="The offline sous-chef that watches, listens, and keeps up.",
    system=SYSTEM,
    watch_prompt=WATCH_PROMPT,
    tools=COMMON_TOOLS + [load_recipe, create_recipe, go_to_step, scale_recipe],
    summary=summary,
    panels=panels,
    watch_context=watch_context,
    on_watch=on_watch,
    reset=reset,
    quick_prompts=["Let's make guacamole", "What can I make with what's on my counter?", "Next step", "Which jar is the cumin?",
                   "Set a timer for 30 seconds", "Does this look right?", "I just added the salt"],
    accent="#e8743b",
)
