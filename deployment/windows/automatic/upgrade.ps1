param([string] $Root)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
if ($env:OS -ne 'Windows_NT') { throw 'WINDOWS_DEPLOYMENT_REQUIRED' }
if ($Root -and ($Root.Contains('"') -or $Root.Contains("`r") -or $Root.Contains("`n"))) { throw 'LOCAL_HOST_ROOT_REQUIRED' }
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments='-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'"'
    if ($Root) { $arguments+=' -Root "'+$Root.TrimEnd('\')+'"' }
    $p=Start-Process (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -Verb RunAs -ArgumentList $arguments -Wait -PassThru
    exit $p.ExitCode
}
. (Join-Path $PSScriptRoot 'host-identity.ps1')
. (Join-Path $PSScriptRoot 'host-log.ps1')
Start-HostLog $PSScriptRoot
try {
    $files=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'files.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($file in @('upgrade.json','quote-host.exe','THIRD_PARTY_NOTICES.md','upgrade.ps1','cleanup.ps1','host-identity.ps1','host-log.ps1','upgrade.cmd')) {
        if ((Get-FileDigest (Join-Path $PSScriptRoot $file)) -ne $files.$file) { throw 'UPGRADE_RESOURCE_CHANGED' }
    }
    if (-not $Root) {
        $roots=@(Get-ScheduledTask -TaskName 'Quote777-Host-*' -ErrorAction SilentlyContinue | ForEach-Object {
            foreach ($action in $_.Actions) { if ($action.Arguments -match '-Root "([^"]+)"') { $Matches[1] } }
        } | Sort-Object -Unique)
        if ($roots.Count -ne 1) { throw 'UPGRADE_EXISTING_DEPLOYMENT_AMBIGUOUS' }
        $Root=$roots[0]
    }
    $candidate=Get-FileDigest (Join-Path $PSScriptRoot 'quote-host.exe')
    $d=Get-HostDeployment $Root $candidate
    if ($d.active_address -ne '192.168.4.23' -or $d.port -ne 8477) { throw 'AUTOMATIC_PRIMARY_ENDPOINT_CONFLICT' }
    $taskName='Quote777-Host-'+$d.ledger_id
    $task=Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    $expected='777-host-task-v1:'+$d.ledger_id+':'+$d.owner_sid
    $runner=Join-Path $Root 'private\host-run.ps1'
    $shell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $arguments='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+$runner+'" -Root "'+$Root.TrimEnd('\')+'"'
    if ($task.Description -ne $expected -or $task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $shell -or $task.Actions[0].Arguments -ne $arguments) { throw 'HOST_TASK_OWNERSHIP_CONFLICT' }
    Write-HostEvent 'upgrade.start' @{ledger_id=$d.ledger_id}
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    if ($task.State -eq 'Running') {
        [IO.File]::WriteAllText((Join-Path $Root 'private\stop.request'),'stop')
        $deadline=[DateTime]::UtcNow.AddSeconds(60)
        do {
            Start-Sleep -Milliseconds 500
            $task=Get-ScheduledTask -TaskName $taskName
            if ([DateTime]::UtcNow -gt $deadline) { throw 'HOST_GRACEFUL_STOP_TIMED_OUT' }
        } while ($task.State -eq 'Running')
    }
    $native=Join-Path $PSScriptRoot 'quote-host.exe'
    & $native automatic-upgrade --root $Root --kit (Join-Path $PSScriptRoot 'upgrade.json') --notices (Join-Path $PSScriptRoot 'THIRD_PARTY_NOTICES.md')
    if ($LASTEXITCODE -ne 0) { throw 'HOST_AUTOMATIC_UPGRADE_FAILED' }
    $kit=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'upgrade.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $ruleName='Quote777-Pairing-'+$kit.upgrade_id
    $existing=Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        if ($existing.Description -ne ('777-pairing:'+ $kit.upgrade_id)) { throw 'PAIRING_FIREWALL_OWNERSHIP_CONFLICT' }
        $p=$existing | Get-NetFirewallPortFilter
        $app=$existing | Get-NetFirewallApplicationFilter
        $addr=$existing | Get-NetFirewallAddressFilter
        if ($p.LocalPort -ne '8478' -or $app.Program -ne (Join-Path $Root 'private\rust-service-host.exe') -or @($addr.RemoteAddress).Count -ne 1 -or $addr.RemoteAddress[0] -ne $kit.allowed_peer) { throw 'PAIRING_FIREWALL_OWNERSHIP_CONFLICT' }
    } else {
        New-NetFirewallRule -Name $ruleName -Description ('777-pairing:'+ $kit.upgrade_id) -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8478 -Program (Join-Path $Root 'private\rust-service-host.exe') -RemoteAddress $kit.allowed_peer -Profile Domain,Private | Out-Null
    }
    $cleanup='-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $PSScriptRoot 'cleanup.ps1')+'" -Root "'+$Root.TrimEnd('\')+'" -Rule "'+$ruleName+'" -UpgradeId "'+$kit.upgrade_id+'" -Directory "'+$PSScriptRoot+'"'
    Start-Process $shell -ArgumentList $cleanup -WindowStyle Hidden | Out-Null
    $stop=Join-Path $Root 'private\stop.request'
    if (Test-Path -LiteralPath $stop) { Remove-Item -LiteralPath $stop }
    Enable-ScheduledTask -TaskName $taskName | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-HostEvent 'upgrade.started' @{ledger_id=$d.ledger_id}
    Write-Host '后台程序已升级并发出启动请求。开发侧将自动完成发行绑定；接通结果以日志为准。'
} catch {
    $code=$_.Exception.Message
    if ($code -notmatch '^[A-Z][A-Z0-9_]{4,100}$') { $code='HOST_AUTOMATIC_UPGRADE_FAILED' }
    Write-HostEvent 'upgrade.failed' @{error=$code}
    Write-Host ('升级尚未完成：'+$code+'。已有数据保留，可重新运行本升级包。')
    exit 1
}
