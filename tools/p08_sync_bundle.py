"""Exercise real SDK-free join modules; startup registration alone is stubbed."""
import json
import os
from pathlib import Path
import subprocess
from deployment.bundle.archive import assemble

HARNESS = r'''
param([string] $Directory,[string] $Root,[string] $Invitation,[int] $Port)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
foreach ($name in @('host-identity.ps1','host-log.ps1','host-package.ps1','host-site.ps1','host-paths.ps1','host-native.ps1','host-prepare.ps1','host-access.ps1','host-settings.ps1','host-cluster-files.ps1','host-cluster-join.ps1')) { . (Join-Path $Directory ('scripts\'+$name)) }
Start-HostLog $Directory
$script:fixtureInvitation=$Invitation
function Select-HostClusterFile([bool] $Save) { if ($Save) { throw 'UNEXPECTED_INVITE_EXPORT' }; return $script:fixtureInvitation }
# Only scheduled-task/credential creation is replaced. Native join and ownership checks run.
$script:starts=0
function Invoke-HostSetup($Directory,$Bundle,$Settings) {
    $deployment=Get-HostDeployment $Settings.root
    if ($deployment.deployment_mode -ne 'cluster' -or $deployment.replication -ne 'primary_async_snapshot_v1') { throw 'CLUSTER_MANIFEST_INVALID' }
    $script:starts++
}
if (@(Get-Command git,node,python,cargo -ErrorAction SilentlyContinue).Count) { throw 'SDK_COMMANDS_PRESENT_IN_RESTRICTED_PATH' }
$site=Get-LocalHostInventory
$addresses=@(Get-HostCandidateAddresses $site.addresses)
if (-not $addresses.Count) { throw 'WINDOWS_FIXTURE_HAS_NO_LOCAL_ADDRESS' }
$settings=[pscustomobject]@{root=$Root;backup=($Root+'-backups');hidden=($Root+'-hidden');address=$addresses[0];port=$Port;hour=23;admin='manager';configured=$true}
$bundle=Get-HostBundle $Directory
Join-HostCluster $Directory $bundle $settings
$manifest=Get-HostDeployment $Root
$state=Invoke-HostNative (Join-Path $Root 'private\rust-service-host.exe') @('cluster-status','--root',$Root)
if ($script:starts -ne 1 -or $state.role -ne 'replica' -or $manifest.ledger_id -ne $state.ledger_id) { throw 'JOINED_ROOT_IDENTITY_INVALID' }
if (-not (Test-Path -LiteralPath (Join-Path $Root 'connection.json'))) { throw 'PUBLIC_CONNECTION_MISSING' }
@{status='passed';ledger_id=$state.ledger_id;role=$state.role;startup_registered=$false;SDK_commands_available=$false} | ConvertTo-Json -Compress
'''


def check(source, base, invitation, port, root):
    host = root / 'target/release/quote-host.exe'
    worker = root / 'target/release/quote-ledger.exe'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    assemble(root, base / 'bundle', host, worker, commit)
    bundle = base / 'bundle/Quote777Host'
    harness = base / 'bundle-join.ps1'
    harness.write_text(HARNESS, encoding='utf-8-sig')
    shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(harness),
                             '-Directory', str(bundle), '-Root', str(base / 'portable-replica'), '-Invitation', str(invitation), '-Port', str(port)],
                            capture_output=True, text=True, encoding='utf-8', timeout=180,
                            env={**os.environ, 'PATH': str(Path(os.environ['SystemRoot']) / 'System32')})
    if result.returncode:
        # Only stable native/script diagnostics; invitations are never echoed by the harness.
        raise AssertionError('SDK_FREE_JOIN_FAILED: ' + result.stderr[-1200:])
    checked = json.loads(result.stdout.strip().splitlines()[-1])
    assert checked['ledger_id'] == source.config['ledger_id'] and checked['status'] == 'passed'
    for path in bundle.glob('logs/*/runtime.jsonl'):
        raw = path.read_text(encoding='utf-8')
        assert source.password not in raw
        assert json.loads(invitation.read_bytes())['ticket'] not in raw
    return checked
