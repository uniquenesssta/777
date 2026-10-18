"""Convert a public Host connection into the existing pinned operator client configuration."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import ssl
import tempfile
from quote_service.client import connection_settings


@contextmanager
def operator_connection(path, username):
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('CONNECTION_FILE_TOO_LARGE')
    value = json.loads(raw.decode('utf-8-sig'))
    if value.get('schema') == '777-service-client-v1':
        yield connection_settings(value)
        return
    if set(value) != {'schema', 'connection'} or value['schema'] != '777-public-connection-v1':
        raise ValueError('PUBLIC_CONNECTION_REQUIRED')
    public = value['connection']
    if set(public) != {'url', 'certificate_pem', 'certificate_sha256'}:
        raise ValueError('PUBLIC_CONNECTION_REQUIRED')
    pem = public['certificate_pem']
    if not isinstance(pem, str) or pem.count('BEGIN CERTIFICATE') != 1 or 'PRIVATE KEY' in pem:
        raise ValueError('PUBLIC_CERTIFICATE_REQUIRED')
    if hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() != public['certificate_sha256']:
        raise ValueError('CERTIFICATE_PIN_MISMATCH')
    with tempfile.TemporaryDirectory(prefix='777-public-cert-') as owned:
        certificate = Path(owned) / 'service.pem'
        certificate.write_text(pem, encoding='ascii')
        yield connection_settings(dict(schema='777-service-client-v1', url=public['url'],
                                       certificate=str(certificate), certificate_sha256=public['certificate_sha256'], username=username))
