param(
    [Parameter(Mandatory=$true)][ValidateSet('install','status','start','stop','remove')][string] $Operation,
    [Parameter(Mandatory=$true)][string] $Root
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
trap {
    [Console]::Error.WriteLine((@{error=$_.Exception.Message;hresult=$_.Exception.HResult;error_type=$_.Exception.GetType().Name} | ConvertTo-Json -Compress))
    exit 1
}
. (Join-Path $PSScriptRoot 'host-identity.ps1')
$deployment = Get-HostDeployment $Root
$Root = $deployment.root
$taskName = 'Quote777-Host-' + $deployment.ledger_id
$description = '777-host-task-v1:' + $deployment.ledger_id + ':' + $deployment.owner_sid
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -ne $task -and $task.Description -ne $description) { throw 'HOST_TASK_OWNERSHIP_CONFLICT' }
$runner = Join-Path $Root 'private\host-run.ps1'
$executable = Join-Path $Root 'private\rust-service-host.exe'
$shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $runner + '" -Root "' + $Root.TrimEnd('\') + '"'
if ($null -ne $task -and ($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $shell -or $task.Actions[0].Arguments -ne $arguments)) {
    throw 'HOST_TASK_ACTION_CONFLICT'
}
if ($Operation -eq 'status') {
    $state = if ($null -eq $task) { 'not_registered' } else { [string] $task.State }
    $info = if ($null -eq $task) { $null } else { Get-ScheduledTaskInfo -TaskName $taskName }
    $lastResult = if ($null -eq $info) { $null } else { $info.LastTaskResult }
    [ordered]@{task=$taskName;state=$state;last_task_result=$lastResult;account=$deployment.owner_account;host=$deployment.active_address;replication=$deployment.replication} | ConvertTo-Json -Compress
    exit 0
}
if ($Operation -eq 'stop') {
    if ($null -eq $task) { throw 'HOST_TASK_NOT_REGISTERED' }
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    # Also cover a task queued just before it was disabled.
    [IO.File]::WriteAllText((Join-Path $Root 'private\stop.request'), 'stop')
    Write-Output 'Future startup disabled; graceful shutdown requested. Check status before maintenance.'
    exit 0
}
if ($Operation -eq 'start') {
    if ($null -eq $task) { throw 'HOST_TASK_NOT_REGISTERED' }
    if ($task.State -eq 'Running') { throw 'HOST_TASK_ALREADY_RUNNING' }
    $stop = Join-Path $Root 'private\stop.request'
    if (Test-Path -LiteralPath $stop) { Remove-Item -LiteralPath $stop }
    Enable-ScheduledTask -TaskName $taskName | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Write-Output 'Startup task started; confirm HTTPS readiness and business access separately.'
    exit 0
}
if ($null -ne $task -and $task.State -eq 'Running') { throw 'STOP_HOST_GRACEFULLY_BEFORE_CHANGING_TASK' }
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'ELEVATED_WINDOWS_DEPLOYMENT_SHELL_REQUIRED' }
$ruleName = 'Quote777-Host-' + $deployment.ledger_id
$rule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($null -ne $rule) {
    $program = $rule | Get-NetFirewallApplicationFilter
    $ports = $rule | Get-NetFirewallPortFilter
    if ($program.Program -ne $executable -or $ports.LocalPort -ne [string]$deployment.port) { throw 'HOST_FIREWALL_OWNERSHIP_CONFLICT' }
}
if ($Operation -eq 'remove') {
    if ($null -ne $task) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
    if ($null -ne $rule) { Remove-NetFirewallRule -Name $ruleName }
    Write-Output 'Only the owned startup task and firewall rule were removed; all data and backups remain.'
    exit 0
}
$credential = Get-Credential -UserName $deployment.owner_account -Message 'Windows account password for startup before login; not the business administrator password'
if ($null -eq $credential) { throw 'WINDOWS_STARTUP_CREDENTIAL_REQUIRED' }
$sid = [Security.Principal.NTAccount]::new($credential.UserName).Translate([Security.Principal.SecurityIdentifier]).Value
if ($sid -ne $deployment.owner_sid) { throw 'STARTUP_ACCOUNT_MUST_MATCH_HOST_OWNER' }
$createdTask = $false
$createdRule = $false
try {
    $action = New-ScheduledTaskAction -Execute $shell -Argument $arguments -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $taskPassword = $credential.GetNetworkCredential().Password
    Register-ScheduledTask -TaskName $taskName -Description $description -Action $action -Trigger $trigger -Settings $settings -User $credential.UserName -Password $taskPassword -RunLevel Limited -Force | Out-Null
    $createdTask = ($null -eq $task)
    if ($null -eq $rule) {
        New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort $deployment.port -Program $executable -RemoteAddress LocalSubnet -Profile Domain,Private | Out-Null
        $createdRule = $true
    }
    # Installation registers startup; explicit 'start' runs it after the operator reviews the result.
    Write-Output 'Registered startup for the existing host owner. The host has not been started.'
} catch {
    if ($createdRule) { Remove-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue }
    if ($createdTask) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue }
    throw
} finally {
    $taskPassword = $null
    $credential = $null
}
