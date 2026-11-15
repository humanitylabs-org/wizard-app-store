"""Ciphertext-only HTTP relay. No SDK, body parsing, persistence or request logging.

Only HTTP framing is interpreted. Payload bytes are copied in bounded chunks;
read1/flush avoids waiting for a full buffer during encrypted response streams.
"""
import fcntl
import http.client
import ipaddress
import os
import re
import socket
import struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

POOL = ipaddress.ip_network('10.252.0.0/16')
CHUNK = 64 * 1024


def interface_networks():
    """Inspect actual IPv4 interface addresses/netmasks; no privileged tools needed.

    Re-evaluated on admission: the runtime attaches the relay network after start.
    Refuse broad interfaces which merely overlap the reserved pool.
    """
    networks = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _, name in socket.if_nameindex():
            request = struct.pack('256s', name.encode()[:15])
            try:
                addr = socket.inet_ntoa(fcntl.ioctl(sock, 0x8915, request)[20:24])
                mask = socket.inet_ntoa(fcntl.ioctl(sock, 0x891b, request)[20:24])
                network = ipaddress.ip_network(f'{addr}/{mask}', strict=False)
                if ipaddress.ip_address(addr) in POOL and network.prefixlen == 24 and network.subnet_of(POOL):
                    networks.append(network)
            except (OSError, ValueError):
                continue
    return networks


def peer_allowed(peer):
    try:
        address = ipaddress.ip_address(peer)
        return address.version == 4 and any(address in n for n in interface_networks())
    except ValueError:
        return False


def enclave_host(value):
    """Accept only a credential-free HTTPS Tinfoil origin on the standard port."""
    if not isinstance(value, str) or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        raise ValueError('Invalid origin')
    u = urlsplit(value)
    host = u.hostname or ''
    if (u.scheme != 'https' or u.username is not None or u.password is not None
            or u.port not in (None, 443) or u.path not in ('', '/')
            or '?' in value or '#' in value or not host.endswith('.tinfoil.sh')
            or len(host) > 253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in host.split('.'))):
        raise ValueError('Invalid origin')
    return host


class RelayServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        # A transport exception can contain headers or payload; never trace it.
        pass


def upstream_connection(host):
    """TLS stays end-to-end; http.client does not implement proxy env itself."""
    proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if not proxy:
        return http.client.HTTPSConnection(host, timeout=180)
    value = urlsplit(proxy)
    if (value.scheme != 'http' or not value.hostname or value.username is not None
            or value.password is not None or value.path not in ('', '/')
            or value.query or value.fragment):
        raise ValueError('Invalid HTTPS proxy')
    upstream = http.client.HTTPSConnection(value.hostname, value.port or 80, timeout=180)
    upstream.set_tunnel(host, 443)
    return upstream


def make_server(address, token_ok, connection, enabled=lambda: True):
    """enabled() is read on every request: off answers 404 to everyone, before any check or upstream call."""
    class RelayHandler(BaseHTTPRequestHandler):
        # HTTP/1.0 connection-close response framing also works for streams.
        def log_message(self, *args): pass

        def setup(self):
            super().setup()
            self.connection.settimeout(180)

        def reply(self, code, body=b''):
            self.close_connection = True
            self.send_response(code)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Connection', 'close')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def admitted(self):
            if not enabled():
                self.reply(404); return False
            if not peer_allowed(self.client_address[0]):
                self.reply(403); return False
            if self.command == 'GET' and self.path == '/healthz':
                self.reply(200, b'ok'); return False
            auth = self.headers.get_all('Authorization', [])
            if len(auth) != 1 or not auth[0].startswith('Bearer ') or not token_ok(auth[0][7:]):
                self.reply(401); return False
            return True

        def body_chunks(self):
            """Yield payload without decoding it, accepting CL or chunked framing."""
            lengths = self.headers.get_all('Content-Length', [])
            transfers = self.headers.get_all('Transfer-Encoding', [])
            if transfers:
                if lengths or len(transfers) != 1 or transfers[0].lower() != 'chunked':
                    raise ValueError('Ambiguous framing')
                while True:
                    line = self.rfile.readline(1024)
                    if not line.endswith(b'\r\n') or not re.fullmatch(b'[0-9a-fA-F]+\r\n', line):
                        raise ValueError('Invalid framing')
                    left = int(line.strip(), 16)
                    if not left:
                        if self.rfile.read(2) != b'\r\n': raise ValueError('Trailers not accepted')
                        break
                    while left:
                        chunk = self.rfile.read1(min(left, CHUNK))
                        if not chunk: raise ValueError('Truncated request')
                        left -= len(chunk)
                        yield chunk
                    if self.rfile.read(2) != b'\r\n': raise ValueError('Invalid framing')
            else:
                if len(lengths) != 1 or not re.fullmatch(r'[0-9]+', lengths[0]):
                    raise ValueError('Length required')
                left = int(lengths[0])
                while left:
                    chunk = self.rfile.read1(min(left, CHUNK))
                    if not chunk: raise ValueError('Truncated request')
                    left -= len(chunk)
                    yield chunk

        def do_GET(self):
            if not self.admitted(): return
            if self.path != '/attestation': return self.reply(404)
            # Default ATC GET may select an undeclared random router-N host.
            # Request the declared enclave; the client still verifies domain binding.
            self.forward('atc.tinfoil.sh', '/attestation', bundle=True)

        def do_POST(self):
            if not self.admitted(): return
            if not self.path.startswith('/v1/') or any(c in self.path for c in ('\r','\n','#')):
                return self.reply(404)
            try:
                origins = self.headers.get_all('X-Tinfoil-Enclave-Url', [])
                if len(origins) != 1: raise ValueError()
                host = enclave_host(origins[0])
                if not self.headers.get('Ehbp-Encapsulated-Key'): raise ValueError()
                lengths = self.headers.get_all('Content-Length', [])
                transfers = self.headers.get_all('Transfer-Encoding', [])
                if transfers:
                    if lengths or transfers != ['chunked']: raise ValueError()
                elif len(lengths) != 1 or not re.fullmatch(r'[0-9]+', lengths[0]):
                    raise ValueError()
            except ValueError:
                return self.reply(400)
            saved = connection()
            if not saved or not saved.get('key'): return self.reply(503)
            self.forward(host, self.path, saved['key'])

        def forward(self, host, path, key=None, bundle=False):
            upstream = upstream_connection(host)
            started = False
            self.close_connection = True
            try:
                bundle_body = b'{"enclaveUrl":"https://inference.tinfoil.sh","repo":"tinfoilsh/confidential-model-router"}'
                upstream.putrequest('POST' if bundle else self.command, path)
                upstream.putheader('Connection', 'close')
                for name in (() if bundle else ('Content-Type', 'Accept', 'Ehbp-Encapsulated-Key')):
                    values = self.headers.get_all(name, [])
                    if len(values) > 1: raise ValueError('Duplicate header')
                    if values: upstream.putheader(name, values[0])
                if key:
                    upstream.putheader('Authorization', 'Bearer '+key)
                    chunked = bool(self.headers.get('Transfer-Encoding'))
                    upstream.putheader('Transfer-Encoding' if chunked else 'Content-Length', 'chunked' if chunked else self.headers['Content-Length'])
                if bundle:
                    upstream.putheader('Content-Type', 'application/json')
                    upstream.putheader('Content-Length', str(len(bundle_body)))
                upstream.endheaders()
                if bundle:
                    upstream.send(bundle_body)
                if key:
                    for chunk in self.body_chunks():
                        if chunked: upstream.send(f'{len(chunk):x}\r\n'.encode())
                        upstream.send(chunk)
                        if chunked: upstream.send(b'\r\n')
                    if chunked: upstream.send(b'0\r\n\r\n')
                response = upstream.getresponse()
                # Never redirect a client or leak provider errors as local diagnostics.
                if 300 <= response.status < 400: return self.reply(502)
                self.send_response(response.status)
                for name, value in response.getheaders():
                    if name.lower() in ('content-type', 'content-encoding', 'ehbp-response-nonce'):
                        self.send_header(name, value)
                self.send_header('Connection', 'close')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                started = True
                while True:
                    chunk = response.read1(CHUNK)
                    if not chunk: break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except Exception:
                if not started:
                    self.reply(502)
                # Once streaming started, close on failure; never append diagnostics.
            finally:
                upstream.close()

    return RelayServer(address, RelayHandler)

