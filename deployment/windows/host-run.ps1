param([Parameter(Mandatory=$true)][string] $Root)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'host-identity.ps1')
$deployment = Get-HostDeployment $Root
$Root = $deployment.root
$lock = $null
$process = $null
try {
    # FileShare.None also excludes another Windows session for this same ledger.
    $lock = [IO.File]::Open((Join-Path $Root 'private\runner.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $stop = Join-Path $Root 'private\stop.request'
    # A stop requested while this task was starting must not be discarded.
    if (Test-Path -LiteralPath $stop) { exit 0 }
    $env:QUOTE777_LOG_ROOT = $Root
    # Every invocation lets the native logger allocate a fresh bounded session folder.
    Remove-Item Env:QUOTE777_LOG_SESSION -ErrorAction SilentlyContinue
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = Join-Path $Root 'private\rust-service-host.exe'
    $start.Arguments = 'run --root "' + $Root.TrimEnd('\') + '" --shutdown-stdin'
    $start.WorkingDirectory = $Root
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    if (-not $process.Start()) { throw 'HOST_PROCESS_START_FAILED' }
    while (-not $process.WaitForExit(1000)) {
        if (Test-Path -LiteralPath $stop) {
            $process.StandardInput.WriteLine('')
            $process.StandardInput.Close()
            if (-not $process.WaitForExit(30000)) { throw 'HOST_GRACEFUL_STOP_TIMED_OUT' }
            break
        }
    }
    $result = $process.ExitCode
    if (Test-Path -LiteralPath $stop) { Remove-Item -LiteralPath $stop }
    exit $result
} finally {
    # Never terminate an arbitrary process or delete the ledger on a stop failure.
    if ($null -ne $process) { $process.Dispose() }
    if ($null -ne $lock) { $lock.Dispose() }
}
