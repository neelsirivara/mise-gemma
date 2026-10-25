"""Runtime configuration. Everything is overridable with env vars so the team
can swap apps/models/backends on the day without touching code."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = Path(os.environ.get("GEMMA_MODELS_DIR", ROOT / "models"))
WEB_DIR = ROOT / "web"
CACHE_DIR = Path(os.environ.get("GEMMA_CACHE_DIR", ROOT / ".litert_cache"))

# which scaffold to serve: mise | bench | sight
APP = os.environ.get("APP", "mise")

# "litert" (primary, LiteRT-LM) or "ollama" (fallback)
ENGINE = os.environ.get("GEMMA_ENGINE", "litert")

# Talk = the conversational model (hears you, sees the camera, calls tools)
# E2B on GPU answers in ~1.5-2s and calls tools more reliably than E4B (~5s); set E4B for "quality mode"
TALK_MODEL = os.environ.get("GEMMA_TALK_MODEL", str(MODELS_DIR / "gemma-4-E2B-it.litertlm"))
TALK_BACKEND = os.environ.get("GEMMA_TALK_BACKEND", "gpu")  # cpu | gpu | npu

# Watch = the always-on vision loop. Empty = share the talk engine.
# Set GEMMA_WATCH_MODEL to a second model (e.g. E2B on CPU, or the LNL build on the NPU) to run both at once.
WATCH_MODEL = os.environ.get("GEMMA_WATCH_MODEL", "")
WATCH_BACKEND = os.environ.get("GEMMA_WATCH_BACKEND", "cpu")  # npu blocked by Smart App Control on this laptop

OLLAMA_TALK = os.environ.get("GEMMA_OLLAMA_TALK", "gemma4:e4b")
OLLAMA_WATCH = os.environ.get("GEMMA_OLLAMA_WATCH", "")

MTP = os.environ.get("GEMMA_MTP", "1") == "1"  # speculative decoding on GPU
MAX_TOKENS = int(os.environ.get("GEMMA_MAX_TOKENS", "8192"))
MAX_IMAGES = int(os.environ.get("GEMMA_MAX_IMAGES", "4"))  # e.g. cupboard + fridge photos in one request
DATA_DIR = Path(os.environ.get("GEMMA_DATA_DIR", ROOT / "data"))  # recipe book etc. (user data, gitignored)
HISTORY_TURNS = int(os.environ.get("GEMMA_HISTORY_TURNS", "6"))
# Phone mode: serve HTTPS to the LAN so an iPhone can use its camera/mic and install the web app
PHONE = os.environ.get("PHONE") == "1"
PORT = int(os.environ.get("PORT", "8443" if PHONE else "8000"))
SETUP_PORT = int(os.environ.get("SETUP_PORT", "8080"))  # plain HTTP: certificate + instructions
PHONE_HOST = os.environ.get("PHONE_HOST", "0.0.0.0")  # 127.0.0.1 for local tests (no firewall prompt)
CERT_DIR = ROOT / ".certs"
LOCAL_PORT = int(os.environ.get("LOCAL_PORT", "8000"))  # phone mode also serves the app to this laptop on plain http://localhost
