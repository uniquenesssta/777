"""Local controller boundary only; cryptography and registration have native tests."""
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from p08_automatic import local_signer

class LocalSignerTests(unittest.TestCase):
    def test_only_public_local_status_crosses_bridge_and_no_legacy_authorization_command_is_called(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            signer=local_signer.LocalSigner(types.SimpleNamespace(dev=types.SimpleNamespace(DEV=root,ROOT=root)))
            with patch.object(local_signer,'os',types.SimpleNamespace(name='nt')), patch.object(signer,'native',return_value=dict(ready=True,phase='local_ready',issuer_id='public-id',signing_key='must-not-cross',profile={'private':'must-not-cross'})) as native:
                status=signer.status()
            self.assertTrue(status['ready'])
            self.assertNotIn('signing_key',status);self.assertNotIn('profile',status)
            native.assert_called_once_with(['automatic-local-status','--state',str(root/'local-signer.bin')])

    def test_corrupt_identity_is_preserved_and_cannot_be_reported_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            signer=local_signer.LocalSigner(types.SimpleNamespace(dev=types.SimpleNamespace(DEV=root,ROOT=root)))
            signer.state.write_bytes(b'original-protected-material')
            with patch.object(local_signer,'os',types.SimpleNamespace(name='nt')),patch.object(signer,'native',side_effect=RuntimeError('DPAPI_UNPROTECT_FAILED')):
                status=signer.status()
            self.assertFalse(status['ready'])
            self.assertEqual(status['error'],'DPAPI_UNPROTECT_FAILED')
            self.assertEqual(signer.state.read_bytes(),b'original-protected-material')
