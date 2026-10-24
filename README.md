# Mise — the offline sous-chef that gets better every time you cook

Built for the **Google Gemma Hardware Hackathon** (AGI House, Oct 24 2026). Every model runs on your own
computer through **LiteRT-LM**: Gemma 4 E2B for voice, vision and writing, plus EmbeddingGemma 2 for visual memory.
Nothing calls the cloud. It works with Wi-Fi off.

**What Mise does**
1. **Photograph your cupboard** (or fridge), say how long you have (15–90 min) and how many you're feeding.
   Gemma reads the photos into an editable ingredient list and suggests three dishes that fit the time.
2. **Pick one** and Mise writes the full recipe (quantities, timed steps, which steps are hands-off) into your **recipe book**.
3. **Cook hands-free.** Cook mode reads each step aloud, starts timers for hands-off steps, tells you what to prep
   while something simmers, warns a minute before a timer ends, and shows when you'll be eating. Say "next",
   "say that again", "how long is left?", "can I use bacon instead?", or hold up the pan and ask "does this look right?".
4. **Say how it went.** Rating, quick notes ("too salty"), typed or spoken. Mise also records how long each step
   really took. It then writes **version 2** with the changes listed and why. The old version stays in the history,
   and next time you cook it, Mise opens with what changed.

| App | One-liner |
|---|---|
| **Mise** (the product) | Cupboard photo → recipe → narrated, timed cook mode → feedback → a better version, every time |
| **Bench** (scaffold) | Offline electronics lab partner: identifies parts, does circuit math with tools, walks you through builds |
| **Sight** (scaffold) | Private, offline narrator for blind and low-vision users: describes scenes, reads labels, finds objects |

## Architecture

```
 web/mise/ (vanilla JS modules)        apps/mise/ (FastAPI router /api/mise)          core/ (shared engine)
 ──────────────────────────────        ─────────────────────────────────────          ───────────────────────────────
 views: home · pantry · recipe ·  ───▶  routes.py   HTTP API, NDJSON progress streams    llm.py   LiteRT-LM engines
        cook · feedback                 book.py     recipe book: JSON per recipe,                 (GPU talk, CPU watch),
 lib/:  api (hub-aware fetch)                       versions, feedback, cook timings              structured output
        voice (VAD → 16 kHz WAV,        chef.py     scan / ideas / write / revise                 (fast path + grammar
               local TTS)                           (schema-validated JSON)                        fallback)
        camera (preview, snapshots)     cook.py     cook-session state machine:          memory.py EmbeddingGemma 2
                                                    narration, timers, time cues                   visual memory
 hold-to-talk / hands-free ───────────▶ companion.py voice intent router (one structured  phone.py  local HTTPS + QR
                                                    call: next/back/repeat/time/finish/   server.py app hooks, events,
                                                    timer/question/feedback/log)                   timers, static UI
```

* **One model hears and sees.** Gemma 4 takes the WAV and the camera frame in the *same* call, with no separate
  speech-to-text step.
* **Structured output, fast.** Recipes, ideas and revisions are JSON validated against a schema. The fast path
  generates freely with multi-token prediction, then validates; only if that fails does it retry with
  grammar-constrained decoding (llguidance), which is slower per token on Gemma's 262k vocabulary.
  Multi-token prediction is switched off for constrained calls, because its draft tokens bypass the grammar.
* **Voice intents, not free-form tools.** In cook mode every utterance goes through one structured call that picks an
  intent from a fixed list and returns a transcript plus an answer. That's reliable on a 2B model, at 2–6 s per command.
* **Visual memory** (`core/memory.py`). Each watch frame is embedded with multimodal EmbeddingGemma 2,
  so text questions retrieve frames ("did I already salt it?", "where are my keys?").
* **Fallbacks.** Set `-Engine ollama` to use Ollama with `gemma4:e4b` (no audio input there; type
  instead). If the camera fails, use the 🖼️ button to load a still image.

## Setup

### macOS (Apple Silicon: M1 or later, macOS 12+) or Linux
```bash
git clone https://github.com/neelsirivara/mise-gemma.git && cd mise-gemma
./setup.sh                 # venv + dependencies + ~3 GB of models (Python 3.10–3.13; uses uv if installed)
./run.sh mise --dual       # opens http://127.0.0.1:8000 when the models are warm
```
LiteRT-LM runs Gemma on the Mac GPU (Metal). It ships wheels for Apple Silicon only; on an Intel Mac, install
Ollama, run `ollama pull gemma4:e4b`, and start with `./run.sh mise --engine ollama` (slower, and no voice input).
The first time, macOS asks for camera and microphone access for your browser; allow it.

### Windows
```powershell
uv python install 3.12            # or any 3.10–3.13
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python scripts\download_models.py      # ~3 GB into .\models (--all adds E4B + the Intel NPU build)
```

Smoke test a model/backend: `python scripts/smoke_test.py models/gemma-4-E2B-it.litertlm gpu`

Benchmark (for the slide): `python scripts/bench.py`

## Run

| | Windows | macOS / Linux |
|---|---|---|
| Mise | `.\run.cmd mise -Dual` | `./run.sh mise --dual` |
| Phone mode (HTTPS + QR setup) | `.\run.cmd mise -Dual -Phone` | `./run.sh mise --dual --phone` |
| Other scaffolds | `.\run.cmd bench` / `sight` | `./run.sh bench` / `sight` |
| Ollama fallback | `.\run.cmd mise -Engine ollama` | `./run.sh mise --engine ollama` |

`-Dual` / `--dual` adds a second Gemma 4 E2B on the CPU as the always-on camera watcher. Open
**http://127.0.0.1:8000** in **Chrome, Edge or Safari**. The camera and mic need a real browser, not an
embedded preview.

## Voice companion
- **Always listening** in cook mode (toggle in the cook screen). Talk over Mise to interrupt it; it stops and listens.
- **Neural voice on the laptop:** Kokoro-82M (Apache-2.0, int8 ONNX, ~120 MB) synthesizes each sentence on the CPU
  and streams it to the phone or browser (`POST /api/tts`). If it's unavailable, the browser's local voice is used.
  Pick a voice with `MISE_VOICE=af_bella` (default), `am_michael`, `af_nicole` or `bf_emma`.
- **Proactive:** a briefing at the start (the longest wait and what to prep during it), chef's tips per step (written
  once per recipe version by Gemma), "while that cooks…" cues, one-minute warnings, a heads-up when an earlier step's
  timer ends, and, with the camera on, "that looks done" check-ins from the watcher model.
- **Smart answers:** questions are answered from the recipe, the current step and the camera frame; short follow-ups
  ("how much of it?") get a focused second pass over the previous exchange.

## Hosting the UI on Vercel
`web/` is a static site (no build step; `web/vercel.json` routes `/` to the Mise app). In Vercel: import the GitHub
repo, set **Root Directory = `web`** and **Framework = Other**. Every push to `main` deploys. The models still run on
the laptop: open the Vercel URL on the phone, tap the hub pill and enter `https://<laptop-ip>:8443` (phone mode must be
running, and the phone must trust the local CA; see PHONE.md). Vercel only serves the page; camera frames, audio and
all model calls go phone ↔ laptop.

## On a phone / as a home-screen app
`.\run.cmd mise -Dual -Phone` serves HTTPS to your local network, with a QR setup page. The phone is the camera,
mic and screen; the models stay on the laptop. You can also deploy `web/` to Vercel. See **PHONE.md**.

## Autonomous tests
- `python scripts/mise_api_test.py <url>`: Mise product API with the real model (pantry photo → ideas → recipe →
  cook mode → voice intents → feedback → version 2).
- `python scripts/mise_ui_test.py`: the same flow driven through the Mise UI in real Chrome with a fake camera and
  mic, plus the phone layout. Screenshots go to `assets/ui_test/mise_*.png`.

### Classic demo UI tests
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
