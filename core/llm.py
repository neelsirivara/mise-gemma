"""Model backends. Both expose the same two calls:

    stream(system, history, text, image, audio, tools) -> iterator of events
        events: {"type": "text", "text": str} | {"type": "tool", "name", "args", "result"}
    complete(prompt, image) -> str      (single-shot, used by the vision watcher)

LiteRT-LM is the primary path (GPU/NPU on-device, native audio + vision).
Ollama is a fallback if LiteRT misbehaves on the day (no audio input there).
"""
from __future__ import annotations

import functools
import json
import queue
import re
import threading
import time
import typing
from typing import Callable, Iterator

from . import config


def _coerce(value, hint):
    """Small models often send every argument as a string ("2", '["a","b"]'); fix that from the type hints."""
    try:
        if hint in (int, float):
            return hint(float(value)) if hint is int else float(value)
        if hint is bool and isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        if getattr(hint, "__origin__", None) is list and isinstance(value, str):
            v = value.strip()
            if v.startswith("["):
                return json.loads(v)
            if re.search(r"(^|\s)\d+[.)]\s", v):  # "1. Dice onion, 2. Mash avocado"
                return [s.strip(" ,;\n") for s in re.split(r"(?:^|\s)\d+[.)]\s", v) if s.strip(" ,;\n")]
            return [s.strip(" -•\t") for s in re.split(r"\n|;|(?<=\D),", v) if s.strip(" -•\t")]
    except (ValueError, TypeError, json.JSONDecodeError):
        pass
    return value


def _wrap_tools(tools: list[Callable], sink: "queue.Queue[dict]") -> list[Callable]:
    """Wrap tool functions so every call is type-coerced and reported to the UI stream."""
    wrapped = []
    for fn in tools:
        hints = typing.get_type_hints(fn)

        @functools.wraps(fn)
        def w(*args, __fn=fn, __hints=hints, **kwargs):
            kwargs = {k: _coerce(v, __hints.get(k)) for k, v in kwargs.items()}
            try:
                result = __fn(*args, **kwargs)
            except Exception as e:  # never let a tool crash the turn
                result = {"ok": False, "error": str(e)}
            sink.put({"type": "tool", "name": __fn.__name__, "args": kwargs or list(args), "result": result})
            return result
        wrapped.append(w)
    return wrapped


# ---------------------------------------------------------------------------
# LiteRT-LM
# ---------------------------------------------------------------------------
class LiteRTLLM:
    def __init__(self, model_path: str, backend: str = "gpu", vision: bool = True, audio: bool = True):
        import litert_lm

        self.lm = litert_lm
        litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
        config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.name = f"LiteRT-LM · {model_path.split('/')[-1].split(chr(92))[-1]} · {backend.upper()}"
        self.lock = threading.Lock()
        be = self._backend(backend)
        t0 = time.time()
        kwargs = dict(backend=be, max_num_tokens=config.MAX_TOKENS, cache_dir=str(config.CACHE_DIR))
        if vision:
            # NPU builds still run the vision encoder on GPU
            kwargs["vision_backend"] = self._backend("gpu" if backend == "npu" else backend)
            kwargs["max_num_images"] = config.MAX_IMAGES
        if audio:
            kwargs["audio_backend"] = litert_lm.Backend.CPU()
        if backend == "gpu" and config.MTP:
            kwargs["enable_speculative_decoding"] = True  # multi-token prediction: ~1.35x decode on Arc
        try:
            self.engine = litert_lm.Engine(model_path, **kwargs)
        except Exception:
            if not kwargs.pop("enable_speculative_decoding", None):
                raise
            self.engine = litert_lm.Engine(model_path, **kwargs)
        self.load_s = time.time() - t0

    def _backend(self, name: str):
        B = self.lm.Backend
        return {"cpu": B.CPU(), "gpu": B.GPU(), "npu": B.NPU()}[name.lower()]

    def _contents(self, text, image, audio):
        C = self.lm.Content
        parts = []
        if image:
            parts.append(C.ImageBytes(bytes=image))
        if audio:
            parts.append(C.AudioBytes(bytes=audio))
        parts.append(C.Text(text=text or ("(The cook spoke; respond to the audio.)" if audio else "Look at the counter.")))
        return self.lm.Contents(parts)

    def stream(self, system, history, text=None, image=None, audio=None, tools=()) -> Iterator[dict]:
        sink: queue.Queue[dict] = queue.Queue()
        msgs = [{"role": "system", "content": system}] + [
            {"role": h["role"], "content": h["content"]} for h in history
        ]
        with self.lock:
            with self.engine.create_conversation(
                messages=msgs,
                tools=_wrap_tools(list(tools), sink) if tools else None,
                max_output_tokens=400,
            ) as conv:
                for chunk in conv.send_message_async(self._contents(text, image, audio)):
                    while not sink.empty():
                        yield sink.get()
                    for item in chunk.get("content", []) if isinstance(chunk.get("content"), list) else []:
                        if item.get("type") == "text" and item.get("text"):
                            yield {"type": "text", "text": item["text"]}
                while not sink.empty():
                    yield sink.get()

    def complete(self, prompt, image=None, max_tokens=200) -> str:
        with self.lock:
            with self.engine.create_conversation(max_output_tokens=max_tokens) as conv:
                r = conv.send_message(self._contents(prompt, image, None))
        return "".join(c.get("text", "") for c in r["content"] if c.get("type") == "text")

    def stream_json(self, prompt, schema, images=(), audio=None, system=None, max_tokens=1200) -> Iterator[str]:
        """Constrained decoding (llguidance): yields raw text chunks whose concatenation parses against `schema`."""
        L, C = self.lm, self.lm.Content
        parts = [C.ImageBytes(bytes=i) for i in list(images)[: config.MAX_IMAGES]]
        if audio:
            parts.append(C.AudioBytes(bytes=audio))
        parts.append(C.Text(text=prompt))
        cfg = L.ConstrainedDecodingConfig(enable=True, provider=L.LiteRtLmConstraintProviderType.LL_GUIDANCE)
        with self.lock:
            with self.engine.create_conversation(messages=[{"role": "system", "content": system}] if system else None,
                                                 constrained_decoding_config=cfg, max_output_tokens=max_tokens) as conv:
                for chunk in conv.send_message_async(L.Contents(parts), response_format=L.ResponseFormat.json(schema)):
                    for item in chunk.get("content", []) if isinstance(chunk.get("content"), list) else []:
                        if item.get("type") == "text" and item.get("text"):
                            yield item["text"]

    def complete_json(self, prompt, schema, **kw) -> dict:
        return json.loads("".join(self.stream_json(prompt, schema, **kw)))


# ---------------------------------------------------------------------------
# Ollama fallback
# ---------------------------------------------------------------------------
class OllamaLLM:
    def __init__(self, model: str):
        import ollama

        self.client = ollama.Client()
        self.model = model
        self.name = f"Ollama · {model}"
        self.load_s = 0.0
        self.lock = threading.Lock()

    def stream(self, system, history, text=None, image=None, audio=None, tools=()) -> Iterator[dict]:
        if audio and not text:
            yield {"type": "text", "text": "Audio input needs the LiteRT engine. Type instead."}
            return
        msgs = [{"role": "system", "content": system}] + list(history)
        user = {"role": "user", "content": text or "Look at the counter."}
        if image:
            user["images"] = [image]
        msgs.append(user)
        by_name = {t.__name__: t for t in tools}
        with self.lock:
            for _ in range(4):  # tool-call rounds
                calls = []
                for chunk in self.client.chat(self.model, messages=msgs, tools=list(tools) or None, stream=True,
                                              options={"num_predict": 400}):
                    m = chunk.message
                    if m.content:
                        yield {"type": "text", "text": m.content}
                    if m.tool_calls:
                        calls.extend(m.tool_calls)
                if not calls:
                    return
                msgs.append({"role": "assistant", "content": "", "tool_calls": calls})
                for c in calls:
                    fn = by_name.get(c.function.name)
                    args = dict(c.function.arguments or {})
                    if fn:
                        hints = typing.get_type_hints(fn)
                        args = {k: _coerce(v, hints.get(k)) for k, v in args.items()}
                    try:
                        result = fn(**args) if fn else {"ok": False, "error": "unknown tool"}
                    except Exception as e:
                        result = {"ok": False, "error": str(e)}
                    yield {"type": "tool", "name": c.function.name, "args": args, "result": result}
                    msgs.append({"role": "tool", "content": json.dumps(result), "tool_name": c.function.name})

    def complete(self, prompt, image=None, max_tokens=200) -> str:
        m = {"role": "user", "content": prompt}
        if image:
            m["images"] = [image]
        with self.lock:
            r = self.client.chat(self.model, messages=[m], options={"num_predict": max_tokens})
        return r.message.content

    def stream_json(self, prompt, schema, images=(), audio=None, system=None, max_tokens=1200) -> Iterator[str]:
        msgs = [{"role": "system", "content": system}] if system else []
        msgs.append({"role": "user", "content": prompt, "images": list(images)[: config.MAX_IMAGES]})
        with self.lock:  # audio input is not supported here; callers pass a text note instead
            for chunk in self.client.chat(self.model, messages=msgs, format=schema, stream=True,
                                          options={"num_predict": max_tokens}):
                if chunk.message.content:
                    yield chunk.message.content

    def complete_json(self, prompt, schema, **kw) -> dict:
        return json.loads("".join(self.stream_json(prompt, schema, **kw)))


# ---------------------------------------------------------------------------
_talk = None
_watch = None


def talk():
    global _talk
    if _talk is None:
        if config.ENGINE == "litert":
            _talk = LiteRTLLM(config.TALK_MODEL, config.TALK_BACKEND)
        else:
            _talk = OllamaLLM(config.OLLAMA_TALK)
    return _talk


def watcher():
    """Second model for the always-on vision loop, or the talk model if none configured."""
    global _watch
    if _watch is None:
        if config.ENGINE == "litert" and config.WATCH_MODEL:
            _watch = LiteRTLLM(config.WATCH_MODEL, config.WATCH_BACKEND, audio=False)
        elif config.ENGINE == "ollama" and config.OLLAMA_WATCH:
            _watch = OllamaLLM(config.OLLAMA_WATCH)
        else:
            _watch = talk()
    return _watch
