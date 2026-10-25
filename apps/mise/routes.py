"""HTTP API for the Mise product UI, mounted at /api/mise.

Long model calls (writing a recipe, revising it) stream NDJSON progress so the UI can show
something better than a spinner; everything else is plain JSON.
"""
from __future__ import annotations

import json
import threading
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from core.state import SESSION

from . import book, chef
from .cook import COOK

router = APIRouter()


def _ndjson(gen):
    def run():
        try:
            for ev in gen:
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:  # surface model/parse failures to the UI instead of a dead stream
            yield json.dumps({"type": "error", "error": f"{type(e).__name__}: {e}"}) + "\n"
    return StreamingResponse(run(), media_type="application/x-ndjson")


def _get(rid: str) -> dict:
    try:
        return book.get(rid)
    except (KeyError, FileNotFoundError):
        raise HTTPException(404, "That recipe isn't in the book anymore.")


# ---------------------------------------------------------------- recipe book
@router.get("/book")
def list_book():
    return [book.summary_row(r) for r in book.all_recipes()]


@router.get("/book/{rid}")
def get_recipe(rid: str):
    return _get(rid)


@router.delete("/book/{rid}")
def delete_recipe(rid: str):
    _get(rid)
    book.delete(rid)
    return {"ok": True}


# ---------------------------------------------------------------- pantry → ideas → recipe
@router.post("/pantry/scan")
async def pantry_scan(images: list[UploadFile] = File(...)):
    data = [await f.read() for f in images][:4]
    t = time.time()
    from anyio import to_thread
    items = await to_thread.run_sync(chef.scan_pantry, data)
    return {"items": items, "seconds": round(time.time() - t, 1)}


class IdeasIn(BaseModel):
    items: list[str]
    minutes: int = Field(30, ge=5, le=240)
    servings: int = Field(2, ge=1, le=12)
    notes: str = ""


@router.post("/pantry/ideas")
def pantry_ideas(body: IdeasIn):
    if not body.items:
        raise HTTPException(400, "Add at least one ingredient first.")
    t = time.time()
    known = [r["title"] for r in book.all_recipes()][:12]
    ideas = chef.suggest(body.items, body.minutes, body.servings, body.notes, avoid=known)
    return {"ideas": ideas, "seconds": round(time.time() - t, 1)}


class RecipeIn(IdeasIn):
    idea: dict


@router.post("/pantry/recipe")
def pantry_recipe(body: RecipeIn):
    def gen():
        for ev in chef.write_recipe(body.idea, body.items, body.minutes, body.servings, body.notes):
            if ev["type"] == "recipe":
                r = book.add(ev["recipe"], source="pantry", pantry=body.items)
                yield {"type": "done", "recipe": r, "seconds": ev["seconds"],
                       "over_time": r["total_minutes"] > body.minutes}
            else:
                yield ev
    return _ndjson(gen())


# ---------------------------------------------------------------- cook mode
class CookIn(BaseModel):
    id: str = ""
    step: int = 0


@router.post("/cook/start")
def cook_start(body: CookIn):
    _get(body.id)
    return COOK.start(body.id)


@router.post("/cook/{action}")
def cook_action(action: str, body: CookIn | None = None):
    fn = {"next": COOK.next, "back": COOK.back, "repeat": COOK.repeat, "finish": COOK.finish}.get(action)
    if action == "goto":
        return COOK.goto(body.step if body else 0)
    if action == "stop":
        COOK.stop()
        return COOK.state()
    if not fn:
        raise HTTPException(404, f"Unknown cook action '{action}'.")
    return fn()


@router.get("/cook/state")
def cook_state():
    return COOK.state()


# ---------------------------------------------------------------- voice note → text
@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    from anyio import to_thread

    from .companion import transcribe as hear
    data = await audio.read()
    t = time.time()
    text = await to_thread.run_sync(hear, data)
    return {"text": text, "seconds": round(time.time() - t, 1)}


# ---------------------------------------------------------------- feedback → new version
def _latest_step_seconds(r: dict) -> list[float]:
    cooks = [c for c in r["cooks"] if c["version"] == r["version"]]
    return cooks[-1]["step_seconds"] if cooks else []


def revise_stream(rid: str, rating: int | None, tags: list[str], notes: str, audio: bytes | None, improve: bool):
    r = book.add_feedback(rid, {"rating": rating, "tags": tags, "notes": notes, "voice_note": bool(audio)})
    if COOK.awaiting_feedback == rid:
        COOK.awaiting_feedback = None
    if not improve:
        yield {"type": "done", "recipe": r, "changes": [], "heard": notes}
        return
    for ev in chef.revise(r, rating, tags, notes, _latest_step_seconds(r), audio):
        if ev["type"] == "revision":
            new = book.revise(rid, ev["recipe"], ev["changes"], ev["note_for_next_time"], ev["heard"])
            # keep what was heard with the feedback entry, so the history reads naturally
            new["feedback"][-1]["heard"] = ev["heard"]
            book._write(new)
            yield {"type": "done", "recipe": new, "changes": ev["changes"], "heard": ev["heard"]}
        else:
            yield ev


@router.post("/feedback")
async def feedback(id: str = Form(...), rating: int = Form(0), tags: str = Form(""), notes: str = Form(""),
                   improve: bool = Form(True), audio: UploadFile | None = File(None)):
    _get(id)
    aud = await audio.read() if audio else None
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    return _ndjson(revise_stream(id, rating or None, tag_list, notes.strip(), aud, improve))


def revise_in_background(rid: str, rating: int | None, notes: str):
    """Used by the voice tool: the chat turn holds the model, so revise after it finishes."""
    def run():
        try:
            for ev in revise_stream(rid, rating, [], notes, None, True):
                if ev["type"] == "done":
                    ch = ev["changes"]
                    SESSION.emit("say", tone="revised", text=f"I've saved version {ev['recipe']['version']}. "
                                 + (f"Main change: {ch[0]}" if ch else ""))
                    SESSION.emit("book", id=rid)
        except Exception as e:
            SESSION.emit("say", tone="error", text=f"I couldn't update the recipe: {e}")
    threading.Thread(target=run, daemon=True).start()
