"""Windows-only real native preparation through the SDK-free PowerShell bundle modules."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from deployment.bundle.archive import assemble
from p01_validation import new_output

HARNESS = r'''
param([string] $Directory, [string] $Root, [string] $Backup, [string] $Hidden)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
foreach ($name in @('host-identity.ps1','host-log.ps1','host-package.ps1','host-site.ps1','host-paths.ps1','host-native.ps1','host-prepare.ps1')) { . (Join-Path $Directory ('scripts\' + $name)) }
Start-HostLog $Directory
$secret=([Console]::In.ReadToEnd() | ConvertFrom-Json).password
$site=Get-LocalHostInventory
# Synthetic local fixture: no binding, task registration or LAN access is performed.
$site.addresses=@('192.168.4.23')
$bundle=Get-HostBundle $Directory
if (@(Get-Command git,node,python,cargo -ErrorAction SilentlyContinue).Count) { throw 'SDK_COMMANDS_PRESENT_IN_RESTRICTED_TEST_PATH' }
$first=Invoke-HostPreparation $site $bundle $Directory $Root $Backup $Hidden 'manager' $secret '192.168.4.23' 8477 23 $false
$again=Invoke-HostPreparation $site $bundle $Directory $Root $Backup $Hidden 'manager' $secret '192.168.4.23' 8477 23 $true
if ($first.ledger_id -ne $again.ledger_id) { throw 'RETRY_CHANGED_LEDGER' }
$check=Invoke-HostNative (Join-Path $again.root 'private\rust-service-host.exe') @('inspect','--root',$again.root)
if ($check.shutdown_control -ne 'stdin-v1') { throw 'NATIVE_SHUTDOWN_CAPABILITY_MISSING' }
@{status='passed';ledger_id=$again.ledger_id;root=$again.root;source_commit=$again.source_commit} | ConvertTo-Json -Compress
$secret=$null
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This check requires actual Windows; no auxiliary acceptance is substituted')
    output = new_output(args.output)
    report = {'task': 'P08-02', 'scope': 'synthetic_real_native_portable_bundle', 'status': 'failed',
              'live_hosts_contacted': False, 'startup_registered': False, 'installers_built': False}
    try:
        with tempfile.TemporaryDirectory(prefix='777-portable-') as folder:
            base = Path(folder)
            commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
            assemble(ROOT, base / 'bundle', ROOT / 'target/release/quote-host.exe', ROOT / 'target/release/quote-ledger.exe', commit)
            bundle = base / 'bundle/Quote777Host'
            harness = base / 'check.ps1'; harness.write_text(HARNESS, encoding='utf-8')
            password = 'Synthetic-portable-credential-2026'
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            env = {**os.environ, 'PATH': str(Path(os.environ['SystemRoot']) / 'System32')}
            result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(harness), '-Directory', str(bundle), '-Root', str(base / 'host'), '-Backup', str(base / 'backup'), '-Hidden', str(base / 'hidden')], input=json.dumps({'password': password}), capture_output=True, text=True, encoding='utf-8', env=env, timeout=240)
            if result.returncode:
                (output / 'powershell-error.log').write_text(result.stderr, encoding='utf-8')
                raise AssertionError('PORTABLE_NATIVE_PREPARATION_FAILED')
            checked = json.loads(result.stdout)
            assert checked['status'] == 'passed'
            root = Path(checked['root'])
            deployment = json.loads((root / 'private/deployment.json').read_text(encoding='utf-8'))
            public = json.loads((root / 'connection.json').read_text(encoding='utf-8'))
            assert deployment['source_commit'] == commit
            assert deployment['ledger_id'] == checked['ledger_id']
            assert public['schema'] == '777-public-connection-v1'
            assert set(public['connection']) == {'url', 'certificate_pem', 'certificate_sha256'}
            for path in [root / 'private/deployment.json', root / 'connection.json', *bundle.glob('logs/*/*.jsonl')]:
                assert password not in path.read_text(encoding='utf-8')
            assert not (root / 'private/stop.request').exists()
            report.update(status='passed', checks=['host_only_archive_manifest', 'PowerShell_5_1_with_developer_commands_absent', 'real_native_initialization_devices_daily_backup_and_inspect', 'authenticated_retry_preserves_ledger_and_provenance', 'public_connection_and_logs_exclude_password'])
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
