param([Parameter(Mandatory=$true)][string]$Resources,[string]$LogSession='',[string]$ExecutionId='')
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$env:QUOTE777_LOG_DISABLED='1'
$shell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
. (Join-Path $PSScriptRoot 'install-paths.ps1')
. (Join-Path $PSScriptRoot 'install-owner.ps1')
. (Join-Path $PSScriptRoot 'install-discovery.ps1')
. (Join-Path $PSScriptRoot 'host-identity.ps1')
. (Join-Path $PSScriptRoot 'host-log.ps1')
. (Join-Path $PSScriptRoot 'host-elevation.ps1')
$directory=Join-Path $env:ProgramData 'Quote777\Quote777Host'
Start-HostLog $Resources $LogSession $ExecutionId
try {
    $elevated=Invoke-HostElevation $PSCommandPath ('-Resources "'+$Resources+'"')
    if ($null -ne $elevated) {exit [int]$elevated}
    $Resources=Assert-AutomaticLocalPath $Resources
    $package=Get-Content -LiteralPath (Join-Path $Resources 'automatic\package.json') -Raw -Encoding UTF8|ConvertFrom-Json
    $localSigned = $package.format -eq '777-local-package-v1'
    if ($localSigned) {
        # Native validation checks the signature and immutable role before touching tasks.
        & (Join-Path $Resources 'host\quote-host.exe') automatic-package-check --package (Join-Path $Resources 'automatic\package.json') | Out-Null
        if ($LASTEXITCODE -ne 0 -or $package.manifest.delivery -ne 'manager') { throw 'AUTOMATIC_PACKAGE_INVALID' }
        $existing = Find-LocalSignedDeployment $package
        $ledger = if ($null -ne $existing) { $existing.ledger_id } else { $null }
        $siteId = if ($null -ne $existing) { $existing.site_id } else { $null }
        $taskId = if ($null -ne $existing) { $existing.task_id } else { $package.manifest.issuer_id }
    } else {
        if ($package.format -ne '777-automatic-package-v1' -or $package.manifest.delivery -ne 'manager' -or $package.profile.primary_url -ne 'https://192.168.4.23:8477' -or $package.manifest.ledger_id -notmatch '^[a-f0-9-]{36}$') { throw 'AUTOMATIC_PACKAGE_INVALID' }
        $existing=Find-AutomaticDeployment $package
        $ledger=$package.manifest.ledger_id; $siteId=$package.manifest.site_id; $taskId=$ledger
    }
    if ($null -ne $existing) {
        $directory=Join-Path ([IO.Path]::GetDirectoryName($existing.root)) 'Quote777Host'
    }
    Start-HostLog $directory $env:QUOTE777_LOG_SESSION $env:QUOTE777_EXECUTION_ID
    if ($null -ne $existing -and $existing.ContainsKey('role') -and $existing.role -eq 'primary') {
        # Never rewrite the primary runner/account/cert/backups during normal installation.
        $native=Join-Path $Resources 'host\quote-host.exe'
        if (-not $localSigned) {
        & $native automatic-node-join --root $existing.root --state (Join-Path $directory 'private') --package (Join-Path $Resources 'automatic\package.json') --backup-dir (Join-Path $directory '..\Quote777Hidden') --worker (Join-Path $Resources 'host\quote-ledger.exe') --notices (Join-Path $Resources 'licenses\desktop-notices.md')|Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'PRIMARY_REUSE_NOT_CONFIRMED' }
        }
        Enable-ScheduledTask -TaskName $existing.task.TaskName|Out-Null
        if ($existing.task.State -ne 'Running') { Start-ScheduledTask -TaskName $existing.task.TaskName }
        Set-AutomaticTopAttributes @($directory,$existing.root,(Join-Path ([IO.Path]::GetDirectoryName($existing.root)) 'Quote777Hidden'))
        Write-HostEvent 'installation.primary.reused' @{ledger_id=$ledger}
        exit 0
    }
    # A local primary address without a proven deployment must never become a replica.
    if (@(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue|Where-Object IPAddress -eq '192.168.4.23').Count) { throw 'PRIMARY_DEPLOYMENT_NOT_FOUND' }
    if ($null -ne $existing) { $directory=Join-Path ([IO.Path]::GetDirectoryName($existing.root)) 'Quote777Host' }
    $directory=Assert-AutomaticLocalPath $directory
    $parent=[IO.Path]::GetDirectoryName($directory)
    $root=if ($null -ne $existing) { $existing.root } else { Join-Path $parent 'Quote777Service' }
    $backup=Join-Path $parent 'Quote777Hidden'
    $null=Assert-AutomaticLocalPath $root
    $null=Assert-AutomaticLocalPath $backup
    if ($null -eq $existing -and [IO.Directory]::Exists($root)) { throw 'CLUSTER_JOIN_REQUIRES_NEW_ROOT' }
    if ([IO.Directory]::Exists($directory) -and -not [IO.File]::Exists((Join-Path $directory 'install.json')) -and $null -eq $existing -and @(Get-ChildItem -LiteralPath $directory -Force|Where-Object Name -ne 'logs').Count) { throw 'HOST_INSTALL_DIRECTORY_CONFLICT' }
    if ($null -ne $existing) { Stop-AutomaticOwnedTask $existing }
    [IO.Directory]::CreateDirectory((Join-Path $directory 'private'))|Out-Null
    # The startup owner is SYSTEM only for new replicas; old owner/task credentials stay intact.
    & icacls.exe $directory /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F'|Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'HOST_PRIVATE_ACL_FAILED' }
    if ($null -ne $existing -and -not $existing.automatic) { & icacls.exe $directory /grant ('*'+$existing.deployment.owner_sid+':(OI)(CI)F')|Out-Null; if ($LASTEXITCODE -ne 0) { throw 'HOST_PRIVATE_ACL_FAILED' } }
    foreach($name in @('quote-host.exe','quote-ledger.exe')) { [IO.File]::Copy((Join-Path $Resources ('host\'+$name)),(Join-Path $directory $name),$true) }
    foreach($name in @('node-run.ps1','install-paths.ps1','host-identity.ps1','host-log.ps1')) { [IO.File]::Copy((Join-Path $PSScriptRoot $name),(Join-Path $directory $name),$true) }
    [IO.File]::Copy((Join-Path $Resources 'automatic\package.json'),(Join-Path $directory 'package.json'),$true)
    [IO.File]::Copy((Join-Path $Resources 'licenses\desktop-notices.md'),(Join-Path $directory 'THIRD_PARTY_NOTICES.md'),$true)
    Write-AutomaticJson (Join-Path $directory 'install.json') @{format='777-automatic-host-install-v1';root=$root;backup=$backup;site_id=$siteId;ledger_id=$ledger;task_id=$taskId;issuer_id=$package.manifest.issuer_id;preserve_owner=($null -ne $existing -and -not $existing.automatic)}
    [IO.Directory]::CreateDirectory($backup)|Out-Null
    $taskName='Quote777-Host-'+$taskId
    if ($null -ne $existing -and -not $existing.automatic) {
        [IO.File]::Copy((Join-Path $directory 'node-run.ps1'),(Join-Path $root 'private\host-run.ps1'),$true)
        $d=$existing.deployment; $d.runner_sha256=Get-FileDigest (Join-Path $root 'private\host-run.ps1')
        Write-AutomaticJson (Join-Path $root 'private\deployment.json') $d
    } elseif ($null -eq $existing) {
        $action=New-ScheduledTaskAction -Execute $shell -Argument ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $directory 'node-run.ps1')+'" -Root "'+$root+'"') -WorkingDirectory $directory
        $trigger=New-ScheduledTaskTrigger -AtStartup
        $settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $taskName -Description ('777-automatic-host-task-v1:'+ $taskId+':S-1-5-18') -Action $action -Trigger $trigger -Settings $settings -User SYSTEM -RunLevel Highest|Out-Null
    }
    foreach($stop in @((Join-Path $directory 'stop.request'),(Join-Path $root 'private\stop.request'))) { if ([IO.File]::Exists($stop)) { [IO.File]::Delete($stop) } }
    Set-AutomaticTopAttributes @($directory,$root,$backup)
    Enable-ScheduledTask -TaskName $taskName|Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-HostEvent 'installation.background.requested' @{ledger_id=$ledger;phase='awaiting_enrollment'}
} catch {
    Write-HostFailure 'installation.failed' 'host_setup' $_
    exit 1
}

finally { Write-HostEvent 'runtime.stop' @{} }
