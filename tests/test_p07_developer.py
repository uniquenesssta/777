"""Owned developer control: directory isolation, failed switch recovery and private HTTP."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from p07_developer import Developer, local


class DeveloperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.devdir = self.base / 'development'
        self.devdir.mkdir()
        self.a = self.host(self.devdir / 'host', 'a')
        self.dev = SimpleNamespace(DEV=self.devdir, ROOT=ROOT, PORT=18477, command=Mock(), stop_host=Mock())
        self.initial_process = object()
        self.operator = Developer(self.dev, self.a, self.initial_process)
        self.operator.upgrade = Mock()

    def host(self, root, key):
        (root / 'private').mkdir(parents=True)
        backup = root.parent / (root.name + '-backups')
        backup.mkdir()
        (backup / '777-backups.json').write_text(json.dumps(dict(last_success=None)))
        cfg = dict(bind='127.0.0.1', port=18477, maintenance=False, ledger_id=key, certificate_sha256=key * 64, backup_dir=str(backup))
        (root / 'private/service.json').write_text(json.dumps(cfg))
        (root / 'service-cert.pem').write_text('isolated certificate')
        return root

    def test_unknown_existing_root_requires_credentials_before_stopping_current_service(self):
        b = self.host(self.base / 'B 中文', 'b')
        with self.assertRaisesRegex(RuntimeError, 'DEVELOPER_CREDENTIAL_REQUIRED'):
            self.operator.select(str(b))
        self.dev.stop_host.assert_not_called()
        self.assertEqual(self.operator.root, self.a)

    def test_authentication_failure_preserves_running_service_and_configuration(self):
        b = self.host(self.base / 'B', 'b')
        self.dev.command.side_effect = RuntimeError('INVALID_CREDENTIALS')
        with self.assertRaisesRegex(RuntimeError, 'INVALID_CREDENTIALS'):
            self.operator.select(str(b), username='admin', password='wrong-password')
        self.dev.stop_host.assert_not_called()
        self.assertFalse(self.operator.preferences_file.exists())

    def test_failed_new_service_start_restores_previous_owned_service(self):
        b = self.host(self.base / 'B', 'b')
        restored = object()
        with patch.object(self.operator, 'start', side_effect=[RuntimeError('START_FAILED'), restored]):
            with self.assertRaisesRegex(RuntimeError, 'START_FAILED'):
                self.operator.select(str(b), username='admin', password='correct-secret')
        self.assertEqual(self.operator.root, self.a)
        self.assertIs(self.operator.process, restored)
        self.assertEqual(self.operator.preferences['root'], str(self.a))
        self.assertFalse(self.operator.preferences_file.exists())

    def test_successful_switch_remembers_encrypted_credentials_and_explicit_root(self):
        b = self.host(self.base / 'B 中文', 'b')
        with patch.object(self.operator, 'start', return_value=object()):
            state = self.operator.select(str(b), username='admin', password='correct-secret')
        self.assertEqual(state['ledger_id'], 'b')
        self.assertNotIn('password', json.dumps(state))
        self.assertNotIn('correct-secret', self.operator.preferences_file.read_text())
        if os.name == 'nt':self.assertNotIn(b'correct-secret', self.operator.credentials_file.read_bytes())
        loaded = Developer(self.dev, self.a, object())
        self.assertEqual(loaded.preferences['root'], str(b))
        self.assertEqual(loaded.credentials[str(b)]['password'], 'correct-secret')

    def test_initialization_never_overwrites_unknown_directory(self):
        target = self.base / 'existing'; target.mkdir()
        original = target / 'keep.txt'; original.write_bytes(b'original')
        with self.assertRaisesRegex(RuntimeError, 'DEVELOPER_EMPTY_DIRECTORY_REQUIRED'):
            self.operator.select(str(target), initialize=True, backup_dir=str(self.base / 'backups'))
        self.assertEqual(original.read_bytes(), b'original')
        self.dev.command.assert_not_called()
        self.dev.stop_host.assert_not_called()

    def test_configuration_is_persistent_and_invalid_version_keeps_previous(self):
        self.operator.handle(dict(op='save_package', output=str(self.base / 'packages'), version='1.2.3', runtime='offlineInstaller'))
        before = self.operator.preferences_file.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'DEVELOPER_PACKAGE_CONFIG_INVALID'):
            self.operator.handle(dict(op='save_package', output=str(self.base / 'packages'), version='../../bad', runtime='offlineInstaller'))
        self.assertEqual(before, self.operator.preferences_file.read_bytes())

    def test_live_build_prevents_data_source_switch(self):
        self.operator.job = dict(state='running')
        with self.assertRaisesRegex(RuntimeError, 'DEVELOPER_BUILD_BUSY'):
            self.operator.select(str(self.base / 'B'))
        self.dev.stop_host.assert_not_called()

    def test_control_rejects_missing_token_and_browser_origin(self):
        old = {key:os.environ.get(key) for key in ['QUOTE777_DEVELOPER_PORT','QUOTE777_DEVELOPER_TOKEN']}
        self.operator.serve()
        def cleanup():
            self.operator.close()
            for key,value in old.items():
                if value is None:os.environ.pop(key,None)
                else:os.environ[key]=value
        self.addCleanup(cleanup)
        url = f'http://127.0.0.1:{self.operator.server.server_port}/control'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for headers in [{}, {'Authorization':'Bearer '+self.operator.token, 'Origin':'http://127.0.0.1:29346'}]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                opener.open(urllib.request.Request(url,data=b'{"op":"status"}',headers=headers),timeout=5)
            self.assertEqual(caught.exception.code,403)
        with opener.open(urllib.request.Request(url,data=b'{"op":"status"}',headers={'Authorization':'Bearer '+self.operator.token}),timeout=5) as response:
            state=json.load(response)['value']
        self.assertEqual(state['root'],str(self.a))
        self.assertNotIn('password',json.dumps(state))

    @unittest.skipIf(os.name=='nt','Windows reparse points covered by Windows native path boundary')
    def test_symlink_path_rejected_before_any_command(self):
        alias=self.base/'alias';alias.symlink_to(self.a,target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,'DEVELOPER_PATH_REPARSE_POINT'):local(alias)


if __name__ == '__main__':unittest.main()
