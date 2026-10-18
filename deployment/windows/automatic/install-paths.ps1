# Disk-only installation paths and atomic metadata; never touches a UNC backup.
function Assert-AutomaticLocalPath([string]$Path) {
    $full=[IO.Path]::GetFullPath($Path).TrimEnd('\')
    if ($full -notmatch '^[A-Za-z]:\\' -or $full.Contains('"') -or $full.Contains("`n") -or $full.Contains("`r")) { throw 'LOCAL_HOST_ROOT_REQUIRED' }
    if ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($full)).DriveType -ne [IO.DriveType]::Fixed) { throw 'LOCAL_HOST_ROOT_REQUIRED' }
    $parent=$full
    while ($parent) {
        if (Test-Path -LiteralPath $parent) {
            $item=Get-Item -LiteralPath $parent -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'HOST_ROOT_REPARSE_POINT' }
        }
        $parent=[IO.Path]::GetDirectoryName($parent)
    }
    return $full
}
function Write-AutomaticJson([string]$Path,$Value) {
    $temp=$Path+'.'+[Guid]::NewGuid().ToString('N')+'.partial'
    try {
        [IO.File]::WriteAllText($temp,($Value|ConvertTo-Json -Depth 40 -Compress),[Text.UTF8Encoding]::new($false))
        if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temp,$Path,[System.Management.Automation.Language.NullString]::Value) }
        else { [IO.File]::Move($temp,$Path) }
    } finally { if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) } }
}
function Set-AutomaticTopAttributes([string[]]$Paths) {
    foreach($p in $Paths) {
        $p=Assert-AutomaticLocalPath $p
        if ([IO.Directory]::Exists($p)) {
            [IO.File]::SetAttributes($p,([IO.File]::GetAttributes($p) -bor [IO.FileAttributes]::Hidden -bor [IO.FileAttributes]::System))
        }
    }
}
