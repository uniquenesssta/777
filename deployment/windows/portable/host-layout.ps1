# New deployments follow the package parent, independent of drive letter or PC.
function Get-HostPackageLayout([string] $Directory,$Template) {
    $package=Get-LocalHostRoot $Directory $false
    $parent=[IO.Path]::GetDirectoryName($package)
    if ([string]::IsNullOrEmpty($parent)) { throw 'HOST_PACKAGE_PARENT_REQUIRED' }
    return @{root=(Join-Path $parent 'Quote777Service');backup=(Join-Path $parent 'Quote777Hidden');hidden=[string]$Template.hidden_backup}
}
