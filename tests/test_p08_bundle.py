import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from deployment.bundle.archive import assemble, PORTABLE, LIFECYCLE

ROOT = Path(__file__).resolve().parents[1]


def fixture(base):
    source = base / 'source'
    (source / 'deployment/windows/portable').mkdir(parents=True)
    (source / 'deployment/bundle').mkdir(parents=True)
    (source / 'THIRD_PARTY_NOTICES.md').write_text('synthetic notices')
    (source / 'deployment/bundle/README.txt').write_text('synthetic README')
    for name in PORTABLE:
        (source / 'deployment/windows/portable' / name).write_bytes((ROOT / 'deployment/windows/portable' / name).read_bytes())
    for name in LIFECYCLE:
        (source / 'deployment/windows' / name).write_bytes((ROOT / 'deployment/windows' / name).read_bytes())
    (source / 'private').mkdir()
    (source / 'private/password.txt').write_text('DO-NOT-PACK')
    host, worker = base / 'host.exe', base / 'worker.exe'
    host.write_bytes(b'MZsynthetic-host'); worker.write_bytes(b'MZsynthetic-worker')
    return source, host, worker


class HostBundleTests(unittest.TestCase):
    def test_host_only_archive_has_exact_resources_and_matching_hashes_without_development_data(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); source, host, worker = fixture(base)
            result = assemble(source, base / 'bundle', host, worker, 'a' * 40)
            with zipfile.ZipFile(result['archive']) as zipped:
                names = zipped.namelist()
                manifest = json.loads(zipped.read('Quote777Host/host-package.json'))
                self.assertEqual(set(names), {'Quote777Host/' + name for name in manifest['files']} | {'Quote777Host/host-package.json'})
                for name, expected in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(zipped.read('Quote777Host/' + name)).hexdigest(), expected)
                self.assertFalse(any(name.endswith(('.py', '.mjs', '.sqlite3')) or '/private/' in name for name in names))
                self.assertNotIn(b'DO-NOT-PACK', b''.join(zipped.read(name) for name in names))
                self.assertEqual(manifest['replication'], 'not_implemented_standby_must_not_write')

    def test_unknown_existing_output_and_non_windows_resources_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); source, host, worker = fixture(base)
            existing = base / 'existing'; existing.mkdir(); sentinel = existing / 'keep'; sentinel.write_bytes(b'keep')
            with self.assertRaisesRegex(ValueError, 'NEW_ABSOLUTE'):
                assemble(source, existing, host, worker, 'a' * 40)
            self.assertEqual(sentinel.read_bytes(), b'keep')
            host.write_bytes(b'ELF-not-windows')
            with self.assertRaisesRegex(ValueError, 'WINDOWS_HOST_RESOURCE'):
                assemble(source, base / 'uncreated', host, worker, 'a' * 40)
            self.assertFalse((base / 'uncreated').exists())


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell 5.1 execution requires Windows')
class PortableWindowsTests(unittest.TestCase):
    def test_native_child_keeps_password_only_on_utf8_stdin_and_quotes_arguments(self):
        shell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            child = base / 'child.ps1'
            child.write_text(r'''[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
$raw=[Console]::In.ReadToEnd()
$hash=$null
if ($raw.Trim()) {
    $password=($raw | ConvertFrom-Json).password
    $sha=[Security.Cryptography.SHA256]::Create()
    try { $hash=([BitConverter]::ToString($sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($password)))).Replace('-','').ToLowerInvariant() } finally { $sha.Dispose() }
}
@{password_sha256=$hash;arguments=@($args)} | ConvertTo-Json -Compress
''', encoding='utf-8')
            harness = base / 'caller.ps1'
            harness.write_text(r'''param([string] $Modules,[string] $Child,[string] $Shell)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
. (Join-Path $Modules 'host-log.ps1')
. (Join-Path $Modules 'host-native.ps1')
$value=[Console]::In.ReadToEnd() | ConvertFrom-Json
Invoke-HostProcess $Shell @('-NoProfile','-ExecutionPolicy','Bypass','-File',$Child,'value with spaces','tail\') $value.password
''', encoding='utf-8')
            for secret in ['Synthetic-中文-quote"-tail\\', None]:
                result = subprocess.run([shell,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(harness),'-Modules',str(ROOT / 'deployment/windows/portable'),'-Child',str(child),'-Shell',shell], input=json.dumps({'password':secret}), capture_output=True, text=True, encoding='utf-8', timeout=45)
                self.assertEqual(result.returncode,0,result.stderr)
                value = json.loads(result.stdout)
                self.assertEqual(value['password_sha256'], hashlib.sha256(secret.encode()).hexdigest() if secret is not None else None)
                self.assertEqual(value['arguments'], ['value with spaces','tail\\'] + (['--secret-stdin'] if secret is not None else []))
                if secret is not None: self.assertNotIn(secret, result.stdout + result.stderr)

    def test_inventory_works_with_no_developer_commands_and_tampering_or_wrong_host_cannot_initialize(self):
        shell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); source, host, worker = fixture(base)
            assemble(source, base / 'bundle', host, worker, 'a' * 40)
            bundle = base / 'bundle/Quote777Host'
            env = {**os.environ, 'PATH': str(Path(os.environ['SystemRoot']) / 'System32')}
            result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(bundle / 'host.ps1')], capture_output=True, text=True, encoding='utf-8', env=env, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['schema'], '777-site-inventory-v1')
            self.assertEqual(len(list((bundle / 'logs').glob('*/runtime.jsonl'))), 1)
            for address in ('192.168.4.38', '192.0.2.199'):
                wrong = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(bundle / 'host.ps1'), '-Operation', 'prepare', '-Address', address, '-Root', str(base / 'must-not-exist')], capture_output=True, text=True, encoding='utf-8', env=env, timeout=45)
                self.assertNotEqual(wrong.returncode, 0)
                self.assertRegex(wrong.stderr, 'DEPLOYMENT_MUST_RUN_ON_SELECTED_HOST|STANDBY_REPLICATION_NOT_IMPLEMENTED')
                self.assertFalse((base / 'must-not-exist').exists())
            with (bundle / 'bin/quote-host.exe').open('ab') as stream: stream.write(b'changed')
            changed = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(bundle / 'host.ps1')], capture_output=True, text=True, encoding='utf-8', env=env, timeout=45)
            self.assertNotEqual(changed.returncode, 0)
            self.assertIn('HOST_PACKAGE_RESOURCE_CHANGED', changed.stderr)


if __name__ == '__main__':
    unittest.main()
