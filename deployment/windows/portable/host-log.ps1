# One bounded log folder per invocation, shared with native child diagnostics.
function Start-HostLog([string] $Directory, [string] $Session = '', [string] $ExecutionId = '') {
    if ($env:QUOTE777_LOG_DISABLED -eq '1') {$script:HostLogDirectory='';$script:HostLogRecent=@{};return}
    if ($Session -and $Session -notmatch '^[A-Za-z0-9_-]{1,96}$') { throw 'HOST_LOG_SESSION_INVALID' }
    $session = $Session
    if (-not $session) { $session = [DateTimeOffset]::Now.ToString('yyyy-MM-dd_HHmmss') + '_' + [Guid]::NewGuid().ToString('N').Substring(0,12) }
    if (-not $ExecutionId) { $ExecutionId=$env:QUOTE777_EXECUTION_ID }
    if (-not $ExecutionId -or $ExecutionId -notmatch '^[A-Za-z0-9_-]{1,96}$') {$ExecutionId=$session}
    $env:QUOTE777_EXECUTION_ID=$ExecutionId
    $script:HostLogRecent=@{}
    $script:HostLogWarned=$false
    $script:HostLogDirectory = Join-Path $Directory ('logs\' + $session)
    try {[IO.Directory]::CreateDirectory($script:HostLogDirectory)|Out-Null} catch {$script:HostLogDirectory='';[Console]::Error.WriteLine('LOG_WRITE_FAILED');return}
    $env:QUOTE777_LOG_ROOT = $Directory
    $env:QUOTE777_LOG_SESSION = $session
    Write-HostEvent 'runtime.start' @{}
}
function Write-HostRecord([string] $Event, [hashtable] $Fields) {
    if ($env:QUOTE777_LOG_DISABLED -eq '1') {return}
    if (-not (Get-Variable HostLogDirectory -Scope Script -ErrorAction SilentlyContinue)) { return }
    if (-not $script:HostLogDirectory) {return}
    $record = [ordered]@{time_unix_ms=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds();pid=$PID;component='host-deployment';session=$env:QUOTE777_LOG_SESSION;execution_id=$env:QUOTE777_EXECUTION_ID;event=$Event;fields=$Fields}
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
            $oldest = Join-Path $script:HostLogDirectory 'runtime.2.jsonl'
            if (Test-Path -LiteralPath $oldest) { [IO.File]::Delete($oldest) }
            for ($index=1; $index -ge 1; $index--) {
                $old = Join-Path $script:HostLogDirectory ('runtime.' + $index + '.jsonl')
                if (Test-Path -LiteralPath $old) { [IO.File]::Move($old,(Join-Path $script:HostLogDirectory ('runtime.' + ($index+1) + '.jsonl'))) }
            }
            [IO.File]::Move($path,(Join-Path $script:HostLogDirectory 'runtime.1.jsonl'))
        }
        $stream = [IO.File]::Open($path,[IO.FileMode]::Append,[IO.FileAccess]::Write,[IO.FileShare]::Read)
        try { $stream.Write($bytes,0,$bytes.Length); $stream.Flush() } finally { $stream.Dispose() }
    } catch { if (-not $script:HostLogWarned) {$script:HostLogWarned=$true;[Console]::Error.WriteLine('LOG_WRITE_FAILED')} }
    finally { if ($null -ne $lock) { if ($locked) { $lock.Unlock(0,1) }; $lock.Dispose() } }
}

function Write-HostEvent([string] $Event, [hashtable] $Fields) {
    if ($env:QUOTE777_LOG_DISABLED -eq '1') {return}
    if (-not (Get-Variable HostLogRecent -Scope Script -ErrorAction SilentlyContinue)) {return}
    $safe=@{}
    foreach($key in $Fields.Keys) {
        $safe[$key]=if ($key -match '(?i)(password|secret|ticket|token|authorization|private_key|body|payload|request|response|orders|customer)$') {'[redacted]'} else {$Fields[$key]}
    }
    $now=[DateTime]::UtcNow
    $key=$Event+':'+($safe|ConvertTo-Json -Depth 6 -Compress)
    if ($script:HostLogRecent.ContainsKey($key) -and ($now-$script:HostLogRecent[$key].since).TotalSeconds -lt 60) {$script:HostLogRecent[$key].count++;return}
    foreach($old in @($script:HostLogRecent.Keys)) {
        $row=$script:HostLogRecent[$old]
        if ($row.count -gt 0 -and (($now-$row.since).TotalSeconds -ge 60 -or $Event -eq 'runtime.stop')) {Write-HostRecord 'repeated.summary' @{event=$old;suppressed=$row.count};$script:HostLogRecent.Remove($old)}
    }
    if ($script:HostLogRecent.Count -ge 256) {$script:HostLogRecent.Clear()}
    $script:HostLogRecent[$key]=@{since=$now;count=0}
    Write-HostRecord $Event $safe
}
function Write-HostFailure([string]$Event,[string]$Stage,$Record) {
    if ($env:QUOTE777_LOG_DISABLED -eq '1') {return}
    $code=if ($Record.Exception.Message -match '^[A-Z][A-Z0-9_]{4,100}$') {$Record.Exception.Message} else {'HOST_OPERATION_FAILED'}
    $native=if ($Record.Exception.PSObject.Properties.Name -contains 'NativeErrorCode') {$Record.Exception.NativeErrorCode} else {$null}
    Write-HostEvent $Event @{stage=$Stage;code=$code;type=$Record.Exception.GetType().Name;hresult=$Record.Exception.HResult;native_code=$native;script=[IO.Path]::GetFileName($Record.InvocationInfo.ScriptName);line=$Record.InvocationInfo.ScriptLineNumber;retry=$true}
}
function Import-HostOperation([string]$Path) {
    try {
        if ((Get-Item -LiteralPath $Path -Force).Length -gt 1024) {return}
        $value=Get-Content -LiteralPath $Path -Raw -Encoding UTF8|ConvertFrom-Json
        if ($value.format -eq '777-operation-context-v1' -and $value.execution_id -match '^[A-Za-z0-9_-]{1,96}$') {$env:QUOTE777_EXECUTION_ID=$value.execution_id}
    } catch {}
}
