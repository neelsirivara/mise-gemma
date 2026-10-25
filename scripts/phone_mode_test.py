"""Browser test of on-phone mode (web/lib/phone) without the model: a fake window.MiseNative bridge
(the same contract the iOS app implements) answers with canned Gemma replies, so every route, the
recipe book in IndexedDB, cook mode, the voice intent router and feedback → version 2 are exercised.

  python scripts/phone_mode_test.py [--headed]

Serves web/ as static files only (like Vercel); no laptop hub is involved. Screenshots go to assets/ui_test/phone_*.png.
"""
import argparse
import functools
import http.server
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "ui_test"
OUT.mkdir(parents=True, exist_ok=True)
ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8620)
ap.add_argument("--headed", action="store_true")
a = ap.parse_args()
BASE = f"http://127.0.0.1:{a.port}"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" - {str(detail)[:200]}" if detail else ""), flush=True)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), functools.partial(Quiet, directory=str(ROOT / "web")))
threading.Thread(target=srv.serve_forever, daemon=True).start()

# Canned "Gemma": picks a reply from what the prompt asks for. Streams it in a few chunks like the real bridge.
FAKE_NATIVE = r"""
(() => {
  const RECIPE = {title: "Chickpea Tomato Skillet", summary: "Spiced chickpeas simmered in tomato.", servings: 2, total_minutes: 20,
    tags: ["one-pan"], ingredients: [{item: "canned chickpeas", qty: "400 g"}, {item: "crushed tomatoes", qty: "400 g"}, {item: "garlic", qty: "2 cloves"}],
    steps: [{text: "Slice the garlic thinly.", minutes: 2, timer: false},
            {text: "Fry the garlic in oil over medium heat until golden.", minutes: 1, timer: true},
            {text: "Add chickpeas and tomatoes and simmer until thick.", minutes: 10, timer: true},
            {text: "Season with salt and serve hot.", minutes: 1, timer: false}]};
  function reply(text) {
    if (text.includes("Classify what the cook")) {
      const said = (text.split("The cook said: ")[1] || "").split(String.fromCharCode(10))[0].toLowerCase();
      const intent = /next|done/.test(said) ? "next" : /timer/.test(said) ? "set_timer" : /turned out|delicious|salty/.test(said) ? "feedback" : "question";
      return {heard: said, intent, timer_seconds: intent === "set_timer" ? 120 : 0, timer_label: intent === "set_timer" ? "rice" : "",
              rating: intent === "feedback" ? 4 : 0, answer: intent === "question" ? "Use medium heat and stir often." : ""};
    }
    if (text.includes("Suggest 3 different dishes")) return {ideas: [1, 2, 3].map((i) => ({title: i === 1 ? "Chickpea Tomato Skillet" : `Idea ${i}`,
      summary: "Quick and tasty.", total_minutes: 15 + i, uses: ["canned chickpeas"], missing: []}))};
    if (text.includes("Write the full recipe")) return RECIPE;
    if (text.includes("chef's tips")) return {tips: [{step: 2, tip: "Pull the garlic as soon as it smells nutty."}]};
    if (text.includes("Improve the recipe")) return {heard: "It was a bit salty.", changes: ["Salt 1 tsp -> 1/2 tsp, because it was salty"],
      note_for_next_time: "Go easy on the salt this time.", recipe: {...RECIPE, title: "ignored"}};
    if (text.includes("List every distinct food ingredient")) return {items: ["canned chickpeas", "garlic", "crushed tomatoes"]};
    return "Happy to help. What are we cooking?";
  }
  window.__nativeLog = [];
  window.MiseNative = {
    available: true, platform: "ios",
    post(msg) {
      window.__nativeLog.push(msg.op);
      const send = (m) => setTimeout(() => window.MiseNative.onMessage(m), 5);
      const status = {ready: true, downloading: false, progress: 1, model: "gemma-4-E2B-it", backend: "gpu", vision: true, audio: true};
      if (msg.op === "status" || msg.op === "load") return send({id: msg.id, ok: true, status});
      if (msg.op === "generate") {
        if (!msg.parts.every((p) => typeof p.text === "string" || typeof p.image === "string" || typeof p.audio === "string"))
          return send({id: msg.id, type: "error", message: "bad parts"});
        const text = msg.parts.filter((p) => p.text).map((p) => p.text).join("\n");
        const r = reply(text), out = typeof r === "string" ? r : JSON.stringify(r);
        const half = Math.floor(out.length / 2);
        send({id: msg.id, type: "chunk", text: out.slice(0, half)});
        send({id: msg.id, type: "chunk", text: out.slice(half)});
        setTimeout(() => window.MiseNative.onMessage({id: msg.id, type: "done", text: out}), 20);
      }
    },
  };
})();
"""

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome", headless=not a.headed)
    ctx = browser.new_context(viewport={"width": 393, "height": 852}, is_mobile=True, has_touch=True)
    ctx.add_init_script(FAKE_NATIVE)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/mise/index.html")
    page.wait_for_function("window.mise && window.mise.view", timeout=15000)
    page.wait_for_timeout(800)
    check("native bridge picked: engine is phone", page.evaluate("localStorage.getItem('mise:engine')") in (None, "phone")
          and page.evaluate("document.querySelector('#hubPill').dataset.engine") == "phone")
    check("hub dot says on this phone", "on this phone" in (page.get_attribute("#hubPill", "aria-label") or ""),
          page.get_attribute("#hubPill", "aria-label"))
    page.screenshot(path=str(OUT / "phone_landing.png"))

    api = "const api = await import('/lib/api.js');"
    book = page.evaluate(f"async () => {{ {api} return api.getJSON('/api/mise/book'); }}")
    check("recipe book seeded from web/mise/starters (4)", len(book) == 4, [r["title"] for r in book])

    ideas = page.evaluate(f"async () => {{ {api} return api.postJSON('/api/mise/pantry/ideas', {{items: ['canned chickpeas', 'garlic'], minutes: 20, servings: 2}}); }}")
    check("ideas from on-phone Gemma", len(ideas["ideas"]) == 3 and ideas["ideas"][0]["title"], ideas)

    evs = page.evaluate(f"""async () => {{ {api}
      return api.stream('/api/mise/pantry/recipe', {{json: {{items: ['canned chickpeas'], minutes: 20, servings: 2, idea: {{title: 'Chickpea Tomato Skillet', summary: 'x'}}}}}}); }}""")
    done = [e for e in evs if e["type"] == "done"]
    check("recipe written, streamed with progress, saved to the book", done and any(e["type"] == "progress" for e in evs)
          and done[0]["recipe"]["version"] == 1, [e["type"] for e in evs])
    rid = done[0]["recipe"]["id"] if done else None

    scan = page.evaluate(f"""async () => {{ {api}
      const c = document.createElement('canvas'); c.width = c.height = 64;
      const blob = await new Promise((r) => c.toBlob(r, 'image/jpeg'));
      const fd = new FormData(); fd.append('images', blob, 'p.jpg');
      return api.postForm('/api/mise/pantry/scan', fd); }}""")
    check("pantry photo scan (image sent over the bridge as base64)", scan["items"][:1] == ["canned chickpeas"], scan)

    # ---- cook mode through the real views
    page.evaluate("id => window.mise.go('recipe', {id})", rid)
    page.wait_for_timeout(600)
    page.screenshot(path=str(OUT / "phone_recipe.png"))
    page.get_by_role("button", name="Start cooking").first.click()
    page.wait_for_function("window.mise.view && document.querySelector('#stage') && document.querySelector('#stage').textContent.includes('Slice')", timeout=8000)
    check("cook mode shows step 1", True)
    page.wait_for_timeout(1500)
    said = page.evaluate("document.querySelector('#said')?.textContent || ''")
    check("narration came through the event feed", "Step 1" in said or "Let's make" in said, said)

    reply = page.evaluate("async () => window.mise.ask({text: 'okay done, next'})")
    page.wait_for_timeout(1200)
    st = page.evaluate(f"async () => {{ {api} return api.getJSON('/api/mise/cook/state'); }}")
    check("voice 'next' routed by the intent router: step 2", st["step"] == 1, st.get("step"))
    check("step 2 started its timer", any("Step 2" in t["label"] for t in page.evaluate("window.mise.timers")), page.evaluate("window.mise.timers"))

    page.wait_for_function("!window.mise.busy", timeout=10000)
    ans = page.evaluate("""async () => { const out = []; const r = await window.mise.ask({text: 'should the pan be really hot for the garlic?'}, () => {}, (t) => out.push(t));
                                          return r || out.at(-1); }""")
    check("cooking question answered", "medium heat" in (ans or ""), ans)
    page.wait_for_function("!window.mise.busy", timeout=10000)
    page.evaluate("async () => window.mise.ask({text: 'set a timer for two minutes for the rice'})")
    page.wait_for_timeout(600)
    check("set_timer intent made a 2-minute timer", any(t["label"] == "rice" and t["seconds"] == 120 for t in page.evaluate("window.mise.timers")))
    page.screenshot(path=str(OUT / "phone_cook.png"))

    tips = page.evaluate(f"async id => {{ {api} return (await api.getJSON('/api/mise/book/' + id)).tips; }}", rid)
    check("chef's tips written in the background and saved", tips and "1" in tips, tips)

    page.evaluate(f"async () => {{ {api} return api.postJSON('/api/mise/cook/finish'); }}")
    page.wait_for_timeout(400)
    evs = page.evaluate(f"""async id => {{ {api}
      const fd = new FormData(); fd.append('id', id); fd.append('rating', '3'); fd.append('tags', 'too salty'); fd.append('notes', 'a bit salty'); fd.append('improve', 'true');
      return api.stream('/api/mise/feedback', {{form: fd}}); }}""", rid)
    done = [e for e in evs if e["type"] == "done"]
    check("feedback revised the recipe to version 2", done and done[0]["recipe"]["version"] == 2 and done[0]["recipe"]["title"] == "Chickpea Tomato Skillet",
          done[0]["changes"] if done else evs)
    r = page.evaluate(f"async id => {{ {api} return api.getJSON('/api/mise/book/' + id); }}", rid)
    check("version history kept (v1 in history, cook logged)", len(r["history"]) == 1 and len(r["cooks"]) == 1 and r["note_for_next_time"])

    ops = page.evaluate("window.__nativeLog")
    check("bridge used status + generate ops", "status" in ops and "generate" in ops, sorted(set(ops)))
    page.reload()
    page.wait_for_function("window.mise && window.mise.view", timeout=15000)
    rows = page.evaluate(f"async () => {{ {api} return api.getJSON('/api/mise/book'); }}")
    check("book persists across reloads (IndexedDB)", any(x["id"] == rid and x["version"] == 2 for x in rows))

    page.click("#hubPill")
    page.wait_for_timeout(300)
    check("dot opens the engine choice with 'On this phone' selected", page.get_attribute("#engPhone", "aria-pressed") == "true"
          and page.is_hidden("#hubFields"))
    page.screenshot(path=str(OUT / "phone_engine_sheet.png"))
    page.keyboard.press("Escape")
    check("no page errors", not errors, errors)
    browser.close()

srv.shutdown()
passed = sum(ok for _, ok in results)
print(f"\n{passed}/{len(results)} passed")
raise SystemExit(0 if passed == len(results) else 1)
