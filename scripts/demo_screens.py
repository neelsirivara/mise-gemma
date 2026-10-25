"""iPhone screenshots of the full Mise journey, for the README and the demo film.

Runs the real web app in on-phone mode at iPhone 17 Pro Max size (440x956 pt, 3x) with a fake camera
(a CC0 fridge photo, assets/demo/photos) and a stand-in for the iOS app's Gemma bridge that returns
scripted, realistic replies, so every screen is reproducible.
  python scripts/demo_screens.py          ->  docs/screenshots/*.png
"""
import functools
import http.server
import subprocess
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
CAM = ROOT / "assets" / "demo" / "fridge.mjpeg"
if not CAM.exists():
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-loop", "1", "-i",
                    str(ROOT / "assets/demo/photos/fridge3.jpg"), "-t", "4", "-vf",
                    "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,format=yuvj420p",
                    "-r", "15", "-q:v", "3", str(CAM)], check=True)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


PORT = 8630
srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), functools.partial(Quiet, directory=str(ROOT / "web")))
threading.Thread(target=srv.serve_forever, daemon=True).start()

BRIDGE = r"""
(() => {
  const RECIPE = {title: "Zucchini & Spinach Frittata", summary: "Golden zucchini, wilted spinach and burst cherry tomatoes set in a fluffy frittata.",
    servings: 2, total_minutes: 25, tags: ["vegetarian", "one-pan"],
    ingredients: [{item: "eggs", qty: "6"}, {item: "zucchini", qty: "1 medium"}, {item: "baby spinach", qty: "2 handfuls"},
      {item: "cherry tomatoes", qty: "12"}, {item: "mozzarella", qty: "60 g"}, {item: "milk", qty: "2 tbsp"}, {item: "lemon", qty: "1/2"},
      {item: "olive oil", qty: "1 tbsp"}, {item: "salt", qty: "1/2 tsp"}],
    steps: [{text: "Slice the zucchini into thin rounds and halve the cherry tomatoes.", minutes: 4, timer: false},
      {text: "Whisk the eggs with the milk, salt and a pinch of pepper.", minutes: 2, timer: false},
      {text: "Fry the zucchini in olive oil over medium-high heat until golden at the edges.", minutes: 5, timer: true, check: "golden edges"},
      {text: "Add the spinach and stir until just wilted.", minutes: 1, timer: false},
      {text: "Pour in the eggs, scatter the tomatoes and torn mozzarella, and cook on low until the edges set.", minutes: 6, timer: true, check: "edges set, centre still wobbly"},
      {text: "Slide the pan under a hot grill until puffed and golden on top.", minutes: 4, timer: true, check: "no wobble in the middle"},
      {text: "Rest for two minutes, squeeze over the lemon and cut into wedges.", minutes: 2, timer: false}]};
  function reply(text) {
    if (text.includes("Classify what the cook")) {
      const said = (text.split("The cook said: ")[1] || "").split(String.fromCharCode(10))[0];
      const s = said.toLowerCase();
      if (/feta/.test(s)) return {heard: said, intent: "question", timer_seconds: 0, timer_label: "", rating: 0,
        answer: "Yes. Crumble 60 grams of feta over the top instead. It's saltier, so skip the salt in the eggs."};
      if (/look right/.test(s)) return {heard: said, intent: "question", timer_seconds: 0, timer_label: "", rating: 0,
        answer: "The edges are set and the centre still wobbles. Perfect. Slide it under the grill now."};
      return {heard: said, intent: "next", timer_seconds: 0, timer_label: "", rating: 0, answer: ""};
    }
    if (text.includes("List every distinct food ingredient")) return {items: ["eggs", "baby spinach", "cherry tomatoes", "zucchini", "eggplant",
      "baby carrots", "mozzarella", "milk", "lemon", "lime", "oranges", "orange juice"]};
    if (text.includes("Suggest 3 different dishes")) return {ideas: [
      {title: "Zucchini & Spinach Frittata", summary: "Golden zucchini and burst tomatoes set in fluffy eggs.", total_minutes: 25,
       uses: ["eggs", "zucchini", "baby spinach", "cherry tomatoes", "mozzarella"], missing: []},
      {title: "Smoky Eggplant Shakshuka", summary: "Eggs poached in a smoky eggplant and tomato sauce.", total_minutes: 30,
       uses: ["eggs", "eggplant", "cherry tomatoes", "baby spinach"], missing: []},
      {title: "Lemony Carrot & Zucchini Fritters", summary: "Crisp grated-veg fritters with a squeeze of lemon.", total_minutes: 20,
       uses: ["zucchini", "baby carrots", "eggs", "lemon"], missing: ["flour"]}]};
    if (text.includes("Write the full recipe")) return RECIPE;
    if (text.includes("chef's tips")) return {tips: [{step: 3, tip: "Don't crowd the pan, or the zucchini steams instead of browning."},
      {step: 5, tip: "Keep the heat low; high heat makes the eggs rubbery."}]};
    if (text.includes("Improve the recipe")) return {heard: "You loved it, but it was a little salty and the middle was a bit runny.",
      changes: ["Salt 1/2 tsp → 1/4 tsp, because it tasted a little salty", "Grill 4 → 6 minutes, because the middle was still runny"],
      note_for_next_time: "Last time the middle was runny, so give it the full 6 minutes under the grill.",
      recipe: {...RECIPE, ingredients: RECIPE.ingredients.map((i) => i.item === "salt" ? {...i, qty: "1/4 tsp"} : i),
               steps: RECIPE.steps.map((s, k) => k === 5 ? {...s, minutes: 6} : s), total_minutes: 27}};
    return "Hi! Show me your fridge and I'll find something good to cook.";
  }
  window.MiseNative = {
    available: true, platform: "ios",
    post(msg) {
      const send = (m, ms = 5) => setTimeout(() => window.MiseNative.onMessage(m), ms);
      const status = {ready: true, downloading: false, progress: 1, model: "gemma-4-E2B-it", backend: "gpu", vision: true, audio: true};
      if (msg.op === "status" || msg.op === "load") return send({id: msg.id, ok: true, status});
      if (msg.op === "generate") {
        const text = msg.parts.filter((p) => p.text).map((p) => p.text).join("\n");
        const r = reply(text), out = typeof r === "string" ? r : JSON.stringify(r);
        for (let k = 0; k < 6; k++) send({id: msg.id, type: "chunk", text: out.slice(k * out.length / 6, (k + 1) * out.length / 6)}, 40 * k);
        send({id: msg.id, type: "done", text: out}, 300);
      }
    },
  };
  // the phone's own voice: keep Mum's mouth moving in screenshots
  try { speechSynthesis.speak = () => {}; } catch {}
})();
"""

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome", args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                                   f"--use-file-for-fake-video-capture={CAM}"])
    ctx = b.new_context(viewport={"width": 440, "height": 956}, device_scale_factor=3, is_mobile=True, has_touch=True,
                        permissions=["camera", "microphone"],
                        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 26_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1")
    ctx.add_init_script(BRIDGE)
    p = ctx.new_page()
    shot = lambda name: (p.wait_for_timeout(350), p.screenshot(path=str(OUT / f"{name}.png")), print("saved", name, flush=True))
    p.goto(f"http://127.0.0.1:{PORT}/mise/index.html")
    p.wait_for_function("window.mise && window.mise.view", timeout=20000)
    p.wait_for_timeout(2500)
    shot("01_snap_your_fridge")
    p.click("#vfShutter"); p.wait_for_timeout(700); p.click("#vfShutter"); p.wait_for_timeout(1500)
    p.click("#times button[data-m='30']")
    p.click("#find")
    p.wait_for_selector(".idea", timeout=15000)
    p.evaluate("document.querySelector('#results').scrollIntoView({block: 'start'})"); p.wait_for_timeout(500)
    shot("02_what_you_have")
    p.evaluate("document.querySelector('.ideas').scrollIntoView({block: 'start'})"); p.wait_for_timeout(500)
    shot("03_ideas")
    p.click(".idea [data-idea='0']")
    p.wait_for_selector("#cook", timeout=15000); p.wait_for_timeout(800)
    shot("04_recipe")
    p.click("#cook")
    p.wait_for_selector("#stage .text", timeout=15000); p.wait_for_timeout(1500)
    shot("05_cook_step1")
    p.evaluate("window.mise.ask({text: 'Can I use feta instead of mozzarella?'})"); p.wait_for_timeout(1500)
    for _ in range(2):
        p.evaluate("window.mise.ask({text: 'Okay, done. What is next?'})"); p.wait_for_timeout(1300)
    shot("06_cook_timer_and_question")
    p.evaluate("(async () => { const a = await import('/lib/api.js'); await a.postJSON('/api/mise/cook/goto', {step: 4}); })()"); p.wait_for_timeout(1300)
    p.evaluate("window.mise.ask({text: 'Does this look right?'})"); p.wait_for_timeout(1500)
    shot("07_cook_does_this_look_right")
    p.evaluate("(async () => { const a = await import('/lib/api.js'); await a.postJSON('/api/mise/cook/finish'); })()"); p.wait_for_timeout(600)
    p.evaluate("(async () => { const a = await import('/lib/api.js'); const s = await a.getJSON('/api/mise/cook/state'); window.mise.go('feedback', {id: s.awaiting_feedback}); })()")
    p.wait_for_selector("#improve", timeout=10000)
    p.locator(".rating button").nth(3).click()
    p.locator("#tags button", has_text="salty").first.click() if p.locator("#tags button", has_text="salty").count() else None
    p.fill("#notes", "Loved it, but a little salty and the middle was runny.")
    shot("08_how_did_it_go")
    p.click("#improve")
    p.wait_for_selector("#result:not([hidden])", timeout=15000); p.wait_for_timeout(800)
    shot("09_version_2")
    p.click("#view"); p.wait_for_selector("#cook", timeout=10000); p.wait_for_timeout(600)
    shot("10_recipe_v2")
    p.evaluate("window.mise.go('home')"); p.wait_for_timeout(1000)
    shot("11_recipe_book")
    p.click("#hubPill"); p.wait_for_timeout(500)
    shot("12_where_gemma_runs")
    b.close()
srv.shutdown()
