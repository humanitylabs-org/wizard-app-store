"""TEST ONLY: captures ciphertext; never deploy this relay with capture enabled."""
import hmac
import http.client
import ipaddress
import json
import os
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

TOKEN = os.environ['RELAY_TOKEN']
KEY = os.environ.get('TINFOIL_API_KEY', '')
CAPTURE = os.environ.get('CAPTURE_FILE', '/capture/requests.bin')
MODE_FILE = os.environ.get('MODE_FILE', '/capture/mode')
LOCK = threading.Lock()


def mode():
    try:
        with open(MODE_FILE) as file:
            return file.read().strip()
    except FileNotFoundError:
        return 'normal'


class Relay(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, format, *args):
        pass

    def reply(self, status, body=b'', content_type='application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if ipaddress.ip_address(self.client_address[0]) not in ipaddress.ip_network('10.252.0.0/16'):
            self.reply(403)
            return False
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN):
            self.reply(401)
            return False
        return True

    def do_GET(self):
        if self.path == '/healthz':
            self.reply(200, b'ok', 'text/plain')
            return
        if not self.authorized():
            return
        if self.path == '/attestation':
            connection = http.client.HTTPSConnection('atc.tinfoil.sh', timeout=60)
            try:
                connection.request('GET', '/attestation')
                response = connection.getresponse()
                data = response.read()
                if response.status == 200 and mode() == 'tampered':
                    bundle = json.loads(data)
                    bundle['digest'] = '0' * 64
                    data = json.dumps(bundle).encode()
                elif response.status == 200 and mode() == 'wrong-domain':
                    bundle = json.loads(data)
                    bundle['domain'] = 'wrong-enclave.tinfoil.sh'
                    data = json.dumps(bundle).encode()
                self.reply(response.status, data)
            except Exception:
                self.reply(502)
            finally:
                connection.close()
        elif self.path == '/v1/models':
            self.reply(200, b'{"object":"list","data":[{"id":"mock-local","object":"model"}]}')
        else:
            self.reply(404)

    def body_chunks(self):
        if self.headers.get('Transfer-Encoding', '').lower() == 'chunked':
            while True:
                line = self.rfile.readline(1024)
                length = int(line.split(b';')[0], 16)
                if not length:
                    while self.rfile.readline(1024) not in (b'\r\n', b'\n', b''):
                        pass
                    break
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(65536, remaining))
                    if not chunk:
                        raise ConnectionError('Truncated request')
                    remaining -= len(chunk)
                    yield chunk
                if self.rfile.read(2) != b'\r\n':
                    raise ValueError('Invalid chunk delimiter')
        else:
            remaining = int(self.headers.get('Content-Length', '0'))
            while remaining:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    raise ConnectionError('Truncated request')
                remaining -= len(chunk)
                yield chunk

    def do_POST(self):
        if not self.authorized():
            self.close_connection = True
            return
        if self.path == '/v1/chat/completions' and mode() == 'mock':
            body = b''.join(self.body_chunks())
            request = json.loads(body)
            if request.get('stream'):
                self.reply(200, b'data: {"choices":[{"delta":{"content":"mock-ok"}}]}\n\ndata: [DONE]\n\n', 'text/event-stream')
            else:
                self.reply(200, b'{"choices":[{"message":{"content":"mock-ok"}}]}')
            return
        if not self.path.startswith('/v1/') or '?' in self.path:
            self.reply(404)
            self.close_connection = True
            return
        target = urlsplit(self.headers.get('X-Tinfoil-Enclave-Url', ''))
        if target.scheme != 'https' or not target.hostname or not target.hostname.endswith('.tinfoil.sh') or target.port not in (None, 443) or target.username or target.password or target.query or target.fragment or target.path not in ('', '/'):
            self.reply(400)
            self.close_connection = True
            return
        headers = {'Authorization': 'Bearer ' + KEY, 'Content-Type': self.headers.get('Content-Type', 'application/json')}
        encapsulated = self.headers.get('Ehbp-Encapsulated-Key')
        if encapsulated:
            headers['Ehbp-Encapsulated-Key'] = encapsulated
        host = 'wrong-enclave.tinfoil.sh' if mode() == 'wrong-enclave' else target.hostname
        connection = http.client.HTTPSConnection(host, timeout=90, context=ssl.create_default_context())
        response_started = False
        try:
            # Capture header names/key ciphertext and exactly the bytes sent upstream.
            # Never capture auth headers (either relay token or provider key).
            with LOCK, open(CAPTURE, 'ab', buffering=0) as capture:
                capture.write(('\nPOST ' + self.path + '\nEhbp-Encapsulated-Key: ' + (encapsulated or 'MISSING') + '\n\n').encode())

                def chunks():
                    for chunk in self.body_chunks():
                        capture.write(chunk)
                        yield chunk

                connection.request('POST', self.path, body=chunks(), headers=headers, encode_chunked=True)
            response = connection.getresponse()
            self.send_response(response.status)
            for name in ('Content-Type', 'Ehbp-Response-Nonce'):
                value = response.getheader(name)
                if value:
                    self.send_header(name, value)
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            response_started = True
            while True:
                data = response.read1(65536)
                if not data:
                    break
                self.wfile.write(f'{len(data):x}\r\n'.encode() + data + b'\r\n')
                self.wfile.flush()
            self.wfile.write(b'0\r\n\r\n')
            self.wfile.flush()
        except Exception:
            if not response_started:
                self.reply(502)
            else:
                self.close_connection = True
        finally:
            connection.close()


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8090), Relay).serve_forever()
