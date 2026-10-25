"""Browser test of the Mise product UI: real Chrome, fake camera + mic, real models.

  python scripts/mise_ui_test.py            # starts its own server on :8060 with a temp recipe book
  python scripts/mise_ui_test.py --headed

Flow: landing (4 steps, live camera) → book → photograph fridge (2 photos) → 20 min → ideas → write recipe → cook (narration,
spoken "next" through the fake mic, buttons) → feedback → version 2 shown → phone layout.
Screenshots of every screen go to assets/ui_test/mise_*.png.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FAKE, TEST, OUT = ROOT / "assets" / "fake", ROOT / "assets" / "test", ROOT / "assets" / "ui_test"
OUT.mkdir(parents=True, exist_ok=True)
ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8060)
ap.add_argument("--headed", action="store_true")
a = ap.parse_args()
BASE = f"http://127.0.0.1:{a.port}"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {str(detail)[:160]}" if detail else ""), flush=True)


data_dir = tempfile.mkdtemp(prefix="mise_ui_")
env = {**os.environ, "PYTHONUTF8": "1", "PORT": str(a.port), "GEMMA_DATA_DIR": data_dir,
       "GEMMA_WATCH_MODEL": str(ROOT / "models" / "gemma-4-E2B-it.litertlm"), "GEMMA_WATCH_BACKEND": "cpu"}
env.pop("OPEN_BROWSER", None)
server = subprocess.Popen([sys.executable, "-m", "core.server", "mise"], cwd=ROOT, env=env,
                          stdout=open(OUT / "mise_server.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT)
for _ in range(240):
    try:
        if json.loads(urllib.request.urlopen(BASE + "/api/state", timeout=3).read())["engine"].get("ready"):
            break
    except OSError:
        pass
    if server.poll() is not None:
        sys.exit("server exited; see assets/ui_test/mise_server.log")
    time.sleep(1)
print("server ready", flush=True)

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome", headless=not a.headed, args=[
        "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
        f"--use-file-for-fake-video-capture={FAKE / 'counter.mjpeg'}",
        f"--use-file-for-fake-audio-capture={FAKE / 'u_next.wav'}%noloop"])
    ctx = browser.new_context(permissions=["camera", "microphone"], viewport={"width": 1280, "height": 860})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and "favicon" not in m.text and errors.append(m.text))
    page.goto(BASE + "/")
    page.evaluate("window.mise.speaker.enabled = false")  # headless has no voices; keep timing deterministic

    print("\n== first screen: the four steps, camera live in step 1")
    page.wait_for_selector(".landing", timeout=15000)
    page.wait_for_function("document.querySelector('#vfVideo').videoWidth > 0", timeout=10000)
    check("landing shows 4 steps", page.locator(".step-head h2").count() == 4, page.locator(".step-head h2").all_inner_texts())
    check("all steps fit one laptop screen", page.evaluate("document.querySelector('#find').getBoundingClientRect().bottom <= innerHeight"))
    page.screenshot(path=str(OUT / "mise_landing.png"))
    page.click("[data-go='home']")

    print("\n== home + recipe book")
    page.wait_for_selector(".recipe-row", timeout=15000)
    check("book lists starter recipes", page.locator(".recipe-row").count() >= 4)
    page.wait_for_function("document.getElementById('hubPill').dataset.state === 'ok'", timeout=15000)
    check("hub dot is solid (connected)", page.get_attribute("#hubPill", "data-state") == "ok",
          page.get_attribute("#hubPill", "aria-label"))
    check("no 'internet not used' pill", page.locator("#netPill").count() == 0)
    page.screenshot(path=str(OUT / "mise_home.png"))

    print("\n== pantry: photos + time → ideas → recipe")
    page.click("#goPantry")
    page.wait_for_selector("#upload")
    with page.expect_file_chooser() as fc:
        page.click("#upload")
    fc.value.set_files([str(TEST / "spice_jars.jpg"), str(TEST / "Avocado_Hass_-_single_and_halved.jpg")])
    page.wait_for_function("document.querySelectorAll('.photo').length === 2")  # the scan starts straight away
    check("2 photos attached", page.locator(".photo").count() == 2)
    page.click("#vfExpand")
    page.wait_for_selector("#capShutter")
    check("full-screen camera shares the photos", page.locator(".cap-thumb").count() == 2)
    page.screenshot(path=str(OUT / "mise_capture.png"))
    page.click("#capClose")
    page.wait_for_selector(".landing")
    page.click("#times button[data-m='20']")
    t = time.time()
    page.click("#find")
    page.wait_for_selector("#items .chip", timeout=120000)
    items = page.locator("#items .chip").all_inner_texts()
    check("scan found ingredients", len(items) >= 2, items)
    page.fill("#addItem", "eggs"); page.press("#addItem", "Enter")
    page.fill("#addItem", "bread"); page.press("#addItem", "Enter")
    page.click("#reIdeas")
    page.wait_for_selector(".idea", timeout=120000)
    page.wait_for_function("document.querySelectorAll('.idea').length === 3 && !document.querySelector('#reIdeas').disabled", timeout=120000)
    ideas = page.locator(".idea h3").all_inner_texts()
    check("3 ideas shown", len(ideas) == 3, ideas)
    times = [int(x.split()[0]) for x in page.locator(".idea .time").all_inner_texts()]
    check("ideas fit 20 minutes", all(m <= 20 for m in times), times)
    page.screenshot(path=str(OUT / "mise_pantry.png"), full_page=True)
    page.locator("[data-idea='0']").click()
    page.wait_for_selector("#cook", timeout=180000)
    check("recipe written and opened", page.locator(".steps li").count() >= 3, page.inner_text("h1"))
    print(f"  pantry flow {time.time() - t:.0f}s", flush=True)
    page.screenshot(path=str(OUT / "mise_recipe_new.png"), full_page=True)

    print("\n== cook mode")
    page.click("#cook")
    page.wait_for_selector(".stage .text", timeout=10000)
    page.wait_for_function("document.querySelector('#said').textContent.length > 10", timeout=10000)
    check("step 1 shown + narration caption", "step 1 of" in page.inner_text(".stage").lower(), page.inner_text("#said")[:120])
    check("ETA shown", "Eat around" in page.inner_text("#eta"), page.inner_text("#eta"))
    page.screenshot(path=str(OUT / "mise_cook.png"))
    check("always listening is on by default", page.is_checked("#handsFree"))
    # the fake mic starts when cook mode opens it and says "Okay, I am done with that step. What is next?":
    # hands-free must catch it with nobody touching the screen
    try:
        page.wait_for_function("document.querySelector('.stage .label').textContent.includes('Step 2')", timeout=45000)
    except Exception:
        pass
    page.wait_for_function("!window.mise.busy", timeout=60000)
    check("hands-free: spoken 'what's next' moved to step 2", "step 2 of" in page.inner_text(".stage").lower(),
          page.locator("#convo").inner_text())
    page.uncheck("#handsFree")
    tts = page.evaluate("""fetch('/api/tts', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: 'Step two. Whisk the eggs.'})}).then(async r => [r.status, r.headers.get('content-type'), (await r.arrayBuffer()).byteLength])""")
    check("neural voice (Kokoro) returns speech audio", tts[0] == 200 and "wav" in (tts[1] or "") and tts[2] > 20000, tts)
    page.click("#repeatBtn")
    page.click("#backBtn")
    page.wait_for_timeout(500)
    check("back button returns to step 1", "step 1 of" in page.inner_text(".stage").lower())
    n = int(page.text_content(".stage .label").split()[-1])
    for _ in range(n - 1):
        page.click("#nextBtn")
        page.wait_for_timeout(250)
    check("reached the last step", page.inner_text("#nextBtn").startswith("Finished"))
    page.click("#nextBtn")

    print("\n== feedback → version 2")
    page.wait_for_selector(".rating", timeout=10000)
    check("timing summary shown", page.locator(".timing div").count() >= 3)
    page.click(".rating button[data-n='3']")
    page.click("#tags button[data-t='Too salty']")
    page.fill("#notes", "Way too salty, and I'd like it a bit spicier next time.")
    page.screenshot(path=str(OUT / "mise_feedback.png"), full_page=True)
    page.click("#improve")
    page.wait_for_selector("#result .changes li", timeout=180000)
    check("saved version 2", "version 2" in page.inner_text("#result").lower(), page.inner_text("#result")[:200])
    changes = page.locator("#result .changes li").all_inner_texts()
    check("changes address salt", any("salt" in c.lower() for c in changes), changes)
    page.screenshot(path=str(OUT / "mise_feedback_done.png"), full_page=True)
    page.click("#view")
    page.wait_for_selector(".since", timeout=10000)
    check("recipe page shows v2 changes", "version 2" in page.inner_text(".since").lower())
    check("version history lists v1", page.locator(".history .stamp").count() >= 2)
    page.screenshot(path=str(OUT / "mise_recipe_v2.png"), full_page=True)
    check("no console errors", not errors, errors[:3])

    print("\n== phone layout")
    m = dict(pw.devices["iPhone 15 Pro"]); m.pop("default_browser_type", None)
    mctx = browser.new_context(**m, permissions=["camera", "microphone"])
    mp = mctx.new_page()
    mp.goto(BASE + "/")
    mp.wait_for_selector(".landing", timeout=15000)
    check("phone landing: no sideways scroll", mp.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
    mp.screenshot(path=str(OUT / "mise_phone_landing.png"), full_page=True)
    mp.click("[data-go='home']")
    mp.wait_for_selector(".recipe-row", timeout=15000)
    check("phone home: no sideways scroll", mp.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
    mp.screenshot(path=str(OUT / "mise_phone_home.png"), full_page=True)
    mp.locator(".recipe-row").first.click()
    mp.wait_for_selector("#cook")
    mp.click("#cook")
    mp.wait_for_selector(".stage .text")
    check("phone cook: no sideways scroll", mp.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"))
    box = mp.locator("#mic").bounding_box()
    check("phone cook: mic is big", box and box["height"] >= 72, box)
    mp.screenshot(path=str(OUT / "mise_phone_cook.png"))
    mp.evaluate("fetch('/api/mise/cook/stop', {method: 'POST'})")
    browser.close()

server.terminate()
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed · screenshots in {OUT}")
sys.exit(1 if failed else 0)
