"""Compare speech-recognition approaches on assets/asr (noisy cooking commands with ground truth).

  python scripts/asr_eval.py [--methods router,e2b,e4b]
Word error rate per condition (clean / snr15 / snr5 / far) and median latency.
"""
import json, re, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config
from core.llm import LiteRTLLM

ASR = Path(__file__).resolve().parent.parent / "assets" / "asr"
truth = json.loads((ASR / "truth.json").read_text())
methods = (sys.argv[sys.argv.index("--methods") + 1] if "--methods" in sys.argv else "router,e2b,e4b").split(",")

def norm(s):
    s = s.lower().replace("ninety", "90")
    return re.sub(r"[^a-z0-9' ]", " ", s).split()

def wer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / max(1, len(r))

TRANSCRIBE = ("Transcribe exactly what the person says in this audio. Output only their words, "
              "with normal punctuation. If it's unclear, write your best guess.")
engines = {}
def eng(name):
    if name not in engines:
        path = config.MODELS_DIR / ("gemma-4-E4B-it.litertlm" if name == "e4b" else "gemma-4-E2B-it.litertlm")
        engines[name] = LiteRTLLM(str(path), "gpu", vision=False)
    return engines[name]

ROUTER_SCHEMA = {"type": "object", "properties": {"heard": {"type": "string"}, "intent": {"type": "string"}}, "required": ["heard", "intent"]}
def run(method, wav):
    audio = wav.read_bytes()
    if method == "router":  # today's single call: transcribe + classify inside one big JSON prompt
        from apps.mise.companion import GUIDE
        return eng("e2b").complete_json(GUIDE + "\n\nThe cook's words are in the attached audio.", ROUTER_SCHEMA, audio=audio, max_tokens=120)["heard"]
    out = "".join(e.get("text", "") for e in eng(method).stream("You are a precise speech transcriber.", [], TRANSCRIBE, None, audio, []) if e["type"] == "text")
    return out.strip().strip('"')

results = {}
for m in methods:
    eng("e2b" if m == "router" else m)
    run(m, next(iter(sorted(ASR.glob("*.wav")))))  # warm
    rows = []
    for name, ref in sorted(truth.items()):
        t = time.time(); hyp = run(m, ASR / name); dt = time.time() - t
        rows.append((name.split("_")[1].split(".")[0], wer(ref, hyp), dt, ref, hyp))
    results[m] = rows
    by = {}
    for cond, w, dt, *_ in rows:
        by.setdefault(cond, []).append(w)
    print(f"\n== {m}: overall WER {statistics.mean(r[1] for r in rows):.1%} · median {statistics.median(r[2] for r in rows):.2f}s", flush=True)
    for cond in ["clean", "snr15", "snr5", "far"]:
        print(f"   {cond:6} WER {statistics.mean(by.get(cond, [0])):.1%}", flush=True)
    for cond, w, dt, ref, hyp in rows:
        if w > 0.25:
            print(f"   miss [{cond}] '{ref}' -> '{hyp}'", flush=True)
(ASR / "results.json").write_text(json.dumps({m: [r[:2] + r[3:] for r in rows] for m, rows in results.items()}, indent=1))
