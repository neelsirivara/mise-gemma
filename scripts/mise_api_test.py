"""End-to-end test of the Mise product API with the real model (no browser).

  python scripts/mise_api_test.py [base_url]

Flow: pantry photo -> ingredients -> ideas within a time budget -> full recipe saved to the book
-> cook mode (narration, timers, cues) -> feedback -> revised version 2.
"""
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8050"
TEST = Path(__file__).resolve().parent.parent / "assets" / "test"
ok_all = True


def check(name, ok, detail=""):
    global ok_all
    ok_all &= bool(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {str(detail)[:200]}" if detail else ""), flush=True)


def req(method, path, body=None, files=None, fields=None, stream=False):
    headers = {}
    data = None
    if files is not None or fields is not None:
        b = uuid.uuid4().hex
        data = b""
        for k, v in (fields or {}).items():
            data += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, name, blob, ct in files or []:
            data += f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {ct}\r\n\r\n'.encode() + blob + b"\r\n"
        data += f"--{b}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    r = urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=headers, method=method), timeout=300)
    if stream:
        return [json.loads(line) for line in r if line.strip()]
    return json.loads(r.read())


def events(since):
    return [e for e in req("GET", f"/api/state?since={since}")["events"]]


# wait for warm-up
for _ in range(240):
    try:
        if req("GET", "/api/state")["engine"].get("ready"):
            break
    except OSError:
        pass
    time.sleep(1)

print("\n== recipe book")
book = req("GET", "/api/mise/book")
check("starter recipes seeded", len(book) >= 4, [b["title"] for b in book])

print("\n== pantry photo → ingredients → ideas → recipe")
t = time.time()
scan = req("POST", "/api/mise/pantry/scan", files=[("images", "jars.jpg", (TEST / "spice_jars.jpg").read_bytes(), "image/jpeg"),
                                                    ("images", "avo.jpg", (TEST / "Avocado_Hass_-_single_and_halved.jpg").read_bytes(), "image/jpeg")])
check("scan finds ingredients in 2 photos", len(scan["items"]) >= 2, f"{scan['items']} in {scan['seconds']}s")
items = scan["items"] + ["eggs", "bread", "lime"]
ideas = req("POST", "/api/mise/pantry/ideas", {"items": items, "minutes": 20, "servings": 2, "notes": ""})
check("3 ideas returned", len(ideas["ideas"]) == 3, [(i["title"], i["total_minutes"]) for i in ideas["ideas"]])
check("ideas respect 20-minute budget", all(i["total_minutes"] <= 20 for i in ideas["ideas"]), f"{ideas['seconds']}s")
evs = req("POST", "/api/mise/pantry/recipe", {"items": items, "minutes": 20, "servings": 2, "notes": "", "idea": ideas["ideas"][0]}, stream=True)
done = next((e for e in evs if e["type"] == "done"), None)
errs = [e for e in evs if e["type"] == "error"]
check("recipe written + saved to book", done and not errs, errs or (done["recipe"]["title"], f"{done['seconds']}s", f"{len(evs)} progress events"))
r = done["recipe"]
check("recipe within time budget", r["total_minutes"] <= 20, r["total_minutes"])
check("every step has minutes", all(s["minutes"] > 0 for s in r["steps"]), [(s["minutes"], s["timer"]) for s in r["steps"]])
print(f"  pantry flow total {time.time() - t:.1f}s")

print("\n== cook mode (starter recipe with timers: Spaghetti Carbonara)")
carb = next(b for b in req("GET", "/api/mise/book") if "Carbonara" in b["title"])
since = time.time()
st = req("POST", "/api/mise/cook/start", {"id": carb["id"]})
says = [e["text"] for e in events(since) if e["kind"] == "say"]
check("intro narrated with ETA", any("eating around" in s for s in says), says[:1])
check("step 1 narrated + timer started", any("Step 1 of" in s and "timer" in s for s in says), says[-1:])
check("get-ahead cue while water boils", any("get ahead" in s for s in says))
state = req("GET", "/api/state")
check("timer card running", any(not t["fired"] for t in state["timers"]), state["timers"])
since = time.time()
req("POST", "/api/mise/cook/next")
req("POST", "/api/mise/cook/repeat")
says = [e["text"] for e in events(since) if e["kind"] == "say"]
check("next + repeat narrate step 2", sum("Step 2 of" in s for s in says) == 2, says)

print("\n== voice companion (chat tools in cook mode)")
def chat(text):
    b = uuid.uuid4().hex
    data = f'--{b}\r\nContent-Disposition: form-data; name="text"\r\n\r\n{text}\r\n--{b}--\r\n'.encode()
    rr = urllib.request.urlopen(urllib.request.Request(BASE + "/api/chat", data=data,
                                headers={"Content-Type": f"multipart/form-data; boundary={b}"}), timeout=120)
    evs = [json.loads(l) for l in rr if l.strip()]
    return [e["name"] for e in evs if e["type"] == "tool"], "".join(e.get("text", "") for e in evs if e["type"] == "text")
tools, reply = chat("ok done, what's next?")
check("'done, what's next' → next", "next" in tools, f"{tools} {reply}")
tools, reply = chat("how long is left?")
check("'how long is left' → time_left", "time_left" in tools, f"{tools} {reply}")
tools, reply = chat("can I use bacon instead of guanciale?")
check("cooking question → spoken answer", "question" in tools and len(reply) > 20, f"{tools} {reply}")
tools, reply = chat("we're finished, plating up now")
check("'we're finished' → finish", "finish" in tools, f"{tools} {reply}")
cs = req("GET", "/api/mise/cook/state")
check("awaiting feedback after finish", cs.get("awaiting_feedback") == carb["id"])

print("\n== feedback → version 2")
evs = req("POST", "/api/mise/feedback", fields={"id": carb["id"], "rating": "3", "tags": "too salty,sauce scrambled",
                                                 "notes": "Way too salty and the egg scrambled a bit.", "improve": "true"}, stream=True)
done = next((e for e in evs if e["type"] == "done"), None)
check("revision saved as v2", done and done["recipe"]["version"] == 2, [e for e in evs if e["type"] == "error"] or done["changes"])
if done:
    check("changes cite the feedback", any("salt" in c.lower() for c in done["changes"]), done["changes"])
    check("note for next time", bool(done["recipe"]["note_for_next_time"]), done["recipe"]["note_for_next_time"])
    full = req("GET", f"/api/mise/book/{carb['id']}")
    check("v1 kept in history", full["history"] and full["history"][0]["version"] == 1)
    since = time.time()
    req("POST", "/api/mise/cook/start", {"id": carb["id"]})
    intro = next((e["text"] for e in events(since) if e.get("tone") == "intro"), "")
    check("next cook mentions the change", "version 2" in intro, intro)
    req("POST", "/api/mise/cook/stop")

print("\nALL PASS" if ok_all else "\nSOME CHECKS FAILED")
sys.exit(0 if ok_all else 1)
