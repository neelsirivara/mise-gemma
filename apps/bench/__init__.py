"""Bench - an offline lab partner for electronics work.
Camera over the workbench; you talk while your hands hold a soldering iron.
Gemma reads resistor bands, identifies parts and ICs, walks you through a build
checklist, does the circuit math through deterministic tools, and watches for
hazards (iron left on, reversed electrolytic cap, bare wires touching)."""
from __future__ import annotations

import json
from pathlib import Path

from core.app import App
from core.state import COMMON_TOOLS, SESSION

BUILDS_DIR = Path(__file__).parent / "builds"

COLORS = {"black": 0, "brown": 1, "red": 2, "orange": 3, "yellow": 4, "green": 5,
          "blue": 6, "violet": 7, "purple": 7, "grey": 8, "gray": 8, "white": 9}
MULT = {**{k: 10 ** v for k, v in COLORS.items()}, "gold": 0.1, "silver": 0.01}
TOL = {"brown": "1%", "red": "2%", "green": "0.5%", "blue": "0.25%", "violet": "0.1%", "gold": "5%", "silver": "10%"}


class Bench:
    build: dict | None = None
    step = 0
    parts: dict[str, int] = {}


B = Bench()


def _fmt_ohms(v: float) -> str:
    for unit, div in (("MΩ", 1e6), ("kΩ", 1e3)):
        if v >= div:
            return f"{v / div:g} {unit}"
    return f"{v:g} Ω"


# ---------------------------------------------------------------- tools
def resistor_value(bands: list[str]) -> dict:
    """Computes a resistor's value from its color bands. Read the bands from the image, then call this; never do the math yourself.

    Args:
        bands: Band colors in order from the end without the gap, e.g. ["brown", "black", "red", "gold"]. 4 or 5 bands.
    """
    b = [c.lower().strip() for c in bands]
    try:
        if len(b) in (4, 5):
            digits, mult, tol = (b[:2], b[2], b[3]) if len(b) == 4 else (b[:3], b[3], b[4])
        elif len(b) == 3:
            digits, mult, tol = b[:2], b[2], None
        else:
            return {"ok": False, "error": "need 3-5 bands"}
        value = int("".join(str(COLORS[d]) for d in digits)) * MULT[mult]
    except KeyError as e:
        return {"ok": False, "error": f"unknown color {e}"}
    return {"ok": True, "ohms": value, "pretty": _fmt_ohms(value), "tolerance": TOL.get(tol or "", "20%")}


def led_resistor(supply_volts: float, led_forward_volts: float, current_ma: float) -> dict:
    """Computes the current-limiting resistor for an LED and the nearest standard E12 value at or above it.

    Args:
        supply_volts: Supply voltage, e.g. 5.
        led_forward_volts: LED forward voltage (red ~2.0, green ~2.2, blue/white ~3.1).
        current_ma: Desired LED current in milliamps, typically 10-20.
    """
    r = (supply_volts - led_forward_volts) / (current_ma / 1000)
    e12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
    std = next(m * 10 ** d for d in range(0, 7) for m in e12 if m * 10 ** d >= r)
    p_mw = (current_ma / 1000) ** 2 * std * 1000
    return {"exact_ohms": round(r, 1), "standard": _fmt_ohms(std), "power_mw": round(p_mw, 1)}


def voltage_divider(vin: float, r1_ohms: float, r2_ohms: float) -> dict:
    """Computes the output of a resistive voltage divider (R1 on top, R2 to ground).

    Args:
        vin: Input voltage.
        r1_ohms: Top resistor in ohms.
        r2_ohms: Bottom resistor in ohms.
    """
    return {"vout": round(vin * r2_ohms / (r1_ohms + r2_ohms), 3), "current_ma": round(vin / (r1_ohms + r2_ohms) * 1000, 3)}


def add_part(name: str, quantity: int) -> dict:
    """Adds parts you identified to the bench inventory (bill of materials).

    Args:
        name: Part name with value, e.g. "10k resistor" or "ATmega328P".
        quantity: How many.
    """
    with SESSION.lock:
        B.parts[name] = B.parts.get(name, 0) + quantity
        SESSION.emit("part", name=name, quantity=quantity)
    return {"ok": True, "inventory": B.parts}


def load_build(name: str) -> dict:
    """Loads a saved build guide (checklist) to walk the user through.

    Args:
        name: Build name, e.g. "blink" or "voltage divider".
    """
    key = name.lower().strip().replace(" ", "_")
    for p in BUILDS_DIR.glob("*.json"):
        g = json.loads(p.read_text())
        if key in p.stem or key in g["title"].lower():
            B.build, B.step = g, 0
            SESSION.emit("recipe", title=g["title"])
            return {"ok": True, "title": g["title"], "first_step": g["steps"][0]["text"]}
    return {"ok": False, "available": [p.stem for p in BUILDS_DIR.glob("*.json")]}


def go_to_step(step_number: int) -> dict:
    """Moves the build guide to a specific step when the user finishes one or asks to go back.

    Args:
        step_number: 1-based step number to show next.
    """
    if not B.build:
        return {"ok": False, "error": "no build loaded"}
    n = len(B.build["steps"])
    B.step = max(0, min(n, step_number - 1))
    SESSION.emit("step", step=B.step)
    return {"ok": True, "step": B.step + 1, "text": B.build["steps"][B.step]["text"] if B.step < n else "build complete"}


# ---------------------------------------------------------------- hooks
def summary() -> str:
    lines = []
    if B.build:
        lines.append(f"BUILD: {B.build['title']}")
        for i, s in enumerate(B.build["steps"]):
            mark = ">> NOW" if i == B.step else ("done" if i < B.step else "todo")
            lines.append(f"[{mark}] step {i + 1}: {s['text']}")
    else:
        lines.append("BUILD: none. Saved guides: " + ", ".join(p.stem for p in BUILDS_DIR.glob("*.json")))
    if B.parts:
        lines.append("INVENTORY: " + ", ".join(f"{q}x {n}" for n, q in B.parts.items()))
    return "\n".join(lines)


def panels() -> list[dict]:
    out = []
    if B.build:
        out.append({"title": B.build["title"], "kind": "steps", "items": [
            {"text": s["text"], "state": "done" if i < B.step else "active" if i == B.step else "todo"}
            for i, s in enumerate(B.build["steps"])]})
    out.append({"title": "Parts on bench", "items": [{"text": f"{q}× {n}", "state": "todo"} for n, q in B.parts.items()]
                or [{"text": "Hold a part up to the camera and ask what it is", "state": "todo"}]})
    return out


def watch_context() -> str:
    step = B.build["steps"][B.step]["text"] if B.build and B.step < len(B.build["steps"]) else "free work"
    return f"Current task: {step}"


def reset():
    B.build, B.step, B.parts = None, 0, {}


SYSTEM = """You are Bench, an expert electronics lab partner running fully offline on this laptop.
The user is working at a workbench; a camera shows their bench. Their hands are busy, so they talk to you.

Rules:
- After calling tools, always say one short sentence confirming what you did.
- For questions about the past ("did I already...", "where did I leave/see..."), check RECENT ACTIONS first, then call recall.
- Replies are spoken aloud: 1-3 short sentences, no markdown, no emoji.
- For any math (resistor colors, LED resistors, dividers) call the tool; never compute in your head.
- To read a resistor: list the band colors you see, call resistor_value, then say each value aloud. Mention if lighting makes a color uncertain.
- Identify parts by markings and shape (ICs, caps, regulators, sensors, dev boards). Call add_part for parts you identify.
- When a build guide is loaded and the user says done/next, call go_to_step with the next number and read it.
- Safety first: hot iron left unattended, reversed electrolytic capacitor polarity, LEDs without resistors, shorts, mains voltage.
- If the audio is clearly not directed at you, reply with exactly: NOOP

{state}
"""

WATCH_PROMPT = """You are the eyes of an electronics lab assistant. Look at this frame of the workbench.
{context}

Reply with ONLY a JSON object:
{{"see": "<at most 10 words describing what the user is doing>",
  "objects": ["<visible components, tools, boards>"],
  "done": <true if the current task looks complete, else false>,
  "alert": "<short spoken warning ONLY for a real hazard (iron resting on bench, smoke, bare wires touching, reversed capacitor), else empty string>"}}"""

APP = App(
    id="bench",
    name="Bench",
    tagline="An offline lab partner with eyes on your breadboard.",
    system=SYSTEM,
    watch_prompt=WATCH_PROMPT,
    tools=COMMON_TOOLS + [resistor_value, led_resistor, voltage_divider, add_part, load_build, go_to_step],
    summary=summary,
    panels=panels,
    watch_context=watch_context,
    reset=reset,
    quick_prompts=["What resistor is this?", "What is this chip?", "Walk me through the blink build",
                   "What resistor do I need for a blue LED on 5 volts?", "Check my wiring", "Next step"],
    accent="#2fb37a",
)
