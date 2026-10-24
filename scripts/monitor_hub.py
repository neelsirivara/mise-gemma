"""Watch a running Mise hub and print one line per meaningful change (phone connects/drops,
hub down/up, voice turns, cook-mode progress, recipe versions). Used for live demo checks.

  python scripts/monitor_hub.py [https://127.0.0.1:8443]
"""
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://127.0.0.1:8443"
PORT = BASE.rsplit(":", 1)[-1].strip("/")
CA = Path(__file__).resolve().parent.parent / ".certs" / "mise-local-ca.crt"
ctx = ssl.create_default_context(cafile=str(CA)) if CA.exists() else ssl._create_unverified_context()
ctx.check_hostname = False


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def phones():
    """Remote (non-loopback) peers with an established connection to the hub port."""
    try:
        out = subprocess.run(["netstat", "-an"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return set()
    peers = set()
    for line in out.splitlines():
        m = re.search(rf"[\d.]+:{PORT}\s+([\d.]+):\d+\s+(ESTABLISHED|ESTAB)", line)
        if m and not m.group(1).startswith("127."):
            peers.add(m.group(1))
    return peers


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, context=ctx, timeout=5).read())


prev_peers, hub_up, turns, cook_key, versions, since = None, None, None, None, {}, time.time()
idle_since = {}
say(f"monitoring {BASE}")
while True:
    peers = phones()
    if prev_peers is not None:
        for p in peers - prev_peers:
            say(f"phone connected from {p}")
        for p in prev_peers - peers:
            idle_since[p] = time.time()
    # report a drop only if the device stays gone 20 s (Safari closes and reopens connections)
    for p, t in list(idle_since.items()):
        if p in peers:
            del idle_since[p]
        elif time.time() - t > 20:
            say(f"phone {p} disconnected (no connection for 20 s)")
            del idle_since[p]
    prev_peers = peers

    try:
        st = get(f"/api/state?since={since}")
        e = st["engine"]
        if hub_up is not True:
            say(f"hub up · ready={e['ready']} · talk={e['talk']}" + (f" · LOAD ERROR {e['load_error']}" if e.get("load_error") else ""))
        hub_up = True
        if turns is not None and e["turns"] > turns:
            last = e.get("last", {})
            say(f"voice/chat turn #{e['turns']}: first reply in {last.get('ttft_s')}s, total {last.get('total_s')}s"
                + (" · with audio" if last.get("audio") else "") + (" · with camera frame" if last.get("image") else ""))
        turns = e["turns"]
        for ev in st["events"]:
            since = max(since, ev["t"])
            if ev["kind"] == "say" and ev.get("tone") in ("revised", "error"):
                say(f"hub said: {ev['text'][:120]}")
            if ev["kind"] == "timer_done":
                say(f"timer done: {ev['label']}")
        cs = get("/api/mise/cook/state")
        key = (cs.get("recipe", {}) or {}).get("title"), cs.get("step"), cs.get("active"), cs.get("awaiting_feedback")
        if cook_key is not None and key != cook_key:
            if cs.get("active"):
                say(f"cooking {key[0]}: step {cs['step'] + 1}/{len(cs['recipe']['steps'])} · eat around {cs.get('eta')}")
            elif cs.get("awaiting_feedback"):
                say(f"finished cooking {key[0]}; waiting for feedback")
            else:
                say("cook mode closed")
        cook_key = key
        first = not versions
        for r in get("/api/mise/book"):
            if r["id"] in versions and r["version"] > versions[r["id"]]:
                say(f"recipe '{r['title']}' is now version {r['version']}")
            if r["id"] not in versions and not first:
                say(f"new recipe in the book: '{r['title']}' ({r['total_minutes']} min)")
            versions[r["id"]] = r["version"]
    except Exception as ex:
        if hub_up is not False:
            say(f"HUB NOT RESPONDING: {type(ex).__name__}: {str(ex)[:100]}")
        hub_up = False
    time.sleep(3)
