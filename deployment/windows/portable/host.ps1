# Standalone host package entry. Windows PowerShell 5.1; no developer runtimes.
param(
    [ValidateSet('inventory','prepare','configure','install','status','start','stop','remove')][string] $Operation='inventory',
    [string] $Root, [string] $Backup, [string] $Hidden,
    [string] $Admin='manager', [string] $Address='192.168.4.23',
    [int] $Port=8477, [int] $Hour=23
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
if ($env:OS -ne 'Windows_NT') { throw 'WINDOWS_DEPLOYMENT_REQUIRED' }
foreach ($name in @('host-identity.ps1','host-log.ps1','host-package.ps1','host-site.ps1','host-paths.ps1','host-native.ps1','host-prepare.ps1')) { . (Join-Path $PSScriptRoot ('scripts\' + $name)) }
$password=$null
try {
    Start-HostLog $PSScriptRoot
    Write-HostEvent 'deployment.operation.start' @{operation=$Operation}
    $bundle = Get-HostBundle $PSScriptRoot
    if ($Operation -eq 'inventory') {
        $value = Get-LocalHostInventory
        Write-HostEvent 'deployment.inventory' @{machine=$value.machine;os=$value.os;addresses=$value.addresses;account=$value.account;sid=$value.sid}
    } elseif ($Operation -in @('prepare','configure')) {
        # Validate this machine before asking for any business password.
        $site = Get-LocalHostInventory
        if ($Address -notin $site.addresses) { throw 'DEPLOYMENT_MUST_RUN_ON_SELECTED_HOST' }
        if ($Address -ne '192.168.4.23') { throw 'STANDBY_REPLICATION_NOT_IMPLEMENTED' }
        $validatedRoot = Get-LocalHostRoot $Root ($Operation -eq 'prepare')
        Assert-HostBackupLocation $Backup $validatedRoot
        Assert-HostBackupLocation $Hidden $validatedRoot
        $password = Read-HostBusinessPassword ($Operation -eq 'prepare')
        $value = Invoke-HostPreparation $site $bundle $PSScriptRoot $Root $Backup $Hidden $Admin $password $Address $Port $Hour ($Operation -eq 'configure')
    } else {
        if ([string]::IsNullOrWhiteSpace($Root)) { throw 'HOST_ROOT_REQUIRED' }
        $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $raw = Invoke-HostProcess $shell @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'scripts\host-task.ps1'),'-Operation',$Operation,'-Root',$Root)
        $value = [ordered]@{status='task_operation_completed';operation=$Operation;result=$raw}
    }
    Write-HostEvent 'deployment.operation.finish' @{operation=$Operation}
    $value | ConvertTo-Json -Depth 12
} catch {
    $code = $_.Exception.Message
    if ($code -notmatch '^[A-Z][A-Z0-9_]{4,100}$') { $code = 'WINDOWS_HOST_DEPLOYMENT_FAILED' }
    Write-HostEvent 'deployment.operation.failed' @{operation=$Operation;error=$code;hresult=$_.Exception.HResult;error_type=$_.Exception.GetType().Name}
    [Console]::Error.WriteLine((@{error=$code;hresult=$_.Exception.HResult;error_type=$_.Exception.GetType().Name;existing_data='preserved'} | ConvertTo-Json -Compress))
    exit 1
} finally { $password=$null; Write-HostEvent 'runtime.stop' @{} }
