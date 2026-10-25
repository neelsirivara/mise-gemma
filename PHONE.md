# Mise on your phone

Mise's AI models always run on your laptop. Your phone is the camera, microphone and screen, and it talks to the
laptop over your local network. Nothing goes to the cloud.

You pair each phone once. After that, you open Mise from your home screen like any other app.

## Before you start

1. **Start Mise on the laptop.** Double-click the **Mise** icon (see the README if you haven't installed it yet).
   The **Mise Hub** page opens in the laptop's browser at http://localhost:8000/hub.
2. **Put both on the same network.** Join the phone to the same Wi-Fi as the laptop. At a venue, turn on your
   phone's **Personal Hotspot** and join it from the laptop instead. Venue Wi-Fi often blocks devices from
   reaching each other.
3. **Allow the firewall prompt.** The first time Mise runs, the laptop asks whether Python can accept incoming
   connections. Allow it. On Windows, tick public networks too if you use a hotspot, because Windows often
   treats a hotspot as public. On macOS, click **Allow**.

## Pair your phone (once)

Scan the QR code on the Hub page with your phone's camera and tap the link. The pairing page works out whether
you have an iPhone or an Android phone and shows the right steps.

**iPhone**
1. Tap **Install the Mise profile**, then **Allow**, then **Close**.
2. Open **Settings**. Tap **Profile Downloaded** near the top (or go to General → VPN & Device Management),
   then tap **Install**.
3. Go to **Settings → General → About → Certificate Trust Settings** and turn on **Mise local CA**.
4. Switch back to Safari. The pairing page notices by itself when your phone trusts the laptop.

**Android**
1. Tap **Download the Mise certificate**.
2. Open **Settings → Security → More security settings → Install from device storage → CA certificate**,
   pick **mise-local-ca.crt** and confirm. The exact menu names vary a little between phone makers.
3. Switch back to the browser. The pairing page notices by itself.

When it's done, the page says **You're connected**. Tap **Open Mise**, and allow the camera and microphone when
asked. The back camera is used by default.

## Add it to your home screen

- **iPhone:** in Safari, tap **Share → Add to Home Screen**.
- **Android:** open the browser menu and choose **Add to Home screen** or **Install app**.

From now on, start Mise on the laptop, then open Mise from your home screen. The phone shows up under
**Connected phones** on the Hub page.

## The address: mise.local

The laptop announces itself on the network as `mise.local`, so the app's address is **https://mise.local:8443**.
That address stays the same when the laptop's IP address changes or you move to another network, so your
home-screen icon keeps working. If the laptop switches networks while Mise is running, quit Mise from the Hub
page and start it again. You don't need to pair the phone again.

The IP address still works as a fallback: `https://<laptop-ip>:8443`. The Hub page shows the laptop's IP
address under the QR code.

## Why the one-time trust step

iPhones only let web pages use the camera and microphone over HTTPS. A normal HTTPS certificate comes from a
company on the internet, and it can't vouch for a laptop on your home Wi-Fi. So the laptop runs its own small
certificate authority, kept in `.certs/`, and your phone needs to trust it once. That keeps everything on your
local network.

There's no way around this step on iOS. Apple requires you to install the profile and switch on full trust
yourself, in Settings. You only do it once per phone. Restarting Mise or changing networks doesn't undo it,
because the laptop keeps the same certificate authority.

## Using the hosted page

You can also open **https://mise-gemma.vercel.app** on a paired phone. It's the same app, served from Vercel. It
looks for your laptop at `mise.local` and connects by itself. If it can't find the laptop, it shows a
**Can't find Mise on your laptop** screen. Check that Mise is running and that the phone is on the same Wi-Fi,
then tap **Try again**, or tap **Enter the address** and type `https://<laptop-ip>:8443`.

The phone still has to be paired first, because the hosted page talks to the laptop over HTTPS too. Vercel only
serves the page. Camera frames, audio and every model call go straight between the phone and the laptop. For
a fully offline setup with no cloud anywhere, use https://mise.local:8443 directly.

To host your own copy, deploy the `web/` folder (a plain static site with no build step):
- **Dashboard:** push the repo to GitHub, go to vercel.com → Add New Project → import it, set
  **Root Directory = `web`**, set Framework = **Other**, and deploy.
- **CLI** (needs Node.js): `npx vercel deploy web --prod`
- Netlify Drop (drag the `web` folder onto app.netlify.com/drop) works the same way.

## Developer options

You can start phone mode from a terminal instead of the Mise icon:
```
.\run.cmd mise -Dual -Phone        # Windows
./run.sh mise --dual --phone       # macOS / Linux
```
The terminal prints the pairing QR code and addresses, and the Hub page works as usual. The pairing page is on
`http://<laptop-ip>:8080` and the app on port 8443. When Mise is started from the icon, its log is in
`data/hub.log`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| The Hub page says "Mise is starting" for a long time | The first start takes about a minute while Gemma loads. If it says "Mise couldn't start", the reason is on the page, and the full log is in `data/hub.log`. |
| The Hub page says "Mise isn't running" | Double-click the Mise icon again. |
| The phone can't open the pairing page or can't find the laptop | Check that both are on the same Wi-Fi. Venue and office Wi-Fi often block devices from reaching each other, so use your phone's hotspot instead. Also check that the firewall allowed Python. |
| The firewall prompt never appeared, or you clicked "Don't allow" | Allow Python for incoming connections in your firewall settings (on Windows, for the network type you're on, which is often "Public" for a hotspot), then restart Mise. |
| The pairing page keeps saying "Waiting for your phone to trust the laptop" | On iPhone, check both steps: the profile is installed, and **Mise local CA** is switched on in **Certificate Trust Settings**. The second one is easy to miss. |
| `mise.local` doesn't load | Some networks and phones don't resolve `.local` names. Use `https://<laptop-ip>:8443` with the IP address shown on the Hub page. |
| Safari shows "This connection is not private" | The phone doesn't trust the laptop yet. Redo the pairing steps, including the **Certificate Trust Settings** switch. |
| No camera prompt | You're on the `http://…:8080` pairing page. The app is on `https://…:8443`; tap **Open Mise** on the pairing page. |
| No voice reply | Tap the screen once first (iOS unlocks audio on a tap), and check that the ringer switch isn't on silent. |
| The QR code has the wrong IP address | The laptop is on several networks (VPN, Tailscale…). Turn the others off, or type the address on the same network as the phone. |

## Verified (Oct 24, automated)
`scripts/ui_test.py` ran these with real Chrome, a fake camera, a fake mic and the real models, all passing:
- the iPhone 15 Pro layout (no sideways scrolling, a thumb-sized mic, tap-and-hold talk)
- the manifest
- the service worker over HTTPS
- the static-host → laptop hub path (the hosted page)

Not tested here: a physical iPhone (so neither the profile install nor `mise.local` on iOS), or Safari/WebKit itself.
