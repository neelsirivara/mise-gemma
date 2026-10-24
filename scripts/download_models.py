"""Fetch the LiteRT-LM model files into ./models.

  python scripts/download_models.py          # what the app uses: Gemma 4 E2B + EmbeddingGemma 2 (≈ 3 GB)
  python scripts/download_models.py --all    # + Gemma 4 E4B "quality mode" (3.7 GB) and, on Windows, the Intel NPU build
"""
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

MODELS = Path(__file__).resolve().parent.parent / "models"
FILES = [
    ("litert-community/gemma-4-E2B-it-litert-lm", "gemma-4-E2B-it.litertlm"),            # talk + watch model, 2.6 GB
    ("litert-community/embeddinggemma-2-text-vision-440m-litert-lm",
     "embeddinggemma-2-text-vision-440m.litertlm"),                                        # visual memory, 0.4 GB
]
if "--all" in sys.argv:
    FILES.append(("litert-community/gemma-4-E4B-it-litert-lm", "gemma-4-E4B-it.litertlm"))  # quality mode, 3.7 GB
    if sys.platform == "win32":
        FILES.append(("litert-community/gemma-4-E2B-it-litert-lm", "gemma-4-E2B-it_intel_LNL.litertlm"))  # Intel NPU, 3.0 GB
for repo, f in FILES:
    print("->", hf_hub_download(repo, f, local_dir=MODELS))
