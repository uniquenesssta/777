# Child passwords travel only over UTF-8 stdin, never arguments, environment or logs.
function ConvertTo-HostArgument([string] $Value) {
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    return '"' + [regex]::Replace($escaped, '(\\+)$', '$1$1') + '"'
}
function Invoke-HostProcess([string] $Executable, [string[]] $Arguments, $Password = $null) {
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Executable
    if ($null -ne $Password) { $Arguments += '--secret-stdin' }
    $start.Arguments = (($Arguments | ForEach-Object { ConvertTo-HostArgument $_ }) -join ' ')
    $start.UseShellExecute = $false; $start.CreateNoWindow = $true
    $start.RedirectStandardInput = $true; $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = [Text.UTF8Encoding]::new($false)
    $start.StandardErrorEncoding = [Text.UTF8Encoding]::new($false)
    $child = [Diagnostics.Process]::new(); $child.StartInfo = $start
    try {
        if (-not $child.Start()) { throw 'HOST_CHILD_START_FAILED' }
        $stdout = $child.StandardOutput.ReadToEndAsync(); $stderr = $child.StandardError.ReadToEndAsync()
        if ($null -ne $Password) {
            $bytes = [Text.UTF8Encoding]::new($false).GetBytes((@{password=$Password} | ConvertTo-Json -Compress) + "`n")
            $child.StandardInput.BaseStream.Write($bytes,0,$bytes.Length)
            $child.StandardInput.BaseStream.Flush()
            [Array]::Clear($bytes,0,$bytes.Length)
        }
        $child.StandardInput.Close()
        if (-not $child.WaitForExit(180000)) { throw 'HOST_CHILD_TIMED_OUT_RESULT_REQUIRES_REVIEW' }
        $out = $stdout.GetAwaiter().GetResult(); $err = $stderr.GetAwaiter().GetResult()
        if ($child.ExitCode -ne 0) {
            $code = 'HOST_CHILD_OPERATION_FAILED'
            foreach ($line in ($err -split '\r?\n')) {
                try { $failure = $line | ConvertFrom-Json; if ($failure.error -match '^[A-Z][A-Z0-9_]{4,100}$') { $code = $failure.error } } catch {}
            }
            Write-HostEvent 'host.child.failed' @{operation=$Arguments[0];code=$code;exit_code=$child.ExitCode}
            throw $code
        }
        return $out.Trim()
    } finally { $Password = $null; $child.Dispose() }
}
function Invoke-HostNative([string] $Executable, [string[]] $Arguments, $Password = $null) {
    Write-HostEvent 'host.native.start' @{operation=$Arguments[0]}
    $raw = Invoke-HostProcess $Executable $Arguments $Password
    $lines = @($raw -split '\r?\n' | Where-Object { $_.Trim() })
    if (-not $lines.Count) { throw 'HOST_CHILD_EMPTY_RESPONSE' }
    $result = $lines[-1] | ConvertFrom-Json
    Write-HostEvent 'host.native.finish' @{operation=$Arguments[0]}
    return $result
}
function Read-HostBusinessPassword([bool] $Confirm) {
    $secure = Read-Host 'Business administrator password (12-128 characters)' -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $secure.Dispose() }
    if ($Confirm) {
        $again = Read-Host 'Repeat business password' -AsSecureString
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($again)
        try { if ($password -cne [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)) { throw 'PASSWORD_CONFIRMATION_MISMATCH' } }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $again.Dispose() }
    }
    return $password
}
