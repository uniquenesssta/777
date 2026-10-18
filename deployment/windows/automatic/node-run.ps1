param([Parameter(Mandatory=$true)][string]$Root)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$directory=Join-Path ([IO.Path]::GetDirectoryName($Root)) 'Quote777Host'
. (Join-Path $directory 'install-paths.ps1')
. (Join-Path $directory 'host-log.ps1')
. (Join-Path $directory 'host-identity.ps1')
Start-HostLog $directory
$lock=$null
try {
    $Root=Assert-AutomaticLocalPath $Root
    $m=Get-Content -LiteralPath (Join-Path $directory 'install.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if ($m.format -ne '777-automatic-host-install-v1' -or $m.root -ine $Root) { throw 'HOST_RUNNER_OWNERSHIP_CONFLICT' }
    $lock=[IO.File]::Open((Join-Path $directory 'private\runner.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $last='';$lastAt=[DateTime]::MinValue;$attempt=0
    $stops=@((Join-Path $directory 'stop.request'),(Join-Path $Root 'private\stop.request'))
    while (-not @($stops|Where-Object { [IO.File]::Exists($_) }).Count) {
        $native=Join-Path $directory 'quote-host.exe'
        $joining=[Diagnostics.Process]::new()
        $joinStart=[Diagnostics.ProcessStartInfo]::new()
        $joinStart.FileName=$native
        $joinStart.Arguments='automatic-node-join --root "'+$Root+'" --state "'+(Join-Path $directory 'private')+'" --package "'+(Join-Path $directory 'package.json')+'" --backup-dir "'+$m.backup+'" --worker "'+(Join-Path $directory 'quote-ledger.exe')+'" --notices "'+(Join-Path $directory 'THIRD_PARTY_NOTICES.md')+'" --shutdown-stdin'
        $joinStart.UseShellExecute=$false;$joinStart.CreateNoWindow=$true
        $joinStart.RedirectStandardInput=$true;$joinStart.RedirectStandardOutput=$true;$joinStart.RedirectStandardError=$true
        $joining.StartInfo=$joinStart
        try {
            if (-not $joining.Start()) { throw 'HOST_PROCESS_START_FAILED' }
            while (-not $joining.WaitForExit(1000)) {
                if (@($stops|Where-Object {[IO.File]::Exists($_)}).Count) {
                    $joining.StandardInput.WriteLine('');$joining.StandardInput.Close()
                    if (-not $joining.WaitForExit(30000)) { throw 'HOST_GRACEFUL_STOP_TIMED_OUT' }
                    break
                }
            }
            $result=$joining.StandardOutput.ReadToEnd()
            $failure=$joining.StandardError.ReadToEnd()
            $joinExit=$joining.ExitCode
        } finally {$joining.Dispose()}
        if (@($stops|Where-Object {[IO.File]::Exists($_)}).Count) {break}
        $retryAfter=0;$blocked=$false
        if ($joinExit -eq 0) {
            $attempt=0
            $joined=($result -join "`n")|ConvertFrom-Json
            if ($joined.status -ne 'replica_ready' -or $joined.ledger_id -ne $m.ledger_id) { throw 'CLUSTER_IDENTITY_CONFLICT' }
            $private=Join-Path $Root 'private'
            if (-not $m.preserve_owner) {
                foreach($name in @('host-identity.ps1')) { [IO.File]::Copy((Join-Path $directory $name),(Join-Path $private $name),$true) }
                [IO.File]::Copy((Join-Path $directory 'node-run.ps1'),(Join-Path $private 'host-run.ps1'),$true)
                $cfg=Get-Content -LiteralPath (Join-Path $private 'service.json') -Raw -Encoding UTF8|ConvertFrom-Json
                $d=@{schema='777-site-deployment-v1';root=$Root;owner_sid='S-1-5-18';owner_account='NT AUTHORITY\SYSTEM';machine=$env:COMPUTERNAME;ledger_id=$m.ledger_id;active_address='127.0.0.1';port=8477;certificate_sha256=$cfg.certificate_sha256;autostart='registered';replication='primary_async_snapshot_v2';host_sha256=(Get-FileDigest (Join-Path $private 'rust-service-host.exe'));runner_sha256=(Get-FileDigest (Join-Path $private 'host-run.ps1'));identity_sha256=(Get-FileDigest (Join-Path $private 'host-identity.ps1'))}
                Write-AutomaticJson (Join-Path $private 'deployment.json') $d
            } else {
                $d=Get-HostDeployment $Root (Get-FileDigest (Join-Path $directory 'quote-host.exe'))
                $d.host_sha256=Get-FileDigest (Join-Path $private 'rust-service-host.exe')
                Write-AutomaticJson (Join-Path $private 'deployment.json') $d
            }
            Set-AutomaticTopAttributes @($directory,$Root,$m.backup)
            Write-HostEvent 'installation.replica.ready' @{ledger_id=$m.ledger_id;generation=$joined.generation}
            $start=[Diagnostics.ProcessStartInfo]::new()
            $start.FileName=Join-Path $private 'rust-service-host.exe'
            $start.Arguments='run --root "'+$Root+'" --shutdown-stdin'
            $start.WorkingDirectory=$Root;$start.UseShellExecute=$false;$start.CreateNoWindow=$true;$start.RedirectStandardInput=$true
            $process=[Diagnostics.Process]::new();$process.StartInfo=$start
            try {
                if (-not $process.Start()) { throw 'HOST_PROCESS_START_FAILED' }
                while (-not $process.WaitForExit(1000)) {
                    if (@($stops|Where-Object {[IO.File]::Exists($_)}).Count) {
                        $process.StandardInput.WriteLine('');$process.StandardInput.Close()
                        if (-not $process.WaitForExit(30000)) { throw 'HOST_GRACEFUL_STOP_TIMED_OUT' }
                        break
                    }
                }
            } finally { $process.Dispose() }
        } else {
            $code='AUTOMATIC_JOIN_PENDING'
            try {$details=$failure|ConvertFrom-Json;$reported=$details.error;if ($reported -match '^[A-Z][A-Z0-9_]{4,100}$') {$code=$reported};$blocked=@(401,403,409,422,426) -contains [int]$details.http_status;if ($null -ne $details.retry_after) {$retryAfter=[Math]::Min(86400,[Math]::Max(0,[double]$details.retry_after))}} catch {}
            if ($code -ne $last -or ([DateTime]::UtcNow-$lastAt).TotalSeconds -ge 300) {
                Write-HostEvent 'installation.awaiting_enrollment' @{phase=$code;retry=$true}
                $last=$code;$lastAt=[DateTime]::UtcNow
            }
        }
        $attempt=[Math]::Min(9,$attempt+1)
        $base=if ($blocked) {300} else {[Math]::Min(300,[Math]::Pow(2,$attempt))}
        $delay=[Math]::Max($retryAfter,[Math]::Min(300,$base+(Get-Random -Minimum 0 -Maximum ([int][Math]::Max(1,$base/4)))))
        for($i=0;$i -lt $delay;$i++) {if (@($stops|Where-Object {[IO.File]::Exists($_)}).Count) {break};Start-Sleep -Seconds 1}
    }
} catch { Write-HostEvent 'installation.runner.failed' @{type=$_.Exception.GetType().Name};exit 1 }
finally { if ($null -ne $lock) {$lock.Dispose()} }
