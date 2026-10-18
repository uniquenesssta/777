# Hide only the three configured deployment directories, never their contents.
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
    Assert-HostBackupLocation $Settings.hidden $Settings.root
    [IO.Directory]::CreateDirectory($Settings.hidden) | Out-Null
    foreach ($path in @($Settings.hidden,$Settings.root,$Directory)) {
        if (-not [IO.Directory]::Exists($path)) { throw 'HOST_VISIBILITY_DIRECTORY_MISSING' }
        $attributes=[IO.File]::GetAttributes($path)
        if ($attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'HOST_VISIBILITY_REPARSE_POINT' }
        [IO.File]::SetAttributes($path,($attributes -bor [IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::System))
    }
    Write-HostEvent 'host.visibility.finish' @{directories=3;hidden=$true;system=$true}
}
