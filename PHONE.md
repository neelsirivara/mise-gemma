# Mise on an iPhone (home-screen web app)

The **models always run on the laptop**. The phone is the camera, microphone and screen, talking to the
laptop over your local network. Nothing goes to the cloud. iPhones only allow camera and mic access on
**HTTPS** pages, which is why the laptop serves HTTPS with its own small certificate authority.

## Option A — serve the app from the laptop (recommended: works fully offline)

1. **Network.** Put the phone and laptop on the same network. At a venue, use the **iPhone's Personal Hotspot**
   and join it from the laptop: venue Wi-Fi often blocks devices from reaching each other.
2. On the laptop:
   ```
   .\run.cmd mise -Dual -Phone        # Windows
   ./run.sh mise --dual --phone       # macOS / Linux
   ```
   The window prints a **QR code** plus the setup and app addresses. The first time, the firewall asks about
   Python. On Windows, allow it for the network type you're on (your own hotspot often counts as "Public");
   on macOS, click **Allow** for incoming connections.
3. **On the iPhone, once:** scan the QR code to open the setup page (`http://<laptop-ip>:8080`), then:
   - Tap **Download certificate**, then **Allow**.
   - Open **Settings → Profile Downloaded → Install**.
   - Go to **Settings → General → About → Certificate Trust Settings** and switch on **Mise local CA**.
4. Open the app address from the setup page (`https://<laptop-ip>:8443`) in **Safari**, then tap
   **Share → Add to Home Screen**.
5. Open **Mise** from the home screen and allow the camera and microphone. The back camera is used by default.

Switched networks? Restart phone mode. It issues a new server certificate for the new IP. The phone
keeps trusting the same local CA, so step 3 is a one-time thing.

## Option B — host the page on Vercel and point it at the laptop

The `web/` folder is a plain static site (no build step), with `vercel.json`, a manifest, icons and an offline
service worker.

- **Dashboard:** push the repo to GitHub, go to vercel.com → Add New Project → import it, set **Root Directory = `web`**,
  set Framework = **Other**, and deploy.
- **CLI** (needs Node.js): `npx vercel deploy web --prod`
- No account handy? Netlify Drop (drag the `web` folder onto app.netlify.com/drop) works the same way.

Then on the phone: open the Vercel URL, tap **⚙ hub**, and enter `https://<laptop-ip>:8443`. The address is saved.
Then **Add to Home Screen**. You can also open `https://your-app.vercel.app/?hub=https://172.20.10.2:8443` once.

You **still need step 3 of Option A** (trust the local CA). A secure page can only talk to the laptop over
HTTPS that the phone trusts. Vercel serves only the static UI. All camera, audio and model traffic goes
phone ↔ laptop. For the judges' "no cloud anywhere in the loop" rule, Option A is the cleaner story.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Badge says "no Mise hub at …" | The laptop isn't reachable. Check you're on the same network (hotspot), phone mode is running, and the firewall allowed Python. |
| Safari shows "not private" | The CA isn't trusted yet. Redo step 3, including the **Certificate Trust Settings** switch. |
| No camera prompt | You opened the `http://…:8080` setup page. The app is on `https://…:8443`. |
| No voice reply | Tap the screen once first (iOS unlocks audio on a tap), and check that the ringer switch isn't on silent. |
| Wrong IP in the QR code | The laptop has several networks (VPN, Tailscale…). Use the address on the same network as the phone. |

## Verified (Oct 24, automated)
`scripts/ui_test.py` ran these with real Chrome, a fake camera, a fake mic and the real models, all passing:
- the iPhone 15 Pro layout (no sideways scrolling, a thumb-sized mic, tap-and-hold talk)
- the manifest
- the service worker over HTTPS
- the static-host → laptop hub path (Option B)

Not tested here: a physical iPhone, the certificate install flow on iOS, or Safari/WebKit itself.
