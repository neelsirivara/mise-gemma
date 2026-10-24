"""Verify a model/backend combo end to end: load, text, image, audio, tool call.

  .venv\\Scripts\\python scripts\\smoke_test.py models\\gemma-4-E4B-it.litertlm gpu
  .venv\\Scripts\\python scripts\\smoke_test.py models\\gemma-4-E2B-it_intel_LNL.litertlm npu --no-audio
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.llm import LiteRTLLM  # noqa: E402

TEST = ROOT / "assets" / "test"

ap = argparse.ArgumentParser()
ap.add_argument("model")
ap.add_argument("backend", default="gpu", nargs="?")
ap.add_argument("--no-audio", action="store_true")
ap.add_argument("--no-vision", action="store_true")
a = ap.parse_args()


def timed(label, fn):
    t = time.time()
    try:
        out = fn()
        print(f"  [ok]  {label:<10} {time.time() - t:5.2f}s  {str(out)[:160]!r}")
        return out
    except Exception as e:
        print(f"  [FAIL] {label:<10} {time.time() - t:5.2f}s  {type(e).__name__}: {e}")


print(f"\n== {a.model} on {a.backend}")
t0 = time.time()
llm = LiteRTLLM(str(Path(a.model).resolve()), a.backend, vision=not a.no_vision, audio=not a.no_audio)
print(f"  loaded in {time.time() - t0:.1f}s")

timed("text", lambda: llm.complete("In one sentence: why does pasta water need salt?", max_tokens=60))


def stream_tps():
    t = time.time()
    first, n = None, 0
    for ev in llm.stream("You are concise.", [], "Write four sentences about knife safety.", None, None, []):
        if ev["type"] == "text":
            first = first or time.time() - t
            n += 1
    return f"ttft={first:.2f}s chunks={n} chunks/s={n / (time.time() - t - first):.1f}"


timed("stream", stream_tps)

if not a.no_vision:
    for img in sorted(TEST.glob("*.jpg")):
        timed(img.stem[:10], lambda: llm.complete("List what you see in under 15 words.", img.read_bytes(), 40))

if not a.no_audio:
    for wav in sorted(TEST.glob("*.wav")):
        timed("audio:" + wav.stem, lambda: "".join(e.get("text", "") for e in llm.stream(
            "Transcribe the user's audio exactly.", [], "Transcribe.", None, wav.read_bytes(), [])))

calls = []


def set_timer(label: str, minutes: float) -> dict:
    """Starts a countdown timer.

    Args:
        label: What is being timed.
        minutes: Duration in minutes.
    """
    calls.append((label, minutes))
    return {"ok": True}


def tool():
    out = "".join(e.get("text", "") for e in llm.stream(
        "You control kitchen timers with tools.", [], "Set a timer for 3 minutes for the eggs.", None, None, [set_timer]))
    return f"calls={calls} reply={out}"


timed("tool", tool)

if not a.no_audio:
    calls.clear()
    timed("audio+tool", lambda: "".join(e.get("text", "") for e in llm.stream(
        "You control kitchen timers with tools. Act on the user's spoken request.", [], None, None,
        (TEST / "timer.wav").read_bytes(), [set_timer])) + f" calls={calls}")
