"""Phone mode: let an iPhone (or any phone) use the laptop's models over the local network.

iOS only gives web pages the camera and mic over HTTPS, so we:
  1. keep a small local certificate authority in .certs/ (made once, installed once on the phone),
  2. issue a fresh server certificate for this laptop's current IP addresses on every start,
  3. serve a plain-HTTP setup page (QR code, CA download, step-by-step) on SETUP_PORT.
Nothing here talks to the internet.
"""
from __future__ import annotations

import datetime as dt
import html
import io
import ipaddress
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import qrcode
import qrcode.image.svg
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from . import config

MDNS_NAME = "mise.local"  # stable name for the hub on any network (see core/mdns.py)
CA_CERT = config.CERT_DIR / "mise-local-ca.crt"
CA_KEY = config.CERT_DIR / "mise-local-ca.key"
SRV_CERT = config.CERT_DIR / "server.crt"
SRV_KEY = config.CERT_DIR / "server.key"


def local_ips() -> list[str]:
    ips = set()
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:  # the interface with the default route (no packet is sent)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    ips = [i for i in ips if not i.startswith(("127.", "169.254."))]
    # likely-reachable first: phone hotspot (172.20.10.x), home/venue Wi-Fi, then the rest
    return sorted(ips, key=lambda i: (not i.startswith("172.20.10."), not i.startswith("192.168."), i))


def _write(path, obj):
    path.write_bytes(obj)


def _ca():
    if CA_CERT.exists() and CA_KEY.exists():
        return (x509.load_pem_x509_certificate(CA_CERT.read_bytes()),
                serialization.load_pem_private_key(CA_KEY.read_bytes(), None))
    config.CERT_DIR.mkdir(exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Mise local CA ({socket.gethostname()})")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write(CA_KEY, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    _write(CA_CERT, cert.public_bytes(serialization.Encoding.PEM))
    return cert, key


def _server_cert(ips: list[str]):
    ca_cert, ca_key = _ca()
    key = ec.generate_private_key(ec.SECP256R1())
    host = socket.gethostname()
    names = [x509.DNSName("localhost"), x509.DNSName(MDNS_NAME), x509.DNSName(host), x509.DNSName(f"{host}.local")]
    names += [x509.IPAddress(ipaddress.ip_address(i)) for i in ["127.0.0.1", *ips]]
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Mise hub {host}")]))
            .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=365))  # iOS: < 825 days
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write(SRV_KEY, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    # full chain so clients that don't have the CA cached can still build the path
    _write(SRV_CERT, cert.public_bytes(serialization.Encoding.PEM) + ca_cert.public_bytes(serialization.Encoding.PEM))


def _mobileconfig() -> bytes:
    """An Apple configuration profile wrapping the CA. iOS always treats this as an installable profile,
    whereas a bare .crt sometimes lands in the Files app instead."""
    import base64
    import uuid as _uuid
    cert = x509.load_pem_x509_certificate(CA_CERT.read_bytes())
    der = cert.public_bytes(serialization.Encoding.DER)
    fp = cert.fingerprint(hashes.SHA256()).hex()
    u1, u2 = (str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"mise-ca-{fp}-{n}")).upper() for n in (1, 2))
    b64 = base64.encodebytes(der).decode()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>PayloadContent</key><array><dict>
    <key>PayloadCertificateFileName</key><string>mise-local-ca.cer</string>
    <key>PayloadContent</key><data>{b64}</data>
    <key>PayloadDescription</key><string>Lets this phone trust the Mise hub running on your laptop.</string>
    <key>PayloadDisplayName</key><string>Mise local CA</string>
    <key>PayloadIdentifier</key><string>local.mise.ca.cert</string>
    <key>PayloadType</key><string>com.apple.security.root</string>
    <key>PayloadUUID</key><string>{u1}</string>
    <key>PayloadVersion</key><integer>1</integer>
  </dict></array>
  <key>PayloadDescription</key><string>Trust the Mise hub on your laptop so the app can use HTTPS on your local network.</string>
  <key>PayloadDisplayName</key><string>Mise local CA</string>
  <key>PayloadIdentifier</key><string>local.mise.ca</string>
  <key>PayloadRemovalDisallowed</key><false/>
  <key>PayloadType</key><string>Configuration</string>
  <key>PayloadUUID</key><string>{u2}</string>
  <key>PayloadVersion</key><integer>1</integer>
</dict></plist>
""".encode()


def _qr_svg(text: str) -> str:
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    b = io.BytesIO()
    img.save(b)
    return b.getvalue().decode()


def _wizard_page(app_urls: list[str]) -> str:
    """Phone pairing, guided: one-tap profile install, then the page watches until the phone trusts the
    laptop (it keeps trying the hub over HTTPS) and moves on by itself. No addresses to type."""
    import json as _json
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>Set up Mise</title>
<style>
:root{--bg:#dcebdd;--plate:#fffdf7;--ink:#1f3326;--ink2:#4c6454;--line:#cddccf;--rim:#3f6e48;--wash:#d5e8d4;--coral:#c25b2b;--ok:#2f7a45}
@media (prefers-color-scheme:dark){:root{--bg:#13201a;--plate:#1b2b22;--ink:#eef4ec;--ink2:#a8bcab;--line:#2d4234;--rim:#8fd19c;--wash:#213a2a;--coral:#f5a07a;--ok:#8fd19c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.5 -apple-system,system-ui,"Segoe UI",sans-serif;
padding:max(18px,env(safe-area-inset-top)) max(16px,env(safe-area-inset-right)) 32px max(16px,env(safe-area-inset-left))}
main{max-width:520px;margin:auto;display:flex;flex-direction:column;gap:16px}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:22px}.dot{width:22px;height:22px;border-radius:50%;border:4px solid var(--rim);background:var(--plate)}
h1{font-size:28px;line-height:1.15;margin:4px 0 0}p{margin:0}.muted{color:var(--ink2)}
.steps{display:flex;gap:6px}.steps i{flex:1;height:6px;border-radius:3px;background:var(--line)}.steps i.on{background:var(--rim)}
.card{background:var(--plate);border-radius:20px;padding:18px;display:flex;flex-direction:column;gap:12px;box-shadow:0 10px 30px rgb(31 51 38/10%)}
.btn{display:block;text-align:center;background:var(--rim);color:var(--plate);font-weight:800;font-size:18px;padding:15px;border-radius:14px;text-decoration:none;border:0}
.btn.ghost{background:transparent;color:var(--rim);border:2px solid var(--rim)}
ol{margin:0;padding-left:22px;display:grid;gap:8px}b{font-weight:700}
.status{display:flex;align-items:center;gap:10px;font-weight:700;color:var(--ink2)}
.spin{width:18px;height:18px;border-radius:50%;border:3px solid var(--line);border-top-color:var(--rim);animation:s 1s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}.ok{color:var(--ok)}.ok .spin{display:none}
.share{display:inline-block;width:20px;height:20px;vertical-align:-4px}
[hidden]{display:none!important}small{color:var(--ink2)}
</style></head><body><main>
<div class="brand"><span class="dot"></span>Mise</div>
<div class="steps"><i id="s1" class="on"></i><i id="s2"></i><i id="s3"></i></div>

<section id="trust" class="card">
  <h1>Let this phone talk to your laptop</h1>
  <p class="muted">Mise's AI runs on your laptop. This one-time step lets your phone connect to it securely,
  on your own Wi-Fi. Nothing goes to the internet.</p>
  <div id="ios" hidden>
    <a class="btn" href="/mise.mobileconfig">Install the Mise profile</a>
    <ol style="margin-top:12px">
      <li>Tap <b>Allow</b>, then <b>Close</b>.</li>
      <li>Open <b>Settings</b>. Tap <b>Profile Downloaded</b> at the top (or General → VPN &amp; Device Management), then <b>Install</b>.</li>
      <li>Go to <b>Settings → General → About → Certificate Trust Settings</b> and turn on <b>Mise local CA</b>.</li>
      <li>Come back here. This page notices by itself.</li>
    </ol>
  </div>
  <div id="android" hidden>
    <a class="btn" href="/mise-local-ca.crt">Download the Mise certificate</a>
    <ol style="margin-top:12px">
      <li>Open <b>Settings → Security → More security settings → Install from device storage → CA certificate</b>.</li>
      <li>Pick <b>mise-local-ca.crt</b> and confirm.</li>
      <li>Come back here. This page notices by itself.</li>
    </ol>
  </div>
  <div id="other" hidden><a class="btn" href="/mise-local-ca.crt">Download the Mise certificate</a>
    <p class="muted" style="margin-top:8px">Add it to your system's trusted root certificates, then come back here.</p></div>
  <p class="status" id="status"><span class="spin"></span><span id="statusText">Checking the connection…</span></p>
</section>

<section id="open" class="card" hidden>
  <h1>You're connected</h1>
  <p class="muted">Your phone can reach Mise on your laptop. Open it, then keep it on your home screen like an app.</p>
  <a class="btn" id="openBtn" href="#">Open Mise</a>
  <div id="a2hs">
    <p><b>Add it to your home screen:</b> in Safari tap
      <svg class="share" viewBox="0 0 24 24" aria-label="Share"><path d="M12 3v12M7 8l5-5 5 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7" fill="none" stroke="currentColor" stroke-width="2"/></svg>
      Share, then <b>Add to Home Screen</b>.</p>
  </div>
</section>
<small>Trouble? Your phone and laptop must be on the same Wi-Fi (or your phone's hotspot), and Mise must be running on the laptop.</small>
</main>
<script>
const URLS = """ + _json.dumps(app_urls) + """;
const ua = navigator.userAgent, ios = /iPhone|iPad|iPod/.test(ua) || (/Mac/.test(ua) && navigator.maxTouchPoints > 1), android = /Android/.test(ua);
document.getElementById(ios ? "ios" : android ? "android" : "other").hidden = false;
if (!ios) document.getElementById("a2hs").innerHTML = "<p><b>Install it:</b> open your browser menu and choose <b>Add to Home screen</b> or <b>Install app</b>.</p>";
let tries = 0, done = false;
async function reach(u) {
  try { const r = await fetch(u + "/api/meta", { cache: "no-store", signal: AbortSignal.timeout(2500) }); return r.ok; } catch { return false; }
}
async function check() {
  if (done) return;
  tries++;
  for (const u of URLS) {
    if (await reach(u)) {
      done = true;
      const st = document.getElementById("status"); st.classList.add("ok");
      document.getElementById("statusText").textContent = "Connected";
      document.getElementById("trust").hidden = true;
      document.getElementById("open").hidden = false;
      document.getElementById("s2").classList.add("on"); document.getElementById("s3").classList.add("on");
      document.getElementById("openBtn").href = u + "/";
      return;
    }
  }
  document.getElementById("statusText").textContent = tries < 2 ? "Checking the connection…" : "Waiting for your phone to trust the laptop…";
  setTimeout(check, 2000);
}
check();
document.addEventListener("visibilitychange", () => { if (!document.hidden) check(); });
</script></body></html>"""


PAIRING: dict = {}  # filled by prepare(); read by the laptop's Hub page (core/server.py /api/hub/status)


def prepare(app_port: int, setup_port: int) -> tuple[str, str]:
    from . import mdns
    ips = local_ips()
    _server_cert(ips)
    mdns.serve(ips, MDNS_NAME)
    app_urls = [f"https://{MDNS_NAME}:{app_port}"] + [f"https://{i}:{app_port}" for i in ips]
    pair_url = f"http://{ips[0]}:{setup_port}/" if ips else f"http://localhost:{setup_port}/"
    PAIRING.update(pair_url=pair_url, app_urls=app_urls, qr_svg=_qr_svg(pair_url), ips=ips, mdns=MDNS_NAME,
                   app_port=app_port, setup_port=setup_port)
    page = _wizard_page(app_urls).encode()
    ca = CA_CERT.read_bytes()
    profile = _mobileconfig()

    class Setup(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.client_address[0].startswith("127.") and self.path in ("/", ""):
                # the laptop itself: send it to the Hub page instead of the phone wizard
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{config.LOCAL_PORT}/hub")
                self.end_headers()
                return
            if self.path.startswith("/mise.mobileconfig"):
                body, ctype = profile, "application/x-apple-aspen-config"
            elif self.path.startswith("/mise-local-ca.crt"):
                body, ctype = ca, "application/x-x509-ca-cert"
            else:
                body, ctype = page, "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((config.PHONE_HOST, setup_port), Setup)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print("  PHONE MODE")
    print(f"  Hub page on this laptop: http://localhost:{config.LOCAL_PORT}/hub  (shows the pairing QR code)")
    print(f"  Phone pairing page:      {pair_url}")
    q = qrcode.QRCode(border=1)
    q.add_data(pair_url)
    q.print_ascii(invert=True)
    print(f"  App on the phone after pairing: {app_urls[0]}")
    print("  If the firewall asks, allow Python to accept incoming connections.", flush=True)
    return str(SRV_CERT), str(SRV_KEY)
