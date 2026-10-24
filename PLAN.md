# Game plan for Saturday, Oct 24 (AGI House, Hillsborough)

**Deck:** https://claude.ai/artifact/4y63QjHG6nAqh4kZNV8mqL (private until you share it from its Share menu)
**Lead pitch:** **Mise**, the offline sous-chef. Enter the **Physical AI, IoT & Robotics** track and aim for **Best Use of LiteRT** too, which is open to every track.
**Pivots ready:** `bench` (electronics lab partner) and `sight` (offline narrator for blind users) run on the same engine.

---

## Rules that shape everything (from the event page and AGI House's event API)
- Gemma model only, **100% on-device, no cloud anywhere**. Judges will check this, so demo with **Wi-Fi off**.
- **Open source required.** Building on an existing project is allowed, but say what you built today.
  Today's work, honestly stated: the team's features, the real-camera demo, polish, and anything new on top of the scaffold.
- Pick **one main track** at submission. Special prizes (LiteRT $15k, Qualcomm, Pi, Coral, Pixel) stack on top.
- **7:00 pm:** save the draft (finalists are picked from drafts). **8:00 pm:** 3-minute demos. Judges walk round the
  tables science-fair style, then the top 6 demo on stage.
- **12:00:** 30-second pitches for team formation. The script is in the cover slide's speaker notes.

## Tonight / morning checklist (before you leave)
- [ ] Charger packed. In Windows, set **Power mode → Best performance** (the benchmarks look power-limited).
- [ ] Open `http://127.0.0.1:8000` in **Edge or Chrome** once (not an embedded preview) and grant camera and mic
      permission, so you're not clicking prompts on stage.
- [ ] Run `.\run.cmd mise -Dual`, hold Space, say "let's make guacamole" with the webcam pointed at something. Confirm you hear the reply.
- [ ] Buy props on the way (≈$15): 3 avocados, lime, red onion, tomato, cilantro, **2 labelled spice jars (cumin + paprika)**,
      salt, a bowl, fork, butter knife, paper towels. A **box or book stack** to tilt the laptop toward the board.
- [ ] Optional: a cheap USB webcam on a gooseneck aims better than the laptop lid. Not required.

## If the demo has to be on a phone
Run `.\run.cmd mise -Dual -Phone`, then follow **PHONE.md**: join the iPhone hotspot, trust the local certificate once,
open `https://<laptop-ip>:8443` and tap Add to Home Screen. **Do the certificate install before you leave, not on
stage.** Run `scripts\ui_test.py --quick --mobile` after any UI change.

## Hour by hour

| Time | You | Team (once formed) |
|---|---|---|
| 10:00–11:00 | Arrive, set up near a power outlet. Run `scripts\e2e_test.py` to check everything still works. Scout what loaner hardware exists (Jetson, VENTUNO Q, Pixel). | — |
| 11:00–12:00 | Keynote. Note anything the judges say they value, plus any new Gemma or LiteRT release to mention. | — |
| 12:00 | **30-second pitch** (cover slide notes). Recruit a front-end person, an on-device ML person, and someone with an Android phone or hardware. | — |
| 12:15–1:00 | Lunch. Teammates clone the repo, then `pip install -r requirements.txt` and `scripts\download_models.py` (≈7 GB; **use a USB stick from your laptop** if the Wi-Fi is slow). Assign roles (deck appendix slide). | Everyone runs `.\run.cmd mise` |
| 1:00–2:30 | **Real-camera demo with real props**: tune `apps/mise/__init__.py` prompts against what the webcam actually sees; adjust lighting and angle. | FE: kitchen-mode UI (bigger type, step card, timer ring). ML: latency + eval. Stretch: Android/Arduino spike |
| 2:30 | **Milestone:** the full guacamole flow works by voice with props. | |
| 2:30–4:00 | Record a **backup demo video** of the full flow (OBS or Xbox Game Bar, Win+G). Add features from the "pick 2" list below. | |
| 4:00 | AGI House check-in: show the demo and ask what they'd want to see. | |
| 4:00–6:00 | Polish and harden. Rehearse the 3-minute script. Fill in team names and the repo on the close slide. | |
| 6:00 | **Feature freeze.** Dinner. Rehearse 3× with the timer running. | |
| 7:00 | **Save draft**: public GitHub repo (Apache-2.0), README, deck link, backup video. | |
| 8:00 | Demo. **Wi-Fi off. Charger plugged in.** | |

### Pick 2 features for the afternoon (all are small with this engine)
1. **"Learn by watching" (high wow).** Record 30–60 s of someone cooking: sample a frame every 3 s with the watcher, then call
   `create_recipe` from the frame captions. This mirrors the event prompt ("a robot that learns a chore from watching you once").
2. **Kitchen-mode UI.** Full-screen step card in huge type, a ring timer, high contrast for low-vision users.
3. **Proactive hazards.** Tune the watch prompt for "pan smoking / boiling over / knife at edge" and test it with props (a phone video of boiling water works).
4. **Quality mode toggle.** E4B for "does this look done?" questions only (richer vision, about 5 s per turn).
5. **Android port** (if a teammate has a Pixel and Android Studio): LiteRT-LM Kotlin plus the `gemma-4-E2B-it_Google_Tensor_G5/G6.litertlm`
   builds. That makes the app eligible for Best in Show (Android/Pixel), but **only start before 1:30 pm**.
6. **Arduino probe thermometer** (if a loaner UNO Q is around): serial → a `read_temperature()` tool. Answers "is the chicken done?" with a number.

## The 3-minute demo script (rehearse word for word)
1. **0:00 Hook.** "Every recipe app gives you the same recipe forever. Mise looks in your cupboard, cooks with you
   hands-free, and rewrites the recipe every time you tell it how it went. And it runs entirely on this laptop."
   Turn on **airplane mode**; the badge flips to "fully offline".
2. **0:20 Cupboard.** Tap **What can I make?** and photograph the props (or tap + Add photo). Pick **20 min**.
   The ingredients appear as editable chips, then three ideas that fit 20 minutes. Tap **Write this recipe**.
   (About 40 s total: talk over it. "Gemma reads the photo and writes the recipe on the GPU right here.")
   **Backup:** open the saved recipe from the book instead of generating live.
3. **1:00 Cook mode.** Tap **Start cooking**. It narrates step 1, shows when you'll be eating, and starts timers on
   hands-off steps with "while that cooks, get ahead on…". Hold the mic: "Okay, what's next?" → step 2.
   "Can I use lemon instead of lime?" → spoken answer. "How long is left?" → timer read-out.
4. **1:50 Feedback → v2.** Tap through to **Finished**. Give 3 stars, tap **Too salty**, and say or type "I'd like it
   spicier." Tap **Save and improve recipe**. **Version 2** appears with the changes and the reason for each.
   Open the recipe: the v2 note and the version history.
5. **2:30 Under the hood.** "One Gemma 4 E2B on the GPU hears, sees and writes structured recipes. A second copy on
   the CPU watches the counter. EmbeddingGemma 2 remembers what it saw. All of it runs through LiteRT-LM."
6. **2:50** "The more you cook, the better your recipes get, and none of it leaves the kitchen."

**If something breaks:** every voice action has a button (Next, Back, Repeat, Finished). If generation is slow, cook a
starter recipe from the book; carbonara has timers and get-ahead cues. If the model is wedged, restart; it warms
up in about 30 s. Pre-cook one recipe once before the demo so its page already shows a v2 history.

## Known facts and limits (verified tonight on this laptop)
- Gemma 4 **E2B on the Arc GPU** is the default talk model: ~1.7–2.3 s per turn with voice + image + a tool call; transcribing a command takes 0.5–0.8 s.
- **E4B** works but takes ~5 s per turn and called tools less reliably in our runs. Use it as an opt-in quality mode (`$env:GEMMA_TALK_MODEL`).
- Decode speed: E2B GPU 42 tok/s, **57 tok/s with multi-token prediction** (on by default); CPU 28 tok/s.
- **Intel NPU: blocked.** Windows Smart App Control refuses to load the unsigned `LiteRtDispatch.dll`. Do **not** turn
  Smart App Control off (on Windows 11 that can't be undone without a reinstall). The watcher runs on CPU instead.
  The NPU driver (32.0.100.4512) is also older than Google's documented minimum (32.0.100.4724).
- The **Ollama fallback** (`-Engine ollama`) runs CPU-only (~30 s per turn) with no audio input. Emergency use only.
- Small models send tool arguments as strings. `core/llm.py::_coerce` fixes them using the type hints. Keep type hints on every tool.
- The camera and mic need a real browser on `127.0.0.1`/`localhost`. The embedded preview pane blocks them.

## Judging angles to say out loud
- **On-device for real:** Wi-Fi off, three models, two chips, numbers on screen.
- **LiteRT depth:** native audio + vision, function calling, streaming, multi-token prediction, EmbeddingGemma 2 multimodal, multiple engines.
- **Human impact:** blind and low-vision cooks, memory support. Accessibility projects won the last two Gemma challenges.
- **Privacy:** "A camera in your kitchen should never phone home."
- **Portability:** the same `.litertlm` files have builds for Pixel TPU, VENTUNO Q NPU, Raspberry Pi 5 and Intel NPU.
