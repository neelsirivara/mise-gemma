"""Mise - the offline sous-chef that gets better every time you cook.

Product flow (UI in web/mise/, API in routes.py):
  photo of your cupboard + time you have  ->  ideas  ->  full recipe saved to your book
  cook mode: narrated steps, timers, "while that simmers..." cues, voice questions
  after cooking: rating + feedback (typed or spoken)  ->  a revised version of the recipe

Modules: book.py (recipe book + versions), chef.py (model-written content, JSON-constrained),
cook.py (cook-session state machine + time cues), routes.py (HTTP API).
"""
from __future__ import annotations

from core.app import App
from core.state import COMMON_TOOLS, SESSION

from . import book, companion
from .cook import COOK
from .routes import revise_in_background, router


# ---------------------------------------------------------------- voice tools
def start_cooking(recipe_name: str) -> dict:
    """Starts cook mode for a recipe in the recipe book and reads the first step aloud.

    Args:
        recipe_name: The recipe's name, e.g. "guacamole".
    """
    r = book.find(recipe_name)
    if not r:
        return {"ok": False, "in_book": [x["title"] for x in book.all_recipes()][:12]}
    st = COOK.start(r["id"])
    return {"ok": True, "title": r["title"], "version": r["version"], "steps": len(st["recipe"]["steps"]),
            "note": "Step 1 is already being read aloud; just add a short encouragement."}


def next_step() -> dict:
    """Moves to the next step when the cook says done, next, or ready. The new step is read aloud automatically."""
    st = COOK.next()
    return {"ok": st.get("active", False), "step": st.get("step", 0) + 1,
            "note": "The step is read aloud automatically; reply with at most a few words."}


def previous_step() -> dict:
    """Goes back one step. The step is read aloud automatically."""
    st = COOK.back()
    return {"ok": st.get("active", False), "step": st.get("step", 0) + 1}


def repeat_step() -> dict:
    """Reads the current step aloud again."""
    COOK.repeat()
    return {"ok": True, "note": "Already repeated aloud; say nothing else."}


def time_left() -> dict:
    """Reports the running timers and when the meal should be ready."""
    st = COOK.state()
    timers = [{"label": t.label, "seconds_left": round(t.remaining())} for t in SESSION.timers if not t.fired]
    return {"timers": timers, "ready_around": st.get("eta"), "step": st.get("step", 0) + 1}


def finish_cooking() -> dict:
    """Ends cook mode when the cook says they're finished or plating up, then asks how it went."""
    COOK.finish()
    return {"ok": True, "note": "The app already asked how it went aloud; don't repeat the question."}


def give_feedback(rating: int, notes: str) -> dict:
    """Saves the cook's feedback on the dish they just made and improves the recipe for next time.

    Args:
        rating: 1 to 5 stars; estimate from their words if they don't give a number.
        notes: What they said, in their words, e.g. "a bit too salty, onions burned".
    """
    rid = COOK.awaiting_feedback or (COOK.recipe or {}).get("id")
    if not rid:
        return {"ok": False, "error": "no recently cooked recipe"}
    revise_in_background(rid, max(1, min(5, int(rating))), notes)
    return {"ok": True, "note": "Revision is running; tell them you'll update the recipe and it will be ready shortly."}


# ---------------------------------------------------------------- hooks
def summary() -> str:
    s = COOK.summary()
    if s:
        return s
    rows = book.all_recipes()[:12]
    return "NOT COOKING. Recipe book: " + "; ".join(f"{r['title']} v{r['version']} ({r['total_minutes']} min)" for r in rows)


def panels() -> list[dict]:  # used by the generic UI only (web/index.html)
    st = COOK.state()
    if not st.get("recipe"):
        return [{"title": "Recipe book", "items": [{"text": r["title"], "state": "todo"} for r in book.all_recipes()[:8]]}]
    r = st["recipe"]
    return [{"title": r["title"], "kind": "steps", "items": [
        {"text": s["text"], "state": "done" if i < st["step"] else "active" if i == st["step"] else "todo"}
        for i, s in enumerate(r["steps"])]}]


def watch_context() -> str:
    st = COOK.state()
    if not st.get("active"):
        return "The cook is not following a recipe right now."
    s = st["recipe"]["steps"][st["step"]]
    actions = "; ".join(e["text"] for e in SESSION.log[-5:]) or "none"
    return f"Current step: {s['text']}\nWhat 'done' looks like: {s.get('check') or 'use judgement'}\nRecent actions: {actions}"


_watch = {"done_streak": 0}


def on_watch(data: dict):
    # two consecutive "done" frames before nudging; the small watcher is optimistic
    _watch["done_streak"] = _watch["done_streak"] + 1 if data.get("done") else 0
    if _watch["done_streak"] == 2 and COOK.active:
        # proactive, spoken: the camera thinks the step is finished
        SESSION.emit("say", tone="cue", text="That looks done to me. Say next when you're ready.")


def reset():
    COOK.stop()


SYSTEM = """You are Mise, a warm, efficient voice companion in the kitchen. Everything runs offline on this laptop.
The cook's hands are busy: they talk to you, and the camera frame shows their counter when one is attached.

Rules:
- Replies are spoken aloud: one or two short sentences, no markdown, no lists, no emoji.
- Use tools for anything that changes state. Never claim you moved a step, set a timer, or saved feedback without calling the tool.
- In cook mode: "next", "done", "ready" -> next_step. "back" -> previous_step. "again", "what?" -> repeat_step.
  "how long?" -> time_left. "finished", "we're eating" -> finish_cooking. Steps are read aloud by the app itself,
  so after next_step/previous_step/repeat_step reply with at most a few words or nothing.
- Answer cooking questions about the current step concretely (heat, doneness, substitutions) from the recipe and image.
- After cooking, when they describe how it went, call give_feedback with a 1-5 rating and their words.
- When they ask to cook something in the recipe book, call start_cooking.
- To catch mistakes, call log_action when they add salt or other key ingredients; for "did I already...", check RECENT ACTIONS, then call recall.
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

book.seed()

APP = App(
    id="mise",
    name="Mise",
    tagline="The offline sous-chef that gets better every time you cook.",
    system=SYSTEM,
    watch_prompt=WATCH_PROMPT,
    tools=COMMON_TOOLS + [start_cooking, next_step, previous_step, repeat_step, time_left, finish_cooking, give_feedback],
    summary=summary,
    panels=panels,
    watch_context=watch_context,
    on_watch=on_watch,
    reset=reset,
    quick_prompts=["Let's cook the guacamole", "Next", "Say that again", "How long is left?", "We're finished",
                   "It was great but a bit too salty"],
    accent="#2b4fd8",
    router=router,
    web_entry="mise/index.html",
    tick=COOK.tick,
    history_scope=lambda: f"{(COOK.recipe or {}).get('id')}:{(COOK.recipe or {}).get('version')}",
    # while cooking (or right after), voice goes through the structured intent router; otherwise tool chat
    chat=lambda text, image, audio: companion.handle(text, image, audio) if companion.active() else None,
)
