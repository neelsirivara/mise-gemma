"""The cook-mode voice companion.

Free-form tool calling across many tools proved unreliable for a 2B model ("what's next" sometimes
became finish_cooking, or the tool name was spoken aloud). Instead, every utterance in cook mode
goes through ONE constrained-JSON call that must pick an intent from a fixed list, and also returns
what it heard (a transcript for the UI) and a spoken answer for real questions. The server then
carries the intent out deterministically. One model pass, native audio, no malformed output.
"""
from __future__ import annotations

import re
import time
from typing import Iterator

from core import llm
from core.state import SESSION, log_action, set_timer

from .cook import COOK

INTENTS = ["next", "back", "repeat", "time_left", "finish", "set_timer", "question", "feedback", "log", "ignore"]

SCHEMA = {"type": "object", "properties": {
    "heard": {"type": "string"},
    "intent": {"type": "string", "enum": INTENTS},
    "timer_seconds": {"type": "integer"},
    "timer_label": {"type": "string"},
    "rating": {"type": "integer", "minimum": 0, "maximum": 5},
    "answer": {"type": "string"},
}, "required": ["heard", "intent", "timer_seconds", "timer_label", "rating", "answer"]}

GUIDE = """Classify what the cook just said (audio or text) and answer if needed. Intents:
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
- log: they report adding something ("I added the salt") so it can be remembered.
- ignore: background talk not meant for you.
"heard" = what they said, short. "answer" is spoken aloud: plain words, no markdown. For next/back/repeat/finish
leave answer empty; the app narrates the step itself. Unused fields: 0 or empty string."""


_memory: list[tuple[str, str]] = []  # (what the cook said, what Mise answered), for follow-ups
_memory_for = {"id": None}


def active() -> bool:
    return COOK.active or bool(COOK.awaiting_feedback)


def handle(text: str | None, image: bytes | None, audio: bytes | None) -> Iterator[dict]:
    """Yields the same event shapes as core.llm streams: {"type": "tool"|"text"|"heard", ...}."""
    state = COOK.summary()
    timers = "; ".join(f"{t.label}: {round(t.remaining())}s left" for t in SESSION.timers if not t.fired) or "none"
    rid = (COOK.recipe or {}).get("id")
    if _memory_for["id"] != rid:  # new dish, fresh conversation
        _memory.clear()
        _memory_for["id"] = rid
    convo = "\n".join(f"Cook: {h}\nMise: {a or '(acted)'}" for h, a in _memory[-4:])
    last = _memory[-1] if _memory else None
    prompt = (f"{GUIDE}\n\nCURRENT STATE:\n{state}\nRUNNING TIMERS: {timers}\n"
              + (f"\nRECENT CONVERSATION:\n{convo}\n" if convo else "")
              + (f"\nThe previous question was \"{last[0]}\". If the cook now says 'it', 'that', 'how much' or "
                 "'what heat' without naming the thing, they mean what that previous question was about; answer for "
                 "that thing, not for the recipe in general.\n" if last else "")
              + "\n" + (f"The cook said: {text}" if text else "The cook's words are in the attached audio."))
    t0 = time.time()
    out = llm.talk().complete_json(prompt, SCHEMA, images=[image] if image else [], audio=audio, max_tokens=220)
    intent, answer = out["intent"], out["answer"].strip()
    if intent == "question" and last and _is_follow_up(out["heard"]):
        answer = _follow_up(last, out["heard"]) or answer
    if intent != "ignore":
        _memory.append((out["heard"], answer))
        del _memory[:-8]
    yield {"type": "heard", "text": out["heard"], "intent": intent, "seconds": round(time.time() - t0, 2)}
    yield {"type": "tool", "name": intent, "args": {k: out[k] for k in ("timer_seconds", "timer_label", "rating") if out[k]},
           "result": {"ok": True}}

    if intent == "next":
        COOK.next()
    elif intent == "back":
        COOK.back()
    elif intent == "repeat":
        COOK.repeat()
    elif intent == "finish":
        COOK.finish() if COOK.active else None
    elif intent == "time_left":
        live = [t for t in SESSION.timers if not t.fired]
        parts = [f"{t.label.split(':')[0]} has {_dur(t.remaining())} left" for t in live]
        st = COOK.state()
        if st.get("eta"):
            parts.append(f"you'll be eating around {st['eta']}")
        yield {"type": "text", "text": (", and ".join(parts) or "No timers are running") + "."}
    elif intent == "set_timer":
        sec = max(5, int(out["timer_seconds"] or 60))
        set_timer(out["timer_label"] or "timer", sec / 60)
        yield {"type": "text", "text": f"Timer set for {_dur(sec)}."}
    elif intent == "log":
        log_action(out["heard"])
        yield {"type": "text", "text": answer or "Noted."}
    elif intent == "feedback":
        from .routes import revise_in_background
        rid = COOK.awaiting_feedback or (COOK.recipe or {}).get("id")
        if rid:
            revise_in_background(rid, out["rating"] or None, out["heard"])
            yield {"type": "text", "text": "Thanks. I'm updating the recipe for next time; it'll be ready in a moment."}
    elif intent == "question":
        yield {"type": "text", "text": answer or "I'm not sure. Could you ask that another way?"}
    elif intent == "ignore":
        yield {"type": "text", "text": "NOOP"}


_FOLLOW = re.compile(r"\b(it|that|this|them|those|one|how much|how many|what heat|how long|instead)\b", re.I)


def _is_follow_up(heard: str) -> bool:
    """Short questions that lean on the previous one ("how much of it?", "and what heat?")."""
    return len(heard.split()) <= 7 and bool(_FOLLOW.search(heard))


def _follow_up(last: tuple[str, str], heard: str) -> str:
    """A small model resolves 'it' poorly inside the big classification prompt, so answer follow-ups in a
    focused second pass that only sees the previous exchange (the current step pulls it off topic)."""
    dish = (COOK.recipe or {}).get("title", "this dish")
    prompt = (f"We're cooking {dish}. Earlier the cook asked: \"{last[0]}\"\nYou answered: \"{last[1]}\"\n"
              f"Now they ask: \"{heard}\"\n'It' means the thing from the earlier question, so answer about that thing. "
              "Answer in one or two short spoken sentences with a concrete amount, heat or cue. No markdown.")
    try:
        return "".join(e.get("text", "") for e in llm.talk().stream(
            "You are Mise, a concise kitchen coach.", [], prompt, None, None, []) if e["type"] == "text").strip()
    except Exception:
        return ""


def _dur(sec: float) -> str:
    sec = max(0, round(sec))
    if sec < 60:
        return f"{sec} seconds"
    m, s = divmod(sec, 60)
    return f"{m} minute{'s' if m != 1 else ''}" + (f" {s} seconds" if s and m < 5 else "")
