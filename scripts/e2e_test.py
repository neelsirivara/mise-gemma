"""Drive a running server through a scripted demo (no browser needed).

  .venv\\Scripts\\python scripts\\e2e_test.py [base_url] [app]
"""
import json
import sys
import time
from pathlib import Path

import urllib.request
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
APP = sys.argv[2] if len(sys.argv) > 2 else "mise"
TEST = Path(__file__).resolve().parent.parent / "assets" / "test"


def post(path, fields=None, files=None):
    b = uuid.uuid4().hex
    body = b""
    for k, v in (fields or {}).items():
        body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, (name, data, ctype) in (files or {}).items():
        body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n"
    body += f"--{b}--\r\n".encode()
    req = urllib.request.Request(BASE + path, data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    return urllib.request.urlopen(req, timeout=300)


def chat(text="", image=None, audio=None):
    files = {}
    if image:
        files["image"] = ("frame.jpg", (TEST / image).read_bytes(), "image/jpeg")
    if audio:
        files["audio"] = ("speech.wav", (TEST / audio).read_bytes(), "audio/wav")
    t = time.time()
    out, tools, done = "", [], {}
    with post("/api/chat", {"text": text} if text else {}, files) as r:
        for line in r:
            ev = json.loads(line)
            if ev["type"] == "text":
                out += ev["text"]
            elif ev["type"] == "tool":
                tools.append(f"{ev['name']}({json.dumps(ev['args'])})")
            elif ev["type"] == "error":
                out += " [ERROR " + ev["error"] + "]"
            elif ev["type"] == "done":
                done = ev
    label = text or f"<audio {audio}>"
    print(f"\n> {label}{' +' + image if image else ''}\n  tools: {tools}\n  reply: {out.strip()}\n  ttft={done.get('ttft_s')}s total={time.time() - t:.2f}s")


def watch(image):
    with post("/api/watch", files={"image": ("f.jpg", (TEST / image).read_bytes(), "image/jpeg")}) as r:
        print(f"\n[watch {image}] {json.loads(r.read())}")


def wait_ready():
    for _ in range(300):
        try:
            st = json.loads(urllib.request.urlopen(BASE + "/api/state").read())
        except OSError:
            time.sleep(1)
            continue
        if st["engine"].get("load_error"):
            sys.exit("load error: " + st["engine"]["load_error"])
        if st["engine"]["ready"] and st["engine"]["watch"] != "loading…":
            print("engine:", st["engine"]["talk"], "|", st["engine"]["watch"])
            return
        time.sleep(1)


wait_ready()
urllib.request.urlopen(urllib.request.Request(BASE + "/api/reset", method="POST"))

if APP == "mise":
    watch("Avocado_Hass_-_single_and_halved.jpg")
    chat("What can I make with what's on my counter?", image="Avocado_Hass_-_single_and_halved.jpg")
    chat("Actually, let's make the saved guacamole recipe.")
    chat(audio="next.wav")
    chat(audio="timer.wav")
    chat("I just added half a teaspoon of salt.")
    chat("Did I already add salt?")
    watch("Guacamole_IMGP1271.jpg")
    chat("Does this look done?", image="Guacamole_IMGP1271.jpg")
    chat("Where did I see the avocados?")
elif APP == "bench":
    chat("What is this board?", image="Arduino_Uno_-_R3.jpg")
    chat("What resistor do I need for a blue LED on 5 volts at 15 milliamps?")
    chat("Read these resistors' color bands.", image="Electronic-Axial-Lead-Resistors-Array.jpg")
    chat("Walk me through the blink build.")
    chat(audio="next.wav")
elif APP == "sight":
    watch("Avocado_Hass_-_single_and_halved.jpg")
    chat("What's in front of me?", image="Avocado_Hass_-_single_and_halved.jpg")
    chat(audio="read.wav", image="Arduino_Uno_-_R3.jpg")
    chat("Help me find my water bottle.")
    chat("Where did I see the avocado?")

st = json.loads(urllib.request.urlopen(BASE + "/api/state").read())
print("\npanels:", json.dumps(st["panels"])[:600])
print("timers:", st["timers"], "\nlog:", st["log"], "\nmemory:", st["engine"]["memory"], st["engine"]["embedder"])
