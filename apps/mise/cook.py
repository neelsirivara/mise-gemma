"""Cook mode: walk through one recipe, one spoken step at a time.

The session narrates each step (as "say" events the UI speaks), starts a timer for
hands-off steps, suggests what to prep while something cooks, warns before timers end,
and records how long each step actually took, which feeds the next revision.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from core.state import SESSION, Timer, set_timer

from . import book


def _mins(m: float) -> str:
    if m < 1:
        return f"{round(m * 60)} seconds"
    m = round(m) if m >= 2 else round(m, 1)
    return f"{m:g} minute{'s' if m != 1 else ''}"


def _mins_adj(m: float) -> str:
    """'an 8-minute timer', 'a 30-second timer'."""
    s = f"{round(m * 60)}-second" if m < 1 else f"{round(m) if m >= 2 else round(m, 1):g}-minute"
    return ("an " if s[0] == "8" or s.startswith(("11-", "18-")) else "a ") + s


def _short(text: str, words: int = 4) -> str:
    w = text.rstrip(".").split()
    return " ".join(w[:words]) + ("…" if len(w) > words else "")


def _clock(t: float) -> str:
    return time.strftime("%I:%M %p", time.localtime(t)).lstrip("0")


@dataclass
class Cook:
    recipe: dict | None = None
    step: int = 0
    started_at: float = 0.0
    step_started_at: float = 0.0
    step_seconds: list[float] = field(default_factory=list)
    cues_done: set = field(default_factory=set)
    step_timers: dict = field(default_factory=dict)  # step index -> timer id
    active: bool = False
    awaiting_feedback: str | None = None  # recipe id that was just cooked
    last_said: str = ""
    lock: threading.RLock = field(default_factory=threading.RLock)

    # ------------------------------------------------------------- narration
    def say(self, text: str, tone: str = "narration"):
        self.last_said = text
        SESSION.emit("say", text=text, tone=tone)

    def _step_line(self, i: int) -> str:
        r = self.recipe
        s = r["steps"][i]
        n = len(r["steps"])
        parts = [f"Step {i + 1} of {n}." if i < n - 1 else f"Last step, {i + 1} of {n}.", s["text"]]
        if s["timer"]:
            parts.append(f"I've started {_mins_adj(s['minutes'])} timer.")
            nxt = r["steps"][i + 1] if i + 1 < n else None
            if s["minutes"] >= 3 and nxt and not nxt["timer"]:
                parts.append(f"While that's going, you can get ahead on the next step: {nxt['text']}")
        elif s["minutes"] >= 1:
            parts.append(f"This takes about {_mins(s['minutes'])}.")
        tip = (r.get("tips") or {}).get(str(i))
        if tip:
            parts.append(f"Tip: {tip}")
        return " ".join(parts)

    def eta(self) -> float:
        r = self.recipe
        rest = sum(s["minutes"] for s in r["steps"][self.step + 1:])
        cur = r["steps"][self.step]["minutes"] * 60 - (time.time() - self.step_started_at)
        return time.time() + max(cur, 0) + rest * 60

    # ------------------------------------------------------------- actions
    def start(self, rid: str) -> dict:
        with self.lock:
            self.recipe = book.get(rid)
            self.step, self.active, self.awaiting_feedback = 0, True, None
            self.started_at = self.step_started_at = time.time()
            self.step_seconds = [0.0] * len(self.recipe["steps"])
            self.cues_done, self.step_timers = set(), {}
            SESSION.timers = []
            r = self.recipe
            intro = [f"Let's make {r['title']}" + (f", version {r['version']}." if r["version"] > 1 else ".")]
            if r.get("note_for_next_time"):
                intro.append(r["note_for_next_time"])
            done_at = time.time() + r["total_minutes"] * 60
            intro.append(f"It takes about {_mins(r['total_minutes'])}, so you'll be eating around {_clock(done_at)}.")
            waits = [(s["minutes"], k) for k, s in enumerate(r["steps"]) if s["timer"]]
            if waits:
                m, k = max(waits)
                intro.append(f"The longest wait is step {k + 1}, about {_mins(m)}; I'll tell you what to prep while it cooks.")
            intro.append(f"You need {len(r['ingredients'])} ingredients; they're on screen. "
                         "Say next when you're ready to move on, or ask me anything.")
            self.say(" ".join(intro), "intro")
            self._enter(0)
            if not r.get("tips"):
                threading.Thread(target=self._make_tips, args=(r["id"], r["version"]), daemon=True).start()
            return self.state()

    def _make_tips(self, rid: str, version: int):
        """Chef's tips per step (common mistakes, doneness cues), written once per recipe version and saved."""
        from . import chef
        try:
            tips = chef.step_tips(self.recipe)
            r = book.get(rid)
            if r["version"] == version:
                r["tips"] = tips
                book._write(r)
            with self.lock:
                if self.recipe and self.recipe["id"] == rid:
                    self.recipe["tips"] = tips
        except Exception:
            pass  # tips are a bonus; cooking works without them

    def _enter(self, i: int):
        self.step, self.step_started_at = i, time.time()
        SESSION.clear_fired()  # finished timers from earlier steps don't follow you into this one
        s = self.recipe["steps"][i]
        if s["timer"] and i not in self.step_timers:
            set_timer(f"Step {i + 1}: {_short(s['text'])}", s["minutes"])
            self.step_timers[i] = SESSION.timers[-1].id
        SESSION.emit("cook", step=i)
        self.say(self._step_line(i))

    def _leave(self):
        self.step_seconds[self.step] += time.time() - self.step_started_at

    def goto(self, i: int) -> dict:
        with self.lock:
            if not self.active:
                return self.state()
            i = max(0, min(len(self.recipe["steps"]) - 1, i))
            self._leave()
            self._enter(i)
            return self.state()

    def next(self) -> dict:
        with self.lock:
            if not self.active:
                return self.state()
            if self.step >= len(self.recipe["steps"]) - 1:
                self.say("That was the last step. When you've plated up, say finished and tell me how it went.", "cue")
                return self.state()
            return self.goto(self.step + 1)

    def back(self) -> dict:
        return self.goto(self.step - 1)

    def repeat(self) -> dict:
        with self.lock:
            if self.active:
                self.say(self._step_line(self.step))
            return self.state()

    def finish(self) -> dict:
        with self.lock:
            if not self.recipe:
                return self.state()
            if self.active:
                self._leave()
                book.log_cook(self.recipe["id"], self.step_seconds, finished=True)
            total = round((time.time() - self.started_at) / 60)
            self.active, self.awaiting_feedback = False, self.recipe["id"]
            SESSION.timers = []  # the meal is done; so are its timers
            self.say(f"Nice work. That took {total} minutes. How did it turn out? Tell me what you'd change, "
                     "and I'll improve the recipe for next time.", "feedback")
            SESSION.emit("cook", step=self.step, finished=True)
            return self.state()

    def stop(self):
        with self.lock:
            self.active, self.recipe = False, None
            SESSION.timers = []

    # ------------------------------------------------------------- time cues (called ~1/s)
    def tick(self):
        with self.lock:
            if not self.active:
                return
            now = time.time()
            s = self.recipe["steps"][self.step]
            for i, tid in self.step_timers.items():
                t = next((x for x in SESSION.timers if x.id == tid), None)
                if t and not t.fired and t.seconds >= 180 and t.remaining() <= 60 and ("warn", i) not in self.cues_done:
                    self.cues_done.add(("warn", i))
                    self.say(f"One minute left on step {i + 1}.", "cue")
                if t and t.fired and ("done", i) not in self.cues_done:
                    self.cues_done.add(("done", i))
                    if i == self.step:
                        self.say("Time's up on this step. Check it, then say next.", "cue")
                    else:
                        what = self.recipe["steps"][i]["text"].rstrip(".")
                        self.say(f"Heads up: the timer from step {i + 1} is done. {what}. Check it when you can.", "cue")
            planned = max(s["minutes"], 1) * 60
            if not s["timer"] and now - self.step_started_at > max(2 * planned, planned + 120) \
                    and ("slow", self.step) not in self.cues_done:
                self.cues_done.add(("slow", self.step))
                self.say("No rush. Say next when you're ready, or ask me if you're stuck.", "cue")

    # ------------------------------------------------------------- views
    def state(self) -> dict:
        with self.lock:
            if not self.recipe:
                return {"active": False, "awaiting_feedback": self.awaiting_feedback}
            r, now = self.recipe, time.time()
            return {
                "active": self.active, "awaiting_feedback": self.awaiting_feedback,
                "recipe": {k: r[k] for k in ("id", "title", "version", "servings", "total_minutes", "ingredients",
                                             "steps", "note_for_next_time", "changes")},
                "step": self.step, "step_elapsed": round(now - self.step_started_at),
                "elapsed": round(now - self.started_at),
                "eta": _clock(self.eta()) if self.active else None,
                "step_seconds": [round(x) for x in self.step_seconds],
                "last_said": self.last_said,
            }

    def summary(self) -> str:
        with self.lock:
            if not self.recipe:
                return ""
            r = self.recipe
            lines = [f"COOKING: {r['title']} v{r['version']} ({'in progress' if self.active else 'finished'})"]
            for i, s in enumerate(r["steps"]):
                mark = ">> NOW" if i == self.step and self.active else ("done" if i < self.step else "todo")
                lines.append(f"[{mark}] step {i + 1}: {s['text']} ({s['minutes']:g} min{', timer' if s['timer'] else ''})")
            lines.append("INGREDIENTS: " + "; ".join(f"{i['qty']} {i['item']}".strip() for i in r["ingredients"]))
            if self.awaiting_feedback:
                lines.append("The cook just finished. Ask how it went; when they tell you, call give_feedback.")
            return "\n".join(lines)


COOK = Cook()
