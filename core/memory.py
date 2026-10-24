"""Visual memory: every watch tick stores a thumbnail + caption. With
EmbeddingGemma 2 (text+vision) present, frames and questions share one
embedding space, so "where did I leave my keys?" retrieves the frame where keys
were visible, even if the caption never mentioned them.
Falls back to keyword search over captions when the embedder isn't available."""
from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass, field

from . import config
from .state import SESSION

EMBED_MODEL = config.MODELS_DIR / "embeddinggemma-2-text-vision-440m.litertlm"


@dataclass
class Moment:
    id: int
    t: float
    caption: str
    objects: list[str]
    thumb: bytes
    vec: list[float] | None = None


@dataclass
class Memory:
    moments: list[Moment] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    embedder: object = None
    embed_error: str = ""
    _next: int = 0

    def _engine(self):
        if self.embedder is None and not self.embed_error:
            try:
                import litert_lm
                mk = lambda cache: litert_lm.EmbeddingEngine(
                    str(EMBED_MODEL), backend=litert_lm.Backend.GPU(), vision_backend=litert_lm.Backend.GPU(),
                    cache_dir=str(cache))
                try:
                    self.embedder = mk(config.CACHE_DIR)
                except Exception:  # cache locked by another server process
                    alt = config.CACHE_DIR / f"proc-{os.getpid()}"
                    alt.mkdir(parents=True, exist_ok=True)
                    self.embedder = mk(alt)
            except Exception as e:  # missing file / unsupported backend
                self.embed_error = f"{type(e).__name__}: {e}"
        return self.embedder

    def _embed(self, content) -> list[float] | None:
        eng = self._engine()
        if not eng:
            return None
        try:
            return list(eng.compute_embedding(content).embedding)
        except Exception as e:
            self.embed_error = f"{type(e).__name__}: {e}"
            return None

    def add(self, caption: str, objects: list[str], thumb: bytes):
        import litert_lm
        vec = self._embed(litert_lm.Content.ImageBytes(bytes=thumb)) if EMBED_MODEL.exists() else None
        with self.lock:
            m = Moment(self._next, time.time(), caption, objects, thumb, vec)
            self._next += 1
            self.moments.append(m)
            self.moments = self.moments[-500:]
        return m

    def search(self, query: str, k: int = 3) -> list[tuple[float, Moment]]:
        with self.lock:
            ms = list(self.moments)
        if not ms:
            return []
        qv = None
        if any(m.vec for m in ms):
            import litert_lm
            qv = self._embed(litert_lm.Content.Text(text=query))
        q_words = {w.strip("?.,!").lower() for w in query.split() if len(w) > 2}
        scored = []
        for m in ms:
            text = (m.caption + " " + " ".join(m.objects)).lower()
            kw = sum(1 for w in q_words if w in text) / (len(q_words) or 1)
            sim = _cos(qv, m.vec) if qv and m.vec else 0.0
            scored.append((sim + 0.3 * kw, m))
        scored.sort(key=lambda x: -x[0])
        return scored[:k]

    def get(self, mid: int) -> Moment | None:
        with self.lock:
            return next((m for m in self.moments if m.id == mid), None)

    def clear(self):
        with self.lock:
            self.moments = []


def _cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1
    nb = math.sqrt(sum(x * x for x in b)) or 1
    return dot / (na * nb)


MEMORY = Memory()


def _ago(t: float) -> str:
    s = int(time.time() - t)
    return f"{s} seconds ago" if s < 90 else f"{s // 60} minutes ago"


def recall(query: str) -> dict:
    """Searches visual memory of everything the camera has seen, e.g. to answer "where did I leave my keys?" or "did I already add salt?".

    Args:
        query: What to look for, e.g. "keys" or "adding salt to the bowl".
    """
    words = {w.strip("?.,!").lower() for w in query.split() if len(w) > 2}
    with SESSION.lock:
        actions = [{"when": _ago(e["t"]), "action": e["text"]} for e in SESSION.log
                   if any(w in e["text"].lower() for w in words)][-5:]
    hits = MEMORY.search(query)
    if hits:
        SESSION.emit("recall", ids=[m.id for _, m in hits], query=query)
    if not hits and not actions:
        return {"found": False, "note": "nothing logged or seen yet"}
    return {"found": True, "logged_actions": actions, "camera_moments": [
        {"when": _ago(m.t), "scene": m.caption, "objects": m.objects[:8], "score": round(s, 3)} for s, m in hits]}
