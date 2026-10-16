"""Execute the shipped enrollment script in Windows PowerShell, without Get-FileHash.

Files are synthetic fixtures, not installers, DPAPI identities or business data.
Real package install/auth/upgrade/rollback remains p07_package_check.py's gate.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'desktop/tools/enroll.ps1'


@unittest.skipUnless(os.name == 'nt', 'requires built-in Windows PowerShell; no simulated enrollment pass')
class WindowsEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='777-p07-enrollment-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.local = self.root / 'local-app-data'
        self.wrapper = self.root / 'without-filehash.ps1'
        self.wrapper.write_text(
            "param([string]$Script, [string]$Release, [string]$Grant)\n"
            "$ErrorActionPreference = 'Stop'\n"
            "function Get-FileHash { throw 'GET_FILE_HASH_UNAVAILABLE_IN_REGRESSION' }\n"
            "& $Script -ReleaseDirectory $Release -GrantFile $Grant\n",
            encoding='utf-8')

    def fixture(self, delivery):
        release = self.root / delivery / 'release'
        release.mkdir(parents=True)
        shutil.copyfile(SCRIPT, release / 'enroll.ps1')
        pem = (ROOT / 'desktop/tests/fixtures/service-cert.pem').read_text(encoding='utf-8')
        connection = {'url': 'https://localhost:18477', 'certificate_pem': pem,
                      'certificate_sha256': hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()}
        public = {'schema': '777-public-connection-v1', 'connection': connection}
        (release / 'connection.json').write_text(json.dumps(public), encoding='utf-8')
        binary = release / f'quote777-{delivery}.exe'
        binary.write_bytes(b'synthetic executable fixture, not runnable')
        (release / 'synthetic-setup.exe').write_bytes(b'synthetic installer fixture, not runnable')
        (release / 'empty-notice.txt').write_bytes(b'')
        manifest = {'schema': '777-desktop-release-v1', 'delivery': delivery,
                    'identifier': f'cn.uniqueness.quote777.{delivery}', 'version': '0.1.0',
                    'profile_compatibility_epoch': 1, 'service_protocol': '777-service-v1',
                    'device_protocol': '777-device-auth-v1', 'release': True, 'verification': False,
                    'installer': 'synthetic-setup.exe', 'files': []}
        for file in sorted(release.iterdir()):
            raw = file.read_bytes()
            manifest['files'].append({'name': file.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        (release / 'release.json').write_text(json.dumps(manifest), encoding='utf-8')
        grant = {'schema': '777-desktop-bootstrap-v1', 'delivery': delivery, 'connection': connection, 'ticket': 'a' * 43}
        grant_file = release.parent / 'private-grant.json'
        grant_file.write_text(json.dumps(grant), encoding='utf-8')
        profile = self.local / 'cn.uniqueness.quote777' / delivery
        return release, grant_file, profile, grant, binary

    def execute(self, release, grant_file):
        return subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
             '-File', str(self.wrapper), '-Script', str(release / 'enroll.ps1'),
             '-Release', str(release), '-Grant', str(grant_file)],
            env=dict(os.environ, LOCALAPPDATA=str(self.local)), capture_output=True, timeout=30)

    def assert_rejected(self, result, error):
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(error.encode(), result.stderr)
        self.assertNotIn(b'a' * 43, result.stdout + result.stderr)
        self.assertNotIn(b'synthetic-secret-must-not-be-copied', result.stdout + result.stderr)

    def test_both_roles_enroll_without_hash_cmdlet_and_preserve_existing_profile_files(self):
        for delivery in ('manager', 'sales'):
            with self.subTest(delivery=delivery):
                release, grant_file, profile, grant, _ = self.fixture(delivery)
                profile.mkdir(parents=True)
                originals = {'device.bin': b'synthetic-device', 'pending.bin': b'synthetic-pending',
                             'webview2/draft-probe.txt': b'synthetic-draft-probe'}
                for name, raw in originals.items():
                    file = profile / name
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(raw)
                result = self.execute(release, grant_file)
                self.assertEqual(result.returncode, 0, result.stderr)
                raw = (profile / 'bootstrap.json').read_bytes()
                self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
                self.assertEqual(json.loads(raw), grant)
                for name, original in originals.items():
                    self.assertEqual((profile / name).read_bytes(), original)
                self.assertNotIn(grant['ticket'].encode(), result.stdout + result.stderr)

    def test_same_size_tampering_still_fails_sha256_before_writing_bootstrap(self):
        for delivery in ('manager', 'sales'):
            with self.subTest(delivery=delivery):
                release, grant_file, profile, _, binary = self.fixture(delivery)
                raw = binary.read_bytes()
                binary.write_bytes(b'X' + raw[1:])
                self.assert_rejected(self.execute(release, grant_file), 'RELEASE_HASH_MISMATCH')
                self.assertFalse((profile / 'bootstrap.json').exists())

    def test_wrong_role_service_or_extra_secret_is_rejected_before_writing(self):
        for delivery in ('manager', 'sales'):
            release, grant_file, profile, grant, _ = self.fixture(delivery)
            for kind, error in [('role', 'ENROLLMENT_ROLE_OR_TICKET_INVALID'),
                                ('service', 'ENROLLMENT_SERVICE_CONFLICT'),
                                ('password', 'ENROLLMENT_FIELDS_NOT_ALLOWED')]:
                with self.subTest(delivery=delivery, conflict=kind):
                    altered = deepcopy(grant)
                    if kind == 'role':
                        altered['delivery'] = 'sales' if delivery == 'manager' else 'manager'
                    elif kind == 'service':
                        altered['connection']['url'] = 'https://localhost:18478'
                    else:
                        altered['password'] = 'synthetic-secret-must-not-be-copied'
                    grant_file.write_text(json.dumps(altered), encoding='utf-8')
                    self.assert_rejected(self.execute(release, grant_file), error)
                    self.assertFalse((profile / 'bootstrap.json').exists())

    def test_existing_bootstrap_is_not_overwritten(self):
        for delivery in ('manager', 'sales'):
            with self.subTest(delivery=delivery):
                release, grant_file, profile, _, _ = self.fixture(delivery)
                profile.mkdir(parents=True)
                bootstrap = profile / 'bootstrap.json'
                bootstrap.write_bytes(b'original-bootstrap')
                result = self.execute(release, grant_file)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b'GET_FILE_HASH_UNAVAILABLE_IN_REGRESSION', result.stderr)
                self.assertEqual(bootstrap.read_bytes(), b'original-bootstrap')


if __name__ == '__main__':
    unittest.main()
