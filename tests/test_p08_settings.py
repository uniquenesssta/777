"""Windows-only configuration and local ownership protections for generic host packages."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell 5.1 runtime requires Windows')
class HostSettingsTests(unittest.TestCase):
    def run_script(self, script, base):
        harness = base / 'check.ps1'
        harness.write_text(script, encoding='utf-8-sig')
        shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(harness), '-Modules', str(ROOT / 'deployment/windows/portable'), '-Base', str(base)], capture_output=True, text=True, encoding='utf-8', timeout=90)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_defaults_follow_local_machine_and_copied_settings_cannot_bind_another_computer(self):
        script = r'''
param([string] $Modules,[string] $Base)
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
foreach ($name in @('host-log.ps1','host-site.ps1','host-paths.ps1','host-settings.ps1','host-options.ps1')) { . (Join-Path $Modules $name) }
$Base=Get-HostLongPath $Base
$script:site=@{machine='synthetic-first-PC';sid='synthetic-first-owner';addresses=@('127.0.0.1','10.20.30.40','192.168.4.38')}
function Get-LocalHostInventory { return $script:site }
function Read-Host($Prompt) { if ($Prompt -notlike '*地址编号*') { throw 'UNEXPECTED_DIRECTORY_PROMPT' }; return '' }
# Construct a clean package configuration, with no live service roots or dialogs touched.
$package=Join-Path $Base 'Quote777Host'
[IO.Directory]::CreateDirectory($package) | Out-Null
Copy-Item -LiteralPath (Join-Path $Modules 'host-defaults.json') -Destination (Join-Path $package 'host-defaults.json')
$initial=Get-HostSetupSettings $package
if ($initial.root -ne (Join-Path $Base 'Quote777Service') -or $initial.address -ne '10.20.30.40' -or $initial.configured) { throw 'MACHINE_DEFAULTS_NOT_GENERIC' }
if ($initial.backup -ne (Join-Path $Base 'Quote777Hidden') -or $initial.hidden -ne '\\192.168.4.23\共享\backup') { throw 'FIXED_BACKUP_LAYOUT_INVALID' }
$selected=Select-HostSetupSettings $initial
Save-HostSetupSettings $package $selected
$saved=Get-HostSetupSettings $package
if (-not $saved.configured -or $saved.address -ne '10.20.30.40') { throw 'LOCAL_SETTINGS_NOT_REUSED' }
$script:site=@{machine='synthetic-second-PC';sid='synthetic-second-owner';addresses=@('192.168.4.38')}
$otherPackage=Join-Path $Base 'other-PC\Quote777Host'
[IO.Directory]::CreateDirectory($otherPackage) | Out-Null
foreach ($file in @('host-defaults.json','host-local.json')) { Copy-Item -LiteralPath (Join-Path $package $file) -Destination (Join-Path $otherPackage $file) }
$other=Get-HostSetupSettings $otherPackage
if ($other.configured -or $other.address -ne '192.168.4.38' -or $other.root -eq $saved.root) { throw 'COPIED_SETTINGS_BOUND_OTHER_COMPUTER' }
if ($other.root -ne (Join-Path $Base 'other-PC\Quote777Service') -or $other.backup -ne (Join-Path $Base 'other-PC\Quote777Hidden') -or $other.hidden -ne $initial.hidden) { throw 'MOVED_PACKAGE_LAYOUT_INVALID' }
$null=Select-HostSetupSettings $other $true
# Same-machine stale saved directory choices must also not override automatic layout.
$other.root=Join-Path $Base 'unused-old-choice'; $other.backup=Join-Path $Base 'unused-old-backup'; $other.hidden='unused-old-hidden'
Save-HostSetupSettings $otherPackage $other
$other=Get-HostSetupSettings $otherPackage
if ($other.root -ne (Join-Path $Base 'other-PC\Quote777Service') -or $other.hidden -ne $initial.hidden) { throw 'STALE_SETTINGS_OVERRULED_FIXED_LAYOUT' }
@{status='passed';address=$other.address;configured=$other.configured} | ConvertTo-Json -Compress
'''
        with tempfile.TemporaryDirectory() as folder:
            # Prompts print to the console host; the JSON result is the final line.
            value = self.run_script(script, Path(folder))
            self.assertEqual(value, {'status': 'passed', 'address': '192.168.4.38', 'configured': False})

    def test_generic_address_manifest_keeps_account_machine_and_resource_ownership_guards(self):
        script = r'''
param([string] $Modules,[string] $Base)
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
. (Join-Path (Split-Path $Modules -Parent) 'host-identity.ps1')
$root=Join-Path $Base 'host'; $private=Join-Path $root 'private'
[IO.Directory]::CreateDirectory($private) | Out-Null
foreach ($name in @('host-run.ps1','host-identity.ps1','rust-service-host.exe')) { [IO.File]::WriteAllText((Join-Path $private $name),'synthetic-owned-resource') }
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$manifest=[ordered]@{schema='777-site-deployment-v1';root=$root;owner_sid=$sid;machine=$env:COMPUTERNAME;active_address='192.0.2.58';port=8477;ledger_id='00000000-0000-0000-0000-000000000001';host_sha256=(Get-FileDigest (Join-Path $private 'rust-service-host.exe'));runner_sha256=(Get-FileDigest (Join-Path $private 'host-run.ps1'));identity_sha256=(Get-FileDigest (Join-Path $private 'host-identity.ps1'))}
$file=Join-Path $private 'deployment.json'
function Save-Fixture { [IO.File]::WriteAllText($file,($manifest | ConvertTo-Json -Compress)) }
Save-Fixture
$null=Get-HostDeployment $root
$manifest.machine='another-machine'; Save-Fixture
try { $null=Get-HostDeployment $root; throw 'FOREIGN_MACHINE_ALLOWED' } catch { if ($_.Exception.Message -ne 'DEPLOYMENT_OWNER_OR_IDENTITY_CONFLICT') { throw } }
$manifest.machine=$env:COMPUTERNAME; $manifest.owner_sid='another-owner'; Save-Fixture
try { $null=Get-HostDeployment $root; throw 'FOREIGN_OWNER_ALLOWED' } catch { if ($_.Exception.Message -ne 'DEPLOYMENT_OWNER_OR_IDENTITY_CONFLICT') { throw } }
$manifest.owner_sid=$sid; Save-Fixture
[IO.File]::AppendAllText((Join-Path $private 'host-run.ps1'),'changed')
try { $null=Get-HostDeployment $root; throw 'CHANGED_RESOURCE_ALLOWED' } catch { if ($_.Exception.Message -ne 'HOST_DEPLOYMENT_RESOURCE_CHANGED') { throw } }
@{status='passed'} | ConvertTo-Json -Compress
'''
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(self.run_script(script, Path(folder)), {'status': 'passed'})


if __name__ == '__main__':
    unittest.main()
