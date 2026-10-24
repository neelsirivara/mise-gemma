"""Fetch the LiteRT-LM model files into ./models (≈ 9.9 GB total)."""
from pathlib import Path

from huggingface_hub import hf_hub_download

MODELS = Path(__file__).resolve().parent.parent / "models"
FILES = [
    ("litert-community/gemma-4-E4B-it-litert-lm", "gemma-4-E4B-it.litertlm"),            # talk model, GPU, 3.7 GB
    ("litert-community/gemma-4-E2B-it-litert-lm", "gemma-4-E2B-it.litertlm"),            # light model, CPU/GPU, 2.6 GB
    ("litert-community/gemma-4-E2B-it-litert-lm", "gemma-4-E2B-it_intel_LNL.litertlm"),  # Lunar Lake NPU, 3.0 GB
    ("litert-community/embeddinggemma-2-text-vision-440m-litert-lm",
     "embeddinggemma-2-text-vision-440m.litertlm"),                                        # visual memory, 0.4 GB
]
for repo, f in FILES:
    print("->", hf_hub_download(repo, f, local_dir=MODELS))
