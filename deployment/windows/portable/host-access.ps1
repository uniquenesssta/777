# Elevation and owned scheduled-task calls. No credentials in command arguments.
function Test-HostElevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]::new($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
function Assert-HostSetupMachine($Settings) {
    $site = Get-LocalHostInventory
    if ($Settings.address -ne '192.168.4.23') { throw 'STANDBY_REPLICATION_NOT_IMPLEMENTED' }
    if ($Settings.address -notin $site.addresses) { throw 'DEPLOYMENT_MUST_RUN_ON_SELECTED_HOST' }
    return $site
}
function Invoke-HostElevatedConsole([string] $Directory, [string] $Action) {
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $Directory 'host-console.ps1'),'-Action',$Action,'-ExpectedSid',$sid,'-LogSession',$env:QUOTE777_LOG_SESSION)
    $quoted = ($arguments | ForEach-Object { ConvertTo-HostArgument $_ }) -join ' '
    $child = Start-Process -FilePath $shell -ArgumentList $quoted -Verb RunAs -Wait -PassThru
    try { if ($child.ExitCode -ne 0) { throw 'HOST_ELEVATED_ACTION_FAILED' } } finally { $child.Dispose() }
}
function Invoke-HostTaskOperation([string] $Directory, [string] $Root, [string] $Operation) {
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    Write-HostEvent 'host.task.start' @{operation=$Operation}
    $raw = Invoke-HostProcess $shell @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $Directory 'scripts\host-task.ps1'),'-Operation',$Operation,'-Root',$Root)
    Write-HostEvent 'host.task.finish' @{operation=$Operation}
    if ($Operation -eq 'status') { return ($raw | ConvertFrom-Json) }
}
