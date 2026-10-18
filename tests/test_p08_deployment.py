import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deployment.host.policy import HOST_ORDER, local_root, require_local_host, choose_local_address
from deployment.host.prepare import prepare, write_new


class DeploymentPolicyTests(unittest.TestCase):
    def test_any_selected_local_ipv4_can_host_an_independent_service(self):
        for address in ('192.168.4.23', '192.168.4.38', '10.20.30.40'):
            require_local_host(address, [address])
            self.assertEqual(choose_local_address(None, ['127.0.0.1', address]), address)
        for address in ('192.168.4.23', 'bad-address', '0.0.0.0', '127.0.0.1', '224.0.0.1'):
            with self.assertRaises(ValueError):
                require_local_host(address, ['10.20.30.40'])
        with self.assertRaisesRegex(ValueError, 'ADDRESS_SELECTION'):
            choose_local_address(None, ['192.168.4.23', '192.168.4.38'])

    def test_host_root_and_evidence_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(ValueError):
                local_root(root, new=True)
            with self.assertRaises(ValueError):
                local_root(Path('relative'))
            path = root / 'record.json'
            write_new(path, {'ledger': 'existing'})
            write_new(path, {'ledger': 'existing'})
            with self.assertRaises(ValueError):
                write_new(path, {'ledger': 'different'})
            self.assertEqual(json.loads(path.read_text()), {'ledger': 'existing'})


class PreparationTests(unittest.TestCase):
    def test_failure_leaves_host_stopped_and_authenticated_configure_resumes_without_reinitializing(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            address = '10.20.30.40'
            root, backup, hidden = (base / n for n in ['host', 'backup', 'hidden'])
            calls = []
            fail = [True]
            site = {'addresses': [address], 'sid': 'synthetic-sid', 'account': 'synthetic-owner', 'machine': 'synthetic-machine'}

            def command(executable, args, secret=None):
                operation = args[0]
                calls.append(operation)
                if operation == 'init':
                    (root / 'private').mkdir(parents=True)
                    (root / 'private/rust-service-host.exe').write_bytes(b'MZsynthetic-resource')
                    (root / 'private/preserved-orders').write_bytes(b'orders-must-remain')
                    (root / 'private/service.json').write_text(json.dumps({'bind': address, 'port': 8477}))
                    (root / 'client-template.json').write_text(json.dumps({'url': 'https://synthetic:8477', 'certificate_sha256': 'a' * 64}))
                    (root / 'service-cert.pem').write_text('SYNTHETIC PUBLIC CERTIFICATE')
                if operation == 'configure-daily' and fail[0]:
                    fail[0] = False
                    raise ValueError('SYNTHETIC_BACKUP_UNAVAILABLE')
                if operation == 'inspect':
                    return {'shutdown_control': 'stdin-v1', 'inventory': {'ledger_id': '00000000-0000-0000-0000-000000000001'}, 'certificate_sha256': 'a' * 64}
                return {'status': 'ok'}

            with patch('deployment.host.prepare.collect', return_value=site), patch('deployment.host.prepare.native.resources', return_value=(base / 'host.exe', base / 'worker.exe')) as resources, patch('deployment.host.prepare.native.call', side_effect=command):
                with self.assertRaisesRegex(ValueError, 'BACKUP_UNAVAILABLE'):
                    prepare(root, backup, hidden, 'manager', 'synthetic-password')
                self.assertTrue((root / 'private/preserved-orders').exists())
                self.assertFalse((root / 'private/deployment.json').exists())
                result = prepare(root, backup, hidden, 'manager', 'synthetic-password', resume=True)
                self.assertEqual(result['status'], 'prepared_stopped')
                self.assertIsNone(result['source_commit'])  # Do not invent provenance for an existing host.
                self.assertEqual(calls.count('init'), 1)
                self.assertIn('authorize', calls)
                self.assertEqual(resources.call_count, 1)
                self.assertEqual((root / 'private/preserved-orders').read_bytes(), b'orders-must-remain')
                saved = json.loads((root / 'private/deployment.json').read_text())
                self.assertEqual(saved['owner_sid'], site['sid'])
                self.assertEqual(saved['replication'], 'not_implemented')
                self.assertEqual(saved['active_address'], address)
                self.assertEqual(saved['host_order'], [address])
                self.assertEqual(saved['deployment_mode'], 'standalone')
                self.assertNotIn('synthetic-password', json.dumps(saved))
                self.assertFalse((root / 'private/stop.request').exists())

    def test_nonlocal_address_and_overlapping_backup_fail_before_build_or_init(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'host'
            site = {'addresses': list(HOST_ORDER)}
            with patch('deployment.host.prepare.collect', return_value=site), patch('deployment.host.prepare.native.resources') as build:
                with self.assertRaisesRegex(ValueError, 'MUST_RUN_ON_SELECTED_HOST'):
                    prepare(root, Path(folder) / 'b', Path(folder) / 'h', 'manager', 'synthetic', address='192.0.2.199')
                with self.assertRaisesRegex(ValueError, 'SEPARATE'):
                    prepare(root, root / 'backups', Path(folder) / 'h', 'manager', 'synthetic', address=HOST_ORDER[0])
                with self.assertRaisesRegex(ValueError, 'ABSOLUTE_BACKUP'):
                    prepare(root, Path('relative'), Path(folder) / 'h', 'manager', 'synthetic', address=HOST_ORDER[0])
                build.assert_not_called()
                self.assertFalse(root.exists())


if __name__ == '__main__':
    unittest.main()
