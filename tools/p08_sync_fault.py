"""Fault injection in a stopped, owned source endpoint; never used on live hosts."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import ssl
import threading


class DamagedTransfer:
    def __init__(self, source):
        private = source.host_root / 'private/cluster'
        self.publication = json.loads((private / 'current.json').read_bytes())
        p = self.publication
        self.folder = private / 'generations' / f"{p['generation']:020}_{p['sha256']}"
        self.manifest = json.loads((self.folder / 'manifest.json').read_bytes())
        self.damage = True
        self.offsets = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path == '/v1/cluster/manifest':
                    value = dict(publication=fixture.publication, manifest=fixture.manifest)
                elif self.path == '/v1/cluster/chunk':
                    name, offset = data['name'], data['offset']
                    if name not in fixture.manifest['files']:
                        raise AssertionError('UNEXPECTED_FIXTURE_PATH')
                    fixture.offsets.append((name, offset))
                    raw = (fixture.folder / name).read_bytes()[offset:offset + 256 * 1024]
                    if fixture.damage and name == 'ledger.sqlite3' and raw:
                        raw = bytes([raw[0] ^ 1]) + raw[1:]
                    value = dict(generation=fixture.publication['generation'], manifest=fixture.publication['sha256'],
                                 offset=offset, sha256=fixture.manifest['files'][name]['sha256'], data=base64.b64encode(raw).decode())
                elif self.path == '/v1/cluster/ack':
                    value = dict(acknowledged=True, generation=fixture.publication['generation'])
                else:
                    raise AssertionError('UNEXPECTED_FIXTURE_ROUTE')
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(('127.0.0.1', source.port), Handler)
        self.server.daemon_threads = True
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(source.host_root / 'private/tls-cert.pem'), str(source.host_root / 'private/tls-key.pem'))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(10)

    def seed_partial(self, target):
        self.damage = False
        self.offsets.clear()
        entry = self.manifest['files']['ledger.sqlite3']
        raw = (self.folder / 'ledger.sqlite3').read_bytes()
        assert len(raw) > 4096 and hashlib.sha256(raw).hexdigest() == entry['sha256']
        cache = target.host_root / 'private/cluster/cache'
        cache.mkdir(exist_ok=True)
        (cache / (entry['sha256'] + '.partial')).write_bytes(raw[:4096])
        return entry
