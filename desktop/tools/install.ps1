# Operator-side choice flow. Never shown by the business application.
param()
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try {
    $release = $PSScriptRoot
    $manifest = Get-Content -LiteralPath (Join-Path $release 'release.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.delivery -notin @('manager', 'sales') -or
        $manifest.installer -notmatch '^[^\\/:]+-setup\.exe$') { throw 'RELEASE_MANIFEST_INVALID' }
    $profile = Join-Path $env:LOCALAPPDATA "cn.uniqueness.quote777\$($manifest.delivery)"
    # The existing enrollment verifier checks every release hash before writing.
    if (-not [IO.File]::Exists((Join-Path $profile 'device.bin')) -and
        -not [IO.File]::Exists((Join-Path $profile 'device-candidate.bin')) -and
        -not [IO.File]::Exists((Join-Path $profile 'bootstrap.json'))) {
        $picker = New-Object Windows.Forms.OpenFileDialog
        try {
            $picker.Title = '选择管理员提供的本机设备登记文件'
            $picker.Filter = '设备登记文件 (*.json)|*.json'
            if ($picker.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { exit 0 }
            & (Join-Path $release 'enroll.ps1') -ReleaseDirectory $release -GrantFile $picker.FileName
        } finally { $picker.Dispose() }
    }
    # Upgrade paths also validate the installer itself, without replacing identity.
    $entry = @($manifest.files | Where-Object { $_.name -ceq $manifest.installer })
    if ($entry.Count -ne 1) { throw 'RELEASE_FILES_MISSING' }
    $installer = Join-Path $release $manifest.installer
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $inputFile = [IO.File]::OpenRead($installer)
        try { $hash = [BitConverter]::ToString($algorithm.ComputeHash($inputFile)).Replace('-', '').ToLowerInvariant() }
        finally { $inputFile.Dispose() }
    } finally { $algorithm.Dispose() }
    if ($hash -cne $entry[0].sha256) { throw 'RELEASE_HASH_MISMATCH' }
    $process = Start-Process -FilePath $installer -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw 'INSTALLATION_INCOMPLETE' }
} catch {
    # This is the deployment operator, not the delivered business workbench.
    [void][Windows.Forms.MessageBox]::Show('安装未完成，已有设备身份和数据已保留。请检查安装文件与设备登记文件。', '部署', 'OK', 'Error')
    exit 1
}
