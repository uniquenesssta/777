"""Controlled native-upgrade interruption; real Windows identity and atomic files."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell 5.1 runtime requires Windows')
class ClusterUpgradeTests(unittest.TestCase):
    def test_interrupted_native_upgrade_resumes_only_exact_package_hash_and_keeps_identity(self):
        script = r'''
param([string] $Modules,[string] $Base)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
foreach ($name in @('host-log.ps1','host-paths.ps1','host-site.ps1','host-native.ps1','host-prepare.ps1','host-access.ps1','host-settings.ps1','host-cluster-files.ps1','host-cluster-primary.ps1','host-visibility.ps1')) { . (Join-Path $Modules $name) }
. (Join-Path (Split-Path $Modules -Parent) 'host-identity.ps1')
Start-HostLog $Base
$root=Join-Path $Base 'service'; $private=Join-Path $root 'private'
[IO.Directory]::CreateDirectory($private) | Out-Null
[IO.Directory]::CreateDirectory((Join-Path $Base 'bin')) | Out-Null
foreach ($name in @('host-run.ps1','host-identity.ps1','rust-service-host.exe')) { [IO.File]::WriteAllText((Join-Path $private $name),'owned-old-resource') }
$candidate=Join-Path $Base 'bin\quote-host.exe'
[IO.File]::WriteAllText($candidate,'owned-new-resource')
$site=[pscustomobject]@{machine=$env:COMPUTERNAME;sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;account=[Security.Principal.WindowsIdentity]::GetCurrent().Name;addresses=@('192.0.2.58')}
$script:fixtureSite=$site; $script:fixtureRoot=$root
function Get-LocalHostInventory { return $script:fixtureSite }
$manifest=[pscustomobject]@{schema='777-site-deployment-v1';root=$root;owner_sid=$site.sid;owner_account=$site.account;machine=$site.machine;source_commit=('a'*40);active_address='192.0.2.58';port=8477;ledger_id='00000000-0000-0000-0000-000000000001';certificate_sha256=('b'*64);replication='not_implemented';host_sha256=(Get-FileDigest (Join-Path $private 'rust-service-host.exe'));runner_sha256=(Get-FileDigest (Join-Path $private 'host-run.ps1'));identity_sha256=(Get-FileDigest (Join-Path $private 'host-identity.ps1'))}
Write-HostJsonNew (Join-Path $private 'deployment.json') $manifest
Write-HostJsonNew (Join-Path $root 'client-template.json') @{url='https://192.0.2.58:8477';certificate_sha256=('b'*64)}
[IO.File]::WriteAllText((Join-Path $root 'service-cert.pem'),'synthetic-public-certificate')
$bundle=[pscustomobject]@{source_commit=('c'*40);files=@{'bin/quote-host.exe'=(Get-FileDigest $candidate)}}
$settings=@{hidden=(Join-Path $Base 'Quote777Hidden');backup=(Join-Path $Base 'backup');root=$root;address='192.0.2.58';admin='manager';port=8477}
$script:stops=0; $script:starts=0; $script:selections=0; $script:interrupt=$true
function Stop-HostForClusterUpgrade($Directory,$Root) { $script:stops++ }
function Read-HostBusinessPassword($Confirm) { return 'synthetic-only-password' }
function Invoke-HostSetup($Directory,$Bundle,$Settings) { $script:starts++; return @{} }
function Invoke-HostNative($Executable,$Arguments,$Password=$null) {
    switch ($Arguments[0]) {
        'resource-info' { return @{cluster_protocol='777-cluster-v1'} }
        'select-host' {
            if ($Password -ne 'synthetic-only-password') { throw 'PASSWORD_NOT_FORWARDED_OVER_SECURE_CHILD_CHANNEL' }
            $script:selections++
            [IO.File]::Copy($Executable,(Join-Path $script:fixtureRoot 'private\rust-service-host.exe'),$true)
            if ($script:interrupt) { $script:interrupt=$false; throw 'SYNTHETIC_AFTER_NATIVE_SELECTION' }
            return @{}
        }
        'inspect' { return @{inventory=@{ledger_id='00000000-0000-0000-0000-000000000001'};certificate_sha256=('b'*64)} }
        'cluster-primary' { return @{} }
        'cluster-status' { return @{role='primary';ledger_id='00000000-0000-0000-0000-000000000001'} }
        default { throw 'UNEXPECTED_NATIVE_OPERATION' }
    }
}
try { Enable-HostCluster $Base $bundle $settings; throw 'INTERRUPTION_EXPECTED' }
catch { if ($_.Exception.Message -ne 'SYNTHETIC_AFTER_NATIVE_SELECTION') { throw } }
if ($script:starts) { throw 'INTERRUPTED_UPGRADE_STARTED_SERVICE' }
try { $null=Get-HostDeployment $root; throw 'OLD_HASH_ACCEPTED_NEW_BINARY' }
catch { if ($_.Exception.Message -ne 'HOST_DEPLOYMENT_RESOURCE_CHANGED') { throw } }
Enable-HostCluster $Base $bundle $settings
# The original deployed manifest intentionally lacks deployment_mode.
$saved=Get-HostDeployment $root
if ($script:stops -ne 1 -or $script:starts -ne 1 -or $script:selections -ne 2 -or $saved.ledger_id -ne $manifest.ledger_id -or $saved.certificate_sha256 -ne $manifest.certificate_sha256 -or $saved.replication -ne 'primary_async_snapshot_v1' -or $saved.deployment_mode -ne 'cluster') { throw 'UPGRADE_RETRY_CHANGED_IDENTITY_OR_RESTARTED_TWICE' }
# Exercise real Windows attributes and the migrated pinned identity reader.
[IO.Directory]::CreateDirectory((Join-Path $Base 'scripts')) | Out-Null
[IO.File]::Copy((Join-Path (Split-Path $Modules -Parent) 'host-identity.ps1'),(Join-Path $Base 'scripts\host-identity.ps1'))
[IO.Directory]::CreateDirectory($settings.backup) | Out-Null
try {
    Set-HostDeploymentVisibility $Base $settings
    foreach ($path in @($Base,$root,$settings.hidden)) {
        $flags=[IO.File]::GetAttributes($path)
        if (-not ($flags -band [IO.FileAttributes]::Hidden) -or -not ($flags -band [IO.FileAttributes]::System) -or -not ($flags -band [IO.FileAttributes]::Directory)) { throw 'DEPLOYMENT_ATTRIBUTES_MISSING' }
    }
    if ([IO.File]::GetAttributes($settings.backup) -band ([IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::System)) { throw 'ORDINARY_BACKUP_ATTRIBUTES_CHANGED' }
    . (Join-Path $private 'host-identity.ps1')
    $null=Get-HostDeployment $root
    Set-HostDeploymentVisibility $Base $settings
    # Swapping backup roles must not change directory visibility policy.
    $swapped=@{root=$root;backup=$settings.hidden;hidden=$settings.backup}
    Set-HostDeploymentVisibility $Base $swapped
    if ([IO.File]::GetAttributes($settings.backup) -band ([IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::System)) { throw 'BACKUP_ROLE_CHANGED_ATTRIBUTES' }
    $remote=@{root=$root;backup=$settings.hidden;hidden='\\192.0.2.1\share\Quote777Hidden'}
    Set-HostDeploymentVisibility $Base $remote
    $targets=@(Get-HostVisibilityDirectories $Base $remote)
    if ($targets.Count -ne 3 -or $targets -contains $remote.hidden) { throw 'NETWORK_BACKUP_SELECTED_FOR_HIDING' }
} finally {
    foreach ($path in @($Base,$root,$settings.hidden)) {
        if ([IO.Directory]::Exists($path)) { [IO.File]::SetAttributes($path,([IO.File]::GetAttributes($path) -band (-bnot ([IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::System)))) }
    }
}
[IO.File]::AppendAllText($candidate,'tampered-after-console-loaded')
try { Enable-HostCluster $Base $bundle $settings; throw 'CHANGED_PACKAGE_EXECUTED' }
catch { if ($_.Exception.Message -ne 'HOST_PACKAGE_RESOURCE_CHANGED') { throw } }
@{status='passed';stops=$script:stops;starts=$script:starts;selections=$script:selections} | ConvertTo-Json -Compress
'''
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            harness = base / 'check.ps1'; harness.write_text(script, encoding='utf-8-sig')
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(harness),
                                     '-Modules', str(ROOT / 'deployment/windows/portable'), '-Base', str(base)],
                                    capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(value, dict(status='passed', stops=1, starts=1, selections=2))
            for path in base.glob('logs/*/runtime.jsonl'):
                self.assertNotIn('synthetic-only-password', path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
