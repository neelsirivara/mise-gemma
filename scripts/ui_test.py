"""Autonomous browser test of the CLASSIC demo UI (web/index.html), written for the first Mise demo flow.
The Mise product UI (web/mise/) is covered by scripts/mise_ui_test.py; this file is kept for the generic UI
that Bench and Sight use, and its Mise-specific checks predate the recipe book.

Autonomous browser test of the real UI: real Chrome/Edge, fake webcam + fake mic, real models.

Starts its own server on a spare port, drives the page like a person (hold Space to talk,
hands-free voice, watch loop, quick prompts), checks the results, and saves screenshots
plus a JSON report to assets/ui_test/.

  python scripts/ui_test.py                 # desktop suite
  python scripts/ui_test.py --mobile        # + iPhone-sized run
  python scripts/ui_test.py --headed        # watch it happen
  python scripts/ui_test.py --url https://127.0.0.1:8443   # test an already-running server
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import ssl
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / "assets" / "fake"
OUT = ROOT / "assets" / "ui_test"
PY = Path(sys.executable)

ap = argparse.ArgumentParser()
ap.add_argument("--app", default="mise")
ap.add_argument("--port", type=int, default=8040)
ap.add_argument("--url", help="test an already-running server instead of starting one")
ap.add_argument("--channel", default="chrome", help="chrome | msedge")
ap.add_argument("--headed", action="store_true")
ap.add_argument("--mobile", action="store_true", help="also run an iPhone-sized pass")
ap.add_argument("--quick", action="store_true", help="skip the 100 s hands-free session")
a = ap.parse_args()

OUT.mkdir(parents=True, exist_ok=True)
results: list[dict] = []
_ctx = ssl.create_default_context()
_ctx.check_hostname, _ctx.verify_mode = False, ssl.CERT_NONE


def check(name: str, ok: bool, detail: str = ""):
    results.append({"check": name, "ok": bool(ok), "detail": detail[:300]})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail[:160]}" if detail else ""), flush=True)


def get_json(url):
    return json.loads(urllib.request.urlopen(url, timeout=5, context=_ctx).read())


def wait_ready(base, timeout=180, proc=None):
    t = time.time()
    while time.time() - t < timeout:
        if proc is not None and proc.poll() is not None:
            raise SystemExit(f"server exited (code {proc.returncode}); see {OUT / 'server.log'}")
        try:
            e = get_json(base + "/api/state")["engine"]
            if e.get("load_error"):
                raise SystemExit("model load error: " + e["load_error"])
            if e.get("ready"):
                return e
        except OSError:
            pass
        time.sleep(1)
    raise SystemExit("server never became ready")


def start_server(port):
    env = {**os.environ, "PYTHONUTF8": "1", "PORT": str(port), "APP": a.app,
           "GEMMA_WATCH_MODEL": str(ROOT / "models" / "gemma-4-E2B-it.litertlm"), "GEMMA_WATCH_BACKEND": "cpu"}
    env.pop("OPEN_BROWSER", None)
    log = open(OUT / "server.log", "w", encoding="utf-8")
    return subprocess.Popen([str(PY), "-m", "core.server", a.app], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)


def launch(pw, audio: Path | None, mobile=False):
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-video-capture={FAKE / 'counter.mjpeg'}",
            "--autoplay-policy=no-user-gesture-required", "--ignore-certificate-errors"]
    if audio:
        args.append(f"--use-file-for-fake-audio-capture={audio}%noloop")
    browser = pw.chromium.launch(channel=a.channel, headless=not a.headed, args=args)
    opts = dict(ignore_https_errors=True, permissions=["camera", "microphone"])
    if mobile:
        opts.update(pw.devices["iPhone 15 Pro"])
        opts.pop("default_browser_type", None)
    ctx = browser.new_context(**opts)
    page = ctx.new_page()
    page.console_errors = []  # type: ignore[attr-defined]
    page.on("console", lambda m: m.type == "error" and page.console_errors.append(m.text))  # type: ignore
    page.on("pageerror", lambda e: page.console_errors.append(str(e)))  # type: ignore
    return browser, page


def chips(page: Page) -> str:
    return " ".join(page.locator(".chip").all_inner_texts())


def last_bot(page: Page) -> str:
    bots = page.locator(".msg.bot").all_inner_texts()
    return bots[-1] if bots else ""


def wait_idle(page: Page, timeout=60):
    """Wait until the in-flight turn finishes (mic button loses .busy)."""
    page.wait_for_timeout(300)
    page.wait_for_function("!document.getElementById('micBtn').classList.contains('busy')", timeout=timeout * 1000)


def reset(page: Page):
    page.click("#resetBtn")
    page.wait_for_timeout(500)


def open_app(page: Page, base: str, query=""):
    page.goto(base + "/" + query)
    page.wait_for_function("document.getElementById('appName').textContent.length > 1")
    page.uncheck("#speakToggle")  # headless has no TTS voices; keep timing deterministic


# ----------------------------------------------------------------------------- suites
def suite_boot_and_text(pw, base):
    print("\n== boot, camera, quick prompts, watch loop, memory")
    browser, page = launch(pw, None)
    open_app(page, base)
    reset(page)
    ok = page.wait_for_function("document.getElementById('video').videoWidth > 0", timeout=10000)
    check("camera stream live (fake webcam)", bool(ok))
    check("talk model badge shows LiteRT", "LiteRT" in page.inner_text("#talkPill"), page.inner_text("#talkPill"))

    page.check("#watchToggle")
    try:
        page.wait_for_function("document.getElementById('caption').innerText.startsWith('sees')", timeout=30000)
        check("watch loop captions the camera", True, page.inner_text("#caption"))
    except Exception:
        check("watch loop captions the camera", False, page.inner_text("#caption"))

    page.get_by_role("button", name="Let's make guacamole").click()
    wait_idle(page)
    # outcome, not tool name: create_recipe("guacamole…") is redirected to the saved, tested recipe
    check("quick prompt → saved guacamole recipe on screen", "Finely dice the red onion" in page.inner_text("#panels"),
          chips(page))

    page.fill("#text", "Set a timer for 20 seconds for the onions")
    page.press("#text", "Enter")
    wait_idle(page)
    check("typed request → set_timer", "set_timer" in chips(page), last_bot(page))
    check("timer card visible", page.locator(".timer").count() > 0)

    page.fill("#text", "I just added half a teaspoon of salt")
    page.press("#text", "Enter")
    page.fill("#text", "Wait, did I already add salt?")  # typed while busy: must queue, not drop
    page.press("#text", "Enter")
    wait_idle(page, 90)
    page.wait_for_timeout(1500)
    wait_idle(page, 90)
    users = page.locator(".msg.user").all_inner_texts()
    check("message typed while busy is queued, not dropped", any("already add salt" in u for u in users), str(users[-2:]))
    check("memory question → recall tool", "recall" in chips(page), last_bot(page))
    check("recall answer mentions salt", "salt" in last_bot(page).lower(), last_bot(page))

    page.wait_for_timeout(21000)  # let the 20 s timer fire
    check("timer fires (fired state)", page.locator(".timer.fired").count() > 0 or "done" in page.inner_text("#toast").lower())
    page.screenshot(path=str(OUT / "desktop_text_flow.png"), full_page=True)
    check("no console errors", not page.console_errors, "; ".join(page.console_errors))  # type: ignore
    browser.close()


def suite_push_to_talk(pw, base):
    print("\n== push-to-talk with fake microphone")
    browser, page = launch(pw, FAKE / "ptt_guac.wav")
    open_app(page, base)
    reset(page)
    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.down("Space")
    page.wait_for_timeout(3800)  # clip is ~3 s of speech
    page.keyboard.up("Space")
    wait_idle(page)
    users = page.locator(".msg.user").all_inner_texts()
    check("Space hold produced an audio turn", any("speech" in u for u in users), str(users[-1:]))
    check("spoken request → saved guacamole recipe on screen", "Finely dice the red onion" in page.inner_text("#panels"),
          chips(page) + " | " + last_bot(page))
    page.screenshot(path=str(OUT / "desktop_ptt.png"), full_page=True)
    browser.close()


def suite_hands_free(pw, base):
    print("\n== hands-free voice session (≈100 s, six spoken commands)")
    browser, page = launch(pw, FAKE / "session.wav")
    open_app(page, base)
    reset(page)
    page.check("#watchToggle")
    page.check("#handsFree")  # opens the mic → the fake recording starts now
    page.wait_for_timeout(100_000)
    wait_idle(page)
    c = chips(page)
    audio_turns = sum("speech" in u for u in page.locator(".msg.user").all_inner_texts())
    check("VAD segmented ≥5 utterances", audio_turns >= 5, f"{audio_turns} audio turns")
    check("hands-free → saved guacamole recipe loaded", "Finely dice the red onion" in page.inner_text("#panels"))
    for tool in ["go_to_step", "set_timer", "log_action", "recall"]:
        check(f"hands-free → {tool}", tool in c)
    bots = " ".join(page.locator(".msg.bot").all_inner_texts()).lower()
    check("label reading: cumin is on the left", "left" in bots, last_bot(page))
    check("recall shows memory thumbnails", page.locator("img.thumb").count() > 0)
    page.screenshot(path=str(OUT / "desktop_hands_free.png"), full_page=True)
    check("no console errors (hands-free)", not page.console_errors, "; ".join(page.console_errors))  # type: ignore
    browser.close()


def suite_still_fallback(pw, base):
    print("\n== ?still= demo fallback")
    browser, page = launch(pw, None)
    open_app(page, base, "?still=test/spice_jars.jpg")
    reset(page)
    check("still image shown", page.is_visible("#still") and not page.is_visible("#video"))
    page.get_by_role("button", name="Which jar is the cumin?").click()
    wait_idle(page)
    check("still frame answers label question", "left" in last_bot(page).lower(), last_bot(page))
    browser.close()


def suite_mobile(pw, base):
    print("\n== iPhone-sized layout (touch, portrait)")
    browser, page = launch(pw, FAKE / "ptt_guac.wav", mobile=True)
    open_app(page, base)
    reset(page)
    w = page.evaluate("document.documentElement.scrollWidth")
    vw = page.evaluate("innerWidth")
    check("no horizontal scroll on phone", w <= vw + 1, f"scrollWidth={w} innerWidth={vw}")
    mic = page.locator("#micBtn").bounding_box()
    check("mic button is thumb-sized (≥56px tall)", mic and mic["height"] >= 56, str(mic))
    check("manifest linked (installable)", page.locator("link[rel=manifest]").count() == 1)
    check("apple-touch-icon present", page.locator("link[rel=apple-touch-icon]").count() >= 1)
    page.dispatch_event("#micBtn", "pointerdown")
    page.wait_for_timeout(3800)
    page.dispatch_event("#micBtn", "pointerup")
    wait_idle(page)
    check("tap-and-hold mic works on touch layout", "Finely dice the red onion" in page.inner_text("#panels"), last_bot(page))
    man = page.evaluate("fetch('manifest.webmanifest').then(r => r.json())")
    check("manifest parses (name, standalone, icons)", man.get("display") == "standalone" and len(man.get("icons", [])) >= 2, str(man)[:120])
    if page.evaluate("isSecureContext"):
        sw = page.evaluate("navigator.serviceWorker.getRegistration().then(r => !!r)")
        check("service worker registered (offline app shell)", sw)
    page.screenshot(path=str(OUT / "mobile.png"), full_page=True)
    check("no console errors (mobile)", not page.console_errors, "; ".join(page.console_errors))  # type: ignore
    browser.close()


def suite_server_down(pw, base, server):
    print("\n== server goes away mid-session")
    browser, page = launch(pw, None)
    open_app(page, base)
    server.terminate()
    server.wait(10)
    page.fill("#text", "hello")
    page.press("#text", "Enter")
    page.wait_for_timeout(2500)
    check("clear 'can't reach server' message", "reach the server" in last_bot(page), last_bot(page))
    browser.close()


# ----------------------------------------------------------------------------- main
server = None
base = a.url
if not base:
    base = f"http://127.0.0.1:{a.port}"
    server = start_server(a.port)
print("waiting for server…", flush=True)
eng = wait_ready(base, proc=server)
print("engine:", eng["talk"], "|", eng["watch"], "| warm", eng.get("warm_s"), "s")
t0 = time.time()
with sync_playwright() as pw:
    for suite in [suite_boot_and_text, suite_push_to_talk, suite_still_fallback]:
        try:
            suite(pw, base)
        except Exception as e:
            check(f"{suite.__name__} crashed", False, f"{type(e).__name__}: {e}")
    if a.mobile:
        try:
            suite_mobile(pw, base)
        except Exception as e:
            check("suite_mobile crashed", False, f"{type(e).__name__}: {e}")
    if not a.quick:
        try:
            suite_hands_free(pw, base)
        except Exception as e:
            check("suite_hands_free crashed", False, f"{type(e).__name__}: {e}")
    if server:
        suite_server_down(pw, base, server)

failed = [r for r in results if not r["ok"]]
(OUT / "report.json").write_text(json.dumps({"base": base, "seconds": round(time.time() - t0), "results": results}, indent=1))
print(f"\n{len(results) - len(failed)}/{len(results)} checks passed in {time.time() - t0:.0f}s · screenshots in {OUT}")
if server and server.poll() is None:
    server.terminate()
sys.exit(1 if failed else 0)
