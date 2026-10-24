"""Generic FastAPI server: serves the UI and brokers camera/mic -> Gemma -> tools
for whichever app scaffold is selected.

Run:  run.cmd (Windows) / ./run.sh (macOS, Linux), or:  python -m core.server [mise|bench|sight]
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import webbrowser

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import app as app_mod, config, llm
from .memory import MEMORY, recall
from .state import SESSION, note_seen

APP = app_mod.load(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else config.APP)
if recall not in APP.tools:
    APP.tools = APP.tools + [recall]
api = FastAPI(title=APP.name)
if APP.router is not None:
    api.include_router(APP.router, prefix=f"/api/{APP.id}")
HISTORY: list[dict] = []  # text-only rolling history; images/audio are per-turn
_scope = {"v": None}  # APP.history_scope() value the history belongs to
STATS: dict = {"turns": 0, "last": {}, "watch_last": {}}


@api.on_event("startup")
def warm():
    # load models in the background so the page is up immediately
    def _load():
        t = time.time()
        try:
            talk, watch = llm.talk(), llm.watcher()
            STATS["loaded_s"] = round(time.time() - t, 1)
            # first multimodal turn compiles GPU kernels (~8s); pay that before the demo, not during it
            test = config.ROOT / "assets" / "test"
            img = next(test.glob("*.jpg"), None)
            wav = test / "next.wav"
            for _ in talk.stream("Reply with one word.", [], "Warm up.", img.read_bytes() if img else None,
                                 wav.read_bytes() if wav.exists() else None, []):
                pass
            if watch is not talk:
                watch.complete("One word.", img.read_bytes() if img else None, 4)
            if img:
                MEMORY.add("warm-up", [], img.read_bytes())
                MEMORY.clear()
            STATS["warm_s"] = round(time.time() - t, 1)
            local = f"{'https' if config.PHONE else 'http'}://127.0.0.1:{config.PORT}"
            print(f"  ready in {STATS['warm_s']}s -> {local}", flush=True)
            if os.environ.get("OPEN_BROWSER") == "1":
                webbrowser.open(local)
        except Exception as e:
            STATS["load_error"] = f"{type(e).__name__}: {e}"
            print("  MODEL LOAD FAILED:", STATS["load_error"], flush=True)
    threading.Thread(target=_load, daemon=True).start()


api.mount("/assets", StaticFiles(directory=config.ROOT / "assets"), name="assets")  # demo stills: /?still=test/x.jpg

# The page may be hosted elsewhere (e.g. Vercel) and call this laptop over the LAN.
api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@api.middleware("http")
async def headers(request, call_next):
    resp = await call_next(request)
    path = request.url.path
    if not path.startswith(("/api", "/assets")):
        resp.headers["Cache-Control"] = "no-store"  # the UI changes constantly during a hackathon
    # Chrome's Private Network Access: a public https page may call this private-IP hub
    resp.headers["Access-Control-Allow-Private-Network"] = "true"
    return resp


def prompt_state() -> str:
    parts = [APP.summary(), SESSION.summary()]
    return "\n".join(p for p in parts if p)


@api.get("/api/meta")
def meta():
    return {"id": APP.id, "name": APP.name, "tagline": APP.tagline, "accent": APP.accent,
            "quick_prompts": APP.quick_prompts, "watch_interval_s": APP.watch_interval_s,
            "speak_watch": APP.speak_watch, "attach_frame": APP.attach_frame}


@api.get("/api/state")
def state(since: float = 0):
    SESSION.tick()
    APP.tick()
    with SESSION.lock:
        events = [e for e in SESSION.events if e["t"] > since]
    t, w = llm._talk, llm._watch
    return {
        **SESSION.snapshot(),
        "panels": APP.panels(),
        "events": events,
        "engine": {"talk": t.name if t else "loading…", "watch": w.name if w else "loading…",
                   "ready": "warm_s" in STATS, "memory": len(MEMORY.moments),
                   "embedder": "EmbeddingGemma 2" if MEMORY.embedder else (MEMORY.embed_error[:80] or "keyword"),
                   **STATS},
    }


@api.post("/api/chat")
async def chat(text: str = Form(""), image: UploadFile | None = File(None), audio: UploadFile | None = File(None)):
    img = await image.read() if image else None
    aud = await audio.read() if audio else None
    SESSION.last_user = text
    if (scope := APP.history_scope()) != _scope["v"]:  # e.g. started cooking a different recipe
        HISTORY.clear()
        _scope["v"] = scope
    system = APP.system.format(state=prompt_state())
    history = HISTORY[-config.HISTORY_TURNS * 2:]

    def gen():
        t0 = time.time()
        first, out, n, tools_called, heard, custom = None, [], 0, [], None, None
        try:
            custom = APP.chat(text or None, img, aud) if APP.chat else None
            events = custom if custom is not None else llm.talk().stream(system, history, text or None, img, aud, APP.tools)
            for ev in events:
                if ev["type"] == "heard":
                    heard = ev["text"]
                if ev["type"] == "tool":
                    tools_called.append(ev)
                if ev["type"] == "text":
                    first = first or time.time() - t0
                    out.append(ev["text"])
                    n += 1
                yield json.dumps(ev, default=str) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "error": f"{type(e).__name__}: {e}"}) + "\n"
        reply = "".join(out).strip()
        if not reply and tools_called and custom is None:
            # small models often call a tool and then stop; confirm aloud for them
            reply = confirm(tools_called)
            yield json.dumps({"type": "text", "text": reply}) + "\n"
        total = time.time() - t0
        noop = reply.upper().startswith("NOOP")
        if not noop:
            HISTORY.append({"role": "user", "content": text or heard or ("[spoke]" if aud else "[showed camera]")})
            HISTORY.append({"role": "assistant", "content": reply or "(done)"})
        STATS["turns"] += 1
        STATS["last"] = {"ttft_s": round(first or total, 2), "total_s": round(total, 2), "chunks": n,
                         "image": bool(img), "audio": bool(aud)}
        yield json.dumps({"type": "done", "noop": noop, **STATS["last"]}) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def confirm(calls: list[dict]) -> str:
    """Spoken fallback when the model acted through tools but said nothing."""
    said = []
    for c in calls:
        a, r = c.get("args") or {}, c.get("result") or {}
        if not isinstance(a, dict):
            a = {}
        name = c["name"]
        if name == "set_timer":
            said.append(f"Timer set for {a.get('label', 'that')}, {a.get('minutes')} minutes.")
        elif name == "go_to_step" and r.get("ok"):
            said.append(f"Step {r.get('step')}: {r.get('text')}")
        elif name in ("load_recipe", "load_build") and r.get("ok"):
            said.append(f"Loaded {r.get('title')}. First: {r.get('first_step')}")
        elif name == "create_recipe" and r.get("ok"):
            said.append(f"Okay, {a.get('title')}. I've put {r.get('steps')} steps on screen.")
        elif name == "recall":
            acts, ms = r.get("logged_actions") or [], r.get("camera_moments") or []
            if acts:
                said.append(f"Yes, {acts[-1]['when']}: {acts[-1]['action']}.")
            elif ms:
                said.append(f"I last saw that {ms[0]['when']}: {ms[0]['scene']}.")
            else:
                said.append("I don't remember seeing that.")
        elif name == "resistor_value" and r.get("ok"):
            said.append(f"That's {r['pretty']}, {r['tolerance']} tolerance.")
        elif name == "log_action":
            said.append("Noted.")
        else:
            said.append("Done.")
    return " ".join(dict.fromkeys(said))


_watch_busy = threading.Lock()


@api.post("/api/watch")
async def watch(image: UploadFile = File(...)):
    """One tick of the always-on vision loop. Skips if the previous tick is still running."""
    if not _watch_busy.acquire(blocking=False):
        return {"skipped": True}
    try:
        img = await image.read()
        prompt = APP.watch_prompt.format(context=APP.watch_context())
        t0 = time.time()
        raw = await _run_blocking(llm.watcher().complete, prompt, img, 200)
        dt = round(time.time() - t0, 2)
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            data = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            data = {}
        objects = [str(i) for i in data.get("objects") or []][:10]
        if objects:
            note_seen(objects)
        await _run_blocking(MEMORY.add, str(data.get("see", "")), objects, img)
        APP.on_watch(data)
        if data.get("alert"):
            SESSION.emit("alert", text=data["alert"])
        STATS["watch_last"] = {"latency_s": dt}
        return {"see": data.get("see", raw[:100]), "done": bool(data.get("done")),
                "alert": data.get("alert") or "", "latency_s": dt}
    finally:
        _watch_busy.release()


async def _run_blocking(fn, *args):
    import anyio
    return await anyio.to_thread.run_sync(lambda: fn(*args))


@api.get("/api/memory/{mid}.jpg")
def memory_thumb(mid: int):
    m = MEMORY.get(mid)
    return Response(m.thumb, media_type="image/jpeg") if m else JSONResponse({"error": "gone"}, 404)


@api.post("/api/reset")
def reset():
    HISTORY.clear()
    MEMORY.clear()
    APP.reset()
    SESSION.reset()
    return {"ok": True}


@api.post("/api/tool/{name}")
async def run_tool(name: str, args: dict):
    """Direct tool call from the UI - same code path the model uses."""
    fn = {t.__name__: t for t in APP.tools}.get(name)
    if not fn:
        return JSONResponse({"error": "unknown tool"}, 404)
    return fn(**args)


@api.get("/", include_in_schema=False)
def home():
    # each app picks its own front page (Mise has a full UI in web/mise/; others share web/index.html)
    return FileResponse(config.WEB_DIR / APP.web_entry, headers={"Cache-Control": "no-store"})


# the UI files: web/ at the site root (same layout as a static Vercel deploy). Mounted last.
api.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    print(f"\n  {APP.name}: loading models (~30s). The page opens when ready. Keep this window open.\n", flush=True)
    if config.PHONE:
        # phone mode: HTTPS on all interfaces (iPhone camera/mic need HTTPS) + a plain-HTTP setup page
        from . import phone
        cert, key = phone.prepare(config.PORT, config.SETUP_PORT)
        uvicorn.run(api, host=config.PHONE_HOST, port=config.PORT, log_level="warning", ssl_certfile=cert, ssl_keyfile=key)
    else:
        uvicorn.run(api, host="127.0.0.1", port=config.PORT, log_level="warning")
