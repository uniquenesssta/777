param()
$ErrorActionPreference='Stop'
try {
    $m=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'release.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if ($m.schema -ne '777-desktop-release-v1' -or $m.device_protocol -ne '777-auto-enrollment-v1' -or $m.delivery -notin @('manager','sales') -or $m.installer -notmatch '^(?:Quotev?-\d+\.\d+\.\d+|[^\\/:]+-setup)\.exe$') { throw 'RELEASE_MANIFEST_INVALID' }
    $entries=@($m.files|Where-Object name -CEQ $m.installer)
    if ($entries.Count -ne 1) { throw 'RELEASE_FILES_MISSING' }
    $installer=Join-Path $PSScriptRoot $m.installer
    if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entries[0].sha256) { throw 'RELEASE_HASH_MISMATCH' }
    $p=Start-Process $installer -Wait -PassThru
    exit $p.ExitCode
} catch {
    exit 1
}
