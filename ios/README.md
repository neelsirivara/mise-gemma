# Mise for iPhone (native wrapper, Gemma 4 on the device)

This is a SwiftUI app that shows the Mise web app full screen in a `WKWebView`. It runs
**Gemma 4 E2B on the iPhone** through Google's LiteRT-LM runtime, and the page reaches the
model through a small JS bridge (`window.MiseNative`). It downloads the model once on first
launch (about 2.6 GB). After that it works offline.

- UI: `https://mise-gemma.vercel.app/?engine=native` by default. If that can't load (for
  example when offline), it falls back to the copy of `../web` bundled in the app, served from
  `http://localhost:47863`.
- Model: `litert-community/gemma-4-E2B-it-litert-lm` / `gemma-4-E2B-it.litertlm`, stored in
  `Application Support/LiteRTModels` and excluded from iCloud backup. The download is chunked
  and resumable, so an interrupted download continues where it stopped.
- Runtime: [john-rocky/swift-litert-lm](https://github.com/john-rocky/swift-litert-lm), pinned
  to exactly **0.2.0**. It wraps the official LiteRT-LM **v0.15.0** prebuilt `CLiteRTLM.xcframework`
  plus the official Swift wrapper. The text decoder runs on the Metal GPU; if the GPU fails it
  falls back to CPU. The image and audio encoders run on CPU, which is required for Gemma 4 E2B on iOS.

Target: Xcode 26, iOS 26, iPhone 17 Pro Max. Any iPhone with 8 GB+ RAM should work.

---

## Run it on the iPhone (Mac steps)

1. **Install Xcode 26** from the Mac App Store. Open it once and let it install the iOS 26
   platform. Also run `xcode-select --install` if you've never installed the command-line tools.
2. **Install XcodeGen** (generates the `.xcodeproj` from `project.yml`):
   ```bash
   brew install xcodegen          # needs Homebrew: https://brew.sh
   ```
3. **Generate and open the project:**
   ```bash
   git clone https://github.com/neelsirivara/mise-gemma.git   # or git pull
   cd mise-gemma/ios
   xcodegen
   open Mise.xcodeproj
   ```
   Xcode then resolves the Swift package. The first time, it downloads the ~86 MB LiteRT-LM
   xcframework from GitHub. Wait until "Indexing / Resolving packages" finishes.
4. **Signing:** select the **Mise** target, open **Signing & Capabilities**, and set **Team** to
   your Apple ID or team. If Xcode complains about the bundle id, change
   `com.example.mise` to something unique, e.g. `com.<yourname>.mise`.
   (You can also set `DEVELOPMENT_TEAM` and `PRODUCT_BUNDLE_IDENTIFIER` in `project.yml`
   and re-run `xcodegen`.)
5. **Plug in the iPhone** with a cable, unlock it, and tap **Trust This Computer**.
6. **Enable Developer Mode on the phone:** Settings → Privacy & Security → **Developer Mode** →
   On → Restart, then confirm after the reboot. (The switch only appears after the phone has
   been connected to Xcode once.)
7. In Xcode's toolbar, pick the iPhone as the run destination and press **Run** (⌘R).
   - With a free Apple ID, the first launch is blocked as an "Untrusted Developer". Fix it on
     the phone: Settings → General → VPN & Device Management → your Apple ID → Trust.
8. **First launch:** the setup screen downloads Gemma 4 (2.6 GB, Wi-Fi recommended; on
   cellular or Low Data Mode it asks first). It then starts the engine (a few seconds) and
   fades out to show the web app. Allow camera and microphone access when Mise asks.

Optional sanity check before opening Xcode (proves the package builds on this Mac):
```bash
git clone https://github.com/john-rocky/swift-litert-lm /tmp/srl && cd /tmp/srl && git checkout 0.2.0 && swift build
```

> The Metal GPU backend only engages in an Xcode-signed app on a **physical device**. The
> Simulator builds and runs, but it uses the CPU and is slow.

### Switching the web source

- Default `remote`: the hosted page, with an automatic fallback to the bundled copy when the
  network is down.
- `bundled`: always serve the copy of `web/` that was built into the app. Set it either way:
  - permanently: in `project.yml`, set `MISE_WEB_SOURCE: bundled`, then re-run `xcodegen`.
  - per run: Product → Scheme → Edit Scheme → Run → Environment Variables, add
    `MISE_WEB_SOURCE = bundled`.
- `MISE_REMOTE_URL = https://…` (env var) points the app at another https deployment, such as a
  Vercel preview.

The app uses a localhost server rather than a custom `WKURLSchemeHandler` scheme because WebKit
doesn't reliably treat custom schemes as a secure context, and `getUserMedia` (camera/mic)
needs a secure context. `http://localhost` is a secure context. Bundled mode isn't the default
because camera and mic over localhost haven't been verified on a device yet. If they work,
flip the default.

---

## JS bridge contract

Native injects this at document start, in the main frame of every page:

```js
window.MiseNative = { available: true, platform: "ios", post(msg) { webkit.messageHandlers.mise.postMessage(msg) } }
```

The page sets `window.MiseNative.onMessage = (obj) => { ... }` to receive messages.
Messages are only accepted from the main frame of `mise-gemma.vercel.app`, `localhost`, or the
`MISE_REMOTE_URL` host.

### JS → native (`MiseNative.post(obj)`)

| op | message | reply |
|---|---|---|
| status | `{op:"status", id}` | `{id, ok:true, status}` |
| load | `{op:"load", id}` | Downloads the model if needed, then loads the engine. Replies `{id, ok:true, status}` once ready, or `{id, type:"error", message}`. `{type:"status"}` events stream in the meantime. |
| generate | `{op:"generate", id, system, parts, maxTokens, temperature}` | Zero or more `{id, type:"chunk", text}`, then `{id, type:"done", text:<full text>}`; or `{id, type:"error", message}` |
| cancel | `{op:"cancel", id}` (the id of the generate to stop) | No separate reply. That generation ends with `{id, type:"done", text:<partial>, cancelled:true}`. |

- `parts` is an array of `{text:"…"}`, `{image:"<base64 JPEG, no data: prefix>"}` and
  `{audio:"<base64 16 kHz mono WAV>"}`, kept in the given order. A stray `data:…;base64,`
  prefix is tolerated. At most 8 images per request.
- `maxTokens` is clamped to 1…2048 (default 1024). `temperature` defaults to 0.7 and is
  clamped to 0…2. A temperature of 0 means greedy decoding (top-k 1).
- Each generate is **independent**: a fresh LiteRT-LM conversation with the given system
  prompt and no hidden history.
- Generations run **one at a time, FIFO**. Cancelling a queued request finishes it
  immediately with `text:""` and `cancelled:true`.
- A generate that arrives while the model is still loading waits for the load. If the model
  isn't downloaded yet, it fails with an error rather than starting a 2.6 GB download. Use
  `load` to start the download.
- When the app goes to the background, running and queued generations are cancelled, because
  iOS doesn't allow GPU work in the background.

### native → JS (`window.MiseNative.onMessage(obj)`)

- Replies: `{id, ok:true, ...}`
- Streaming: `{id, type:"chunk", text}`, `{id, type:"done", text, cancelled?}`, `{id, type:"error", message}`
- Broadcasts: `{type:"status", status}` on every state change (download progress, load, ready, error)

`status` object:
```js
{ ready, downloading, loading, progress /*0..1*/, bytes, total, model: "gemma-4-E2B-it",
  backend: "gpu" | "cpu", error /*optional string*/, vision, audio }
```
(`loading` is an extra field: true while the engine starts after the download.)
Everything is serialized with `JSONSerialization` and passed to `evaluateJavaScript`. Text is
never string-concatenated into JS.

Quick test from Safari's Web Inspector (Safari → Develop → *your iPhone* → Mise; enabled in
Debug builds):
```js
MiseNative.onMessage = (m) => console.log(m);
MiseNative.post({ op: "status", id: 1 });
MiseNative.post({ op: "generate", id: 2, system: "You are a friendly chef.",
  parts: [{ text: "Two-line pancake recipe, please." }], maxTokens: 200, temperature: 0.7 });
```

---

## Project layout

```
ios/
  project.yml              XcodeGen spec (package pin, settings, scheme)
  Config/Info.plist        usage strings (camera, mic, speech), ATS local networking, MiseWebSource
  Config/Mise.entitlements com.apple.developer.kernel.increased-memory-limit
  Mise/
    MiseApp.swift          @main, ContentView (web view + overlay), scene phase handling
    AppModel.swift         app state, first-run flow, network (Wi-Fi/cellular) check
    ModelService.swift     download + LiteRT-LM Engine + single-turn streaming generation
    ModelStatus.swift      status struct + thread-safe store that publishes changes
    NativeBridge.swift     window.MiseNative bridge, FIFO generation queue, cancel
    BridgeMessages.swift   message parsing / JSON encoding helpers
    WebHost.swift          WKWebView setup, camera/mic permission, offline fallback
    LocalWebServer.swift   loopback static file server (Network.framework) for bundled mode
    ModelSetupOverlay.swift first-run download / loading / retry screen
    Assets.xcassets        app icon (from web/icons), accent color
  ../web                   bundled into the app as the folder "web/"
```

---

## Troubleshooting

**Signing fails because of "Increased Memory Limit"** (common with a free Personal Team): remove
the `CODE_SIGN_ENTITLEMENTS: Config/Mise.entitlements` line from `project.yml` and re-run
`xcodegen`. On a 12 GB iPhone 17 Pro Max the model fits without it (about 1.6 GB peak
footprint with an image, measured by swift-litert-lm on an iPhone 17 Pro).

**"Failed to register bundle identifier"**: change `PRODUCT_BUNDLE_IDENTIFIER` to something unique.

**Package resolution fails** ("could not resolve package", checksum errors): File → Packages →
Reset Package Caches, then File → Packages → Resolve Package Versions. Check that GitHub is
reachable, since the binary comes from `github.com/google-ai-edge/LiteRT-LM/releases`.

**Swift 6 concurrency errors in Mise's own files**: the code is written for the Swift 6
language mode. If a newer SDK annotation trips it up and you need to unblock a demo, set
`SWIFT_VERSION: "5.0"` in `project.yml` and re-run `xcodegen`. Then please report the error
so it can be fixed properly.

**Model download stalls or fails**: tap **Retry**; the download resumes from the last finished
16 MB chunk. You need about 3 GB free. Keep the app in the foreground; iOS only allows a short
grace period in the background. To force a re-download, delete the app, which removes
`Application Support/LiteRTModels`.

**"Couldn't start Gemma on this iPhone"**: tap Retry. Engine start can fail right after a
crash or relaunch while iOS reclaims the previous process's memory. The app already retries
the GPU once before falling back to CPU. If `status.backend` reports `"cpu"`, the GPU path
failed; check the Xcode console (subsystem `com.example.mise`) for the LiteRT-LM error.

**App killed while generating (jetsam)**: close other heavy apps, make sure the memory
entitlement is present, and keep prompts and images modest. The context is capped at 4096
tokens (`AppConfig.maxContextTokens`).

**Camera or mic doesn't work in the page**: the page must be https (or localhost). Check
Settings → Mise → Camera/Microphone. The app grants WebKit's capture request for its own pages
automatically. iOS still shows its own one-time prompt.

**Web page changes don't show up**: the hosted page is loaded with the normal HTTP cache. Pull
to refresh isn't wired up, so kill and relaunch the app. Bundled mode only changes when you
rebuild the app.

**Service worker / offline caching**: WKWebView only enables service workers for
"App-Bound Domains" (`WKAppBoundDomains` + `limitsNavigationsToAppBoundDomains`). Those also
restrict script injection on other domains, so this app doesn't enable them. Offline works
through the bundled fallback instead.
