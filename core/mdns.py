"""A tiny mDNS responder: answers "where is mise.local?" with this laptop's address on that network.

Phones (iOS, Android, macOS, Windows) resolve *.local names over multicast DNS, so the hub gets a
stable address, https://mise.local:8443, that survives IP changes and switching networks; the
home-screen app and the hosted page keep working without typing an IP. Pure Python (the zeroconf
package's compiled parts are blocked by Windows Smart App Control).
"""
from __future__ import annotations

import socket
import struct
import threading

GROUP, PORT = "224.0.0.251", 5353
NAME = "mise.local"


def _encode(name: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0"


def _read_name(data: bytes, off: int) -> tuple[str, int]:
    labels, jumped, end = [], False, off
    for _ in range(64):
        n = data[off]
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:  # compression pointer
            if not jumped:
                end = off + 2
            off = ((n & 0x3F) << 8) | data[off + 1]
            jumped = True
            continue
        labels.append(data[off + 1:off + 1 + n].decode(errors="replace"))
        off += 1 + n
    return ".".join(labels).lower(), (end if jumped else off)


def _ip_towards(addr: str) -> str | None:
    """Our address on the interface that reaches `addr` (no packet is sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((addr, PORT))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def _answer(ip: str, qid: int = 0, question: bytes = b"") -> bytes:
    # multicast answers: cache-flush bit + 120 s TTL; legacy unicast answers (RFC 6762 6.7): neither, TTL <= 10 s
    cls, ttl = (0x0001, 10) if question else (0x8001, 120)
    rr = _encode(NAME) + struct.pack(">HHIH", 1, cls, ttl, 4) + socket.inet_aton(ip)
    qd = 1 if question else 0
    return struct.pack(">HHHHHH", qid, 0x8400, qd, 1, 0, 0) + question + rr


def serve(ips: list[str], name: str = NAME):
    """Run in a daemon thread; returns immediately."""
    global NAME
    NAME = name

    def run():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", PORT))
        except OSError as e:
            print(f"  (mDNS unavailable: {e}; phones can still use the IP address)", flush=True)
            return
        for ip in ips:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(GROUP) + socket.inet_aton(ip))
            except OSError:
                pass
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        for ip in ips:  # announce once per interface so caches pick up the new address
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                sock.sendto(_answer(ip), (GROUP, PORT))
            except OSError:
                pass
        target = _encode(NAME)
        while True:
            try:
                data, (src, sport) = sock.recvfrom(9000)
                if len(data) < 12 or data[2] & 0x80:  # ignore responses
                    continue
                qid, _, qd = struct.unpack(">HHH", data[:6])
                off = 12
                for _ in range(qd):
                    qname, off = _read_name(data, off)
                    qtype, qclass = struct.unpack(">HH", data[off:off + 4])
                    qstart_end = off + 4
                    off = qstart_end
                    if qname == NAME and qtype in (1, 255):
                        ip = _ip_towards(src)
                        if not ip:
                            continue
                        if sport != PORT or qclass & 0x8000:  # legacy/unicast-response query: reply to sender
                            sock.sendto(_answer(ip, qid, target + struct.pack(">HH", qtype, 1)), (src, sport))
                        else:
                            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                            sock.sendto(_answer(ip), (GROUP, PORT))
            except Exception:
                continue

    threading.Thread(target=run, daemon=True, name="mdns").start()
