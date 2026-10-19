"""Pinned, proxy-free loopback HTTPS with explicit accepted status codes."""
import hashlib
import http.client
import json
import ssl
import time
from quote_service.protocol import APIError


class PinnedAPI:
    def __init__(self,host):
        self.host=host

    def call(self, path, body, *, token, accepted=(200, 202), method='POST'):
        deadline = time.monotonic() + 10
        while True:
            context = ssl.create_default_context(cafile=str(self.host.host_root / 'service-cert.pem'))
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            connection = http.client.HTTPSConnection('127.0.0.1', self.host.port, context=context, timeout=10)
            try:
                connection.connect()
                assert hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest() == self.host.config['certificate_sha256']
                self.tls_version = connection.sock.version()
                connection.request(method, path, body=None if body is None else json.dumps(body).encode(),
                                   headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
                response = connection.getresponse()
                value = json.loads(response.read(1048577))
                self.last_status = response.status
                if response.status == 429 and time.monotonic() < deadline:
                    time.sleep(.51)
                    continue
                if response.status not in accepted:
                    raise APIError(response.status, value.get('error', 'UNEXPECTED_RESPONSE'))
                return value
            finally:
                connection.close()
