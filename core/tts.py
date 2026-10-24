"""On-device neural text-to-speech with Kokoro-82M (Apache-2.0) via ONNX Runtime.

Much more natural than the browser's built-in voices, and it still never leaves the laptop:
the phone or browser fetches WAV audio from the hub one sentence at a time (so the first
words play while the rest is synthesized). Falls back to the browser's voices when the model
files aren't present.
"""
from __future__ import annotations

import io
import os
import threading
import time
from collections import OrderedDict

from . import config

MODEL = config.MODELS_DIR / "kokoro" / "kokoro-v1.0.int8.onnx"
VOICES = config.MODELS_DIR / "kokoro" / "voices-v1.0.bin"
VOICE = os.environ.get("MISE_VOICE", "af_bella")  # warm US English; try am_michael, af_nicole, bf_emma
SPEED = float(os.environ.get("MISE_VOICE_SPEED", "1.05"))


class TTS:
    def __init__(self):
        self.engine = None
        self.error = ""
        self.lock = threading.Lock()
        self.cache: OrderedDict[tuple, bytes] = OrderedDict()  # narration repeats a lot ("Step 2 of 6…")
        self.last_ms = 0.0

    @property
    def available(self) -> bool:
        return MODEL.exists() and VOICES.exists() and not self.error

    def _load(self):
        if self.engine is None and not self.error:
            try:
                from kokoro_onnx import Kokoro
                self.engine = Kokoro(str(MODEL), str(VOICES))
            except Exception as e:  # missing package or files: the UI falls back to browser voices
                self.error = f"{type(e).__name__}: {e}"
        return self.engine

    def voices(self) -> list[str]:
        eng = self._load()
        return sorted(eng.get_voices()) if eng else []

    def wav(self, text: str, voice: str | None = None, speed: float | None = None) -> bytes:
        import soundfile as sf

        key = (text.strip(), voice or VOICE, speed or SPEED)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            eng = self._load()
            if not eng:
                raise RuntimeError(self.error or "voice model not available")
            t = time.time()
            samples, sr = eng.create(key[0], voice=key[1], speed=key[2], lang="en-us")
            self.last_ms = (time.time() - t) * 1000
            buf = io.BytesIO()
            sf.write(buf, samples, sr, format="WAV", subtype="PCM_16")
            data = buf.getvalue()
            self.cache[key] = data
            if len(self.cache) > 300:
                self.cache.popitem(last=False)
            return data

    def warm(self):
        try:
            self.wav("Ready when you are.")
        except Exception:
            pass


TTS_ENGINE = TTS()
