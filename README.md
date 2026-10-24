# Gemma Edge Kit — three on-device Gemma 4 scaffolds

Built for the **Google Gemma Hardware Hackathon** (AGI House, Oct 24 2026). Every model runs on the
laptop itself through **LiteRT-LM**. Nothing calls the cloud. The demo still works with Wi-Fi off.

| App | One-liner | Run |
|---|---|---|
| **Mise** (lead pitch) | Hands-free, offline sous-chef that watches the counter, listens, runs timers, remembers what you did | `.\run.cmd mise` |
| **Bench** | Offline electronics lab partner: identifies parts, does circuit math with tools, walks you through builds | `.\run.cmd bench` |
| **Sight** | Private, offline narrator for blind and low-vision users: describes scenes, reads labels, finds objects | `.\run.cmd sight` |

All three share one engine, server and UI. An app is a single Python file (prompts, tools, state
panels). See `apps/*/__init__.py`.

## Architecture

```
 browser (Edge/Chrome, localhost)                      Python (FastAPI)                     LiteRT-LM
 ─────────────────────────────────                     ─────────────────                    ─────────────────────────────
 webcam frame (JPEG) ─┐                                                                     Gemma 4 E4B  · Arc GPU
 mic → VAD → 16k WAV ─┼─ POST /api/chat ─────────────▶ prompt = system + app state ───────▶  (native audio + vision +
 text / quick prompts ┘   (NDJSON stream back)          + tool functions (timers, steps…)    function calling)
                                                        ◀── text chunks + tool events ────
 speechSynthesis (local voice) ◀─ sentences as they arrive

 every ~6s: frame ─────── POST /api/watch ───────────▶ watch prompt → JSON {see, objects,  ▶ Gemma 4 E2B · Intel NPU
                                                        done, alert} → alerts, memory          (or shares E4B)
                                                        every frame → visual memory ───────▶ EmbeddingGemma 2 (text+vision)
                                                        recall(query) tool ◀─ cosine search   · GPU, ~60 ms/frame
```

* **One model for hearing and seeing.** Gemma 4 E4B takes the WAV and the camera frame in the *same* turn,
  so there's no separate speech-to-text step. Audio clips can be up to 30 s; the VAD caps them at 15 s.
* **Tools are plain Python.** LiteRT-LM builds the function-calling schema from type hints and docstrings
  (`core/state.py`, `apps/*/__init__.py`). The UI shows every tool call as a chip.
* **Visual memory** (`core/memory.py`). Each watch frame is embedded with multimodal EmbeddingGemma 2,
  so text questions retrieve frames ("did I already salt it?", "where are my keys?").
* **Fallbacks.** Set `-Engine ollama` to use Ollama with `gemma4:e4b` (no audio input there; type
  instead). If the camera fails, use the 🖼️ button to load a still image.

## Setup (already done on this laptop)

```powershell
uv python install 3.12            # or any 3.10+
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python scripts\download_models.py      # ~7.5 GB into .\models
```

Smoke test a model/backend: `.venv\Scripts\python scripts\smoke_test.py models\gemma-4-E4B-it.litertlm gpu`

Benchmark (for the slide): `.venv\Scripts\python scripts\bench.py`

## Run

```powershell
.\run.cmd mise                 # E4B on GPU does both talking and watching
.\run.cmd mise -Dual           # + E2B on the Intel NPU as an always-on watcher (needs NPU driver >= 32.0.100.4724)
.\run.cmd mise -Dual -WatchBackend cpu   # second model on CPU if the NPU path fails
.\run.cmd bench -Engine ollama # fallback engine
```

Open **http://127.0.0.1:8000** in **Edge or Chrome** (the camera and mic need a real browser, not an
embedded preview). Hold **Space** to talk, or tick **Hands-free**. Tick **Watch** to start the vision loop.

## On a phone / as a home-screen app
`.\run.cmd mise -Dual -Phone` serves HTTPS to your local network, with a QR setup page. The phone is the camera,
mic and screen; the models stay on the laptop. You can also deploy `web/` to Vercel. See **PHONE.md**.

## Autonomous UI tests
`.venv\Scripts\python scripts\ui_test.py --mobile` starts a server and drives real Chrome with a **fake webcam**
(`assets/fake/counter.mjpeg`) and a **fake mic** (`assets/fake/*.wav`). It covers hold-to-talk, a 100 s hands-free
session, the watch loop, memory, timers, the still-image fallback, the iPhone layout and server-down handling.
Screenshots and `report.json` go to `assets/ui_test/`. Add `--quick` to skip the hands-free session, `--headed`
to watch it, and `--url https://127.0.0.1:8443` to test a running phone-mode server.

## Env knobs (`core/config.py`)
`APP`, `GEMMA_ENGINE` (litert|ollama), `GEMMA_TALK_MODEL`, `GEMMA_TALK_BACKEND` (cpu|gpu|npu),
`GEMMA_WATCH_MODEL`, `GEMMA_WATCH_BACKEND`, `GEMMA_MAX_TOKENS`, `PORT`.

## Adding a new app in ~15 minutes
Copy `apps/sight/__init__.py` to `apps/<name>/__init__.py`. Then edit `SYSTEM`, `WATCH_PROMPT` and the
tools, and run `.\run.cmd <name>`.

## License
Apache-2.0 (the hackathon requires open source). Gemma models are under the Gemma / Apache-2.0 terms on their model cards.
