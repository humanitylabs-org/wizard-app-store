#!/usr/bin/env python3
"""Allowlist HTTPS egress proxy for a restricted agent.

The agent sits on an internal-only Docker network, so this proxy is its only route out. It accepts
HTTP CONNECT to port 443 for hostnames on the allowlist and nothing else: no plain HTTP, no IP
literals, no other ports, and no hostname that resolves to a private, loopback, link-local,
CGNAT (tailnet) or otherwise non-global address. One JSON line per decision goes to stdout.

Allowlist file: one hostname per line; a leading "*." allows subdomains (not the bare domain).
"""
import asyncio
import ipaddress
import json
import os
import socket
import sys
import time

ALLOWLIST_FILE = os.environ.get("EGRESS_ALLOWLIST", "/etc/egress/allowlist.txt")
LISTEN_PORT = int(os.environ.get("EGRESS_PORT", "3128"))
MAX_HEAD = 8192
IDLE_TIMEOUT = 300


def load_allowlist(path):
    exact, suffixes = set(), set()
    with open(path) as fh:
        for raw in fh:
            line = raw.split("#", 1)[0].strip().lower().rstrip(".")
            if not line:
                continue
            if line.startswith("*."):
                suffixes.add(line[1:])          # ".example.com"
            else:
                exact.add(line)
    return exact, suffixes


def load_allowlist_env(value):
    exact, suffixes = set(), set()
    for item in value.replace(",", " ").split():
        item = item.strip().lower().rstrip(".")
        if item.startswith("*."):
            suffixes.add(item[1:])
        elif item:
            exact.add(item)
    return exact, suffixes


# EGRESS_ALLOWLIST_HOSTS (space/comma separated) wins over the file, so no host file mount is needed.
if os.environ.get("EGRESS_ALLOWLIST_HOSTS", "").strip():
    EXACT, SUFFIXES = load_allowlist_env(os.environ["EGRESS_ALLOWLIST_HOSTS"])
else:
    EXACT, SUFFIXES = load_allowlist(ALLOWLIST_FILE)


def log(**fields):
    fields["ts"] = round(time.time(), 3)
    sys.stdout.write(json.dumps(fields, sort_keys=True) + "\n")
    sys.stdout.flush()


def host_allowed(host):
    if host in EXACT:
        return True
    return any(host.endswith(s) and len(host) > len(s) for s in SUFFIXES)


def is_ip_literal(host):
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def public_addresses(host):
    """Resolve host; return its addresses only if every one is globally routable."""
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    addrs = sorted({info[4][0] for info in infos})
    for addr in addrs:
        ip = ipaddress.ip_address(addr)
        if not ip.is_global or ip.is_multicast:
            raise PermissionError(f"resolves to non-public address {addr}")
    return addrs


async def pipe(reader, writer):
    try:
        while True:
            data = await asyncio.wait_for(reader.read(65536), IDLE_TIMEOUT)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.TimeoutError, ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def refuse(writer, code, reason, **fields):
    log(decision="deny", code=code, reason=reason, **fields)
    writer.write(f"HTTP/1.1 {code} {reason}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
    try:
        await writer.drain()
    finally:
        writer.close()


async def handle(reader, writer):
    peer = (writer.get_extra_info("peername") or ("?",))[0]
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
        writer.close()
        return
    if len(head) > MAX_HEAD:
        return await refuse(writer, 431, "Header Too Large", peer=peer)
    line = head.split(b"\r\n", 1)[0].decode("latin-1")
    parts = line.split(" ")
    if len(parts) != 3 or parts[0] != "CONNECT":
        return await refuse(writer, 403, "Only HTTPS CONNECT is allowed", peer=peer, method=parts[0][:16])
    target = parts[1]
    host, sep, port = target.rpartition(":")
    host = host.strip().lower().rstrip(".")
    if not sep or port != "443":
        return await refuse(writer, 403, "Only port 443 is allowed", peer=peer, target=target[:255])
    if not host or is_ip_literal(host):
        return await refuse(writer, 403, "IP literals are not allowed", peer=peer, target=target[:255])
    if not host_allowed(host):
        return await refuse(writer, 403, "Host not on allowlist", peer=peer, host=host[:255])
    try:
        addrs = await asyncio.get_running_loop().run_in_executor(None, public_addresses, host)
    except PermissionError as exc:
        return await refuse(writer, 403, "Destination not public", peer=peer, host=host, detail=str(exc))
    except OSError:
        return await refuse(writer, 502, "Resolve failed", peer=peer, host=host)
    try:
        # Connect to the address we vetted, not the name (no second resolution to rebind).
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(str(addrs[0]), 443), 15)
    except (OSError, asyncio.TimeoutError):
        return await refuse(writer, 502, "Upstream connect failed", peer=peer, host=host)
    log(decision="allow", peer=peer, host=host, addr=addrs[0])
    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await writer.drain()
    await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))


async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", LISTEN_PORT, limit=MAX_HEAD * 2)
    log(event="listening", port=LISTEN_PORT, exact=sorted(EXACT), suffixes=sorted(SUFFIXES))
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
