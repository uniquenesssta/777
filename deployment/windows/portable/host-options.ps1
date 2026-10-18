# Console prompts and standard Windows folder pickers, kept separate from setup logic.
function Read-HostDirectoryChoice([string] $Label, [string] $Current, [bool] $ServiceRoot=$false) {
    Write-Host ($Label + '：' + $Current)
    $choice=Read-Host '回车使用此位置；输入1选择文件夹；也可以粘贴完整路径'
    if (-not $choice) { return $Current }
    if ($choice -ne '1') { return $choice.Trim().Trim('"') }
    Add-Type -AssemblyName System.Windows.Forms
    $dialog=[Windows.Forms.FolderBrowserDialog]::new()
    $dialog.Description=if ($ServiceRoot) { '选择数据上级文件夹，将创建 Quote777Service；也可选已有后台根目录' } else { $Label }
    $dialog.ShowNewFolderButton=$true
    try {
        if ($dialog.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { throw 'HOST_DIRECTORY_SELECTION_CANCELLED' }
        $selected=$dialog.SelectedPath
        if ($ServiceRoot -and -not (Test-Path -LiteralPath (Join-Path $selected 'private\service.json'))) { $selected=Join-Path $selected 'Quote777Service' }
        return $selected
    } finally { $dialog.Dispose() }
}
function Select-HostSetupSettings($Settings) {
    $value=$Settings | ConvertTo-Json -Depth 10 | ConvertFrom-Json
    Write-Host '部署会把后台安装在当前这台电脑；新目录创建独立账本，其他电脑的数据不会自动复制过来。'
    $value.root=Read-HostDirectoryChoice '业务数据根目录' $value.root $true
    if (Test-Path -LiteralPath (Join-Path $value.root 'private\service.json')) {
        Write-Host '已找到现有后台，将沿用它的地址、目录和账本。'
        return Get-PreparedHostSettings $value.root $value
    }
    $site=Get-LocalHostInventory
    $candidates=@(Get-HostCandidateAddresses $site.addresses)
    if (-not $candidates.Count) { throw 'NO_LOCAL_LAN_ADDRESS_AVAILABLE' }
    $index=0
    if ($candidates.Count -gt 1) {
        for ($i=0;$i -lt $candidates.Count;$i++) { Write-Host (([string]($i+1))+': '+$candidates[$i]) }
        $choice=Read-Host '选择本机服务地址编号，回车使用1'
        if ($choice) {
            $number=0
            if (-not [int]::TryParse($choice,[ref]$number) -or $number -lt 1 -or $number -gt $candidates.Count) { throw 'LOCAL_HOST_ADDRESS_SELECTION_REQUIRED' }
            $index=$number-1
        }
    }
    $value.address=$candidates[$index]
    Write-Host ('本机服务地址：'+$value.address)
    $value.backup=Read-HostDirectoryChoice '普通备份目录' $value.backup
    $value.hidden=Read-HostDirectoryChoice '隐藏备份目录' $value.hidden
    $value.root=Get-LocalHostRoot $value.root $true
    Assert-HostBackupLocation $value.backup $value.root
    Assert-HostBackupLocation $value.hidden $value.root
    $value.configured=$true
    return $value
}
