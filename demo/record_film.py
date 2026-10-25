"""Record demo/film.html (1920x1080, real time, live app inside the phone frame) to demo/mise_demo.mp4.

  python demo/record_film.py         # needs docs/screenshots from scripts/demo_screens.py
"""
import functools
import http.server
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = (ROOT / "scripts" / "demo_screens.py").read_text(encoding="utf-8").split('BRIDGE = r"""')[1].split('"""')[0]


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = path.split("?")[0]
        base = ROOT if p.startswith(("/docs/", "/demo/")) else ROOT / "web"
        return str(base / p.lstrip("/"))

    def log_message(self, *args):
        pass


PORT = 8640
srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()

vid_dir = Path(tempfile.mkdtemp(prefix="mise_film_"))
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome")
    ctx = b.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(vid_dir),
                        record_video_size={"width": 1920, "height": 1080})
    ctx.add_init_script(BRIDGE)
    t_ctx = time.time()
    p = ctx.new_page()
    p.goto(f"http://127.0.0.1:{PORT}/demo/film.html")
    p.wait_for_timeout(1500)
    p.wait_for_timeout(1200)
    lead = time.time() - t_ctx
    p.evaluate("window.play()")
    total = p.evaluate("window.FILM_SECONDS")
    p.wait_for_function("window.FILM_DONE === true", timeout=(total + 30) * 1000)
    video = p.video.path()
    ctx.close()
    b.close()
srv.shutdown()

out = ROOT / "demo" / "mise_demo.mp4"
ff = imageio_ffmpeg.get_ffmpeg_exe()
subprocess.run([ff, "-loglevel", "error", "-y", "-ss", f"{lead:.2f}", "-i", str(video), "-t", f"{total + 0.3:.2f}",
                "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-movflags", "+faststart",
                str(out)], check=True)
shutil.rmtree(vid_dir, ignore_errors=True)
print("wrote", out, f"{total:.0f}s", flush=True)
