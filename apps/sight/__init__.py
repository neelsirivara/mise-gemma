"""Sight - an offline narrator for blind and low-vision users.
Describes surroundings, reads labels and screens aloud, remembers where things
were last seen ("where did I leave my keys?"), and guides the camera toward a
requested object ("a bit left... it's in the center now"). Nothing leaves the device:
the camera sees your home, your mail, your medication."""
from __future__ import annotations

import time

from core.app import App
from core.state import COMMON_TOOLS, SESSION


class Memory:
    target: str | None = None  # object the user is searching for
    places: dict[str, dict] = {}  # object -> {"where": str, "t": float}
    last_scene = ""


M = Memory()


# ---------------------------------------------------------------- tools
def find_object(name: str) -> dict:
    """Starts guiding the user's camera toward an object until it is in view.

    Args:
        name: The object to find, e.g. "keys" or "the red mug".
    """
    M.target = name
    SESSION.emit("search", target=name)
    last = M.places.get(name.lower())
    return {"ok": True, "searching_for": name, "last_seen": last["where"] if last else None}


def stop_finding() -> dict:
    """Stops the current object search."""
    M.target = None
    SESSION.emit("search", target=None)
    return {"ok": True}


def remember_location(name: str, where: str) -> dict:
    """Remembers where an object is, so the user can ask later.

    Args:
        name: The object, e.g. "keys".
        where: Where it is, e.g. "on the kitchen counter next to the fruit bowl".
    """
    M.places[name.lower()] = {"where": where, "t": time.time()}
    SESSION.emit("memory", name=name, where=where)
    return {"ok": True}


# ---------------------------------------------------------------- hooks
def _ago(t: float) -> str:
    m = int((time.time() - t) // 60)
    return "just now" if m < 1 else f"{m} min ago"


def summary() -> str:
    lines = [f"SEARCHING FOR: {M.target}" if M.target else "SEARCHING FOR: nothing"]
    if M.places:
        lines.append("OBJECT MEMORY: " + "; ".join(f"{k}: {v['where']} ({_ago(v['t'])})" for k, v in M.places.items()))
    if M.last_scene:
        lines.append(f"LAST SCENE: {M.last_scene}")
    return "\n".join(lines)


def panels() -> list[dict]:
    out = []
    if M.target:
        out.append({"title": "Finding", "kind": "steps", "items": [{"text": M.target, "state": "active"}]})
    out.append({"title": "Object memory", "items": [
        {"text": f"{k} — {v['where']} · {_ago(v['t'])}", "state": "todo"} for k, v in M.places.items()]
        or [{"text": "Objects Sight notices are remembered here", "state": "todo"}]})
    return out


def watch_context() -> str:
    ctx = f"Previous description: {M.last_scene or 'none'}"
    if M.target:
        ctx += (f"\nThe user is searching for: {M.target}. If it is visible, set alert to where it is in the frame "
                f"(left/right/center, near/far). If not visible, set alert to empty.")
    return ctx


def on_watch(data: dict):
    if data.get("see"):
        M.last_scene = data["see"]
    for obj, where in (data.get("where") or {}).items():
        if isinstance(where, str) and where:
            M.places[obj.lower()] = {"where": where, "t": time.time()}
    if M.target and data.get("alert"):
        SESSION.emit("found", target=M.target)


def reset():
    M.target, M.places, M.last_scene = None, {}, ""


SYSTEM = """You are Sight, a calm, precise visual assistant for a blind or low-vision user. You run fully offline,
so their private surroundings, mail and medication never leave the device. You see through their camera.

Rules:
- After calling tools, always say one short sentence confirming what you did.
- For questions about the past ("did I already...", "where did I leave/see..."), check RECENT ACTIONS first, then call recall.
- Replies are spoken aloud: short, concrete, no markdown, no emoji. Lead with the most important fact.
- Use clock-face or left/right/near/far directions relative to the camera.
- When reading text (labels, mail, screens, medication), read it verbatim first, then summarize if long.
  For medication, always read the drug name, dose and any warnings.
- When asked to find something, call find_object. When the user says where something is, call remember_location.
- Answer "where is my X" from OBJECT MEMORY when the object is not visible.
- Never guess about safety-critical details (expiry dates, doses, traffic). Say when you can't read something.
- If the audio is clearly not directed at you, reply with exactly: NOOP

{state}
"""

WATCH_PROMPT = """You are the eyes of a blind user's assistant. Look at this camera frame.
{context}

Reply with ONLY a JSON object:
{{"see": "<one short sentence: the scene, only what changed since the previous description>",
  "objects": ["<notable objects>"],
  "where": {{"<object>": "<where it is, e.g. on the desk left of the laptop>"}},
  "done": false,
  "alert": "<obstacle or hazard directly ahead, OR the location of the searched object, else empty string>"}}"""

APP = App(
    id="sight",
    name="Sight",
    tagline="Private, offline eyes for people who can't see.",
    system=SYSTEM,
    watch_prompt=WATCH_PROMPT,
    tools=COMMON_TOOLS + [find_object, stop_finding, remember_location],
    summary=summary,
    panels=panels,
    watch_context=watch_context,
    on_watch=on_watch,
    reset=reset,
    quick_prompts=["What's in front of me?", "Read this to me", "Help me find my water bottle",
                   "Where did I leave my keys?", "Is this the right medication?", "Describe the person in front of me"],
    accent="#5b8def",
    watch_interval_s=5.0,
    speak_watch=True,
)
