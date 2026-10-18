# Integrity detects accidental/incomplete copies; it is not a publisher signature.
function Get-HostBundle([string] $Directory) {
    $path = Join-Path $Directory 'host-package.json'
    if ((Get-Item -LiteralPath $path).Length -gt 131072) { throw 'HOST_PACKAGE_MANIFEST_TOO_LARGE' }
    $bundle = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($bundle.schema -ne '777-host-bundle-v1' -or $bundle.platform -ne 'windows-x86_64' -or $bundle.source_commit -notmatch '^[a-f0-9]{40}$') { throw 'HOST_PACKAGE_FORMAT_INVALID' }
    $expected = @('host.ps1','host-console.ps1','host-defaults.json','collect.cmd','manage.cmd','setup.cmd','check.cmd','README.txt','THIRD_PARTY_NOTICES.md','bin/quote-host.exe','bin/quote-ledger.exe','scripts/host-log.ps1','scripts/host-package.ps1','scripts/host-site.ps1','scripts/host-paths.ps1','scripts/host-native.ps1','scripts/host-prepare.ps1','scripts/host-access.ps1','scripts/host-settings.ps1','scripts/host-options.ps1','scripts/host-setup.ps1','scripts/host-check.ps1','scripts/HostProbe.cs','scripts/host-identity.ps1','scripts/host-run.ps1','scripts/host-task.ps1')
    $actual = @($bundle.files.PSObject.Properties.Name)
    if (@(Compare-Object ($expected | Sort-Object) ($actual | Sort-Object)).Count) { throw 'HOST_PACKAGE_FILE_SET_INVALID' }
    foreach ($name in $expected) {
        $resource = Join-Path $Directory $name
        if ((Get-Item -LiteralPath $resource).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'HOST_PACKAGE_RESOURCE_REPARSE_POINT' }
        if ((Get-FileDigest $resource) -ne $bundle.files.$name) { throw 'HOST_PACKAGE_RESOURCE_CHANGED' }
    }
    return $bundle
}
