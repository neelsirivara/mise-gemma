"""End-to-end test of the consumer onboarding (phone mode): Hub page, laptop-only endpoints, setup-port
wizard + profile, wizard auto-advance in Chrome, mDNS (mise.local), device tracking, the app's
"Can't find Mise" screen, and Quit.

  python scripts/onboarding_test.py            # own server on :8543 (https), :8180 (setup), :8100 (laptop)
  python scripts/onboarding_test.py --headed

Uses alternate ports so it never touches a live hub on 8443/8080/8000. mDNS shares UDP 5353 with any
live hub (both answer mise.local with the same address).
"""
import argparse
import json
import os
import plistlib
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8543)
ap.add_argument("--setup-port", type=int, default=8180)
ap.add_argument("--local-port", type=int, default=8100)
ap.add_argument("--headed", action="store_true")
a = ap.parse_args()

from core.phone import local_ips  # noqa: E402  (pure function; doesn't start anything)

IPS = local_ips()
LAN = IPS[0] if IPS else None
LOCAL = f"http://127.0.0.1:{a.local_port}"
results = []
NOVERIFY = ssl.create_default_context()
NOVERIFY.check_hostname = False
NOVERIFY.verify_mode = ssl.CERT_NONE


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {str(detail)[:300]}" if detail else ""), flush=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kw):
        return None


OPENER = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=NOVERIFY))


def http(url, method="GET", headers=None, timeout=10):
    """(status, headers, body) without following redirects or verifying certificates."""
    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        r = OPENER.open(req, timeout=timeout)
        return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


data_dir = tempfile.mkdtemp(prefix="mise_onboard_")
log_path = Path(data_dir) / "server.log"
env = {**os.environ, "PYTHONUTF8": "1", "APP": "mise", "PHONE": "1", "PORT": str(a.port),
       "SETUP_PORT": str(a.setup_port), "LOCAL_PORT": str(a.local_port), "GEMMA_DATA_DIR": data_dir,
       "OPEN_BROWSER": "0"}
print(f"LAN IPs: {IPS}; server log: {log_path}", flush=True)
server = subprocess.Popen([sys.executable, "-m", "core.server", "mise"], cwd=ROOT, env=env,
                          stdout=open(log_path, "w", encoding="utf-8"), stderr=subprocess.STDOUT)


def stop_server():
    if server.poll() is None:
        try:
            http(LOCAL + "/api/hub/quit", "POST", timeout=3)
        except Exception:
            pass
        try:
            server.wait(8)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(5)


try:
    t0 = time.time()
    ready = False
    for _ in range(300):
        try:
            if json.loads(urllib.request.urlopen(LOCAL + "/api/state", timeout=3).read())["engine"].get("ready"):
                ready = True
                break
        except OSError:
            pass
        if server.poll() is not None:
            break
        time.sleep(1)
    check("server ready (engine.ready)", ready, f"{time.time() - t0:.0f}s; exit={server.poll()}")
    if not ready:
        print(log_path.read_text(encoding="utf-8", errors="replace")[-3000:])
        sys.exit(1)
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    check("mDNS responder bound (no 'mDNS unavailable' in log)", "mDNS unavailable" not in log_text,
          [l for l in log_text.splitlines() if "mDNS" in l])

    # ------------------------------------------------------------------ 2. laptop-only status (before any LAN traffic)
    s, _, b = http(LOCAL + "/api/hub/status")
    st = json.loads(b) if s == 200 else {}
    check("2a /api/hub/status from 127.0.0.1 -> 200", s == 200, s)
    check("6a no devices before LAN traffic", st.get("devices") == [], st.get("devices"))
    pairing = st.get("pairing", {})
    check("pairing.app_urls starts with https://mise.local:<PORT>",
          (pairing.get("app_urls") or [""])[0] == f"https://mise.local:{a.port}", pairing.get("app_urls"))
    check("local_app is http://localhost:<LOCAL_PORT>/", st.get("local_app") == f"http://localhost:{a.local_port}/",
          st.get("local_app"))

    if LAN:
        s, _, b = http(f"https://{LAN}:{a.port}/api/hub/status")
        check("2b /api/hub/status from LAN IP -> 403", s == 403, f"{s} {b[:100]!r}")
        s, _, b = http(f"https://{LAN}:{a.port}/hub")
        check("2c /hub from LAN IP -> 403", s == 403, f"{s} {b[:100]!r}")
        s, _, b = http(f"https://{LAN}:{a.port}/api/hub/quit", "POST")
        check("2d /api/hub/quit from LAN IP -> 403 (server survives)", s == 403 and server.poll() is None, s)

    # ------------------------------------------------------------------ 3. setup port
    s, h, _ = http(f"http://127.0.0.1:{a.setup_port}/")
    check("3a setup / from 127.0.0.1 -> 302 to hub", s == 302 and h.get("Location") == f"http://localhost:{a.local_port}/hub",
          f"{s} Location={h.get('Location')}")
    if LAN:
        s, h, b = http(f"http://{LAN}:{a.setup_port}/")
        wiz = b.decode("utf-8", "replace")
        check("3b setup / from LAN IP -> wizard HTML", s == 200 and "Set up Mise" in wiz and "text/html" in h.get("Content-Type", ""),
              f"{s} {h.get('Content-Type')}")
        check("3c wizard URL list uses PORT, not 8443", f":{a.port}" in wiz and ":8443" not in wiz,
              [l.strip() for l in wiz.splitlines() if "const URLS" in l])
        s, h, b = http(f"http://{LAN}:{a.setup_port}/mise.mobileconfig")
        try:
            pl = plistlib.loads(b)
            ok_pl = pl.get("PayloadType") == "Configuration" and pl["PayloadContent"][0]["PayloadType"] == "com.apple.security.root"
            from cryptography import x509
            x509.load_der_x509_certificate(pl["PayloadContent"][0]["PayloadContent"])
        except Exception as e:  # noqa: BLE001
            ok_pl, pl = False, e
        check("3d mobileconfig content-type", h.get("Content-Type") == "application/x-apple-aspen-config", h.get("Content-Type"))
        check("3e mobileconfig parses (plistlib) with a DER root cert", ok_pl, "" if ok_pl else pl)
        s, h, b = http(f"http://{LAN}:{a.setup_port}/mise-local-ca.crt")
        check("3f CA .crt served", s == 200 and b.startswith(b"-----BEGIN CERTIFICATE"), f"{s} {h.get('Content-Type')}")

    # ------------------------------------------------------------------ 6. device tracking
    if LAN:
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1"
        s, _, _ = http(f"https://{LAN}:{a.port}/api/meta", headers={"User-Agent": ua})
        _, _, b = http(LOCAL + "/api/hub/status")
        devs = json.loads(b)["devices"]
        check("6b LAN API request shows up in /api/hub/status devices",
              any(d["ip"] == LAN and d["name"] == "iPhone" for d in devs), f"meta={s} devices={devs}")

    # ------------------------------------------------------------------ 5. mDNS
    def mdns_query(name="mise.local", src_ip=LAN, wait=3.0):
        q = struct.pack(">HHHHHH", 0x4D53, 0, 1, 0, 0, 0)
        q += b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0" + struct.pack(">HH", 1, 1)
        sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sk.bind((src_ip or "0.0.0.0", 0))
        if src_ip:
            sk.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(src_ip))
        sk.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
        sk.settimeout(0.3)
        sk.sendto(q, ("224.0.0.251", 5353))
        answers, end = [], time.time() + wait
        while time.time() < end:
            try:
                data, src = sk.recvfrom(9000)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                qid, flags, qd, an = struct.unpack(">HHHH", data[:8])
                off = 12
                for _ in range(qd):
                    while data[off] != 0:
                        if data[off] & 0xC0 == 0xC0:
                            off += 1
                            break
                        off += 1 + data[off]
                    off += 1 + 4
                for _ in range(an):
                    labels = []
                    while True:
                        n = data[off]
                        if n == 0:
                            off += 1
                            break
                        if n & 0xC0 == 0xC0:
                            labels.append("<ptr>")
                            off += 2
                            break
                        labels.append(data[off + 1:off + 1 + n].decode())
                        off += 1 + n
                    typ, cls, ttl, rdlen = struct.unpack(">HHIH", data[off:off + 10])
                    off += 10
                    rd = data[off:off + rdlen]
                    off += rdlen
                    if typ == 1:
                        answers.append({"from": src, "id": qid, "name": ".".join(labels), "ip": socket.inet_ntoa(rd),
                                        "ttl": ttl, "cache_flush": bool(cls & 0x8000)})
            except Exception as e:  # noqa: BLE001
                answers.append({"from": src, "parse_error": str(e)})
        sk.close()
        return answers

    ans = mdns_query()
    a_ips = {x.get("ip") for x in ans if x.get("name") == "mise.local"}
    check("5a legacy unicast mDNS query for mise.local -> A == LAN IP", LAN in a_ips and a_ips <= set(IPS),
          ans)
    if ans:
        x = next((x for x in ans if "ip" in x), {})
        # RFC 6762 6.7: legacy unicast replies must not set cache-flush and should use TTL <= 10 s
        check("5b legacy unicast reply follows RFC 6762 6.7 (no cache-flush, TTL<=10)",
              not x.get("cache_flush") and x.get("ttl", 999) <= 10, x)
    t = time.time()
    try:
        gai = sorted({r[4][0] for r in socket.getaddrinfo("mise.local", a.port, socket.AF_INET)})
    except OSError as e:
        gai = f"error: {e}"
    check("5c socket.getaddrinfo('mise.local') resolves on Windows (informational)", isinstance(gai, list) and LAN in gai,
          f"{gai} in {time.time() - t:.1f}s")

    # ------------------------------------------------------------------ browser checks
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=not a.headed, args=["--ignore-certificate-errors"])

        # 1. Hub page
        ctx = browser.new_context(viewport={"width": 1280, "height": 860})
        page = ctx.new_page()
        page.goto(f"http://localhost:{a.local_port}/hub")
        try:
            page.wait_for_function("document.getElementById('statusTitle').textContent === 'Mise is ready'", timeout=10000)
            title_ok = True
        except Exception:
            title_ok = False
        check("1a Hub page shows 'Mise is ready'", title_ok, page.text_content("#statusTitle"))
        page.wait_for_timeout(500)
        check("1b Hub QR svg present", page.locator("#qr svg").count() == 1)
        pu = page.text_content("#pairUrl")
        check("1c Hub shows pair URL", pu == pairing.get("pair_url") and pu.startswith("http"), pu)
        href = page.get_attribute("#openHere", "href")
        check("1d 'Open Mise on this laptop' -> http://localhost:<LOCAL_PORT>/",
              page.text_content("#openHere").strip() == "Open Mise on this laptop" and href == f"http://localhost:{a.local_port}/", href)
        ctx.close()

        # 4. wizard auto-advance, iPhone emulation
        if LAN:
            dev = dict(pw.devices["iPhone 15 Pro"])
            dev.pop("default_browser_type", None)
            ctx = browser.new_context(**dev, ignore_https_errors=True)
            page = ctx.new_page()
            reqs = []
            page.on("request", lambda r: reqs.append(r.url) if "/api/meta" in r.url else None)
            t = time.time()
            page.goto(f"http://{LAN}:{a.setup_port}/")
            check("4a wizard shows iOS profile step", page.locator("#ios").is_visible())
            try:
                page.wait_for_selector("#open:not([hidden])", timeout=12000)
                adv = True
            except Exception:
                adv = False
            check("4b wizard auto-advances to \"You're connected\"", adv and "You're connected" in page.text_content("#open h1"),
                  f"{time.time() - t:.1f}s; statusText={page.text_content('#statusText')!r}; tried={sorted(set(reqs))}")
            ob = page.get_attribute("#openBtn", "href")
            check("4c Open Mise href is https on PORT", ob and ob.startswith("https://") and f":{a.port}/" in ob, ob)
            if adv and ob:
                r = page.goto(ob)
                ok = r is not None and r.ok
                try:
                    page.wait_for_function("document.getElementById('hubPill')?.dataset.state === 'ok'", timeout=15000)
                    pill = "ok"
                except Exception:
                    pill = page.get_attribute("#hubPill", "data-state")
                check("4d Open Mise URL loads the app and connects", ok and pill == "ok", f"status={r and r.status} pill={pill}")
            ctx.close()

        # 7. unreachable screen
        def unreachable(label, setup):
            ctx = browser.new_context(viewport={"width": 390, "height": 844})
            # never let the app reach the live hub (findHub tries https://mise.local:8443)
            ctx.route("**://mise.local:8443/**", lambda r: r.abort())
            setup(ctx)
            page = ctx.new_page()
            t = time.time()
            page.goto(f"http://localhost:{a.local_port}/?hub=https://10.255.255.1:9")
            try:
                page.wait_for_selector("text=Can't find Mise on your laptop", timeout=15000)
                shown = True
            except Exception:
                shown = False
            state = page.get_attribute("#hubPill", "data-state")
            check(f"7{label} 'Can't find Mise' screen shown", shown,
                  f"{time.time() - t:.1f}s; url={page.url}; pill={state}; h2={page.locator('h2').all_text_contents()[:3]}")
            if shown:
                check(f"7{label} hub dot data-state='bad'", state == "bad", state)
                check(f"7{label} Try again button exists", page.locator("#retryHub").count() == 1)
            ctx.close()

        unreachable("a (as specified)", lambda ctx: None)
        # the page's own origin also unreachable (what a phone sees from the hosted page / stale address)
        unreachable("b (origin /api also down)",
                    lambda ctx: ctx.route(f"http://localhost:{a.local_port}/api/**", lambda r: r.abort()))
        browser.close()

    # ------------------------------------------------------------------ 8. quit
    s, _, b = http(LOCAL + "/api/hub/quit", "POST")
    t = time.time()
    try:
        server.wait(5)
        exited = True
    except subprocess.TimeoutExpired:
        exited = False
    check("8 POST /api/hub/quit -> process exits within 5 s", s == 200 and exited, f"{s} {b[:60]!r} exit={server.poll()} in {time.time() - t:.1f}s")
finally:
    stop_server()

fails = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(fails)}/{len(results)} passed" + (f"; FAILED: {fails}" if fails else ""))
sys.exit(1 if fails else 0)
