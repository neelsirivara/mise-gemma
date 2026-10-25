"""Regression checks for the bugs found in the iPhone walkthroughs, in Chrome and WebKit (Safari's engine).

  python scripts/smoothness_test.py            # both engines
  python scripts/smoothness_test.py chromium   # one

Runs the app in on-phone mode against static files with the scripted Gemma bridge from scripts/demo_screens.py
(no models needed): double taps, removed ingredients, stale views, the back button, Mum on small and rotated
screens, a reload mid-cook, the no-model download guard and offline start-up.
"""
import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = (ROOT / "scripts" / "demo_screens.py").read_text(encoding="utf-8").split('BRIDGE = r"""')[1].split('"""')[0]
# count model calls, and let a test make the bridge slow
BRIDGE += r"""
(() => { const post = window.MiseNative.post; window.__gen = 0; window.__delay = 0;
  window.MiseNative.post = (m) => { if (m.op === "generate") window.__gen++; setTimeout(() => post(m), window.__delay); }; })();
"""
IPHONE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1"
results = []


def check(engine, name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {engine}: {name}" + (f" - {str(detail)[:160]}" if detail and not ok else ""), flush=True)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


PORT = 8690
srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), functools.partial(Quiet, directory=str(ROOT / "web")))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"
API = "const api = await import('/lib/api.js');"


def new_page(browser, w=440, h=956, bridge=True):
    ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2, is_mobile=browser.browser_type.name == "chromium",
                              has_touch=True, user_agent=IPHONE_UA)
    if bridge:
        ctx.add_init_script(BRIDGE)
    p = ctx.new_page()
    p.errors = []
    p.on("pageerror", lambda e: p.errors.append(str(e)) if "AudioContext" not in str(e) else None)  # Windows WebKit has no WebAudio
    return ctx, p


def boot(p, path="/mise/index.html"):
    p.goto(BASE + path)
    p.wait_for_function("window.mise && window.mise.view", timeout=20000)
    p.wait_for_timeout(500)


def recipe(p):
    return p.evaluate(f"""async () => {{ {API}
      const ideas = await api.postJSON('/api/mise/pantry/ideas', {{items: ['eggs', 'zucchini'], minutes: 30, servings: 2}});
      const evs = await api.stream('/api/mise/pantry/recipe', {{json: {{idea: ideas.ideas[0], items: ['eggs'], minutes: 30, servings: 2}}}});
      return evs.find((e) => e.type === 'done').recipe.id; }}""")


def run(engine_name):
    with sync_playwright() as pw:
        b = getattr(pw, engine_name).launch(**({"channel": "chrome"} if engine_name == "chromium" else {}))
        E = engine_name

        # 1. pantry: a removed ingredient stays removed; a double tap asks for ideas once
        ctx, p = new_page(b)
        boot(p)
        p.evaluate("""(async () => { const v = await import('/mise/js/views/pantry.js');
          const c = document.createElement('canvas'); c.width = c.height = 32; const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg'));
          v.photos().push(blob); })()""")
        p.evaluate("window.mise.go('pantry')")
        p.wait_for_timeout(300)
        p.click("#find")
        p.wait_for_selector(".idea", timeout=10000)
        chip = p.locator("#items .chip", has_text="eggplant").first
        chip.locator(".x").click()
        p.evaluate("(async () => { const v = await import('/mise/js/views/pantry.js'); const c = document.createElement('canvas'); c.width = c.height = 32; v.photos().push(await new Promise((r) => c.toBlob(r, 'image/jpeg'))); })()")
        before = p.evaluate("window.__gen")
        p.evaluate("document.querySelector('#find').click(); document.querySelector('#find').click(); document.querySelector('#find').click();")
        p.wait_for_timeout(1500)
        items = p.locator("#items .chip").all_inner_texts()
        check(E, "removed ingredient doesn't come back after another scan", not any("eggplant" in t for t in items), items)
        check(E, "triple tap on 'See what I can cook' runs one search", p.evaluate("window.__gen") - before <= 2, p.evaluate("window.__gen") - before)
        # writing a recipe locks 'Update ideas'
        p.evaluate("window.__delay = 1500")
        p.click(".idea [data-idea='0']")
        p.wait_for_timeout(200)
        check(E, "'Update ideas' is disabled while a recipe is being written", p.is_disabled("#reIdeas"))
        p.wait_for_selector("#cook", timeout=15000)
        p.evaluate("window.__delay = 0")
        ctx.close()

        # 2. cook mode: double tap Next moves one step; back button stays in the app; reload keeps the cook going
        ctx, p = new_page(b)
        boot(p)
        rid = recipe(p)
        p.evaluate(f"window.mise.go('recipe', {{id: '{rid}'}})")
        p.wait_for_selector("#cook")
        p.dblclick("#cook")
        p.wait_for_selector("#stage .text", timeout=10000)
        p.wait_for_timeout(600)
        p.evaluate("document.querySelector('#nextBtn').click(); document.querySelector('#nextBtn').click();")
        p.wait_for_timeout(1200)
        st = p.evaluate(f"async () => {{ {API} return api.getJSON('/api/mise/cook/state'); }}")
        check(E, "double tap on Next moves exactly one step", st["step"] == 1, st["step"])
        mum = p.evaluate("(() => { const i = document.querySelector('#mum img'); const r = i && i.getBoundingClientRect(); return i && {w: i.naturalWidth, top: r.top, bottom: r.bottom, h: innerHeight}; })()")
        check(E, "Mum is loaded and fully on screen (iPhone 17 Pro Max)", mum and mum["w"] > 0 and mum["top"] >= 0 and mum["bottom"] <= mum["h"], mum)
        p.reload()
        p.wait_for_function("window.mise && window.mise.view", timeout=20000)
        p.wait_for_timeout(1200)
        st = p.evaluate(f"async () => {{ {API} return api.getJSON('/api/mise/cook/state'); }}")
        check(E, "a reload mid-cook resumes the cook at the same step", st.get("active") and st.get("step") == 1 and bool(p.query_selector("#stage .text")), st.get("step"))
        p.evaluate("window.mise.go('home')")
        p.wait_for_timeout(400)
        p.evaluate(f"window.mise.go('recipe', {{id: '{rid}'}})")
        p.wait_for_timeout(400)
        p.go_back()
        p.wait_for_timeout(500)
        check(E, "back button goes to the previous screen inside the app", p.evaluate("window.mise.viewName") == "home" and "127.0.0.1" in p.url,
              p.evaluate("window.mise.viewName"))
        check(E, "no page errors (journey)", not p.errors, p.errors)
        ctx.close()

        # 3. Mum on a small phone, in landscape, and no sideways scrolling at 320 px
        for (w, h, label) in [(375, 667, "iPhone SE"), (956, 440, "landscape"), (320, 640, "320 px")]:
            ctx, p = new_page(b, w, h)
            boot(p)
            rid = recipe(p)
            p.evaluate(f"(async () => {{ {API} await api.postJSON('/api/mise/cook/start', {{id: '{rid}'}}); window.mise.go('cook'); }})()")
            p.wait_for_selector("#stage .text", timeout=10000)
            p.wait_for_timeout(800)
            m = p.evaluate("""(() => { const i = document.querySelector('#mum img'), r = i.getBoundingClientRect(), say = document.querySelector('#said');
              return {top: r.top, bottom: r.bottom, h: innerHeight, sw: document.scrollingElement.scrollWidth, w: innerWidth,
                      bubble: say && getComputedStyle(say).display !== 'none' ? say.getBoundingClientRect().top : null}; })()""")
            check(E, f"Mum fully on screen ({label})", m["top"] >= 0 and m["bottom"] <= m["h"] + 1, m)
            check(E, f"speech bubble on screen or hidden ({label})", m["bubble"] is None or m["bubble"] >= 0, m)
            check(E, f"no sideways scrolling ({label})", m["sw"] <= m["w"] + 1, m)
            ctx.close()

        # 4. on-phone mode with no model yet (browser engine, no iOS app): asking for ideas opens the download screen
        ctx, p = new_page(b, bridge=False)
        hits = []
        p.route("**/huggingface.co/**", lambda r: (hits.append(r.request.url), r.abort()))
        p.goto(BASE + "/mise/index.html?engine=phone")
        p.wait_for_timeout(2500)
        on_setup = p.evaluate("window.mise?.viewName")
        p.evaluate("window.mise.go('pantry')")
        p.wait_for_timeout(300)
        p.evaluate(f"(async () => {{ {API} try {{ await api.postJSON('/api/mise/pantry/ideas', {{items: ['eggs'], minutes: 30, servings: 2}}); }} catch {{}} }})()")
        p.wait_for_timeout(800)
        check(E, "no model: setup screen first, and a model call returns to it (no silent 2 GB download)",
              on_setup == "phone" and p.evaluate("window.mise.viewName") == "phone" and not hits, (on_setup, p.evaluate("window.mise.viewName"), hits[:1]))
        ctx.close()

        # 5. offline start-up (service worker), Chrome only: WebKit on Windows doesn't run service workers over plain http
        if E == "chromium":
            ctx, p = new_page(b)
            boot(p)
            p.wait_for_timeout(2500)  # let the service worker save the app
            ctx.set_offline(True)
            p.reload()
            try:
                p.wait_for_function("window.mise && window.mise.view", timeout=15000)
                ok = True
            except Exception:
                ok = False
            check(E, "opens offline after one visit (service worker)", ok)
            ctx.close()
        b.close()


engines = sys.argv[1:] or ["chromium", "webkit"]
for e in engines:
    print(f"== {e}", flush=True)
    run(e)
srv.shutdown()
print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
