"""Shared session state (timers, action log, UI event feed) + tools every app gets.

Tool functions are plain Python with type hints + Google-style docstrings;
LiteRT-LM (and Ollama) build the function-calling schema from them.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Timer:
    id: str
    label: str
    seconds: float
    ends_at: float
    fired: bool = False

    def remaining(self) -> float:
        return max(0.0, self.ends_at - time.time())


@dataclass
class Session:
    timers: list[Timer] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)  # things the user did / the model saw
    seen: list[str] = field(default_factory=list)  # objects noticed by the watcher
    events: list[dict] = field(default_factory=list)  # feed polled by the UI
    last_user: str = ""  # the latest typed request, so tools can sanity-check the model's arguments
    lock: threading.RLock = field(default_factory=threading.RLock)

    def emit(self, kind: str, **data):
        with self.lock:
            self.events.append({"id": uuid.uuid4().hex[:8], "t": time.time(), "kind": kind, **data})
            self.events = self.events[-200:]

    def tick(self):
        """Fire finished timers. Called by the UI poll loop."""
        with self.lock:
            for t in self.timers:
                if not t.fired and t.remaining() <= 0:
                    t.fired = True
                    self.emit("timer_done", label=t.label)

    def summary(self) -> str:
        with self.lock:
            lines = []
            active = [t for t in self.timers if not t.fired]
            if active:
                lines.append("TIMERS: " + "; ".join(
                    f"{t.label} {int(t.remaining() // 60)}m{int(t.remaining() % 60):02d}s left" for t in active))
            if self.seen:
                lines.append("SEEN RECENTLY: " + ", ".join(self.seen[-20:]))
            if self.log:
                lines.append("RECENT ACTIONS: " + " | ".join(e["text"] for e in self.log[-8:]))
            return "\n".join(lines)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "timers": [{"id": t.id, "label": t.label, "remaining": round(t.remaining(), 1),
                            "seconds": t.seconds, "fired": t.fired} for t in self.timers],
                "log": self.log[-20:],
                "seen": self.seen[-30:],
            }

    def reset(self):
        with self.lock:
            self.timers, self.log, self.seen = [], [], []
            self.emit("reset")


SESSION = Session()


def set_timer(label: str, minutes: float) -> dict:
    """Starts a countdown timer.

    Args:
        label: Short name for what is being timed, e.g. "pasta" or "solder cool-down".
        minutes: Duration in minutes. Use decimals for seconds (0.5 = 30 seconds).
    """
    with SESSION.lock:
        t = Timer(uuid.uuid4().hex[:6], label, minutes * 60, time.time() + minutes * 60)
        SESSION.timers.append(t)
        SESSION.emit("timer_set", label=label, seconds=t.seconds)
    return {"ok": True, "label": label, "minutes": minutes}


def cancel_timer(label: str) -> dict:
    """Cancels a running timer.

    Args:
        label: The label of the timer to cancel.
    """
    with SESSION.lock:
        before = len(SESSION.timers)
        SESSION.timers = [t for t in SESSION.timers if t.fired or label.lower() not in t.label.lower()]
        SESSION.emit("timer_cancel", label=label)
        return {"ok": len(SESSION.timers) < before}


def log_action(text: str) -> dict:
    """Records something the user did or that you observed, so you can catch mistakes later.

    Args:
        text: What happened, in a few words, e.g. "added 1 tsp salt".
    """
    with SESSION.lock:
        SESSION.log.append({"t": time.time(), "text": text})
        SESSION.emit("log", text=text)
    return {"ok": True}


def note_seen(items: list[str]) -> dict:
    """Records objects or ingredients you can see in the camera frame.

    Args:
        items: Short names, e.g. ["eggs", "spinach"].
    """
    with SESSION.lock:
        for i in items:
            if i and i.lower() not in (s.lower() for s in SESSION.seen):
                SESSION.seen.append(i)
        SESSION.emit("seen", items=items)
    return {"ok": True}


COMMON_TOOLS = [set_timer, cancel_timer, log_action]
