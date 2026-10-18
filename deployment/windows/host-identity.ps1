# Shared local ownership checks. Never reads passwords, tickets or business rows.
function Get-FileDigest([string] $File) {
    $stream = [IO.File]::OpenRead($File)
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hash.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
    finally { $hash.Dispose(); $stream.Dispose() }
}

function Get-HostDeployment([string] $Directory,[string] $CandidateHostSha256) {
    $full = [IO.Path]::GetFullPath($Directory).TrimEnd('\')
    if ($full.StartsWith('\\') -or $full.Contains('"') -or $full.Contains("`r") -or $full.Contains("`n")) {
        throw 'LOCAL_HOST_ROOT_REQUIRED'
    }
    $item = Get-Item -LiteralPath $full -Force -ErrorAction Stop
    while ($null -ne $item) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'HOST_ROOT_REPARSE_POINT' }
        $item = $item.Parent
    }
    $file = Join-Path $full 'private\deployment.json'
    if ((Get-Item -LiteralPath $file).Length -gt 65536) { throw 'DEPLOYMENT_MANIFEST_TOO_LARGE' }
    $value = Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $address = $null
    if ($value.schema -ne '777-site-deployment-v1' -or
        -not [string]::Equals($full, [IO.Path]::GetFullPath($value.root).TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase) -or
        $value.owner_sid -ne $identity.User.Value -or $value.machine -ne $env:COMPUTERNAME -or
        -not [Net.IPAddress]::TryParse([string]$value.active_address,[ref]$address) -or
        $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
        $value.port -lt 1 -or $value.port -gt 65535 -or
        $value.ledger_id -notmatch '^[a-f0-9-]{36}$') { throw 'DEPLOYMENT_OWNER_OR_IDENTITY_CONFLICT' }
    foreach ($entry in @(@('rust-service-host.exe', 'host_sha256'), @('host-run.ps1', 'runner_sha256'), @('host-identity.ps1', 'identity_sha256'))) {
        $resource = Join-Path $full ('private\' + $entry[0])
        if ((Get-Item -LiteralPath $resource).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'HOST_RESOURCE_REPARSE_POINT' }
        $digest=Get-FileDigest $resource
        if ($digest -ne $value.($entry[1]) -and -not ($entry[0] -eq 'rust-service-host.exe' -and $CandidateHostSha256 -match '^[a-f0-9]{64}$' -and $digest -eq $CandidateHostSha256)) { throw 'HOST_DEPLOYMENT_RESOURCE_CHANGED' }
    }
    return $value
}
