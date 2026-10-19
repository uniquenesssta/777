# Caller starts its log before elevation. Explicit context survives UAC environment boundaries.
function Invoke-HostElevation([string]$ScriptPath,[string]$Arguments) {
    $principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {return $null}
    $arguments='-NoProfile -ExecutionPolicy Bypass -File "'+$ScriptPath+'" '+$Arguments
    if ($env:QUOTE777_LOG_DISABLED -ne '1') {$arguments+=' -LogSession "'+$env:QUOTE777_LOG_SESSION+'" -ExecutionId "'+$env:QUOTE777_EXECUTION_ID+'"'}
    Write-HostEvent 'elevation.requested' @{stage='windows_authorization'}
    try {
        $process=Start-Process (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -Verb RunAs -WindowStyle Hidden -ArgumentList $arguments -Wait -PassThru
        Write-HostEvent 'elevation.completed' @{exit_code=$process.ExitCode}
        return [int]$process.ExitCode
    } catch {Write-HostFailure 'elevation.failed' 'windows_authorization' $_;throw 'HOST_ELEVATION_NOT_COMPLETED'}
}
