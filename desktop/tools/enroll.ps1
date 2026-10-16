param(
    [Parameter(Mandatory = $true)][string]$ReleaseDirectory,
    [Parameter(Mandatory = $true)][string]$GrantFile
)
$ErrorActionPreference = 'Stop'
$release = (Resolve-Path -LiteralPath $ReleaseDirectory).Path
$manifest = Get-Content -LiteralPath (Join-Path $release 'release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.schema -ne '777-desktop-release-v1' -or $manifest.delivery -notin @('manager', 'sales') -or
    $manifest.identifier -ne "cn.uniqueness.quote777.$($manifest.delivery)" -or
    $manifest.verification -ne $false -or $manifest.release -ne $true -or
    $manifest.profile_compatibility_epoch -ne 1 -or $manifest.version -notmatch '^\d+\.\d+\.\d+$' -or
    $manifest.service_protocol -ne '777-service-v1' -or $manifest.device_protocol -ne '777-device-auth-v1') { throw 'RELEASE_MANIFEST_INVALID' }
$names = @()
foreach ($entry in $manifest.files) {
    if (-not $entry.name -or $entry.name -in @('.', '..') -or $entry.name -match '[\\/:]' -or $entry.name -in $names -or $entry.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'RELEASE_FILE_INVALID' }
    $names += $entry.name
    $file = Get-Item -LiteralPath (Join-Path $release $entry.name)
    if ($file.Length -ne $entry.bytes -or (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw 'RELEASE_HASH_MISMATCH' }
}
if ('connection.json' -notin $names -or "quote777-$($manifest.delivery).exe" -notin $names -or $manifest.installer -notin $names) { throw 'RELEASE_FILES_MISSING' }
$public = Get-Content -LiteralPath (Join-Path $release 'connection.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$grantInfo = Get-Item -LiteralPath $GrantFile
if ($grantInfo.Length -gt 65536) { throw 'ENROLLMENT_TOO_LARGE' }
$grant = Get-Content -LiteralPath $GrantFile -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($key in $grant.PSObject.Properties.Name) {
    if ($key -notin @('schema', 'delivery', 'connection', 'ticket')) { throw 'ENROLLMENT_FIELDS_NOT_ALLOWED' }
}
if ($grant.schema -ne '777-desktop-bootstrap-v1' -or $grant.delivery -ne $manifest.delivery -or $grant.ticket -cnotmatch '^[A-Za-z0-9_-]{43}$') { throw 'ENROLLMENT_ROLE_OR_TICKET_INVALID' }
foreach ($key in $grant.connection.PSObject.Properties.Name) {
    if ($key -notin @('url', 'certificate_pem', 'certificate_sha256')) { throw 'ENROLLMENT_CONNECTION_FIELDS_NOT_ALLOWED' }
}
if ($public.schema -ne '777-public-connection-v1' -or
    $grant.connection.url.TrimEnd('/') -cne $public.connection.url.TrimEnd('/') -or
    $grant.connection.certificate_pem.Trim() -cne $public.connection.certificate_pem.Trim() -or
    $grant.connection.certificate_sha256 -cne $public.connection.certificate_sha256) { throw 'ENROLLMENT_SERVICE_CONFLICT' }
if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA_REQUIRED' }
$profile = Join-Path $env:LOCALAPPDATA "cn.uniqueness.quote777\$($manifest.delivery)"
function Assert-NoReparse([string]$Directory) {
    $item = [IO.DirectoryInfo]$Directory
    while ($null -ne $item) {
        if ($item.Exists -and (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) { throw 'DEPLOYMENT_PATH_REPARSE_POINT' }
        $item = $item.Parent
    }
}
Assert-NoReparse $profile
[void][IO.Directory]::CreateDirectory($profile)
Assert-NoReparse $profile
$target = Join-Path $profile 'bootstrap.json'
$stream = [IO.FileStream]::new($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
    $raw = $grant | ConvertTo-Json -Depth 10 -Compress
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($raw)
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush($true)
} finally { $stream.Dispose() }
Write-Output 'Enrollment prepared for the current Windows user. Start the assigned app.'
