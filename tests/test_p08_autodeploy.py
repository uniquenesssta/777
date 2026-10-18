"""Windows one-click routing and invitation selection; no live service or task changes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell 5.1 execution requires Windows')
class AutoDeploymentTests(unittest.TestCase):
    def test_fresh_join_existing_resume_and_single_invitation_without_directory_prompts(self):
        script = r'''
param([string] $Modules,[string] $Base)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
. (Join-Path $Modules 'host-autodeploy.ps1')
. (Join-Path $Modules 'host-paths.ps1')
. (Join-Path $Modules 'host-cluster-files.ps1')
$settings=@{root=(Join-Path $Base 'Quote777Service')}
$invitation=Join-Path $Base 'source invite.777join'
[IO.File]::WriteAllText($invitation,'synthetic-ticket-not-logged')
$script:ops=[Collections.Generic.List[string]]::new()
$script:dialogs=0
function Select-HostClusterFile($Save) { $script:dialogs++; throw 'CLUSTER_FILE_SELECTION_CANCELLED' }
function Invoke-HostSetup($Directory,$Bundle,$Settings) { $script:ops.Add('setup'); return @{} }
function Enable-HostCluster($Directory,$Bundle,$Settings) { $script:ops.Add('primary') }
function Join-HostCluster($Directory,$Bundle,$Settings,[switch] $AutoInvitation) {
    if (-not $AutoInvitation) { throw 'AUTOMATIC_INVITATION_NOT_REQUESTED' }
    $chosen=Get-HostAutoInvitation $Directory
    # Windows TEMP may use an 8.3 alias while enumeration returns its long name.
    if ((Get-HostLongPath $chosen) -ne (Get-HostLongPath $invitation)) { throw 'WRONG_INVITATION_SELECTED' }
    $script:ops.Add('join')
}
function Get-HostConnectionCheck($Directory,$Settings) { return @{https='verified_response'} }
function Show-ConnectionCheck($Check) { $script:ops.Add('check') }
function Show-HostClusterStatus($Settings) { $script:ops.Add('status') }
function Assert-Route([string] $Expected) {
    $script:ops.Clear()
    Invoke-HostAutoDeployment $Base @{} $settings
    if (($script:ops -join ',') -ne $Expected) { throw 'AUTODEPLOY_ROUTE_INVALID' }
}
Assert-Route 'join,check,status'
if ([IO.Directory]::Exists($settings.root)) { throw 'FRESH_JOIN_ROUTER_CREATED_AN_INDEPENDENT_LEDGER' }
$private=Join-Path $settings.root 'private'
[IO.Directory]::CreateDirectory((Join-Path $private 'cluster')) | Out-Null
$cluster=Join-Path $private 'cluster\config.json'
$manifest=Join-Path $private 'deployment.json'
$service=Join-Path $private 'service.json'
[IO.File]::WriteAllText($cluster,'{}')
Assert-Route 'join,check,status'
[IO.File]::WriteAllText($manifest,'{}')
Assert-Route 'setup,check,status'
[IO.File]::Delete($cluster)
[IO.File]::WriteAllText($service,'{}')
Assert-Route 'primary,check,status'
[IO.File]::Delete($manifest)
Assert-Route 'setup,primary,check,status'
if ($script:dialogs) { throw 'SINGLE_INVITATION_OPENED_DIALOG' }
[IO.File]::WriteAllText((Join-Path $Base 'second.777join'),'another-ticket')
try { $null=Get-HostAutoInvitation $Base; throw 'AMBIGUOUS_INVITATION_AUTOSELECTED' }
catch { if ($_.Exception.Message -ne 'CLUSTER_FILE_SELECTION_CANCELLED') { throw } }
[IO.File]::Delete($invitation)
[IO.File]::Delete((Join-Path $Base 'second.777join'))
try { $null=Get-HostAutoInvitation $Base; throw 'MISSING_INVITATION_IGNORED' }
catch { if ($_.Exception.Message -ne 'CLUSTER_FILE_SELECTION_CANCELLED') { throw } }
if ($script:dialogs -ne 2) { throw 'INVITATION_DIALOG_ROUTING_INVALID' }
Write-Output 'passed'
'''
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            harness = base / 'check.ps1'
            harness.write_text(script, encoding='utf-8-sig')
            shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(harness), '-Modules', str(ROOT / 'deployment/windows/portable'), '-Base', str(base)], capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip().splitlines()[-1], 'passed')
            self.assertNotIn('synthetic-ticket-not-logged', result.stdout + result.stderr)
