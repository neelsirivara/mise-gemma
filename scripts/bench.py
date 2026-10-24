"""Measure prefill/decode speed per model x backend with LiteRT-LM's built-in benchmark.
Numbers go on the "runs on this laptop" slide.

  .venv\\Scripts\\python scripts\\bench.py            # all models present, gpu + cpu
  .venv\\Scripts\\python scripts\\bench.py gpu         # one backend
"""
import json
import sys
from pathlib import Path

import litert_lm

ROOT = Path(__file__).resolve().parent.parent
litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
backends = sys.argv[1:] or ["gpu", "cpu"]
B = {"cpu": litert_lm.Backend.CPU(), "gpu": litert_lm.Backend.GPU(), "npu": litert_lm.Backend.NPU()}
rows = []
for name in ["gemma-4-E2B-it.litertlm", "gemma-4-E4B-it.litertlm"]:
    path = ROOT / "models" / name
    if not path.exists():
        continue
    for be in backends:
        for spec in ([False, True] if be == "gpu" else [False]):
            try:
                info = litert_lm.Benchmark(model_path=str(path), backend=B[be], prefill_tokens=1024, decode_tokens=256,
                                           max_num_tokens=2048, cache_dir=str(ROOT / ".litert_cache"),
                                           enable_speculative_decoding=spec).run()
                row = {"model": name.split(".")[0], "backend": be + (" +MTP" if spec else ""),
                       "init_s": round(info.init_time_in_second, 1), "ttft_s": round(info.time_to_first_token_in_second, 2),
                       "prefill_tps": round(info.last_prefill_tokens_per_second), "decode_tps": round(info.last_decode_tokens_per_second, 1)}
            except Exception as e:
                row = {"model": name, "backend": be + (" +MTP" if spec else ""), "error": str(e)[:120]}
            print(row, flush=True)
            rows.append(row)
(ROOT / "assets" / "bench.json").write_text(json.dumps(rows, indent=1))
