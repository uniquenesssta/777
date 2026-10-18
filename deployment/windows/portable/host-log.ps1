# One bounded log folder per invocation, shared with native child diagnostics.
function Start-HostLog([string] $Directory) {
    $session = [DateTimeOffset]::Now.ToString('yyyy-MM-dd_HHmmss') + '_' + [Guid]::NewGuid().ToString('N').Substring(0,12)
    $script:HostLogDirectory = Join-Path $Directory ('logs\' + $session)
    [IO.Directory]::CreateDirectory($script:HostLogDirectory) | Out-Null
    $env:QUOTE777_LOG_ROOT = $Directory
    $env:QUOTE777_LOG_SESSION = $session
    Write-HostEvent 'runtime.start' @{}
}
function Write-HostEvent([string] $Event, [hashtable] $Fields) {
    if (-not (Get-Variable HostLogDirectory -Scope Script -ErrorAction SilentlyContinue)) { return }
    $record = [ordered]@{time_unix_ms=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds();pid=$PID;component='host-deployment';session=$env:QUOTE777_LOG_SESSION;event=$Event;fields=$Fields}
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($record | ConvertTo-Json -Depth 6 -Compress) + "`n")
    if ($bytes.Length -gt 16384) { return }
    $lock = $null; $locked = $false
    try {
        $lock = [IO.File]::Open((Join-Path $script:HostLogDirectory 'runtime.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite)
        for ($attempt=0; $attempt -lt 10; $attempt++) {
            try { $lock.Lock(0,1); $locked=$true; break } catch [IO.IOException] { Start-Sleep -Milliseconds 10 }
        }
        if (-not $locked) { return }
        $path = Join-Path $script:HostLogDirectory 'runtime.jsonl'
        if ((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path).Length + $bytes.Length -gt 4194304)) {
            $oldest = Join-Path $script:HostLogDirectory 'runtime.4.jsonl'
            if (Test-Path -LiteralPath $oldest) { [IO.File]::Delete($oldest) }
            for ($index=3; $index -ge 1; $index--) {
                $old = Join-Path $script:HostLogDirectory ('runtime.' + $index + '.jsonl')
                if (Test-Path -LiteralPath $old) { [IO.File]::Move($old,(Join-Path $script:HostLogDirectory ('runtime.' + ($index+1) + '.jsonl'))) }
            }
            [IO.File]::Move($path,(Join-Path $script:HostLogDirectory 'runtime.1.jsonl'))
        }
        $stream = [IO.File]::Open($path,[IO.FileMode]::Append,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush() } finally { $stream.Dispose() }
    } catch { [Console]::Error.WriteLine('LOG_WRITE_FAILED') }
    finally { if ($null -ne $lock) { if ($locked) { $lock.Unlock(0,1) }; $lock.Dispose() } }
}
