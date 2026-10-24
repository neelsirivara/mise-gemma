"""The contract every project scaffold implements. The server and the web UI are
generic; an App only supplies prompts, tools and how to render its state."""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class App:
    id: str
    name: str
    tagline: str
    system: str  # format()-ed with {state}
    watch_prompt: str  # format()-ed with {context}; must ask for the JSON shape in core.server.watch
    tools: list[Callable] = field(default_factory=list)
    summary: Callable[[], str] = lambda: ""  # app-specific state text for the prompt
    panels: Callable[[], list[dict]] = lambda: []  # [{"title", "items": [{"text", "state": done|active|todo}]}]
    watch_context: Callable[[], str] = lambda: ""
    on_watch: Callable[[dict], None] = lambda data: None
    reset: Callable[[], None] = lambda: None
    quick_prompts: list[str] = field(default_factory=list)  # demo-safe one-tap prompts
    accent: str = "#e8743b"
    watch_interval_s: float = 6.0
    speak_watch: bool = False  # Sight speaks every scene change; others only speak alerts
    attach_frame: bool = True  # send the current camera frame with each chat turn
    # optional extensions for a full product app (see apps/mise)
    router: Any = None  # fastapi.APIRouter mounted at /api/<id>
    web_entry: str = "index.html"  # page served at "/", relative to web/
    tick: Callable[[], None] = lambda: None  # called ~1/s from the UI poll (time-based cues)
    history_scope: Callable[[], str] = lambda: ""  # history resets when this changes (e.g. cooking a new recipe)
    # optional custom conversation handler: (text, image, audio) -> event iterator, or None to use tool chat
    chat: Callable[[Any, Any, Any], Any] | None = None


def load(app_id: str) -> App:
    return importlib.import_module(f"apps.{app_id}").APP
