# Directory visibility is independent of ordinary/hidden backup roles.
function Get-HostVisibilityDirectories([string] $Directory,$Settings) {
    $targets=@($Settings.root,$Directory)
    foreach ($path in @($Settings.backup,$Settings.hidden)) {
        # Never touch UNC shares or mapped network drives, even with this name.
        if ($path -notmatch '^[a-zA-Z]:[\\/]') { continue }
        $full=[IO.Path]::GetFullPath($path).TrimEnd('\')
        if ([IO.Path]::GetFileName($full) -ine 'Quote777Hidden') { continue }
        $drive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($full))
        if ($drive.DriveType -ne [IO.DriveType]::Fixed) { continue }
        Assert-HostBackupLocation $full $Settings.root
        $targets+= $full
    }
    return @($targets | Select-Object -Unique)
}
function Set-HostDeploymentVisibility([string] $Directory,$Settings) {
    # Old pinned identity readers need explicit hidden-directory support on restart.
    $deployment=Get-HostDeployment $Settings.root
    $identity=Join-Path $Settings.root 'private\host-identity.ps1'
    $source=Join-Path $Directory 'scripts\host-identity.ps1'
    $digest=Get-FileDigest $source
    if ($deployment.identity_sha256 -ne $digest) {
        [IO.File]::Copy($source,$identity,$true)
        $deployment.identity_sha256=$digest
        Write-HostJsonReplace (Join-Path $Settings.root 'private\deployment.json') $deployment
    }
    $targets=@(Get-HostVisibilityDirectories $Directory $Settings)
    foreach ($path in $targets) {
        if (-not [IO.Directory]::Exists($path)) {
            if ($path -eq $Directory -or $path -eq $Settings.root) { throw 'HOST_VISIBILITY_DIRECTORY_MISSING' }
            [IO.Directory]::CreateDirectory($path) | Out-Null
        }
        $attributes=[IO.File]::GetAttributes($path)
        if ($attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'HOST_VISIBILITY_REPARSE_POINT' }
        [IO.File]::SetAttributes($path,($attributes -bor [IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::System))
    }
    Write-HostEvent 'host.visibility.finish' @{directories=$targets.Count;hidden=$true;system=$true}
}
