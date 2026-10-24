"""The recipe book: every recipe you've generated or saved, with its full version history.

One JSON file per recipe in data/mise/recipes/. A recipe is mutable only through `revise()`,
which snapshots the current version into `history` before applying changes, so every
"v3: halved the salt because you said it was too salty" stays traceable.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from core import config

BOOK_DIR = config.DATA_DIR / "mise" / "recipes"
SEED_DIR = Path(__file__).parent / "recipes"
_lock = threading.RLock()

# fields that define a version of the dish (snapshotted on every revision)
VERSIONED = ("title", "summary", "servings", "total_minutes", "ingredients", "steps")


def _now() -> float:
    return round(time.time(), 1)


def slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "recipe"


def normalize(r: dict) -> dict:
    """Coerce model output or a hand-written file into the canonical shape."""
    ings = []
    for i in r.get("ingredients", []):
        if isinstance(i, str):
            ings.append({"item": i, "qty": ""})
        else:
            ings.append({"item": str(i.get("item", "")).strip(), "qty": str(i.get("qty", "")).strip()})
    steps = []
    for s in r.get("steps", []):
        if isinstance(s, str):
            s = {"text": s}
        minutes = s.get("minutes", s.get("timer_min", 2)) or 0
        steps.append({
            "text": str(s.get("text", "")).strip(),
            "minutes": round(float(minutes), 1),
            # a timer makes sense for hands-off waits (simmer, bake, rest), not for active chopping
            "timer": bool(s.get("timer", bool(s.get("timer_min")))),
            "check": str(s.get("check", "") or ""),
        })
    total = r.get("total_minutes") or round(sum(s["minutes"] for s in steps))
    return {
        "title": str(r.get("title", "Untitled")).strip(),
        "summary": str(r.get("summary", "") or "").strip(),
        "servings": int(r.get("servings", 2) or 2),
        "total_minutes": int(round(float(total))),
        "tags": [str(t) for t in r.get("tags", [])][:6],
        "ingredients": [i for i in ings if i["item"]],
        "steps": [s for s in steps if s["text"]],
    }


def _path(rid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{1,64}", rid):
        raise KeyError(rid)
    return BOOK_DIR / f"{rid}.json"


def _write(r: dict):
    BOOK_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path(r["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(r, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_path(r["id"]))  # atomic on the same volume


def add(recipe: dict, source: str = "generated", pantry: list[str] | None = None) -> dict:
    with _lock:
        base = normalize(recipe)
        rid = f"{slug(base['title'])}-{uuid.uuid4().hex[:4]}"
        r = {"id": rid, **base, "version": 1, "source": source, "pantry": pantry or [],
             "created": _now(), "updated": _now(), "changes": [], "note_for_next_time": "",
             "history": [], "feedback": [], "cooks": []}
        _write(r)
        return r


def get(rid: str) -> dict:
    with _lock:
        return json.loads(_path(rid).read_text(encoding="utf-8"))


def all_recipes() -> list[dict]:
    with _lock:
        out = [json.loads(p.read_text(encoding="utf-8")) for p in BOOK_DIR.glob("*.json")]
    # most recently cooked or edited first
    return sorted(out, key=lambda r: max([r["updated"]] + [c["t"] for c in r["cooks"]]), reverse=True)


def summary_row(r: dict) -> dict:
    ratings = [f["rating"] for f in r["feedback"] if f.get("rating")]
    return {"id": r["id"], "title": r["title"], "summary": r["summary"], "total_minutes": r["total_minutes"],
            "servings": r["servings"], "version": r["version"], "tags": r["tags"], "source": r["source"],
            "cooked": len(r["cooks"]), "rating": ratings[-1] if ratings else None,
            "last_cooked": r["cooks"][-1]["t"] if r["cooks"] else None, "steps": len(r["steps"])}


def find(name: str) -> dict | None:
    key = name.lower().strip()
    rows = all_recipes()
    return (next((r for r in rows if r["title"].lower() == key), None)
            or next((r for r in rows if key in r["title"].lower() or slug(key) in r["id"]), None))


def delete(rid: str):
    with _lock:
        _path(rid).unlink(missing_ok=True)


def log_cook(rid: str, step_seconds: list[float], finished: bool) -> dict:
    with _lock:
        r = get(rid)
        r["cooks"].append({"t": _now(), "version": r["version"], "step_seconds": [round(x) for x in step_seconds],
                           "finished": finished})
        _write(r)
        return r


def add_feedback(rid: str, fb: dict) -> dict:
    with _lock:
        r = get(rid)
        r["feedback"].append({"t": _now(), "version": r["version"], **fb})
        _write(r)
        return r


def revise(rid: str, new_recipe: dict, changes: list[str], note: str, reason: str) -> dict:
    """Save a new version. The previous version is kept whole in `history`."""
    with _lock:
        r = get(rid)
        r["history"].append({"version": r["version"], "t": r["updated"], "changes": r["changes"],
                             **{k: r[k] for k in VERSIONED}})
        base = normalize(new_recipe)
        base["title"] = r["title"]  # the dish keeps its name across versions
        r.update({k: base[k] for k in VERSIONED})
        r["tags"] = base["tags"] or r["tags"]
        r["version"] += 1
        r["changes"] = [c for c in changes if c][:8]
        r["note_for_next_time"] = note
        r["revision_reason"] = reason
        r["updated"] = _now()
        _write(r)
        return r


def seed():
    """First run: import the bundled starter recipes so the book isn't empty."""
    with _lock:
        if BOOK_DIR.exists() and any(BOOK_DIR.glob("*.json")):
            return
        for p in sorted(SEED_DIR.glob("*.json")):
            src = json.loads(p.read_text(encoding="utf-8"))
            r = add(src, source="starter")
            r["created"] = r["updated"] = _now() - 86400  # sort below anything you make today
            _write(r)
