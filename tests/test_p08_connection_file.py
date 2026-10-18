"""Public operator connection parsing; contains only synthetic certificates."""
import hashlib
import json
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from p08_connection_file import operator_connection

class PublicConnectionTests(unittest.TestCase):
    def test_public_connection_uses_temporary_certificate_and_rejects_private_kind(self):
        pem=(ROOT/'desktop/tests/fixtures/service-cert.pem').read_text()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'connection.json'
            public=dict(schema='777-public-connection-v1',connection=dict(url='https://localhost:18477',certificate_pem=pem,certificate_sha256=hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()))
            path.write_text(json.dumps(public))
            with operator_connection(path,'manager') as value:
                self.assertEqual(value['url'],public['connection']['url'])
                certificate=Path(value['certificate']);self.assertTrue(certificate.exists())
                self.assertNotIn('password',value)
            self.assertFalse(certificate.exists())
            public['schema']='777-desktop-bootstrap-v1';public['ticket']='not-public'
            path.write_text(json.dumps(public))
            with self.assertRaisesRegex(ValueError,'PUBLIC_CONNECTION_REQUIRED'):
                with operator_connection(path,'manager'):pass
