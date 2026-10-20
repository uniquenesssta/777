"""Issuer retries preserve existing preparation; no installer or remote host runs."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from p08_automatic import issuer


class IssuerRecoveryTests(unittest.TestCase):
    def test_status_failure_is_not_a_new_preparation_and_cannot_replace_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            controller = issuer.Issuer(types.SimpleNamespace(dev=types.SimpleNamespace(DEV=root, ROOT=root)))
            controller.state.write_bytes(b'protected-state')
            with patch.object(issuer, 'os', types.SimpleNamespace(name='nt')), patch.object(controller, 'native', side_effect=RuntimeError('DPAPI_UNPROTECT_FAILED')):
                status = controller.status(refresh=True)
                self.assertEqual(status['phase'], 'unavailable')
                self.assertEqual(status['error'], 'DPAPI_UNPROTECT_FAILED')
                with self.assertRaisesRegex(RuntimeError, 'DPAPI_UNPROTECT_FAILED'):
                    controller.prepare(None, restart=True)
            self.assertEqual(controller.state.read_bytes(), b'protected-state')

    def test_opening_pending_kit_preserves_identity_without_preparing_again(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            controller = issuer.Issuer(types.SimpleNamespace(dev=types.SimpleNamespace(DEV=root, ROOT=root)))
            kit = root/'Quote777Upgrade-existing'
            kit.mkdir()
            controller.location.write_text(json.dumps(dict(directory=str(kit))))
            controller.state.write_bytes(b'protected-state')
            native = Mock()
            start = Mock()
            with patch.object(issuer, 'os', types.SimpleNamespace(name='nt', startfile=start)), patch.object(controller, 'native', native), patch.object(controller, 'status', return_value=dict(ready=False, phase='pending', interfaces=['192.0.2.2'])):
                controller.prepare(None)
            native.assert_not_called()
            start.assert_called_once_with(str(kit))
            self.assertEqual(controller.state.read_bytes(), b'protected-state')


if __name__ == '__main__':
    unittest.main()
