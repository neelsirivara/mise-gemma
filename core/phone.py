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
    names = [x509.DNSName("localhost"), x509.DNSName(host), x509.DNSName(f"{host}.local")]
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


def _qr_svg(text: str) -> str:
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    b = io.BytesIO()
    img.save(b)
    return b.getvalue().decode()


def _setup_page(app_urls: list[str], setup_port: int) -> str:
    cards = "".join(f'<div class="card"><div class="qr">{_qr_svg(u)}</div><a href="{html.escape(u)}">{html.escape(u)}</a></div>'
                    for u in app_urls)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Mise phone setup</title>
<style>
body{{font-family:-apple-system,system-ui,'Segoe UI',sans-serif;background:#0f1115;color:#e9ecf1;margin:0;padding:20px;line-height:1.5}}
main{{max-width:640px;margin:auto}} h1{{color:#e8743b;margin:0 0 4px}} .muted{{color:#8b93a3}}
ol li{{margin:10px 0}} a{{color:#e8743b}} .btn{{display:inline-block;background:#e8743b;color:#111;font-weight:700;
padding:12px 18px;border-radius:12px;text-decoration:none;margin:6px 0}} .card{{background:#171a21;border:1px solid #2a2f3a;
border-radius:14px;padding:14px;margin:10px 0;text-align:center}} .qr svg{{width:200px;height:200px;background:#fff;border-radius:8px}}
code{{background:#1e222b;padding:2px 6px;border-radius:6px}}
</style></head><body><main>
<h1>Mise on your phone</h1>
<p class="muted">The models run on this laptop. Your phone is the camera, mic and screen, over your local network.
Nothing goes to the internet.</p>
<h2>1 · Trust this laptop (once per phone)</h2>
<p><a class="btn" href="/mise-local-ca.crt">Download certificate</a></p>
<ol>
<li><b>iPhone:</b> tap <i>Allow</i> on the download prompt. Open <b>Settings</b>, tap <i>Profile Downloaded</i> near the top, then tap <b>Install</b>.</li>
<li>Go to <b>Settings → General → About → Certificate Trust Settings</b> and switch on <i>Mise local CA</i>.</li>
<li><b>Android:</b> go to Settings → Security → Encryption &amp; credentials → Install a certificate → CA certificate.</li>
</ol>
<h2>2 · Open the app</h2>
<p class="muted">Use the address on the same network as your phone. Your phone's hotspot is usually <code>172.20.10.x</code>.</p>
{cards}
<h2>3 · Add to Home Screen</h2>
<ol><li>In Safari tap <b>Share</b> → <b>Add to Home Screen</b>.</li>
<li>Open <b>Mise</b> from the home screen and allow the camera and microphone.</li></ol>
<p class="muted">Seeing “can't connect”? Check that the phone and laptop are on the same network. Venue Wi-Fi often blocks
devices from reaching each other, so turn on your iPhone's Personal Hotspot and join it from the laptop. Also check that
the laptop firewall allows Python (Windows: Private networks; macOS: allow incoming connections). Setup page: port {setup_port}.</p>
</main></body></html>"""


def prepare(app_port: int, setup_port: int) -> tuple[str, str]:
    ips = local_ips()
    _server_cert(ips)
    app_urls = [f"https://{i}:{app_port}" for i in ips] or [f"https://localhost:{app_port}"]
    page = _setup_page(app_urls, setup_port).encode()
    ca = CA_CERT.read_bytes()

    class Setup(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/mise-local-ca.crt"):
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

    setup_urls = [f"http://{i}:{setup_port}" for i in ips]
    print("  PHONE MODE")
    print("  1) On the phone, open the setup page (scan this QR with the camera):")
    if setup_urls:
        q = qrcode.QRCode(border=1)
        q.add_data(setup_urls[0])
        q.print_ascii(invert=True)
    for u in setup_urls:
        print("       ", u)
    print("  2) Then the app (after trusting the certificate):")
    for u in app_urls:
        print("       ", u)
    print("  If the firewall asks, allow Python to accept incoming connections.\n", flush=True)
    return str(SRV_CERT), str(SRV_KEY)
