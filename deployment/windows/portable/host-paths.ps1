function Get-LocalHostRoot([string] $Directory, [bool] $New) {
    if ([string]::IsNullOrWhiteSpace($Directory) -or $Directory -notmatch '^[a-zA-Z]:[\\/]' -or $Directory.Contains('"') -or $Directory.Contains("`r") -or $Directory.Contains("`n")) { throw 'ABSOLUTE_LOCAL_HOST_ROOT_REQUIRED' }
    $path = [IO.Path]::GetFullPath($Directory).TrimEnd('\')
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($path))
    if ($drive.DriveType -ne [IO.DriveType]::Fixed) { throw 'HOST_DATABASE_REQUIRES_LOCAL_FIXED_DISK' }
    $probe = $path
    while (-not (Test-Path -LiteralPath $probe)) { $probe = [IO.Path]::GetDirectoryName($probe) }
    $item = Get-Item -LiteralPath $probe -Force
    while ($null -ne $item) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'HOST_ROOT_REPARSE_POINT' }
        $item = $item.Parent
    }
    $parent = [IO.Path]::GetDirectoryName($path)
    if ($New -and ((Test-Path -LiteralPath $path) -or -not (Test-Path -LiteralPath $parent -PathType Container))) { throw 'NEW_HOST_ROOT_WITH_EXISTING_PARENT_REQUIRED' }
    # Resolve the existing parent to a long canonical name, including TEMP 8.3 aliases.
    return Get-HostLongPath $path
}
function Assert-HostBackupLocation([string] $Location, [string] $Root) {
    if ([string]::IsNullOrWhiteSpace($Location) -or ($Location -notmatch '^[a-zA-Z]:[\\/]' -and $Location -notmatch '^\\\\[^\\]+\\[^\\]+')) { throw 'ABSOLUTE_BACKUP_DIRECTORIES_REQUIRED' }
    $value = Get-HostLongPath $Location
    # Native configure-daily additionally resolves mapped/junction aliases and identities.
    if ([string]::Equals($value,$Root,[StringComparison]::OrdinalIgnoreCase) -or $value.StartsWith($Root+'\',[StringComparison]::OrdinalIgnoreCase) -or $Root.StartsWith($value+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'HOST_ROOT_AND_BACKUPS_MUST_BE_SEPARATE' }
}
function Get-HostLongPath([string] $Directory) {
    if (-not ('Quote777.LongPath' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
namespace Quote777 {
    public static class LongPath {
        [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
        public static extern uint GetLongPathName(string path, StringBuilder result, uint size);
    }
}
'@
    }
    $full = [IO.Path]::GetFullPath($Directory).TrimEnd('\')
    $tail = [Collections.Generic.List[string]]::new()
    $probe = $full
    while (-not (Test-Path -LiteralPath $probe)) {
        $tail.Insert(0,[IO.Path]::GetFileName($probe))
        $probe = [IO.Path]::GetDirectoryName($probe)
        if ([string]::IsNullOrEmpty($probe)) { throw 'PATH_PARENT_UNAVAILABLE' }
    }
    $buffer = [Text.StringBuilder]::new(32768)
    $length = [Quote777.LongPath]::GetLongPathName($probe,$buffer,32768)
    if ($length -eq 0 -or $length -ge 32768) { throw 'WINDOWS_LONG_PATH_RESOLUTION_FAILED' }
    $result = $buffer.ToString().TrimEnd('\')
    if ($result -match '^[a-zA-Z]:$') { $result += '\' }
    foreach ($name in $tail) { $result = Join-Path $result $name }
    return $result.TrimEnd('\')
}
