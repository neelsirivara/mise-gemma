"""Fetch the LiteRT-LM model files into ./models.

  python scripts/download_models.py          # what the app uses: Gemma 4 E2B + EmbeddingGemma 2 + Kokoro voice (≈ 3.1 GB)
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

# Kokoro-82M neural voice (Apache-2.0), int8 ONNX build: 92 MB + 28 MB of voice styles
import urllib.request  # noqa: E402

KOKORO = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
(MODELS / "kokoro").mkdir(parents=True, exist_ok=True)
for f in ["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"]:
    dest = MODELS / "kokoro" / f
    if not dest.exists():
        urllib.request.urlretrieve(KOKORO + f, dest)
    print("->", dest)
