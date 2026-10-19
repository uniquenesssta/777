"""Offline cancellation survives restart and only closes the original package."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from p08_automatic.close_queue import CloseQueue

class CloseQueueTests(unittest.TestCase):
    def test_offline_close_reloads_and_retries_the_same_candidate_without_new_issuance(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);key='00000000-0000-4000-8000-000000000001'
            candidate=directory/(key+'.bin');candidate.write_bytes(b'protected-secret-material')
            issuer=types.SimpleNamespace(state=directory/'issuer.bin',native=Mock(side_effect=RuntimeError('CLUSTER_PRIMARY_UNREACHABLE_OR_CERTIFICATE_REJECTED')))
            with patch('p08_automatic.close_queue.diagnostics.event'),patch('p08_automatic.close_queue.diagnostics.failure'):
                q=CloseQueue(issuer,directory);q.enqueue(key);q.once(100)
                saved=json.loads(q.file.read_text());self.assertEqual(saved['pending'][0]['package_id'],key);self.assertNotIn('protected-secret-material',q.file.read_text())
                issuer.native.reset_mock(side_effect=True);issuer.native.return_value={'status':'closed'}
                resumed=CloseQueue(issuer,directory);resumed.once(101);issuer.native.assert_not_called()
                resumed.once(103)
                issuer.native.assert_called_once_with(['automatic-close','--state',str(issuer.state),'--candidate',str(candidate)],timeout=10)
                self.assertEqual(json.loads(q.file.read_text())['pending'],[])
                self.assertEqual(candidate.read_bytes(),b'protected-secret-material')

    def test_absent_unissued_candidate_needs_no_network_but_binding_failure_remains_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            issuer=types.SimpleNamespace(state=Path(temp)/'issuer.bin',native=Mock(side_effect=RuntimeError('PACKAGE_CLOSE_BINDING_CONFLICT')))
            key='00000000-0000-4000-8000-000000000002'
            with patch('p08_automatic.close_queue.diagnostics.event'),patch('p08_automatic.close_queue.diagnostics.failure'):
                q=CloseQueue(issuer,temp);q.enqueue(key);q.once(1);issuer.native.assert_not_called()
                (Path(temp)/(key+'.bin')).write_bytes(b'protected');q.enqueue(key);q.once(3)
                self.assertIn(key,CloseQueue(issuer,temp).rows)

if __name__=='__main__':unittest.main()
